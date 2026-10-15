"""Stage 8 — parse sandbox results, diff baseline vs migrated, attribute and explain the gaps."""
from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import gemma, prompts, pysrc, state

PASS = "passed"


def _test_id(classname: str, name: str) -> str:
    if not classname:  # collection error: name is a dotted module path
        return name.replace(".", "/") + ".py" if not name.endswith(".py") else name
    parts = classname.split(".")
    # pytest: classname = tests.test_mod or tests.test_mod.TestClass
    mod_parts, cls = parts, None
    if parts and parts[-1][:1].isupper():
        mod_parts, cls = parts[:-1], parts[-1]
    path = "/".join(mod_parts) + ".py"
    return f"{path}::{cls}::{name}" if cls else f"{path}::{name}"


def parse_junit(path: Path) -> tuple[list[dict], dict[str, str]]:
    """Returns (tests, collection_errors{module_path: message})."""
    if not path.exists():
        return [], {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return [], {}
    tests, coll = [], {}
    for tc in root.iter("testcase"):
        tid = _test_id(tc.get("classname", ""), tc.get("name", ""))
        outcome, msg = PASS, None
        for tag, oc in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
            el = tc.find(tag)
            if el is not None:
                outcome = oc
                msg = ((el.get("message") or "") + "\n" + (el.text or "")).strip()
                break
        if "::" not in tid and outcome == "error":
            coll[tid] = msg or "collection error"
            continue
        t = {"id": tid, "outcome": outcome}
        if msg:
            t["message"] = msg[:4000]
        try:
            t["duration_s"] = round(float(tc.get("time", "0")), 3)
        except ValueError:
            pass
        tests.append(t)
    return tests, coll


def _short(msg: str | None, n: int = 300) -> str:
    if not msg:
        return ""
    lines = [l for l in msg.splitlines() if l.strip()]
    e_lines = [l[1:].strip() for l in lines if l.startswith("E ")]
    if e_lines:
        return e_lines[-1][:n]
    key = [l for l in lines if re.search(r"(Error|Exception|assert)", l)]
    return (key[-1] if key else lines[0] if lines else "")[:n]


def load_run(job_dir: Path, run_id: str, repo_for_collection: Path | None = None) -> dict:
    rdir = job_dir / "runs" / run_id
    res = state.read(rdir, "result.json", {}) or {}
    tests, coll = parse_junit(rdir / "junit.xml")
    status = res.get("status", "error")
    if not tests and not coll and status in ("tests_failed", "error"):
        # session-level failure (e.g. conftest import error): every test is effectively an error
        log_path = rdir / "test.log"
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        m = re.search(r"(ImportError while loading conftest.*?)(?:\n\s*\nexit code|\Z)", text, re.DOTALL)
        if m or "Error" in text:
            coll["__session__"] = (m.group(1) if m else text[-2000:]).strip()[:4000]
    totals = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "total": 0}
    for t in tests:
        key = {"passed": "passed", "failed": "failed", "error": "errors", "skipped": "skipped"}[t["outcome"]]
        totals[key] += 1
    totals["errors"] += len(coll)
    totals["total"] = len(tests) + len(coll)
    return {
        "id": run_id,
        "kind": res.get("kind", "baseline" if run_id == "baseline" else "migrated"),
        "image": res.get("image", "python:3.12-slim"),
        "command": res.get("command", []),
        "status": status,
        "install_exit_code": res.get("install_exit_code"),
        "test_exit_code": res.get("test_exit_code"),
        "duration_s": res.get("duration_s", 0),
        "totals": totals,
        "tests": tests,
        "_collection_errors": coll,
        "log_urls": {"install": f"/runs/{run_id}/log?stream=install", "test": f"/runs/{run_id}/log?stream=test"},
        "junit_url": f"/runs/{run_id}/junit",
    }


def _outcomes(run: dict, all_ids: set[str]) -> dict[str, tuple[str, str]]:
    out = {t["id"]: (t["outcome"], t.get("message", "")) for t in run["tests"]}
    if run["status"] in ("install_failed", "timeout", "error") and not run["tests"]:
        return {i: ("install_failed" if run["status"] == "install_failed" else "not_run", run["status"]) for i in all_ids}
    for tid in all_ids:
        if tid in out:
            continue
        mod = tid.split("::")[0]
        if mod in run["_collection_errors"]:
            out[tid] = ("error", run["_collection_errors"][mod])
        elif run["_collection_errors"] and not run["tests"]:
            out[tid] = ("error", next(iter(run["_collection_errors"].values())))
        else:
            out[tid] = ("not_run", "")
    return out


def _test_file_deps(repo: Path, test_id: str, file_deps: dict[str, set[str]], import_map: dict[str, str]) -> set[str]:
    """Deps reachable from a test file: its direct dependency imports + deps used in local modules it imports."""
    path = repo / test_id.split("::")[0]
    tree, _ = pysrc.parse(path) if path.exists() else (None, [])
    found: set[str] = set()
    if tree is None:
        return found
    for n in ast.walk(tree):
        mods = []
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            mods = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
        for m in mods:
            top = m.split(".")[0]
            if top in import_map:
                found.add(import_map[top])
            rel = m.replace(".", "/") + ".py"
            found |= file_deps.get(rel, set())
    return found


_FRAME = re.compile(r"^(\S+\.py):\d+")
_SITE = re.compile(r"site-packages[/\\]([A-Za-z0-9_]+)")


def _attribute(msg: str, import_map: dict[str, str]) -> set[str]:
    """Which dependency broke? The library the project's own code calls into at the failure point (the first
    third-party frame after the last project frame), plus modules named on the error line. Outer frames, like a
    CLI framework dispatching to project code, are only the call path and are ignored."""
    lines = msg.splitlines()
    frames = [m.group(1) for m in (_FRAME.match(l) for l in lines) if m]
    hits: set[str] = set()
    last_local = max((i for i, f in enumerate(frames) if "site-packages" not in f), default=-1)
    for f in frames[last_local + 1:]:
        m = _SITE.search(f)
        if m and m.group(1) in import_map:
            hits.add(import_map[m.group(1)])
            break
    err_lines = [l for l in lines if l.startswith("E ")] or lines[-3:]
    err = "\n".join(err_lines)
    for imp, dep in import_map.items():
        if re.search(rf"(named '{re.escape(imp)}[.']|from '{re.escape(imp)}'|module '{re.escape(imp)}')", err):
            hits.add(dep)
    return hits


async def run(job_dir: Path, run_ids: list[str], py: str, log: gemma.CallLog) -> dict:
    deps = state.merged_dependencies(job_dir)
    import_map = {i.split(".")[0]: d["name"] for d in deps for i in d["import_names"]}
    file_deps: dict[str, set[str]] = {}
    for d in deps:
        for f in d["usage"]["files"]:
            file_deps.setdefault(f, set()).add(d["name"])
    repo = job_dir / "repo"

    runs = [load_run(job_dir, rid) for rid in run_ids if (job_dir / "runs" / rid).exists()]
    # a run whose whole session failed gets an explicit error for every test the other runs know about
    known = {t["id"] for r in runs for t in r["tests"]}
    for r in runs:
        session = r["_collection_errors"].pop("__session__", None)
        if session and not r["tests"] and known:
            r["tests"] = [{"id": i, "outcome": "error", "message": session} for i in sorted(known)]
            r["totals"] = {"passed": 0, "failed": 0, "errors": len(known), "skipped": 0, "total": len(known)}
    base = next((r for r in runs if r["id"] == "baseline"), None)
    gaps: list[dict] = []
    sandbox_ind: dict[str, list[dict]] = {}

    # runtime incompatibility evidence from the ORIGINAL dependencies on this Python
    if base:
        msgs = [t.get("message", "") for t in base["tests"] if t["outcome"] in ("error", "failed")]
        msgs += list(base["_collection_errors"].values())
        for m in msgs:
            if not re.search(r"(ImportError|ModuleNotFoundError|AttributeError|DeprecationWarning|SyntaxError)", m):
                continue
            for dep in _attribute(m, import_map):
                sandbox_ind.setdefault(dep, [])
                if sandbox_ind[dep]:
                    continue
                sandbox_ind[dep].append({
                    "code": "PY312_INCOMPATIBLE", "severity": "critical",
                    "detail": f"Fails on Python {py} with the pinned version: {_short(m, 200)}",
                    "evidence": [{"source": "sandbox", "ref": "baseline", "detail": _short(m, 200),
                                  "url": "/runs/baseline/log?stream=test"}],
                    "provenance": "evidence"})
        if base["status"] == "install_failed":
            log_path = job_dir / "runs" / "baseline" / "install.log"
            text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            for m in re.finditer(r"(?:Failed to build|Failed building wheel for|No matching distribution found for|"
                                 r"Could not find a version that satisfies the requirement)\s+([A-Za-z0-9._-]+)", text):
                dep = m.group(1).lower().replace("_", "-")
                sandbox_ind.setdefault(dep, []).append({
                    "code": "PY312_INCOMPATIBLE", "severity": "critical",
                    "detail": f"Install fails on Python {py}: {m.group(0)}",
                    "evidence": [{"source": "sandbox", "ref": "baseline", "detail": m.group(0),
                                  "url": "/runs/baseline/log?stream=install"}],
                    "provenance": "evidence"})

    if base:
        for other in (r for r in runs if r["id"] != "baseline"):
            if base["status"] == "install_failed" and other["status"] != "install_failed":
                gaps.append({"test_id": None, "baseline": "install_failed", "migrated": other["status"],
                             "change": "install_fixed", "dependencies": sorted(sandbox_ind), "run_id": other["id"]})
            elif other["status"] == "install_failed" and base["status"] != "install_failed":
                gaps.append({"test_id": None, "baseline": base["status"], "migrated": "install_failed",
                             "change": "install_regressed", "dependencies": [], "run_id": other["id"]})
            ids = {t["id"] for t in base["tests"]} | {t["id"] for t in other["tests"]}
            bo, mo = _outcomes(base, ids), _outcomes(other, ids)
            for tid in sorted(ids):
                (b, bmsg), (m, mmsg) = bo[tid], mo[tid]
                if b == m == PASS or (b == "skipped" and m == "skipped"):
                    continue
                if b != PASS and m == PASS:
                    change = "fixed"
                elif b == PASS and m != PASS:
                    change = "regressed"
                elif b in ("failed", "error") and m in ("failed", "error", "install_failed"):
                    change = "still_failing"
                else:
                    continue
                sus = (_attribute(mmsg, import_map) if m != PASS else set()) |                       (_attribute(bmsg, import_map) if b != PASS else set())
                sus = sus or _test_file_deps(repo, tid, file_deps, import_map)
                gaps.append({"test_id": tid, "baseline": b if b in ("passed", "failed", "error", "skipped") else b,
                             "migrated": m, "change": change, "dependencies": sorted(sus), "run_id": other["id"],
                             "_baseline_error": _short(bmsg, 400), "_migrated_error": _short(mmsg, 400)})

    headline = ""
    if gaps:
        payload = [{"test_id": g["test_id"] or "__install__", "run": g["run_id"], "baseline": g["baseline"],
                    "migrated": g["migrated"], "change": g["change"], "suspected_dependencies": g["dependencies"],
                    "baseline_error": g.get("_baseline_error", ""), "migrated_error": g.get("_migrated_error", "")}
                   for g in gaps[:40]]
        ctx = {r["id"]: {"status": r["status"], **r["totals"]} for r in runs}
        reply = await gemma.complete_json(log, "explain_gaps", prompts.explain_gaps(py, payload, ctx), prompts.GapsReply)
        items = {i.test_id: i for i in reply.items} if reply else {}
        headline = reply.headline if reply else ""
        for g in gaps:
            it = items.get(g["test_id"] or "__install__")
            if it:
                g["explanation"], g["severity"], g["provenance"] = it.explanation, it.severity, "ai"
            else:
                g["explanation"] = _fallback_explanation(g)
                g["severity"] = {"regressed": "high", "install_regressed": "critical", "still_failing": "medium"}.get(g["change"], "low")
                g["provenance"] = "derived"
    for g in gaps:
        g.pop("_baseline_error", None)
        g.pop("_migrated_error", None)
    for r in runs:
        r.pop("_collection_errors", None)
    return {"runs": runs, "gaps": gaps, "sandbox_indicators": sandbox_ind, "headline": headline}


def _fallback_explanation(g: dict) -> str:
    base = {"fixed": "Fails with the original dependencies and passes after migration.",
            "regressed": "Passes with the original dependencies but fails after migration.",
            "still_failing": "Fails both before and after migration.",
            "install_fixed": "The original dependencies fail to install; the migrated set installs.",
            "install_regressed": "The migrated dependency set fails to install."}[g["change"]]
    err = g.get("_migrated_error") or g.get("_baseline_error")
    return base + (f" Error: {err}" if err else "")
