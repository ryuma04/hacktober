"""Python source discovery and parsing helpers (never imports or executes target code)."""
from __future__ import annotations

import ast
import sys
from functools import lru_cache
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "env", "build", "dist", "node_modules", "__pycache__", ".tox", ".eggs",
             ".depexit", "site-packages"}
STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def py_files(repo: Path) -> list[Path]:
    out = []
    for p in repo.rglob("*.py"):
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in p.relative_to(repo).parts[:-1]):
            continue
        out.append(p)
    return sorted(out)


def rel(repo: Path, p: Path) -> str:
    return p.relative_to(repo).as_posix()


@lru_cache(maxsize=512)
def _parse_cached(path: str, mtime: float) -> tuple[ast.Module | None, list[str]]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    try:
        return ast.parse(text), text.splitlines()
    except SyntaxError:
        return None, text.splitlines()


def parse(p: Path) -> tuple[ast.Module | None, list[str]]:
    return _parse_cached(str(p), p.stat().st_mtime)


def local_packages(repo: Path) -> set[str]:
    names = set()
    for base in (repo, repo / "src"):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "__init__.py").exists():
                names.add(child.name)
            elif child.suffix == ".py":
                names.add(child.stem)
    for d in ("tests", "test", "testing"):
        names.add(d)
    names.add("conftest")
    return names


def is_test_file(relpath: str) -> bool:
    parts = relpath.split("/")
    return parts[0] in {"tests", "test"} or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def top_level_imports(repo: Path) -> dict[str, list[tuple[str, int]]]:
    """module -> [(file, line)] for absolute imports (top-level package only)."""
    found: dict[str, list[tuple[str, int]]] = {}
    for p in py_files(repo):
        tree, _ = parse(p)
        if tree is None:
            continue
        r = rel(repo, p)
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for m in mods:
                found.setdefault(m.split(".")[0], []).append((r, node.lineno))
    return found
