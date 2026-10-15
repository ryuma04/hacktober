# DepExit — exit risky dependencies, with proof

**Track 1 — Gemma 4: Dependency Resilience.** DepExit analyses a Python repository, finds the dependencies that put
it at risk, maps exactly where they are used, asks **Gemma 4** to choose a replacement and rewrite the code, **runs
the test suite in Docker before and after**, and ships everything as a reusable **Dependency Exit Capsule**.

```
clone → scan → usage → propose (Gemma 4) → materialize (Gemma 4) ─┐
   └──────────── sandbox: baseline (original deps) ────────────────┤
                                     sandbox: migrated (new deps) ─┴→ compare (Gemma 4) → Exit Capsule
```

## Why
Maintainers usually discover dependency rot when something breaks. Existing tools tell you a package is old or
vulnerable; they don't tell you **where it is used, what to replace it with, whether the replacement actually works,
or what still breaks**. DepExit connects AI reasoning to real repository inspection and real test execution, and
labels every claim as **evidence** (PyPI, OSV, AST, sandbox), **computed**, or **AI (Gemma 4)**.

## What it detects
| Signal | Source |
|---|---|
| Known vulnerabilities in the pinned version | OSV API |
| Deprecated / superseded / unmaintained packages, yanked releases | PyPI metadata + ecosystem hints |
| Major versions behind, outdated, unpinned | PyPI + manifest specifiers |
| **Manifest drift** (requirements.txt vs pyproject.toml disagree) | Manifest parsing |
| **Undeclared** imports (only present transitively) and declared-but-unused packages | AST + PyPI `requires_dist` |
| **Private API use** and **monkeypatching** of a dependency | AST |
| Deprecated APIs (`pkg_resources`, Pydantic v1 `validator`/`class Config`, …) | AST + hints |
| **Fails on Python 3.12** with the pinned version | Docker baseline run (ImportError traces, install failures) |

## The Dependency Exit Capsule
For every dependency: details · risk indicators with evidence links · usage locations (`file:line`) · proposed
replacement · migration steps · suggested tests · executed test results · compatibility gaps · open concerns —
plus the run results, a unified `patch.diff`, raw install/test logs, JUnit XML, every Gemma prompt/response, and an
honest **limitations** list. Output: `capsule.json` (JSON-Schema validated, `ai/schemas/capsule.schema.json`) and
`CAPSULE.md`.

## How Gemma 4 is used (and verified)
| Step | Gemma 4 does | Deterministic code does |
|---|---|---|
| Risk | Explains why each dependency is risky | Collects indicators, computes the 0–100 score |
| Usage | Summarises how each dependency is used | Finds every location by AST |
| Propose | **Chooses** strategy + replacement, writes steps, suggested tests, concerns | Supplies candidates and their PyPI health; validates the package exists and the specifier parses |
| Materialize | **Rewrites each affected source file** | Rewrites manifests; rejects edits that don't compile, add unexpected imports or change size wildly; never edits tests |
| Compare | **Explains each test gap** and rates severity | Parses JUnit, pairs tests, attributes gaps to dependencies |

If Gemma is unavailable the pipeline still finishes with deterministic fallbacks, and the capsule says so
(`ai.fallback_used`, `provenance: "derived"`).

### Model, access and terms
- **Model:** Gemma 4 instruction-tuned — `gemma-4-26b-a4b-it` (primary, ~8 s per call), `gemma-4-31b-it` (fallback when the primary is overloaded or unavailable). Configurable via `GEMMA_MODELS`.
- **Access:** hosted, via the **Google AI Studio** Gemini API (`generateContent`), API keys in `GEMINI_API_KEYS`.
- **Key rotation:** several keys can be listed; when one hits its quota (HTTP 429) it is cooled down and the next key is used automatically; rejected keys are retired. `.env` is re-read on change, so keys can be added without a restart.
- **Optional last-resort fallback:** xAI Grok (`XAI_API_KEYS`), used only if every Gemma key and model fails; such calls are recorded under their own model name in `ai_calls.jsonl`.
- **Terms:** [Gemma Terms of Use](https://ai.google.dev/gemma/terms) and the [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms).

## Quick start
Requirements: Python 3.12, Go 1.22+, Docker Desktop (running), git.

```bash
cp .env.example .env      # then put your Google AI Studio key(s) in GEMINI_API_KEYS
```
Windows:
```bash
powershell -ExecutionPolicy Bypass -File run.ps1
```
macOS/Linux:
```bash
make setup && make dev
```
Then:
```bash
curl -X POST localhost:8080/api/analyses -H "Content-Type: application/json" -d "{\"repo_url\":\"https://github.com/rishrek/LinkWatch\"}"
```
Follow progress at `GET /api/analyses/{id}/events` (SSE) and fetch `GET /api/analyses/{id}/capsule` when done.
Everything for a run lives in `data/<id>/` (stage JSON files, `patch.diff`, `runs/*/install.log|test.log|junit.xml`,
`ai/*.txt` prompts and replies).

## Architecture
| Component | Port | Role |
|---|---|---|
| `backend/` (Go, stdlib only) | 8080 | Pipeline orchestration, Docker sandbox, REST + SSE ([API_CONTRACT](docs/API_CONTRACT.md)) |
| `ai/` (Python, FastAPI) | 8001 | Manifest/AST analysis, PyPI/OSV, Gemma 4, capsule ([AI_SERVICE_CONTRACT](docs/AI_SERVICE_CONTRACT.md)) |
| `frontend/` | 3000 | Dashboard ([FRONTEND_GUIDE](docs/FRONTEND_GUIDE.md)) |
| `vscode-extension/` | – | Inline diagnostics from the capsule |

Sandbox: `python:3.12-slim`; install with network, **tests with `--network none`**, memory/CPU/PID limits,
`no-new-privileges`, timeouts. Target code is never imported or executed on the host.
Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Limitations
- Verification reaches only as far as the project's own tests; untested paths can still break.
- Replacement choices and code edits are model-generated and need maintainer review.
- Python only; `requirements*.txt`, `pyproject.toml` (PEP 621) and `setup.cfg` are parsed; Poetry/`setup.py` install_requires are not.
- OSV data is as of analysis time; unpinned dependencies are not checked for advisories.
- Tests run offline; network-dependent behaviour is not exercised.

## License
MIT — see [LICENSE](LICENSE).
