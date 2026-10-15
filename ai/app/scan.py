"""Stage 2 — dependency discovery, registry facts, risk indicators and score."""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from . import gemma, knowledge, manifests, prompts, pysrc, registry, risk
from .manifests import normalize

TWO_YEARS_DAYS = 730


def _ind(code: str, severity: str, detail: str, evidence: list[dict], provenance: str = "evidence", **extra) -> dict:
    return {"code": code, "severity": severity, "detail": detail, "evidence": evidence, "provenance": provenance, **extra}


def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (date.today() - datetime.fromisoformat(iso[:10]).date()).days
    except ValueError:
        return None


def _parse_version(v: str | None) -> Version | None:
    try:
        return Version(v) if v else None
    except InvalidVersion:
        return None


def _py_tuple(py: str) -> tuple[int, int]:
    a, b = (py.split(".") + ["0"])[:2]
    return int(a), int(b)


def _osv_severity(v: dict) -> str:
    sev = (v.get("database_specific") or {}).get("severity", "")
    return "critical" if str(sev).upper() == "CRITICAL" else "high"


async def _facts(name: str, pinned: str | None) -> dict:
    proj = await registry.pypi_project(name)
    facts: dict = {"exists": proj is not None}
    if not proj:
        return facts
    info = proj.get("info", {})
    latest = info.get("version")
    facts.update(latest_version=latest, latest_release_date=registry.release_date(proj, latest) if latest else None,
                 homepage=info.get("home_page") or (info.get("project_urls") or {}).get("Homepage")
                 or info.get("project_url"),
                 summary=info.get("summary") or "", classifiers=info.get("classifiers") or [],
                 requires_python=info.get("requires_python"))
    if pinned:
        rel = await registry.pypi_release(name, pinned)
        if rel:
            rinfo = rel.get("info", {})
            facts["requires_python_pinned"] = rinfo.get("requires_python")
            facts["requires_dist_pinned"] = rinfo.get("requires_dist") or []
            facts["classifiers_pinned"] = rinfo.get("classifiers") or []
            facts["yanked"] = bool(rinfo.get("yanked"))
            facts["yanked_reason"] = rinfo.get("yanked_reason")
        facts["last_release_of_pinned"] = registry.release_date(proj, pinned)
        facts["vulns"] = await registry.osv_query(name, pinned)
    else:
        facts["requires_dist_pinned"] = info.get("requires_dist") or []
    return facts


def _requires_names(requires_dist: list[str]) -> set[str]:
    out = set()
    for r in requires_dist or []:
        try:
            req = Requirement(r)
        except InvalidRequirement:
            continue
        if req.marker and "extra" in str(req.marker):
            continue
        out.add(normalize(req.name))
    return out


async def run(repo: Path, py: str, log: gemma.CallLog) -> dict:
    ms = manifests.discover(repo)
    imports = pysrc.top_level_imports(repo)
    local = pysrc.local_packages(repo)
    third_party = {m: locs for m, locs in imports.items() if m not in pysrc.STDLIB and m not in local}

    # group declarations per package
    by_name: dict[str, list[manifests.Decl]] = {}
    for d in ms.decls:
        by_name.setdefault(d.name, []).append(d)

    # import name -> declared dist
    import_owner: dict[str, str] = {}
    for name in by_name:
        for imp in knowledge.import_names_for(name):
            import_owner[imp.split(".")[0]] = name
    undeclared: dict[str, list[tuple[str, int]]] = {}
    for mod, locs in third_party.items():
        if mod in import_owner:
            continue
        dist = knowledge.dist_for_import(mod)
        if dist in by_name:
            import_owner[mod] = dist
        else:
            undeclared.setdefault(dist, []).extend(locs)
            import_owner[mod] = dist

    names = list(by_name) + [n for n in undeclared if n not in by_name]
    pins: dict[str, str | None] = {}
    for name in names:
        decls = by_name.get(name, [])
        # the version actually installed comes from the install files (requirements*.txt) first
        ordered = sorted(decls, key=lambda d: d.file not in ms.install_files)
        pins[name] = next((p for p in (manifests.pinned_version(d.specifier) for d in ordered) if p), None)

    facts_list = await asyncio.gather(*(_facts(n, pins[n]) for n in names))
    facts = dict(zip(names, facts_list))

    # who brings undeclared deps transitively
    transitive: dict[str, list[str]] = {}
    for name in by_name:
        for sub in _requires_names(facts[name].get("requires_dist_pinned", [])):
            transitive.setdefault(sub, []).append(name)

    py_t = _py_tuple(py)
    deps = []
    for name in names:
        decls = by_name.get(name, [])
        f = facts[name]
        pinned = pins[name]
        inds: list[dict] = []
        imp_names = sorted({m for m, owner in import_owner.items() if owner == name} or
                           set(knowledge.import_names_for(name)))
        used = any(m in third_party for m in imp_names)

        if not decls:
            via = transitive.get(name)
            detail = "Imported but not declared in any manifest"
            if via:
                detail += f"; only available transitively via {', '.join(via)}"
            ev = [{"source": "ast", "ref": f"{fl}:{ln}"} for fl, ln in undeclared[name][:3]]
            if via:
                ev.append({"source": "pypi", "detail": f"{via[0]} requires {name}"})
            inds.append(_ind("UNDECLARED", "medium", detail, ev))
        else:
            ok, why = manifests.specs_compatible([d.specifier for d in decls])
            if not ok:
                inds.append(_ind("MANIFEST_DRIFT", "medium", f"Manifests disagree: {why}",
                                 [{"source": "manifest", "ref": f"{d.file}:{d.line}", "detail": d.spec} for d in decls]))
            if not used and name not in knowledge.TOOL_PACKAGES:
                inds.append(_ind("DECLARED_UNUSED", "low", "Declared but never imported",
                                 [{"source": "ast", "detail": f"0 imports of {', '.join(imp_names)}"}]))
            if all(not d.specifier for d in decls):
                inds.append(_ind("UNPINNED", "low", "No version constraint",
                                 [{"source": "manifest", "ref": f"{decls[0].file}:{decls[0].line}"}]))

        if f.get("exists"):
            latest = f.get("latest_version")
            pv, lv = _parse_version(pinned), _parse_version(latest)
            pypi_ev = {"source": "pypi", "url": f"https://pypi.org/project/{name}/"}
            vulns = f.get("vulns") or []
            if vulns:
                ids = [v.get("id") for v in vulns]
                fixed = sorted({e.get("fixed") for v in vulns for a in v.get("affected", []) for r in a.get("ranges", [])
                                for e in r.get("events", []) if e.get("fixed")}, key=lambda s: _parse_version(s) or Version("0"))
                detail = f"{len(vulns)} advisories affect {pinned}"
                if fixed:
                    detail += f"; fixed in {fixed[-1]}"
                sev = "critical" if any(_osv_severity(v) == "critical" for v in vulns) else "high"
                inds.append(_ind("KNOWN_VULNERABILITY", sev, detail,
                                 [{"source": "osv", "ref": v.get("id"), "url": f"https://osv.dev/vulnerability/{v.get('id')}",
                                   "detail": (v.get("summary") or "")[:160]} for v in vulns[:8]], count=len(vulns)))
            if pv and lv and lv > pv:
                majors = lv.major - pv.major
                if majors >= 1:
                    inds.append(_ind("MAJOR_VERSIONS_BEHIND", "medium",
                                     f"Pinned {pinned}, latest {latest} ({majors} major{'s' if majors > 1 else ''} behind)",
                                     [pypi_ev], "derived", majors=majors))
                else:
                    inds.append(_ind("OUTDATED", "low", f"Pinned {pinned}, latest {latest}", [pypi_ev], "derived"))
            age = _days_since(f.get("latest_release_date"))
            if age is not None and age > TWO_YEARS_DAYS:
                inds.append(_ind("UNMAINTAINED", "medium",
                                 f"No release since {f['latest_release_date']} ({age // 365} years)", [pypi_ev]))
            inactive = any("Development Status :: 7 - Inactive" in c for c in f.get("classifiers", []))
            deprecated_text = re.search(r"\b(deprecated|no longer maintained|unmaintained)\b", f.get("summary", ""), re.I)
            if name in knowledge.DEPRECATED_PACKAGES or inactive or deprecated_text:
                ev = []
                if name in knowledge.DEPRECATED_PACKAGES:
                    ev.append({"source": "knowledge", "detail": knowledge.DEPRECATED_PACKAGES[name]})
                if inactive:
                    ev.append({"source": "pypi", "detail": "Classifier: Development Status :: 7 - Inactive", "url": pypi_ev["url"]})
                if deprecated_text:
                    ev.append({"source": "pypi", "detail": f"Summary: {f.get('summary')}", "url": pypi_ev["url"]})
                inds.append(_ind("DEPRECATED_PACKAGE", "high",
                                 knowledge.DEPRECATED_PACKAGES.get(name, "Marked deprecated/inactive on PyPI"), ev))
            if name in knowledge.STDLIB_REPLACEMENTS:
                mod, since = knowledge.STDLIB_REPLACEMENTS[name]
                if py_t >= since:
                    inds.append(_ind("STDLIB_REPLACEMENT_AVAILABLE", "medium",
                                     f"Standard library alternative: {mod} (Python {since[0]}.{since[1]}+)",
                                     [{"source": "knowledge", "detail": f"{name} -> {mod}"}]))
            if f.get("yanked"):
                inds.append(_ind("YANKED", "high", f"{pinned} was yanked: {f.get('yanked_reason') or 'no reason given'}", [pypi_ev]))
            # metadata-only Python compatibility signal (strong signal comes later from the sandbox)
            rp = f.get("requires_python_pinned")
            if rp:
                try:
                    if not SpecifierSet(rp).contains(Version(f"{py_t[0]}.{py_t[1]}")):
                        inds.append(_ind("PY312_INCOMPATIBLE", "high", f"{pinned} declares requires_python '{rp}'", [pypi_ev]))
                except (InvalidVersion, ValueError):
                    pass
            pinned_age = _days_since(f.get("last_release_of_pinned"))
            cls = f.get("classifiers_pinned") or []
            py3x = [c for c in cls if re.match(r"Programming Language :: Python :: 3\.\d+$", c)]
            if pinned and pinned_age and pinned_age > TWO_YEARS_DAYS and py3x and not any(
                    c.endswith(f"3.{py_t[1]}") for c in py3x):
                newest = max(py3x, key=lambda c: int(c.rsplit(".", 1)[1])).rsplit(" ", 1)[1]
                if not any(i["code"] == "PY312_INCOMPATIBLE" for i in inds):
                    inds.append(_ind("PY312_INCOMPATIBLE", "low",
                                     f"{pinned} ({f.get('last_release_of_pinned')}) only declares support up to Python {newest}",
                                     [pypi_ev]))
        else:
            inds.append(_ind("UNMAINTAINED", "medium", "Package not found on PyPI", [{"source": "pypi", "detail": "404"}]))

        s, lvl = risk.score(inds)
        deps.append({
            "name": name,
            "import_names": imp_names,
            "declared": [d.to_api() for d in decls],
            "group": decls[0].group if decls else "main",
            "pinned_version": pinned,
            "latest_version": f.get("latest_version"),
            "latest_release_date": f.get("latest_release_date"),
            "last_release_of_pinned": f.get("last_release_of_pinned"),
            "requires_python": f.get("requires_python_pinned") or f.get("requires_python"),
            "homepage": f.get("homepage"),
            "risk": {"level": lvl, "score": s, "indicators": inds, "rationale": "", "rationale_provenance": "derived"},
        })

    for d in deps:
        if not d["risk"]["rationale"]:
            inds = d["risk"]["indicators"]
            d["risk"]["rationale"] = ("; ".join(i["detail"] for i in inds[:3]) + ".") if inds else "No risk indicators found."

    deps.sort(key=lambda d: -d["risk"]["score"])
    return {"manifests": ms.manifests, "install_files": ms.install_files or ["requirements.txt"],
            "local_packages": sorted(local), "dependencies": deps, "notes": ms.notes}
