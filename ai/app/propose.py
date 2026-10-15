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


async def _candidate_health(dep: dict) -> list[dict]:
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


def _fallback(dep: dict) -> dict:
    """Deterministic decision when Gemma is unavailable or keeps returning invalid output."""
    codes = {i["code"] for i in dep["risk"]["indicators"]}
    latest = dep.get("latest_version")
    if "UNDECLARED" in codes:
        strat, pkg, spec = "declare", dep["name"], f">={latest}" if latest else None
    elif "DECLARED_UNUSED" in codes and dep["name"] not in knowledge.TOOL_PACKAGES:
        strat, pkg, spec = "remove", None, None
    elif latest and dep.get("pinned_version") != latest and "DEPRECATED_PACKAGE" not in codes:
        major = Version(latest).major
        strat, pkg, spec = "upgrade", dep["name"], f">={latest},<{major + 1}"
    else:
        strat, pkg, spec = "keep", dep["name"], None
    return {"strategy": strat, "package": pkg, "version_spec": spec,
            "rationale": f"Deterministic fallback ({strat}); Gemma 4 was unavailable for this decision.",
            "confidence": 0.4, "alternatives": [], "steps": [f"{strat} {pkg or dep['name']} {spec or ''}".strip()],
            "code_changes_needed": False, "suggested_tests": [],
            "open_concerns": ["Decision made without AI analysis; review manually."], "provenance": "derived"}


async def _validate(dec: Decision) -> str | None:
    if dec.strategy in ("replace", "upgrade", "declare"):
        if not dec.package:
            return "package is required for this strategy"
        if not await registry.pypi_project(dec.package):
            return f"package '{dec.package}' does not exist on PyPI"
        if dec.version_spec:
            try:
                SpecifierSet(dec.version_spec)
            except InvalidSpecifier:
                return f"version_spec '{dec.version_spec}' is not a valid PEP 440 specifier"
    return None


async def _one(dep: dict, py: str, others: list[str], log: gemma.CallLog) -> dict:
    usage_lines = [f"{l['file']}:{l['line']}: {l['code']}" for l in dep["usage"]["locations"][:40]]
    facts = {k: dep.get(k) for k in ("name", "pinned_version", "latest_version", "latest_release_date",
                                     "requires_python", "declared", "import_names", "group")}
    facts["risk_level"] = dep["risk"]["level"]
    facts["indicators"] = [{"code": i["code"], "detail": i["detail"]} for i in dep["risk"]["indicators"]]
    cands = await _candidate_health(dep)
    prompt = decide(py, facts, usage_lines, cands, others)
    for attempt in range(2):
        dec = await gemma.complete_json(log, f"decide:{dep['name']}", prompt, Decision)
        if dec is None:
            break
        err = await _validate(dec)
        if not err:
            out = dec.model_dump()
            if out["strategy"] in ("stdlib", "remove"):
                out["version_spec"] = None
            out["provenance"] = "ai"
            return out
        prompt += f"\n\nYour previous decision was rejected: {err}. Fix it and reply with ONLY the JSON."
    return _fallback(dep)


async def run(job_dir: Path, py: str, min_level: str, log: gemma.CallLog) -> dict:
    deps = state.merged_dependencies(job_dir)
    others = [d["name"] for d in deps]
    todo = [d for d in deps if _needs_proposal(d, min_level)]
    results = await asyncio.gather(*(_one(d, py, others, log) for d in todo))
    proposals = {d["name"]: r for d, r in zip(todo, results)}
    for d in deps:
        if d["name"] in proposals:
            continue
        latest = d.get("latest_version")
        codes = {i["code"] for i in d["risk"]["indicators"]}
        strat = "upgrade" if "OUTDATED" in codes and latest else "keep"
        proposals[d["name"]] = {"strategy": strat, "package": d["name"],
                                "version_spec": f">={latest}" if strat == "upgrade" else None,
                                "rationale": "Low risk; no migration needed." if strat == "keep" else "Minor update available.",
                                "confidence": 0.9, "alternatives": [], "steps": [], "code_changes_needed": False,
                                "suggested_tests": [], "open_concerns": [], "provenance": "derived"}
    return {"proposals": proposals}
