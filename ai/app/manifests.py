"""Parse dependency manifests with file:line provenance."""
from __future__ import annotations

import configparser
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class Decl:
    name: str
    file: str
    line: int
    spec: str               # raw requirement text, e.g. "Jinja2==2.11.3"
    specifier: str          # e.g. "==2.11.3"
    group: str = "main"     # main | dev | optional | build
    marker: str | None = None

    def to_api(self) -> dict:
        return {"file": self.file, "line": self.line, "spec": self.spec}


@dataclass
class ManifestSet:
    manifests: list[str] = field(default_factory=list)
    install_files: list[str] = field(default_factory=list)
    decls: list[Decl] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _parse_req(text: str) -> Requirement | None:
    try:
        return Requirement(text)
    except InvalidRequirement:
        return None


def _parse_requirements_file(repo: Path, rel: str, out: ManifestSet, seen: set[str], group: str) -> None:
    if rel in seen:
        return
    seen.add(rel)
    path = repo / rel
    if not path.is_file():
        return
    out.manifests.append(rel)
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            body = line.lstrip("#").strip()
            if _parse_req(body) and re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*\s*[=<>!~]", body):
                out.notes.append(f"{rel}:{i} commented-out requirement '{body}' (ignored)")
            continue
        if line.startswith(("-r ", "--requirement ")):
            inc = line.split(None, 1)[1].strip()
            inc_rel = str((Path(rel).parent / inc).as_posix())
            _parse_requirements_file(repo, inc_rel, out, seen, group)
            continue
        if line.startswith("-"):
            continue
        line = line.split(" #", 1)[0].strip()
        req = _parse_req(line)
        if not req:
            out.notes.append(f"{rel}:{i} could not parse '{line}'")
            continue
        out.decls.append(Decl(normalize(req.name), rel, i, line, str(req.specifier), group,
                              str(req.marker) if req.marker else None))


def _find_line(lines: list[str], needle: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i + 1
    return 1


def _parse_pyproject(repo: Path, out: ManifestSet) -> None:
    path = repo / "pyproject.toml"
    if not path.is_file():
        return
    out.manifests.append("pyproject.toml")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        out.notes.append(f"pyproject.toml is not valid TOML: {e}")
        return
    project = data.get("project", {})
    groups: list[tuple[str, list[str]]] = [("main", project.get("dependencies", []))]
    for extra, deps in (project.get("optional-dependencies") or {}).items():
        groups.append((f"optional:{extra}", deps))
    for group, deps in groups:
        for d in deps:
            req = _parse_req(d)
            if not req:
                continue
            line = _find_line(lines, f'"{d}"') if f'"{d}"' in text else _find_line(lines, d)
            out.decls.append(Decl(normalize(req.name), "pyproject.toml", line, d, str(req.specifier),
                                  "main" if group == "main" else "optional",
                                  str(req.marker) if req.marker else None))
    build = data.get("build-system", {}).get("requires", [])
    if build:
        out.notes.append(f"pyproject.toml build-system requires {', '.join(build)} (not risk-scored)")
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies")
    if poetry:
        out.notes.append("Poetry dependencies detected but not analysed (unsupported in this version)")


def _parse_setup_cfg(repo: Path, out: ManifestSet) -> None:
    path = repo / "setup.cfg"
    if not path.is_file():
        return
    cp = configparser.ConfigParser()
    try:
        cp.read(path, encoding="utf-8")
    except configparser.Error:
        return
    raw = cp.get("options", "install_requires", fallback="")
    if not raw.strip():
        return
    out.manifests.append("setup.cfg")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for d in (x.strip() for x in raw.splitlines() if x.strip()):
        req = _parse_req(d)
        if req:
            out.decls.append(Decl(normalize(req.name), "setup.cfg", _find_line(lines, d), d, str(req.specifier)))


def discover(repo: Path) -> ManifestSet:
    out = ManifestSet()
    seen: set[str] = set()
    req_files = sorted(p.name for p in repo.glob("requirements*.txt"))
    # main requirements first, then dev-ish
    req_files.sort(key=lambda n: (n != "requirements.txt", n))
    for name in req_files:
        group = "main" if name == "requirements.txt" else "dev"
        before = len(out.manifests)
        _parse_requirements_file(repo, name, out, seen, group)
        if len(out.manifests) > before:
            out.install_files.append(name)
    _parse_pyproject(repo, out)
    _parse_setup_cfg(repo, out)
    if (repo / "setup.py").is_file():
        out.manifests.append("setup.py")
        out.notes.append("setup.py present; install_requires in setup.py is not parsed")
    return out


def pinned_version(specifier: str) -> str | None:
    m = re.fullmatch(r"===?\s*([^,*\s]+)", specifier.strip())
    return m.group(1) if m else None


def specs_compatible(specs: list[str]) -> tuple[bool, str]:
    """True if some version could satisfy all specifiers (checked via the pinned versions)."""
    pins = [p for p in (pinned_version(s) for s in specs) if p]
    if len(set(pins)) > 1:
        return False, f"different pins: {', '.join(sorted(set(pins)))}"
    if pins:
        try:
            v = Version(pins[0])
        except InvalidVersion:
            return True, ""
        for s in specs:
            if s and not SpecifierSet(s).contains(v, prereleases=True):
                return False, f"pinned {pins[0]} does not satisfy '{s}'"
    return True, ""
