"""Stage 4 — Gemma 4 decides the exit strategy for each at-risk dependency."""
from __future__ import annotations

import asyncio
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from . import gemma, knowledge, pysrc, registry, risk, state
from .prompts import Decision, decide


def _needs_proposal(d: dict, min_level: str) -> bool:
    codes = {i["code"] for i in d["risk"]["indicators"]}
    return (risk.LEVELS.index(d["risk"]["level"]) >= risk.LEVELS.index(min_level)
            or bool(codes & {"UNDECLARED", "DECLARED_UNUSED", "DEPRECATED_PACKAGE", "KNOWN_VULNERABILITY"}))


async def _candidate_health(dep: dict, ecosystem: str = "python") -> list[dict]:
    if ecosystem == "npm":
        f = await registry.npm_package(dep["name"])
        if not f or f.get("_missing"):
            return []
        return [{"candidate": dep["name"], "latest_version": f.get("latest"),
                 "latest_release_date": (f.get("latest_time") or "")[:10], "deprecated": f.get("deprecated_latest"),
                 "summary": f.get("description", "")[:120]}]
    out = []
    names = [dep["name"]]
    for c in knowledge.candidates_for(dep["name"]):
        first = c.split()[0]
        if "(stdlib" in c or first in ("(remove:", "upgrade"):
            out.append({"candidate": c})
            continue
        names.append(first)
    for n in dict.fromkeys(names):
        proj = await registry.pypi_project(n)
        if proj:
            info = proj["info"]
            latest = info.get("version")
            out.append({"candidate": n, "latest_version": latest,
                        "latest_release_date": registry.release_date(proj, latest),
                        "requires_python": info.get("requires_python"), "summary": (info.get("summary") or "")[:120]})
    return out


def _range(latest: str, ecosystem: str) -> str:
    if ecosystem == "npm":
        return f"^{latest}"
    try:
        return f">={latest},<{Version(latest).major + 1}"
    except Exception:
        return f">={latest}"


def _fallback(dep: dict, ecosystem: str = "python") -> dict:
    """Deterministic decision when Gemma is unavailable or keeps returning invalid output."""
    codes = {i["code"] for i in dep["risk"]["indicators"]}
    latest = dep.get("latest_version")
    if "UNDECLARED" in codes:
        strat, pkg, spec = "declare", dep["name"], (_range(latest, ecosystem) if ecosystem == "npm" else f">={latest}") if latest else None
    elif "DECLARED_UNUSED" in codes and dep["name"] not in knowledge.TOOL_PACKAGES:
        strat, pkg, spec = "remove", None, None
    elif (latest and dep.get("pinned_version") != latest and "DEPRECATED_PACKAGE" not in codes
          and not (codes & {"DEPRECATED_API_USE", "PRIVATE_API_USE", "MONKEYPATCH"} and "MAJOR_VERSIONS_BEHIND" in codes)):
        # without AI review, only upgrade when the code does not lean on APIs a major release may have removed
        strat, pkg, spec = "upgrade", dep["name"], _range(latest, ecosystem)
    else:
        strat, pkg, spec = "keep", dep["name"], None
    return {"strategy": strat, "package": pkg, "version_spec": spec,
            "rationale": f"Deterministic fallback ({strat}); Gemma 4 was unavailable for this decision.",
            "confidence": 0.4, "alternatives": [], "steps": [f"{strat} {pkg or dep['name']} {spec or ''}".strip()],
            "code_changes_needed": False, "suggested_tests": [],
            "open_concerns": ["Decision made without AI analysis; review manually."], "provenance": "derived"}


async def _validate(dec: Decision, ecosystem: str = "python") -> str | None:
    if dec.strategy in ("replace", "upgrade", "declare"):
        if not dec.package:
            return "package is required for this strategy"
        if ecosystem == "npm":
            f = await registry.npm_package(dec.package)
            if f is not None and f.get("_missing"):
                return f"package '{dec.package}' does not exist on the npm registry"
            return None  # semver ranges are accepted as given
        if not await registry.pypi_project(dec.package):
            return f"package '{dec.package}' does not exist on PyPI"
        if dec.version_spec:
            try:
                SpecifierSet(dec.version_spec)
            except InvalidSpecifier:
                return f"version_spec '{dec.version_spec}' is not a valid PEP 440 specifier"
    return None


async def _one(dep: dict, py: str, others: list[str], log: gemma.CallLog, ecosystem: str = "python") -> dict:
    usage_lines = [f"{l['file']}:{l['line']}: {l['code']}" for l in dep["usage"]["locations"][:40]]
    facts = {k: dep.get(k) for k in ("name", "pinned_version", "latest_version", "latest_release_date",
                                     "requires_python", "declared", "import_names", "group")}
    facts["risk_level"] = dep["risk"]["level"]
    facts["indicators"] = [{"code": i["code"], "detail": i["detail"]} for i in dep["risk"]["indicators"]]
    cands = await _candidate_health(dep, ecosystem)
    prompt = decide(py if ecosystem == "python" else "Node.js (npm)", facts, usage_lines, cands, others, ecosystem)
    for attempt in range(2):
        dec = await gemma.complete_json(log, f"decide:{dep['name']}", prompt, Decision)
        if dec is None:
            break
        err = await _validate(dec, ecosystem)
        if not err:
            out = dec.model_dump()
            # which model actually answered (Gemma 4, or a disclosed fallback model)
            out["model"] = next((c["model"] for c in reversed(log.calls)
                                 if c["purpose"] == f"decide:{dep['name']}" and c["ok"]), None)
            if out["strategy"] in ("stdlib", "remove"):
                out["version_spec"] = None
            out["provenance"] = "ai"
            return out
        prompt += f"\n\nYour previous decision was rejected: {err}. Fix it and reply with ONLY the JSON."
    return _fallback(dep, ecosystem)


async def run(job_dir: Path, py: str, min_level: str, log: gemma.CallLog, ecosystem: str = "python") -> dict:
    deps = state.merged_dependencies(job_dir)
    others = [d["name"] for d in deps]
    todo = [d for d in deps if _needs_proposal(d, min_level)]
    results = await asyncio.gather(*(_one(d, py, others, log, ecosystem) for d in todo))
    proposals = {d["name"]: r for d, r in zip(todo, results)}
    for d in deps:
        if d["name"] in proposals:
            continue
        latest = d.get("latest_version")
        codes = {i["code"] for i in d["risk"]["indicators"]}
        strat = "upgrade" if "OUTDATED" in codes and latest else "keep"
        proposals[d["name"]] = {"strategy": strat, "package": d["name"],
                                "version_spec": (f"^{latest}" if ecosystem == "npm" else f">={latest}") if strat == "upgrade" else None,
                                "rationale": "Low risk; no migration needed." if strat == "keep" else "Minor update available.",
                                "confidence": 0.9, "alternatives": [], "steps": [], "code_changes_needed": False,
                                "suggested_tests": [], "open_concerns": [], "provenance": "derived"}
    return {"proposals": proposals}
