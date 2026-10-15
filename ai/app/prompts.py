"""All Gemma 4 prompt templates and the pydantic schemas their replies must match."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

PREAMBLE = (
    "You are a senior Python maintainer helping migrate dependencies safely.\n"
    "Use ONLY the facts provided. If information is missing, say so; never invent versions, APIs, CVEs or test results.\n"
    "Target runtime: Python {py}.\n"
    "Reply with a single JSON object and nothing else (no markdown, no commentary).\n\n"
)


def _j(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False)


# ---------- risk_rationale ----------
class _Item(BaseModel):
    name: str
    text: str


class ItemsReply(BaseModel):
    items: list[_Item]


def risk_rationale(py: str, deps: list[dict]) -> str:
    return PREAMBLE.format(py=py) + (
        "For each dependency below, write a rationale of at most 2 sentences explaining WHY it is risky for this "
        "project, citing the indicator facts (versions, advisories, usage). Do not repeat the package name first.\n"
        'Reply shape: {"items": [{"name": "<dependency name>", "text": "<rationale>"}]}\n\n'
        f"DEPENDENCIES:\n{_j(deps)}"
    )


def usage_summary(py: str, deps: list[dict]) -> str:
    return PREAMBLE.format(py=py) + (
        "For each dependency below, summarise in 1-2 sentences HOW the project uses it, based only on the code "
        "locations given (what it is used for, which modules, anything unusual like private APIs or monkeypatching).\n"
        'Reply shape: {"items": [{"name": "<dependency name>", "text": "<summary>"}]}\n\n'
        f"DEPENDENCIES AND USAGE LOCATIONS:\n{_j(deps)}"
    )


# ---------- decide ----------
class Alternative(BaseModel):
    package: str
    reason_rejected: str


class SuggestedTest(BaseModel):
    name: str
    purpose: str
    code: str | None = None


class Decision(BaseModel):
    strategy: Literal["replace", "upgrade", "remove", "stdlib", "declare", "keep"]
    package: str | None = None
    version_spec: str | None = None
    rationale: str
    confidence: float = Field(ge=0, le=1)
    alternatives: list[Alternative] = []
    steps: list[str]
    code_changes_needed: bool = False
    suggested_tests: list[SuggestedTest] = []
    open_concerns: list[str] = []


def decide(py: str, dep: dict, usage: list[str], candidates: list[dict], others: list[str]) -> str:
    return PREAMBLE.format(py=py) + (
        "Decide how this project should exit or fix the dependency below.\n"
        "Strategies: replace (different package), upgrade (same package, newer version), stdlib (use the standard "
        "library), remove (not needed), declare (it is imported but undeclared: add it to the manifests), keep.\n"
        "Rules:\n"
        "- Prefer the smallest change that removes the risk; prefer stdlib when it fully covers the APIs used.\n"
        "- The plan must cover EVERY usage location listed. If code must change, set code_changes_needed=true.\n"
        "- For replace/upgrade/declare give a PyPI package and a version_spec like '>=X.Y,<Z'. For stdlib give the "
        "module name in package and version_spec null. For remove/keep package may be null.\n"
        "- steps: ordered, concrete, mention file paths.\n"
        "- suggested_tests: 1-3 runnable pytest functions using only the project's public API, covering behaviour "
        "that could change with this migration.\n"
        "- open_concerns: behaviour differences or risks that the existing tests may not catch.\n"
        "- confidence: 0..1, how sure you are the migration is safe.\n"
        'Reply shape: {"strategy": "...", "package": "...", "version_spec": "...", "rationale": "...", '
        '"confidence": 0.8, "alternatives": [{"package": "...", "reason_rejected": "..."}], "steps": ["..."], '
        '"code_changes_needed": true, "suggested_tests": [{"name": "test_...", "purpose": "...", "code": "def test_...():\\n    ..."}], '
        '"open_concerns": ["..."]}\n\n'
        f"DEPENDENCY FACTS:\n{_j(dep)}\n\n"
        f"USAGE LOCATIONS (file:line: code):\n" + ("\n".join(usage) or "(not imported anywhere)") + "\n\n"
        f"CANDIDATES (with PyPI health; hints only, you may choose otherwise):\n{_j(candidates)}\n\n"
        f"OTHER PROJECT DEPENDENCIES: {', '.join(others)}"
    )


# ---------- rewrite_file ----------
class Rewrite(BaseModel):
    path: str
    new_content: str
    changes: list[str] = []


def rewrite_file(py: str, path: str, content: str, decisions: list[dict], usage: list[str]) -> str:
    return PREAMBLE.format(py=py) + (
        f"Rewrite the file `{path}` to apply the dependency migrations below.\n"
        "Rules:\n"
        "- Change ONLY what the migrations require. Keep every public function/class name, signature and behaviour.\n"
        "- Keep comments, docstrings and formatting style. Do not add new third-party imports other than the chosen "
        "replacement packages.\n"
        "- The result must be valid Python and complete (the ENTIRE file, not a diff).\n"
        "- If the file needs no change, return it unchanged with changes = [].\n"
        'Reply shape: {"path": "<path>", "new_content": "<entire new file>", "changes": ["<one line per change>"]}\n\n'
        f"MIGRATIONS:\n{_j(decisions)}\n\n"
        f"RELEVANT LINES IN THIS FILE:\n" + "\n".join(usage) + "\n\n"
        f"ORIGINAL FILE `{path}`:\n<<<FILE\n{content}\nFILE>>>"
    )


# ---------- explain_gaps ----------
class GapItem(BaseModel):
    test_id: str
    explanation: str
    severity: Literal["critical", "high", "medium", "low"]


class GapsReply(BaseModel):
    headline: str
    items: list[GapItem] = []


def explain_gaps(py: str, gaps: list[dict], context: dict) -> str:
    return PREAMBLE.format(py=py) + (
        "Below are test outcome differences between the ORIGINAL dependencies (baseline) and the MIGRATED "
        "dependencies, measured by running pytest in Docker. For each gap explain the most likely CAUSE (cite the "
        "error) and WHAT a maintainer should do. Severity: critical (feature broken), high, medium, low (cosmetic or "
        "test-only). Use test_id '__install__' for install-level gaps.\n"
        "Also write a one-sentence headline summarising the migration outcome with the numbers.\n"
        'Reply shape: {"headline": "...", "items": [{"test_id": "...", "explanation": "...", "severity": "medium"}]}\n\n'
        f"RUN SUMMARY:\n{_j(context)}\n\nGAPS:\n{_j(gaps)}"
    )


# ---------- repair (stretch) ----------
class RepairReply(BaseModel):
    files: list[Rewrite] = []


def repair(py: str, failures: list[dict], files: dict[str, str], decisions: list[dict]) -> str:
    return PREAMBLE.format(py=py) + (
        "After migrating dependencies, these tests fail. Fix the MIGRATED SOURCE FILES (not the tests) so behaviour "
        "matches the original, changing as little as possible. Return at most 3 files, each complete.\n"
        'Reply shape: {"files": [{"path": "...", "new_content": "...", "changes": ["..."]}]}\n\n'
        f"MIGRATIONS:\n{_j(decisions)}\n\nFAILURES:\n{_j(failures)}\n\n"
        + "\n\n".join(f"FILE `{p}`:\n<<<FILE\n{c}\nFILE>>>" for p, c in files.items())
    )
