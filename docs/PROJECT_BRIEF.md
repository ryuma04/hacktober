# PROJECT_BRIEF.md — DepExit

> Working name: **DepExit** (rename freely; update all docs if you do).
> Track: **Track 1 — Gemma 4: Dependency Resilience**. Hackathon window: **3 hours**.

## 1. One-liner
DepExit points at a Python repository, finds the dependencies that put it at risk, maps exactly where they are used, asks **Gemma 4** to propose a replacement and write the migration, **runs the test suite in Docker before and after**, and ships the evidence as a reusable **Dependency Exit Capsule**.

## 2. Problem
Maintainers discover dependency rot only after something breaks. Existing tools (pip-audit, Dependabot, `pip list --outdated`) say *"this is old / vulnerable"* but not *where it is used, what to replace it with, whether the replacement actually works, or what still breaks*. AI suggestions alone are not trustworthy. DepExit connects AI reasoning to real repository inspection and real test execution, and labels which claims come from evidence and which from the model.

## 3. Target repository
- https://github.com/rishrek/LinkWatch — Python CLI link/uptime checker, ~450 LOC, 4 pytest files.
- **Python 3.12 / 3.13 only** (not 3.14). Sandbox uses `python:3.12-slim`.
- The tool must analyse it **dynamically** (clone → scan → run). No pre-written answers.

Classes of problems the tool must be able to *detect generically* (examples of what exists in this kind of repo — never hardcode them):
| Class | Detection method |
|---|---|
| Known vulnerabilities | OSV API for the pinned version |
| Deprecated / superseded package (stdlib replacement exists, project archived) | PyPI metadata + classifiers + knowledge hints + Gemma |
| Many major versions behind | PyPI latest vs pinned |
| Unmaintained (no release in > 2 years) | PyPI release dates |
| Python 3.12 incompatible | Baseline sandbox install/import/test failure + classifiers |
| Manifest drift (requirements.txt vs pyproject.toml disagree) | Parse both, compare specs |
| Undeclared dependency (imported, not declared) | AST imports vs declared deps |
| Declared but unused | Declared deps vs AST imports |
| Unpinned / loosely pinned | Spec parsing |
| Private-API use (`module._private`) | AST |
| Monkeypatching of a dependency | AST (assignment to attribute of an imported module/class) |
| Deprecated API (e.g. `pkg_resources`) | AST + knowledge hints |

## 4. Required outputs (from the problem statement)
For **every** at-risk dependency:
1. Dependency details  2. Risk indicators (with evidence)  3. Usage locations (file:line)  4. Proposed replacement  5. Migration steps (+ code patch)  6. Suggested tests  7. Executed test results (original vs replacement)  8. Compatibility gaps  9. Open concerns & limitations.

All bundled into the **Dependency Exit Capsule**: `capsule.json` (schema-validated), `CAPSULE.md` (human readable), `patch.diff`, raw run logs + JUnit XML.

## 5. Where Gemma 4 is meaningful (not decorative)
| Step | Gemma 4 does | Deterministic code does |
|---|---|---|
| Risk | Writes rationale per dependency from collected indicators | Collects indicators, computes score |
| Usage | One-paragraph summary of how the dep is used | AST locations |
| Replacement | **Chooses** replacement + strategy among candidates, explains trade-offs | Supplies candidates + PyPI health of each |
| Migration | **Writes the code edits** (full new file content for affected files) + steps | Validates edits compile, builds diff, rewrites manifests |
| Tests | Suggests new tests that cover the migrated behaviour | — |
| Gaps | **Explains each failing/changed test** and classifies severity | JUnit diff baseline vs migrated |
| Repair (stretch) | One repair attempt from failing test output | Re-runs sandbox |

Every AI-written field is tagged `provenance: "ai"`; every evidence field `provenance: "evidence"`.

## 6. Model & access (must appear in README)
- **Model:** Gemma 4 (instruction-tuned) — exact ID in env `GEMMA_MODEL`; confirm with `GET https://generativelanguage.googleapis.com/v1beta/models` (pick the `gemma-4-*` entry).
- **Access method:** Google AI Studio API key → Gemini API `generateContent` endpoint (hosted).
- **Terms:** Gemma Terms of Use (https://ai.google.dev/gemma/terms) + Gemini API Additional Terms. Record both in README.
- **Fallback:** if Gemma is unreachable, pipeline still completes using deterministic logic and the capsule says `ai.fallback_used: true`. Never silently fake AI output.

## 7. Evaluation mapping
| Criterion | How DepExit scores |
|---|---|
| Problem relevance | Real maintainer pain; works on a real repo end to end |
| Technical implementation (identification) | 12 risk-indicator classes incl. drift, undeclared, private API, monkeypatch |
| Meaningful AI integration | Gemma chooses replacements, writes patches, explains gaps |
| Proof, testing, reliability | Docker A/B runs, JUnit evidence, provenance tags, honest limitations section |
| Originality | Evidence-linked capsule + AST risk signals most tools ignore + A/B execution |
| Open-source quality | MIT, README, contracts, schema, one-command run, tests for the tool itself |

## 8. Scope
**In MVP:** clone → scan → usage → propose (Gemma) → materialize migrated workspace → Docker baseline run + migrated run → compare (Gemma) → capsule (json/md/diff) → REST + SSE → UI dashboard.
**Stretch (in order):** per-dependency isolated runs · one Gemma repair loop · capsule-to-PR export · support `uv.lock` / poetry.
**Out of scope:** non-Python ecosystems, auth, databases, multi-user.

## 9. Team & lanes
- **Lane A — Backend + AI (solo dev, Claude Code):** Go API, FastAPI AI service, Docker sandbox.
- **Lane B — UI (teammate, Antigravity):** frontend built only against `API_CONTRACT.md` + fixtures, following `docs/design.md`.

## 10. Doc index
`PROJECT_BRIEF.md` (this) · `ARCHITECTURE.md` · `API_CONTRACT.md` (Go ↔ UI) · `AI_SERVICE_CONTRACT.md` (Go ↔ FastAPI, Gemma prompts, capsule schema) · `MVP_TASKS.md` · `AGENT_RULES.md` · `FRONTEND_GUIDE.md` (UI spec) · `design.md` (UI look, skip §9) · `../fixtures/` (mock data).
