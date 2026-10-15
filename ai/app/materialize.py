"""Stage 5 — build the migrated workspace: deterministic manifest rewrite + Gemma 4 code rewrites (validated)."""
from __future__ import annotations

import ast
import asyncio
import difflib
import re
import shutil
from pathlib import Path

from . import gemma, knowledge, pysrc, state
from .manifests import normalize
from .prompts import Rewrite, rewrite_file

CODE_STRATEGIES = {"replace", "stdlib", "remove", "upgrade"}


def _req_line(pkg: str, spec: str | None) -> str:
    spec = (spec or "").strip()
    if spec and spec[0] not in "<>=!~":
        spec = "==" + spec
    return f"{pkg}{spec}"


def _target(p: dict) -> str | None:
    """New requirement text for a proposal, or None if the declaration should be deleted."""
    s = p["strategy"]
    if s in ("stdlib", "remove"):
        return None
    if s in ("replace", "upgrade", "declare"):
        return _req_line(p["package"], p.get("version_spec"))
    return "KEEP"


def _rewrite_manifests(src: Path, dst: Path, deps: list[dict], proposals: dict, install_files: list[str]) -> list[dict]:
    edits: dict[str, dict[int, str | None]] = {}
    for d in deps:
        p = proposals.get(d["name"])
        if not p:
            continue
        new = _target(p)
        if new == "KEEP":
            continue
        for decl in d["declared"]:
            edits.setdefault(decl["file"], {})[decl["line"]] = new if decl["file"] != "pyproject.toml" else f"{decl['spec']}\x00{new or ''}"
    adds_req: list[str] = []
    adds_py: list[str] = []
    for d in deps:
        p = proposals.get(d["name"])
        if p and p["strategy"] == "declare" and not d["declared"]:
            line = _req_line(p["package"] or d["name"], p.get("version_spec"))
            adds_req.append(line)
            adds_py.append(line)

    changes = []
    for rel in sorted(set(edits) | ({install_files[0]} if adds_req and install_files else set())
                      | ({"pyproject.toml"} if adds_py and (src / "pyproject.toml").exists() else set())):
        path = dst / rel
        if not path.exists():
            continue
        before = path.read_text(encoding="utf-8")
        lines = before.splitlines()
        file_edits = edits.get(rel, {})
        out: list[str] = []
        for i, line in enumerate(lines, start=1):
            if i not in file_edits:
                out.append(line)
                continue
            if rel == "pyproject.toml":
                old_spec, new_spec = file_edits[i].split("\x00")
                if new_spec:
                    out.append(line.replace(f'"{old_spec}"', f'"{new_spec}"').replace(f"'{old_spec}'", f"'{new_spec}'"))
                else:
                    stripped = re.sub(rf"""\s*["']{re.escape(old_spec)}["']\s*,?""", "", line)
                    if stripped.strip():
                        out.append(stripped)
            else:
                if file_edits[i] is not None:
                    comment = line.split(" #", 1)[1] if " #" in line else None
                    out.append(file_edits[i] + (f"  #{comment}" if comment else ""))
        if rel == (install_files[0] if install_files else None):
            out.extend(adds_req)
        if rel == "pyproject.toml" and adds_py:
            text = "\n".join(out)
            m = re.search(r"(dependencies\s*=\s*\[)(.*?)(\n?\s*\])", text, re.DOTALL)
            if m:
                body = m.group(2).rstrip()
                indent = re.search(r"\n(\s+)\S", m.group(2))
                ind = indent.group(1) if indent else "    "
                sep = "" if body.endswith(",") or not body.strip() else ","
                body += sep + "".join(f'\n{ind}"{a}",' for a in adds_py)
                text = text[:m.start(2)] + body + text[m.end(2):]
                out = text.splitlines()
        after = "\n".join(out) + ("\n" if before.endswith("\n") else "")
        if after != before:
            path.write_text(after, encoding="utf-8")
            changes.append({"file": rel, "before": before, "after": after})
    return changes


def _imports(tree: ast.AST) -> set[str]:
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            mods.add(n.module.split(".")[0])
    return mods


def _validate(rel: str, original: str, new: str, allowed: set[str], before_imports: set[str]) -> str | None:
    if not new.strip():
        return "empty file returned"
    ratio = len(new) / max(1, len(original))
    if not 0.5 <= ratio <= 2.0:
        return f"size changed too much ({ratio:.1f}x)"
    try:
        tree = ast.parse(new)
        compile(new, rel, "exec")
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"
    added = _imports(tree) - before_imports - pysrc.STDLIB - allowed
    if added:
        return f"introduces unexpected imports: {', '.join(sorted(added))}"
    return None


async def run(job_dir: Path, repo: Path, out_repo: Path, py: str, log: gemma.CallLog) -> dict:
    scan = state.read(job_dir, "scan.json")
    proposals = state.read(job_dir, "proposals.json")["proposals"]
    deps = state.merged_dependencies(job_dir)

    if out_repo.exists():
        shutil.rmtree(out_repo)
    shutil.copytree(repo, out_repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".depexit"))
    manifest_changes = _rewrite_manifests(repo, out_repo, deps, proposals, scan["install_files"])

    # imports the migrated code may use: local packages + every remaining/new dependency's import names
    allowed = set(scan.get("local_packages", []))
    for d in deps:
        allowed |= {i.split(".")[0] for i in d["import_names"]}
    for p in proposals.values():
        if p.get("package"):
            allowed |= {i.split(".")[0] for i in knowledge.import_names_for(normalize(p["package"]))}
            allowed.add(p["package"].split(".")[0])

    # group code changes by file (never touch tests: they are the evidence)
    per_file: dict[str, list[dict]] = {}
    for d in deps:
        p = proposals.get(d["name"])
        if not p or p["strategy"] not in CODE_STRATEGIES:
            continue
        if p["strategy"] == "upgrade" and not p.get("code_changes_needed"):
            continue
        for f in d["usage"]["files"]:
            if not pysrc.is_test_file(f):
                per_file.setdefault(f, []).append(d)

    async def rewrite(rel: str, fdeps: list[dict]) -> dict:
        src = (out_repo / rel).read_text(encoding="utf-8")
        decisions = [{"dependency": d["name"], **{k: proposals[d["name"]].get(k) for k in
                                                  ("strategy", "package", "version_spec", "steps")}} for d in fdeps]
        lines = [f"{l['line']}: {l['code']}" for d in fdeps for l in d["usage"]["locations"] if l["file"] == rel]
        tree = ast.parse(src)
        reply = await gemma.complete_json(log, f"rewrite_file:{rel}", rewrite_file(py, rel, src, decisions, lines),
                                          Rewrite, max_tokens=16384, deadline_s=240)
        deps_names = [d["name"] for d in fdeps]
        if reply is None:
            return {"path": rel, "status": "rejected", "reason": "Gemma 4 unavailable or returned invalid output",
                    "deps": deps_names, "changes": []}
        new = reply.new_content.replace("\r\n", "\n")
        if new.strip() == src.strip():
            return {"path": rel, "status": "unchanged", "deps": deps_names, "changes": reply.changes}
        err = _validate(rel, src, new, allowed, _imports(tree))
        if err:
            return {"path": rel, "status": "rejected", "reason": err, "deps": deps_names, "changes": reply.changes}
        if not new.endswith("\n"):
            new += "\n"
        (out_repo / rel).write_text(new, encoding="utf-8")
        return {"path": rel, "status": "applied", "deps": deps_names, "changes": reply.changes}

    files = list(await asyncio.gather(*(rewrite(f, ds) for f, ds in per_file.items())))

    # unified diff of everything that changed
    diff_parts, ins, dels, changed = [], 0, 0, 0
    touched = sorted({c["file"] for c in manifest_changes} | {f["path"] for f in files if f["status"] == "applied"})
    for rel in touched:
        a = (repo / rel).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        b = (out_repo / rel).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        d = list(difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel}"))
        if not d:
            continue
        changed += 1
        for line in d:
            if line.startswith("+") and not line.startswith("+++"):
                ins += 1
            elif line.startswith("-") and not line.startswith("---"):
                dels += 1
        diff_parts.append("".join(x if x.endswith("\n") else x + "\n" for x in d))
    (job_dir / "patch.diff").write_text("".join(diff_parts), encoding="utf-8")

    # per-dependency application status
    applied: dict[str, dict] = {}
    for d in deps:
        p = proposals.get(d["name"])
        if not p:
            continue
        mine = [f for f in files if d["name"] in f["deps"]]
        rejected = [f for f in mine if f["status"] == "rejected"]
        applied[d["name"]] = {
            "applied": not rejected,
            "not_applied_reason": "; ".join(f"{f['path']}: {f['reason']}" for f in rejected) or None,
            "files_changed": sorted({c["file"] for c in manifest_changes
                                     if any(decl["file"] == c["file"] for decl in d["declared"])
                                     or p["strategy"] == "declare"}
                                    | {f["path"] for f in mine if f["status"] == "applied"}),
        }
    return {"files": files,
            "manifest_changes": [{"file": c["file"]} for c in manifest_changes],
            "applied": applied,
            "patch": {"files_changed": changed, "insertions": ins, "deletions": dels},
            "tests_modified": False}
