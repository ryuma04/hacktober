"""Stage 3 — where and how each dependency is used (AST only; target code is never imported)."""
from __future__ import annotations

import ast
from pathlib import Path

from . import blast, gemma, knowledge, prompts, pysrc


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _attr_chain(node: ast.AST) -> list[str]:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def _private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


class _Visitor(ast.NodeVisitor):
    def __init__(self, relpath: str, lines: list[str], import_map: dict[str, str]):
        self.rel, self.lines, self.import_map = relpath, lines, import_map
        self.aliases: dict[str, tuple[str, str]] = {}   # local name -> (dep, qualified symbol)
        self.locs: dict[str, list[dict]] = {}
        self.flags: dict[str, list[dict]] = {}
        self._seen: set[tuple] = set()

    def _code(self, line: int) -> str:
        return self.lines[line - 1].strip() if 0 < line <= len(self.lines) else ""

    def _add(self, dep: str, node: ast.AST, kind: str, symbol: str | None) -> None:
        key = (dep, node.lineno, kind)
        if key in self._seen:
            return
        self._seen.add(key)
        self.locs.setdefault(dep, []).append({"file": self.rel, "line": node.lineno, "col": node.col_offset,
                                              "code": self._code(node.lineno), "kind": kind, "symbol": symbol})

    def _flag(self, dep: str, code: str, node: ast.AST, detail: str, severity: str = "medium") -> None:
        self.flags.setdefault(dep, []).append({"code": code, "severity": severity, "detail": detail,
                                               "evidence": [{"source": "ast", "ref": f"{self.rel}:{node.lineno}",
                                                             "detail": self._code(node.lineno)}],
                                               "provenance": "evidence"})

    def _deprecated(self, dep: str, qual: str, node: ast.AST) -> None:
        for key, advice in knowledge.DEPRECATED_APIS.items():
            if qual == key or qual.startswith(key + "."):
                self._flag(dep, "DEPRECATED_API_USE", node, f"`{qual}`: {advice}")
                return

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            top = a.name.split(".")[0]
            dep = self.import_map.get(top)
            if not dep:
                continue
            local = a.asname or top
            self.aliases[local] = (dep, a.name if a.asname else top)
            self._add(dep, node, "import", a.name)
            self._deprecated(dep, a.name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or not node.module:
            return
        dep = self.import_map.get(node.module.split(".")[0])
        if not dep:
            return
        for a in node.names:
            qual = f"{node.module}.{a.name}"
            self.aliases[a.asname or a.name] = (dep, qual)
            self._add(dep, node, "from_import", a.name)
            self._deprecated(dep, qual, node)
            self._deprecated(dep, node.module, node)
            if _private(a.name) or any(_private(p) for p in node.module.split(".")):
                self._add(dep, node, "private_api", qual)
                self._flag(dep, "PRIVATE_API_USE", node, f"Imports private API `{qual}`")

    def _resolve(self, node: ast.AST) -> tuple[str, str] | None:
        chain = _attr_chain(node)
        if not chain or chain[0] not in self.aliases:
            return None
        dep, qual = self.aliases[chain[0]]
        return dep, ".".join([qual] + chain[1:])

    def visit_Call(self, node: ast.Call) -> None:
        r = self._resolve(node.func)
        if r:
            self._add(r[0], node, "call", r[1].split(".", 1)[-1])
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        r = self._resolve(node)
        if r and isinstance(node.ctx, ast.Load):
            dep, qual = r
            self._add(dep, node, "attribute", qual)
            self._deprecated(dep, qual, node)
            if any(_private(p) for p in qual.split(".")[1:]):
                self._add(dep, node, "private_api", qual)
                self._flag(dep, "PRIVATE_API_USE", node, f"Uses private API `{qual}`")
            return  # don't double count inner parts of the chain
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for t in node.targets:
            if isinstance(t, ast.Attribute):
                r = self._resolve(t)
                if r:
                    self._add(r[0], node, "monkeypatch", r[1])
                    self._flag(r[0], "MONKEYPATCH", node, f"Replaces `{r[1]}` at runtime (monkeypatch)")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for b in node.bases:
            r = self._resolve(b)
            if r:
                self._add(r[0], b, "subclass", r[1])
                pkg = r[0]
                if pkg in knowledge.V1_CONFIG_CLASS_PACKAGES and any(
                        isinstance(s, ast.ClassDef) and s.name == "Config" for s in node.body):
                    inner = next(s for s in node.body if isinstance(s, ast.ClassDef) and s.name == "Config")
                    self._flag(pkg, "DEPRECATED_API_USE", inner,
                               f"`{node.name}.Config`: {knowledge.V1_CONFIG_CLASS_PACKAGES[pkg]}")
        for d in node.decorator_list:
            self._decorator(d)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for d in node.decorator_list:
            self._decorator(d)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _decorator(self, d: ast.AST) -> None:
        r = self._resolve(d.func if isinstance(d, ast.Call) else d)
        if r:
            self._add(r[0], d, "decorator", r[1])


async def run(repo: Path, scan: dict, py: str, log: gemma.CallLog) -> dict:
    import_map: dict[str, str] = {}
    for d in scan["dependencies"]:
        for imp in d["import_names"]:
            import_map[imp.split(".")[0]] = d["name"]
    usage: dict[str, dict] = {d["name"]: {"locations": [], "files": [], "summary": "", "summary_provenance": "derived"}
                              for d in scan["dependencies"]}
    extra: dict[str, list[dict]] = {}
    for p in pysrc.py_files(repo):
        tree, lines = pysrc.parse(p)
        if tree is None:
            continue
        v = _Visitor(pysrc.rel(repo, p), lines, import_map)
        v.visit(tree)
        for dep, locs in v.locs.items():
            usage[dep]["locations"].extend(sorted(locs, key=lambda x: (x["line"], x["col"])))
        for dep, flags in v.flags.items():
            extra.setdefault(dep, []).extend(flags)
    for dep, u in usage.items():
        u["files"] = sorted({l["file"] for l in u["locations"]}, key=lambda f: (pysrc.is_test_file(f), f))
    # collapse duplicate flags (same code+location)
    for dep, flags in extra.items():
        uniq = {}
        for f in flags:
            uniq.setdefault((f["code"], f["evidence"][0]["ref"]), f)
        merged: dict[str, dict] = {}
        for f in uniq.values():
            if f["code"] in merged:
                merged[f["code"]]["evidence"].extend(f["evidence"])
                if f["detail"] not in merged[f["code"]]["detail"]:
                    merged[f["code"]]["detail"] += "; " + f["detail"]
            else:
                merged[f["code"]] = {**f, "evidence": list(f["evidence"])}
        extra[dep] = list(merged.values())

    for n, u in usage.items():
        if not u["summary"]:
            u["summary"] = (f"Used in {len(u['files'])} file(s): {', '.join(u['files'][:4])}."
                            if u["locations"] else "Not imported anywhere in the code.")
    return {"usage": usage, "extra_indicators": extra, "blast_radius": blast.compute(repo, usage)}
