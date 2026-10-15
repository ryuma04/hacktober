"""Blast radius: which project code breaks if a dependency is removed or changes its API.

Direct impact comes from the AST usage locations. Indirect impact follows the project's own import graph
backwards: a module that imports a directly affected module is affected too (with the import chain as evidence).
Tests are affected when they import affected code directly, through other modules, or through a conftest.py
that pytest loads for them."""
from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

from . import pysrc


def _module_name(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def import_graph(repo: Path) -> dict[str, set[str]]:
    """file -> set of project files it imports (absolute and relative imports)."""
    files = [pysrc.rel(repo, p) for p in pysrc.py_files(repo)]
    by_module = {_module_name(f): f for f in files}
    graph: dict[str, set[str]] = {f: set() for f in files}
    for f in files:
        tree, _ = pysrc.parse(repo / f)
        if tree is None:
            continue
        pkg = _module_name(f) if f.endswith("__init__.py") else _module_name(f).rpartition(".")[0]
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg.split(".") if pkg else []
                    base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
                    mod = ".".join(base + ([node.module] if node.module else []))
                else:
                    mod = node.module or ""
                targets = [mod] + [f"{mod}.{a.name}" if mod else a.name for a in node.names]
            for t in targets:
                # longest prefix that is a project module (handles `from pkg import submodule`)
                parts = t.split(".")
                for i in range(len(parts), 0, -1):
                    hit = by_module.get(".".join(parts[:i]))
                    if hit and hit != f:
                        graph[f].add(hit)
                        break
    return graph


def _conftest_scope(conftest: str, test_files: list[str]) -> list[str]:
    base = conftest.rsplit("/", 1)[0] + "/" if "/" in conftest else ""
    return [t for t in test_files if t.startswith(base) and t != conftest]


def compute(repo: Path, usage: dict[str, dict], graph: dict[str, set[str]] | None = None,
            is_test=None) -> dict[str, dict]:
    """`graph` (file -> project files it imports) and `is_test` default to the Python implementations; other
    ecosystems (npm) pass their own."""
    graph = import_graph(repo) if graph is None else graph
    is_test = is_test or pysrc.is_test_file
    reverse: dict[str, set[str]] = {f: set() for f in graph}
    for src, dsts in graph.items():
        for d in dsts:
            reverse.setdefault(d, set()).add(src)
    test_files = sorted(f for f in graph if is_test(f) and not f.endswith("conftest.py"))
    out: dict[str, dict] = {}
    for dep, u in usage.items():
        locs = u.get("locations", [])
        if not locs:
            continue
        direct: dict[str, list[dict]] = {}
        for l in locs:  # one entry per line, listing every kind of use on it (import, call, private_api, ...)
            lines = direct.setdefault(l["file"], [])
            hit = next((x for x in lines if x["line"] == l["line"]), None)
            if hit:
                if l["kind"] not in hit["kinds"]:
                    hit["kinds"].append(l["kind"])
            else:
                lines.append({"line": l["line"], "kinds": [l["kind"]], "code": l["code"]})
        # BFS backwards through the import graph; remember how each file was reached
        via: dict[str, list[str]] = {f: [f] for f in direct}
        queue = deque(direct)
        while queue:
            cur = queue.popleft()
            for importer in sorted(reverse.get(cur, ())):
                if importer not in via:
                    via[importer] = [importer] + via[cur]
                    queue.append(importer)
        # pytest loads conftest.py for every test in its directory tree
        for conf in [f for f in via if f.endswith("conftest.py")]:
            for t in _conftest_scope(conf, test_files):
                if t not in via:
                    via[t] = [t] + via[conf]
        indirect = sorted(f for f in via if f not in direct and not is_test(f))
        tests = sorted(f for f in via if f in test_files)

        nodes = [{"id": f"dep:{dep}", "type": "dependency", "label": dep}]
        edges = []
        for f in sorted(direct):
            nodes.append({"id": f, "type": "test" if is_test(f) else "module", "label": f,
                          "impact": "direct", "lines": len(direct[f])})
            edges.append({"from": f, "to": f"dep:{dep}", "kind": "uses"})
        for f in sorted(set(via) - set(direct)):
            nodes.append({"id": f, "type": "test" if is_test(f) else "module", "label": f,
                          "impact": "indirect"})
            edges.append({"from": f, "to": via[f][1], "kind": "conftest" if via[f][1].endswith("conftest.py")
                          and f in test_files and via[f][1] not in graph.get(f, set()) else "imports"})
        out[dep] = {
            "direct": [{"file": f, "lines": sorted(direct[f], key=lambda x: x["line"])} for f in sorted(direct)],
            "indirect": [{"file": f, "via": via[f]} for f in indirect],
            "tests": [{"file": f, "via": via[f]} for f in tests],
            "nodes": nodes,
            "edges": edges,
            "stats": {"direct_files": len(direct), "lines": sum(len(v) for v in direct.values()),
                      "indirect_files": len(indirect), "test_files": len(tests),
                      "total_test_files": len(test_files)},
            "provenance": "evidence",
        }
    return out
