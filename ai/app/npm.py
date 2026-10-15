"""npm ecosystem — scan-only support.

What is analysed for JavaScript/TypeScript repositories (no code is executed):
  * package.json (+ package-lock.json for installed versions), with file:line evidence
  * npm registry facts (latest version, release dates, deprecation messages) and OSV advisories (ecosystem "npm")
  * where each package is imported (ES imports, re-exports, require(), dynamic import(), CSS @import/@plugin)
  * blast radius through the project's own relative imports
Migration and Docker verification are Python-only for now; the capsule says so explicitly.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from pathlib import Path

from . import blast, registry, risk

CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}
STYLE_EXT = {".css", ".scss", ".sass", ".less", ".pcss"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "out", ".next", ".nuxt", "coverage", ".turbo", ".cache",
             ".svelte-kit", ".vercel", ".output", "vendor"}
NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants", "crypto", "dgram", "dns",
    "domain", "events", "fs", "http", "http2", "https", "inspector", "module", "net", "os", "path", "perf_hooks",
    "process", "punycode", "querystring", "readline", "repl", "stream", "string_decoder", "sys", "timers", "tls",
    "trace_events", "tty", "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib", "test",
}
DEP_GROUPS = [("dependencies", "main"), ("devDependencies", "dev"), ("peerDependencies", "peer"),
              ("optionalDependencies", "optional")]
TWO_YEARS = 730

# patterns are applied per line; `from '...'` also catches the last line of multi-line imports
PATTERNS = [
    (re.compile(r"""\bfrom\s+['"]([^'"]+)['"]"""), "from_import"),
    (re.compile(r"""^\s*import\s+['"]([^'"]+)['"]"""), "import"),
    (re.compile(r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)"""), "import"),
    (re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)"""), "call"),
]
STYLE_PATTERN = re.compile(r"""@(?:import|plugin|use|forward|config)\s+(?:url\()?['"]([^'"]+)['"]""")


def is_npm_repo(repo: Path) -> bool:
    return (repo / "package.json").is_file()


def is_test_file(rel: str) -> bool:
    return bool(re.search(r"(\.(test|spec)\.[cm]?[jt]sx?$)|(^|/)__tests__/|(^|/)(tests?|e2e)/", rel))


def source_files(repo: Path) -> list[Path]:
    out = []
    for p in repo.rglob("*"):
        if not p.is_file() or (p.suffix not in CODE_EXT and p.suffix not in STYLE_EXT):
            continue
        parts = p.relative_to(repo).parts[:-1]
        if any(x in SKIP_DIRS or x.startswith(".") for x in parts):
            continue
        out.append(p)
    return sorted(out)


def package_of(spec: str) -> str | None:
    """'react-dom/client' -> 'react-dom', '@tailwindcss/vite' -> '@tailwindcss/vite'; None for local/builtin."""
    if not spec or spec.startswith((".", "/", "#", "~/", "@/", "virtual:", "data:", "http:", "https:", "\0")):
        return None
    if spec.startswith("node:"):
        return None
    if spec.startswith("@"):
        parts = spec.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else None
    name = spec.split("/")[0]
    return None if name in NODE_BUILTINS else name


def _semver(v: str | None) -> tuple[int, int, int] | None:
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", v or "")
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)) if m else None


def _lower_bound(spec: str) -> str | None:
    m = re.search(r"(\d+(?:\.\d+){0,2}(?:-[\w.]+)?)", spec or "")
    return m.group(1) if m else None


def _days_since(iso: str | None) -> int | None:
    try:
        return (date.today() - datetime.fromisoformat((iso or "")[:10]).date()).days if iso else None
    except ValueError:
        return None


def _ind(code, severity, detail, evidence, provenance="evidence", **extra):
    return {"code": code, "severity": severity, "detail": detail, "evidence": evidence, "provenance": provenance, **extra}


def _line_of(lines: list[str], needle: str) -> int:
    for i, l in enumerate(lines, 1):
        if needle in l:
            return i
    return 1


def manifests(repo: Path) -> tuple[list[dict], dict[str, str], list[str]]:
    """Declarations [{name, file, line, spec, group}], installed versions from the lockfile, notes."""
    pkg_path = repo / "package.json"
    text = pkg_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    notes: list[str] = []
    try:
        pkg = json.loads(text)
    except json.JSONDecodeError as e:
        return [], {}, [f"package.json is not valid JSON: {e}"]
    decls = []
    for key, group in DEP_GROUPS:
        for name, spec in (pkg.get(key) or {}).items():
            decls.append({"name": name, "file": "package.json", "line": _line_of(lines, f'"{name}"'),
                          "spec": f"{name}@{spec}", "range": str(spec), "group": group})
    installed: dict[str, str] = {}
    lock = repo / "package-lock.json"
    if lock.is_file():
        try:
            data = json.loads(lock.read_text(encoding="utf-8", errors="replace"))
            for path, meta in (data.get("packages") or {}).items():  # lockfile v2/v3
                if path.startswith("node_modules/") and "/node_modules/" not in path[len("node_modules/"):]:
                    installed[path[len("node_modules/"):]] = meta.get("version", "")
            for name, meta in (data.get("dependencies") or {}).items():  # lockfile v1
                installed.setdefault(name, meta.get("version", ""))
        except json.JSONDecodeError:
            notes.append("package-lock.json is not valid JSON; installed versions taken from version ranges")
    else:
        for other in ("yarn.lock", "pnpm-lock.yaml", "bun.lockb"):
            if (repo / other).exists():
                notes.append(f"{other} is not parsed; installed versions taken from version ranges")
        if not any((repo / o).exists() for o in ("yarn.lock", "pnpm-lock.yaml", "bun.lockb")):
            notes.append("No lockfile: installed versions are approximated by the lower bound of each version range")
    return decls, installed, notes


def imports(repo: Path) -> dict[str, list[dict]]:
    """package -> usage locations; also returns nothing for local/builtin specifiers."""
    found: dict[str, list[dict]] = {}
    for p in source_files(repo):
        rel = p.relative_to(repo).as_posix()
        style = p.suffix in STYLE_EXT
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if s.startswith(("//", "*", "/*")):
                continue
            pats = [(STYLE_PATTERN, "import")] if style else PATTERNS
            for rx, kind in pats:
                for m in rx.finditer(line):
                    pkg = package_of(m.group(1))
                    if pkg:
                        found.setdefault(pkg, []).append({"file": rel, "line": i, "col": m.start(1), "code": s[:240],
                                                          "kind": kind, "symbol": m.group(1)})
    return found


def import_graph(repo: Path) -> dict[str, set[str]]:
    """file -> project files it imports through relative specifiers (for the blast radius)."""
    files = source_files(repo)
    rels = {f.relative_to(repo).as_posix() for f in files}
    graph: dict[str, set[str]] = {r: set() for r in rels if Path(r).suffix in CODE_EXT}
    exts = ["", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"]
    for f in files:
        rel = f.relative_to(repo).as_posix()
        if rel not in graph:
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            for rx, _ in PATTERNS:
                for m in rx.finditer(line):
                    spec = m.group(1)
                    if not spec.startswith("."):
                        continue
                    base = (Path(rel).parent / spec).as_posix()
                    parts = []
                    for seg in base.split("/"):
                        if seg == "..":
                            if parts:
                                parts.pop()
                        elif seg not in (".", ""):
                            parts.append(seg)
                    target = "/".join(parts)
                    for cand in [target + e for e in exts] + [f"{target}/index{e}" for e in exts[1:]]:
                        if cand in graph and cand != rel:
                            graph[rel].add(cand)
                            break
    return graph


async def scan(repo: Path) -> dict:
    decls, installed, notes = manifests(repo)
    used = imports(repo)
    by_name: dict[str, list[dict]] = {}
    for d in decls:
        by_name.setdefault(d["name"], []).append(d)
    undeclared = sorted(p for p in used if p not in by_name)
    names = list(by_name) + undeclared
    pinned = {}
    for n in names:
        rng = by_name[n][0]["range"] if n in by_name else ""
        pinned[n] = installed.get(n) or (_lower_bound(rng) if rng and not rng.startswith(("file:", "link:", "git", "http", "workspace:")) else None)
    facts_list = await asyncio.gather(*(registry.npm_package(n) for n in names))
    facts = dict(zip(names, facts_list))
    for n in [n for n, f in facts.items() if f is None]:  # transient network failure: retry once
        facts[n] = await registry.npm_package(n)
    failed_lookups = [n for n, f in facts.items() if f is None]
    if failed_lookups:
        notes.append("npm registry lookup failed (network) for " + ", ".join(failed_lookups) +
                     "; their freshness and deprecation status could not be checked")
    vulns_list = await asyncio.gather(*(registry.osv_query(n, pinned[n], "npm") if pinned[n] else asyncio.sleep(0, None)
                                        for n in names))
    vulns = dict(zip(names, vulns_list))

    # packages that imported packages need at runtime (dependencies + peers): declared-but-not-imported is then fine
    needed_by: dict[str, str] = {}
    for n in names:
        if n in used and facts[n] and not facts[n].get("_missing"):
            meta = (facts[n].get("versions") or {}).get(pinned[n] or "") or {}
            for sub in (meta.get("dependencies") or []) + (meta.get("peers") or []):
                needed_by.setdefault(sub, n)

    deps = []
    for name in names:
        ds, f, pv = by_name.get(name, []), facts[name], pinned[name]
        inds: list[dict] = []
        ev_reg = {"source": "npm", "url": f"https://www.npmjs.com/package/{name}"}
        if not ds:
            detail = "Imported but not declared in package.json"
            if name in installed:
                detail += "; only present transitively in package-lock.json"
            inds.append(_ind("UNDECLARED", "medium", detail,
                             [{"source": "ast", "ref": f"{l['file']}:{l['line']}"} for l in used[name][:3]]))
        else:
            group = ds[0]["group"]
            if name not in used and group == "main" and not name.startswith("@types/") and name not in needed_by:
                inds.append(_ind("DECLARED_UNUSED", "low", "Declared in dependencies but never imported",
                                 [{"source": "ast", "detail": f"0 imports of {name}"}]))
            rng = ds[0]["range"].strip()
            if rng in ("*", "", "latest", "x") or rng.startswith(("git", "http", "github:")):
                inds.append(_ind("UNPINNED", "low", f"Unbounded version range '{rng or '*'}'",
                                 [{"source": "manifest", "ref": f"package.json:{ds[0]['line']}"}]))
        if f and not f.get("_missing"):
            latest = f.get("latest")
            pv_t, lv_t = _semver(pv), _semver(latest)
            if pv_t and lv_t and lv_t > pv_t:
                majors = lv_t[0] - pv_t[0]
                if majors >= 1 or (pv_t[0] == 0 and lv_t[1] > pv_t[1]):  # 0.x: a minor bump is breaking in semver
                    inds.append(_ind("MAJOR_VERSIONS_BEHIND", "medium", f"Installed {pv}, latest {latest} ({max(majors, 1)} major behind)",
                                     [ev_reg], "derived", majors=max(majors, 1)))
                else:
                    inds.append(_ind("OUTDATED", "low", f"Installed {pv}, latest {latest}", [ev_reg], "derived"))
            age = _days_since(f.get("latest_time"))
            if age is not None and age > TWO_YEARS:
                inds.append(_ind("UNMAINTAINED", "medium", f"No release since {f['latest_time'][:10]} ({age // 365} years)", [ev_reg]))
            dep_msg = ((f.get("versions") or {}).get(pv or "") or {}).get("deprecated") or f.get("deprecated_latest")
            if dep_msg:
                inds.append(_ind("DEPRECATED_PACKAGE", "high", f"npm deprecation notice: {str(dep_msg)[:200]}",
                                 [{**ev_reg, "detail": str(dep_msg)[:200]}]))
        elif f and f.get("_missing"):
            inds.append(_ind("UNMAINTAINED", "medium", "Package not found on the npm registry", [{"source": "npm", "detail": "404"}]))
        vs = vulns.get(name) or []
        if vs:
            sev = "critical" if any(str((v.get("database_specific") or {}).get("severity", "")).upper() == "CRITICAL" for v in vs) else "high"
            inds.append(_ind("KNOWN_VULNERABILITY", sev, f"{len(vs)} advisories affect {pv}",
                             [{"source": "osv", "ref": v.get("id"), "url": f"https://osv.dev/vulnerability/{v.get('id')}",
                               "detail": (v.get("summary") or "")[:160]} for v in vs[:8]], count=len(vs)))
        s, lvl = risk.score(inds)
        deps.append({
            "name": name, "import_names": [name],
            "declared": [{"file": d["file"], "line": d["line"], "spec": d["spec"]} for d in ds],
            "group": ds[0]["group"] if ds else "main",
            "pinned_version": pv, "latest_version": (f or {}).get("latest"),
            "latest_release_date": ((f or {}).get("latest_time") or "")[:10] or None,
            "last_release_of_pinned": ((((f or {}).get("versions") or {}).get(pv or "") or {}).get("time") or "")[:10] or None,
            "requires_python": None, "homepage": (f or {}).get("homepage"),
            "risk": {"level": lvl, "score": s, "indicators": inds,
                     "rationale": ("; ".join(i["detail"] for i in inds[:3]) + ".") if inds else "No risk indicators found.",
                     "rationale_provenance": "derived"},
        })
    deps.sort(key=lambda d: -d["risk"]["score"])
    notes.append("npm support is scan-only: dependencies are analysed and replacements proposed, but code migration "
                 "and Docker verification are not run for npm projects yet")
    return {"ecosystem": "npm", "manifests": ["package.json"] + (["package-lock.json"] if (repo / "package-lock.json").is_file() else []),
            "install_files": [], "local_packages": [], "dependencies": deps, "notes": notes}


def usage(repo: Path, scan_out: dict) -> dict:
    used = imports(repo)
    out: dict[str, dict] = {}
    for d in scan_out["dependencies"]:
        locs = used.get(d["name"], [])
        files = sorted({l["file"] for l in locs}, key=lambda f: (is_test_file(f), f))
        out[d["name"]] = {"locations": locs, "files": files,
                          "summary": (f"Imported in {len(files)} file(s): {', '.join(files[:4])}." if locs
                                      else "Not imported anywhere in the source (may be used by tooling or config)."),
                          "summary_provenance": "derived"}
    return {"usage": out, "extra_indicators": {},
            "blast_radius": blast.compute(repo, out, graph=import_graph(repo), is_test=is_test_file)}
