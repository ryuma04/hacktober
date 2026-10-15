"""Stage 9 — assemble, validate and render the Dependency Exit Capsule."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from . import config, gemma, risk, state
from .models import Capsule

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "capsule.schema.json"

# (text, applies to sandboxed runs only)
FIXED_LIMITATIONS = [
    ("Behaviour is verified only as far as the project's own test suite reaches; untested code paths can still break.", True),
    ("Replacement choices and code edits are AI-generated and must be reviewed by a maintainer.", True),
    ("Replacement choices are AI-generated proposals and must be reviewed by a maintainer.", False),
    ("Vulnerability data comes from OSV at analysis time; unpinned dependencies are not checked for advisories.", None),
    ("Tests run offline in a python:3.12-slim container; network-dependent behaviour is not exercised.", True),
    ("Test files are never modified by the migration, so test-only incompatibilities show up as gaps.", True),
]

PRIMARY_PROVIDER = "Google AI Studio (Gemini API)"


def provider_of(model: str) -> str:
    """Which service actually produced an answer, from the model id recorded in ai_calls.jsonl."""
    if model.startswith("groq:"):
        return "Groq"
    if model.startswith("xai:"):
        return "xAI"
    return PRIMARY_PROVIDER  # gemma-* and gemini-* both come from Google AI Studio


def strip_number(step: str) -> str:
    """AI steps sometimes come pre-numbered ("1. Update…"); we number them ourselves."""
    return re.sub(r"^\s*(?:step\s*)?\d+[.):]\s*", "", str(step), flags=re.I)


def model_label(model: str | None) -> str:
    if not model:
        return "AI"
    if model.startswith("gemma"):
        return "Gemma 4"
    return f"fallback {model}"


def write_schema() -> None:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(json.dumps(Capsule.model_json_schema(), indent=2), encoding="utf-8")


def _prefix(base: str, u: str | None) -> str | None:
    if u and u.startswith("/runs/"):
        return base + u
    return u


def _calls(job_dir: Path) -> tuple[int, int, str, int, dict[str, int]]:
    """(calls, failed attempts, primary model, cached answers, answers per model)."""
    p = job_dir / "ai_calls.jsonl"
    primary = gemma.models()[0] if gemma.models() else "gemma-4"
    if not p.exists():
        return 0, 0, primary, 0, {}
    recs = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    used: dict[str, int] = {}
    for r in recs:
        if r.get("ok"):
            used[r["model"]] = used.get(r["model"], 0) + 1
    gemma_ok = {m: n for m, n in used.items() if m.startswith("gemma")}
    model = max(gemma_ok, key=gemma_ok.get) if gemma_ok else primary  # the primary model is always Gemma 4
    return len(recs), sum(1 for r in recs if not r.get("ok")), model, sum(1 for r in recs if r.get("cached")), used


def run(job_dir: Path, target: dict, stage_errors: dict, base_url: str) -> dict:
    deps = state.merged_dependencies(job_dir)
    scan = state.read(job_dir, "scan.json", {})
    proposals = (state.read(job_dir, "proposals.json", {}) or {}).get("proposals", {})
    mat = state.read(job_dir, "materialize.json", {}) or {}
    cmp_ = state.read(job_dir, "compare.json", {}) or {}
    runs = cmp_.get("runs", [])
    gaps = cmp_.get("gaps", [])
    limitations: list[str] = []

    for r in runs:
        r["log_urls"] = {k: _prefix(base_url, v) for k, v in r["log_urls"].items()}
        r["junit_url"] = _prefix(base_url, r.get("junit_url"))
    by_run = {r["id"]: {t["id"]: t["outcome"] for t in r["tests"]} for r in runs}

    ecosystem = scan.get("ecosystem", "python")
    scan_only = ecosystem != "python"
    out_deps = []
    for d in deps:
        for ind in d["risk"]["indicators"]:
            for e in ind["evidence"]:
                e["url"] = _prefix(base_url, e.get("url"))
            ind.pop("count", None)
            ind.pop("majors", None)
        p = proposals.get(d["name"])
        a = (mat.get("applied") or {}).get(d["name"])
        dep_gaps = [g for g in gaps if d["name"] in g.get("dependencies", [])]
        test_files = set(d["usage"]["files"])
        affected = sorted({t for r in by_run.values() for t in r
                           if t.split("::")[0] in test_files or any(d["name"] in g["dependencies"] and g["test_id"] == t
                                                                    for g in gaps)})
        if not affected:
            affected = sorted({g["test_id"] for g in dep_gaps if g.get("test_id")})
        status = "not_run"
        if runs and affected:
            mig = by_run.get("migrated", {})
            outs = [mig.get(t) for t in affected if t in mig]
            status = "pass" if outs and all(o == "passed" for o in outs) else \
                "fail" if outs and all(o != "passed" for o in outs) else "mixed" if outs else "not_run"
        elif runs:
            status = "pass" if not dep_gaps else "mixed"
        if p and p.get("provenance") == "ai":  # summaries written by Gemma inside the same decide call
            if p.get("risk_summary"):
                d["risk"]["rationale"], d["risk"]["rationale_provenance"] = p["risk_summary"], "ai"
            if p.get("usage_summary") and d["usage"]["locations"]:
                d["usage"]["summary"], d["usage"]["summary_provenance"] = p["usage_summary"], "ai"
        concerns = [{"text": c, "provenance": p.get("provenance", "ai")} for c in (p or {}).get("open_concerns", [])]
        if a and not a["applied"]:
            concerns.insert(0, {"text": f"Code migration not applied: {a['not_applied_reason']}", "provenance": "derived"})
        entry = {
            **{k: d.get(k) for k in ("name", "import_names", "declared", "pinned_version", "latest_version",
                                     "latest_release_date", "last_release_of_pinned", "requires_python", "homepage")},
            "risk": d["risk"],
            "usage": d["usage"],
            "blast_radius": d.get("blast_radius"),
            "replacement": None if not p else {
                "strategy": p["strategy"], "package": p.get("package"), "version_spec": p.get("version_spec"),
                "rationale": p["rationale"], "confidence": float(p.get("confidence", 0.5)),
                "alternatives": p.get("alternatives", []), "provenance": p.get("provenance", "ai"),
                "model": p.get("model")},
            "migration": None if not p or p["strategy"] == "keep" else {
                "steps": p.get("steps", []), "files_changed": (a or {}).get("files_changed", []),
                "applied": (a or {}).get("applied", False) if a else False,
                "not_applied_reason": ((a or {}).get("not_applied_reason") if a else
                                       f"Proposed only: {ecosystem} projects are scan-only (no migration or sandbox run)"
                                       if scan_only else "Materialize stage did not run"),
                "proposed_only": scan_only,
                "provenance": p.get("provenance", "ai")},
            "suggested_tests": [{**t, "provenance": "ai"} for t in (p or {}).get("suggested_tests", [])],
            "test_results": {"run_ids": [r["id"] for r in runs], "affected_tests": affected, "status": status},
            "compatibility_gaps": dep_gaps,
            "open_concerns": concerns,
        }
        out_deps.append(entry)

    def tot(rid: str) -> dict:
        r = next((x for x in runs if x["id"] == rid), None)
        if not r:
            return {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "total": 0, "status": "error"}
        return {**r["totals"], "status": r["status"]}

    gap_counts = {"fixed": sum(g["change"] in ("fixed", "install_fixed") for g in gaps),
                  "regressed": sum(g["change"] in ("regressed", "install_regressed") for g in gaps),
                  "still_failing": sum(g["change"] == "still_failing" for g in gaps)}
    mig = tot("migrated")
    crit_regress = any(g["change"] in ("regressed", "install_regressed") and g.get("severity") == "critical" for g in gaps)
    if mig["status"] in ("install_failed", "error", "timeout") or crit_regress:
        verdict = "blocked"
    elif mig["status"] == "passed" and gap_counts["regressed"] == 0:
        verdict = "safe_to_migrate"
    else:
        verdict = "migrate_with_care"
    if scan_only:
        verdict = "migrate_with_care"  # nothing was migrated or executed, so never "safe" nor "blocked" by a test run
    by_level = {lv: 0 for lv in ("critical", "high", "medium", "low", "none")}
    for d in out_deps:
        by_level[d["risk"]["level"]] += 1
    at_risk = sum(1 for d in out_deps if risk.at_risk(d["risk"]["level"]))
    base = tot("baseline")
    headline = cmp_.get("headline") or (
        f"{at_risk} of {len(out_deps)} dependencies are at risk; tests passing {base['passed']}/{base['total']} "
        f"before and {mig['passed']}/{mig['total']} after migration.")
    if scan_only:
        headline = (f"Scan-only ({ecosystem}): {at_risk} of {len(out_deps)} dependencies are at risk. Replacements are "
                    "proposed by AI but not migrated or verified in a sandbox.")

    n_calls, n_failed, model, n_cached, models_used = _calls(job_dir)
    fallback_answers = {m: n for m, n in models_used.items() if not m.startswith("gemma")}
    n_answers = sum(models_used.values())
    if fallback_answers:
        limitations.append(
            f"{sum(fallback_answers.values())} of {n_answers} AI answers came from fallback models ("
            + ", ".join(f"{m} via {provider_of(m)} x{n}" for m, n in sorted(fallback_answers.items()))
            + ") because Gemma 4 did not answer within its time budget when they were generated. Each decision records "
              "the model that produced it.")
    for stage, err in (stage_errors or {}).items():
        limitations.append(f"Stage '{stage}' failed: {err}")
    if not gemma.configured() or (n_calls and not n_answers):
        limitations.append("No AI model was available; AI-written fields fell back to deterministic logic.")
    # only proposals that were sent to the AI and fell back (low-risk packages are decided deterministically by design)
    derived = sum(1 for p in proposals.values() if str(p.get("rationale", "")).startswith("Deterministic fallback"))
    if derived:
        limitations.append(f"{derived} proposal(s) were made by deterministic fallback logic (no AI answer in time); "
                           "they are marked 'computed'.")
    if n_cached:
        limitations.append(f"{n_cached} of {n_answers} AI answers were reused from an earlier analysis of identical "
                           "code and facts (same prompt); set GEMMA_CACHE=0 to force fresh answers.")
    for f in mat.get("files", []):
        if f["status"] == "rejected":
            limitations.append(f"Gemma's rewrite of {f['path']} was rejected ({f['reason']}); original file kept.")
        elif f["status"] == "reverted":
            limitations.append(f"Rewrite of {f['path']} was {f['reason']}.")
    if scan_only:
        limitations.insert(0, f"{ecosystem} support is scan-only: dependencies, risks, usage and blast radius are "
                              "analysed and AI (Gemma 4 first) proposes replacements, but no code is migrated and nothing is "
                              "executed in the Docker sandbox for this ecosystem yet.")
    elif not any(r["tests"] for r in runs):
        limitations.append("No test results were collected; compatibility could not be verified by execution.")
    limitations += [n for n in scan.get("notes", []) if "not parsed" in n or "not analysed" in n
                    or "lookup failed" in n or "No lockfile" in n]
    limitations += [text for text, sandboxed in FIXED_LIMITATIONS if sandboxed is None or sandboxed == (not scan_only)]

    capsule = {
        "schema_version": "1.0",
        "capsule_id": job_dir.name,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {"name": "DepExit", "version": config.TOOL_VERSION},
        "target": {**target, "manifests": scan.get("manifests", []), "ecosystem": ecosystem,
                   "verification": "scan_only" if scan_only else "sandbox"},
        "ai": {"provider": PRIMARY_PROVIDER, "model": model,
               "answered_by": [{"model": m, "provider": provider_of(m), "answers": n}
                               for m, n in sorted(models_used.items(), key=lambda x: -x[1])],
               "calls": n_calls, "failed_calls": n_failed, "cached_calls": n_cached,
               "models_used": models_used, "fallback_models_used": sorted(fallback_answers),
               "fallback_used": n_failed > 0 or not gemma.configured(), "terms_url": config.GEMMA_TERMS_URL},
        "summary": {"dependencies_total": len(out_deps), "at_risk": at_risk, "by_level": by_level,
                    "baseline": base, "migrated": mig, "gaps": gap_counts, "verdict": verdict, "headline": headline},
        "dependencies": out_deps,
        "runs": runs,
        "patch": {"url": f"{base_url}/patch.diff", **(mat.get("patch") or {"files_changed": 0, "insertions": 0, "deletions": 0})},
        "limitations": limitations,
    }
    try:
        if not SCHEMA_PATH.exists():
            write_schema()
        jsonschema.validate(capsule, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
        capsule["schema_valid"] = True
    except jsonschema.ValidationError as e:
        capsule["limitations"].append(f"Capsule schema validation error at {list(e.absolute_path)}: {e.message[:200]}")
        capsule["schema_valid"] = False
    state.write(job_dir, "capsule.json", capsule)
    (job_dir / "CAPSULE.md").write_text(render_md(capsule), encoding="utf-8")
    try:  # the PDF is a convenience copy; never fail the capsule because of it
        from . import report_pdf
        report_pdf.build(capsule, job_dir / "capsule.pdf")
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("depexit.capsule").warning("PDF report failed: %s", e)
    return {"summary": capsule["summary"], "schema_valid": capsule["schema_valid"]}


def _prov(p: str, model: str | None = None) -> str:
    if p == "ai":
        return f" _({model_label(model)})_"
    return {"derived": " _(computed)_", "evidence": ""}.get(p, "")


def render_md(c: dict) -> str:
    s = c["summary"]
    t = c["target"]
    scan_only = t.get("verification") == "scan_only"
    eco = t.get("ecosystem", "python")
    runtime = f"Python {t.get('python_version')}" if eco == "python" else f"{eco} (scan-only)"
    tests = ("not run (scan-only)", "not run (scan-only)") if scan_only else (
        f"{s['baseline']['passed']}/{s['baseline']['total']} passed ({s['baseline']['status']})",
        f"{s['migrated']['passed']}/{s['migrated']['total']} passed ({s['migrated']['status']})")
    gaps_cell = "n/a (scan-only)" if scan_only else f"{s['gaps']['fixed']} / {s['gaps']['regressed']} / {s['gaps']['still_failing']}"
    L = [f"# Dependency Exit Capsule — {t.get('repo_url')} @ {t.get('commit', '')[:10]}", "",
         f"Generated {c['generated_at']} by DepExit {c['tool']['version']} · {runtime} · capsule `{c['capsule_id']}`", "",
         f"**Verdict:** `{s['verdict']}` — {s['headline']}", "",
         "| Dependencies | At risk | Baseline tests | Migrated tests | Gaps fixed / regressed / still failing |",
         "|---|---|---|---|---|",
         f"| {s['dependencies_total']} | {s['at_risk']} | {tests[0]} | {tests[1]} | {gaps_cell} |", ""]
    L += ["## Dependencies", "", "| Dependency | Pinned → latest | Risk | Proposal | Applied |", "|---|---|---|---|---|"]
    for d in c["dependencies"]:
        r = d.get("replacement") or {}
        m = d.get("migration") or {}
        prop = f"{r.get('strategy', '-')} {r.get('package') or ''} {r.get('version_spec') or ''}".strip()
        L.append(f"| {d['name']} | {d.get('pinned_version') or ('undeclared' if not d['declared'] else 'unpinned')} → "
                 f"{d.get('latest_version') or '?'} | {d['risk']['level']} ({d['risk']['score']}) | {prop} | "
                 f"{'proposed' if m.get('proposed_only') else ('✓' if m.get('applied') else ('✗' if m else '-'))} |")
    for d in c["dependencies"]:
        if not risk.at_risk(d["risk"]["level"]) and not d["compatibility_gaps"]:
            continue
        r, m = d.get("replacement") or {}, d.get("migration") or {}
        L += ["", f"## {d['name']} — {d['risk']['level']} ({d['risk']['score']})", "", "### Details",
              f"- Pinned: `{d.get('pinned_version')}` · latest: `{d.get('latest_version')}` ({d.get('latest_release_date')})",
              f"- Declared: " + (", ".join(f"`{x['file']}:{x['line']}` `{x['spec']}`" for x in d["declared"]) or "**not declared**"),
              *([f"- requires_python: `{d['requires_python']}`"] if d.get("requires_python") else []), "",
              "### Risk indicators", f"{d['risk']['rationale']}{_prov(d['risk']['rationale_provenance'], r.get('model'))}", ""]
        for i in d["risk"]["indicators"]:
            ev = ", ".join(e.get("ref") or e.get("url") or e.get("detail") or e["source"] for e in i["evidence"][:4])
            L.append(f"- **{i['code']}** ({i['severity']}): {i['detail']} — evidence: {ev}")
        L += ["", "### Usage locations", f"{d['usage']['summary']}{_prov(d['usage']['summary_provenance'], r.get('model'))}", ""]
        L += [f"- `{l['file']}:{l['line']}` [{l['kind']}] `{l['code']}`" for l in d["usage"]["locations"][:30]] or ["- (not imported)"]
        br = d.get("blast_radius")
        if br:
            st = br["stats"]
            L += ["", "### Blast radius",
                  f"{st['lines']} line(s) in {st['direct_files']} file(s) use it directly; {st['indirect_files']} more "
                  f"module(s) import those; {st['test_files']} of {st['total_test_files']} test file(s) reach it."]
            L += [f"- indirect: `{x['file']}` via " + " → ".join(f"`{v}`" for v in x["via"][1:]) for x in br["indirect"]]
            L += [f"- test: `{x['file']}` via " + " → ".join(f"`{v}`" for v in x["via"][1:]) for x in br["tests"]]
        L += ["", "### Proposed replacement",
              f"**{r.get('strategy')}** {r.get('package') or ''} {r.get('version_spec') or ''} "
              f"(confidence {r.get('confidence')}){_prov(r.get('provenance', ''), r.get('model'))}", "", r.get("rationale", "")]
        for alt in r.get("alternatives", []):
            L.append(f"- Rejected `{alt['package']}`: {alt['reason_rejected']}")
        L += ["", "### Migration steps"] + [f"{n}. {strip_number(st)}" for n, st in enumerate(m.get("steps", []), 1)]
        if m.get("proposed_only"):
            L.append("\nProposed only — not applied (scan-only).")
        elif m:
            L.append(f"\nApplied: {'yes' if m.get('applied') else 'no — ' + str(m.get('not_applied_reason'))} · files: "
                     + ", ".join(f"`{f}`" for f in m.get("files_changed", [])))
        L += ["", "### Suggested tests"]
        for st in d["suggested_tests"]:
            L += [f"- **{st['name']}** — {st['purpose']}"] + ([f"```python\n{st['code']}\n```"] if st.get("code") else [])
        tr = d.get("test_results") or {}
        L += ["", "### Executed test results", "Not run (scan-only)." if scan_only else f"Status: `{tr.get('status')}` · affected tests: "
              + (", ".join(f"`{x}`" for x in tr.get("affected_tests", [])) or "none identified")]
        L += ["", "### Compatibility gaps"]
        L += [f"- `{g['test_id'] or 'install'}`: {g['baseline']} → {g['migrated']} (**{g['change']}**, {g['severity']}): "
              f"{g['explanation']}{_prov(g['provenance'])}" for g in d["compatibility_gaps"]] or ["- none"]
        L += ["", "### Open concerns"] + ([f"- {x['text']}{_prov(x['provenance'], r.get('model'))}" for x in d["open_concerns"]] or ["- none"])
    if scan_only:
        L += ["", "## Test runs", "", "Not run: this project was analysed in scan-only mode (no migration, no sandbox)."]
    else:
        L += ["", "## Test runs", "", "| Run | Status | Passed | Failed | Errors | Skipped | Duration |", "|---|---|---|---|---|---|---|"]
        for r in c["runs"]:
            tt = r["totals"]
            L.append(f"| {r['id']} | {r['status']} | {tt['passed']} | {tt['failed']} | {tt['errors']} | {tt['skipped']} | {r['duration_s']}s |")
        p = c["patch"]
        L += ["", "## Patch", f"{p.get('files_changed')} files changed, +{p.get('insertions')} / -{p.get('deletions')} — see `patch.diff`."]
    L += ["", "## Limitations"] + [f"- {x}" for x in c["limitations"]]
    L += ["", "## AI disclosure", ai_disclosure(c["ai"]), ""]
    return "\n".join(L)


def ai_disclosure(a: dict) -> str:
    """One honest paragraph: primary model + provider, who actually answered, cache use, terms."""
    by = a.get("answered_by") or []
    who = "; ".join(f"{x['model']} via {x['provider']}: {x['answers']} answer(s)" for x in by) or "no AI answers"
    return (f"Primary model: Gemma 4 (`{a['model']}`) via {a['provider']}. Answers by model: {who}. "
            f"{a['calls']} AI calls logged, {a.get('cached_calls', 0)} served from the answer cache. "
            f"Gemma Terms of Use: {a['terms_url']}. AI-written fields name the model that wrote them; evidence fields "
            "come from the package registry, OSV, code analysis or the sandbox.")
