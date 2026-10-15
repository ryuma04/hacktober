# DepExit: exit risky dependencies, with proof

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![Go](https://img.shields.io/badge/Go-1.22+-00ADD8)
![Model](https://img.shields.io/badge/Gemma%204-powered-4285F4)

**Track 1, Gemma 4: Dependency Resilience.**

DepExit analyses a Python repository, finds the dependencies that put it at risk, maps exactly where each one is used, asks **Gemma 4** to choose a replacement and rewrite the code, then **runs the project's own test suite in Docker before and after**. Everything is packaged as a reusable **Dependency Exit Capsule**.

```
clone → scan → usage → propose (Gemma 4) → materialize (Gemma 4) ─┐
   └──────────── sandbox: baseline (original deps) ────────────────┤
                                     sandbox: migrated (new deps) ─┴→ compare (Gemma 4) → Exit Capsule
```

A full feature list is in [FEATURES.md](FEATURES.md).

## Why

Maintainers usually discover dependency rot when something breaks. Existing tools say a package is old or vulnerable. They don't say where it is used, what to replace it with, whether the replacement works, or what still breaks.

DepExit connects AI reasoning to real repository inspection and real test execution. Every claim is labelled as **evidence** (PyPI, OSV, AST, sandbox), **computed**, or **AI (Gemma 4)**.

## What it detects

| Signal | Source |
|---|---|
| Known vulnerabilities in the pinned version | OSV API |
| Deprecated, superseded or unmaintained packages, yanked releases | PyPI metadata + ecosystem hints |
| Major versions behind, outdated, unpinned | PyPI + manifest specifiers |
| Manifest drift (`requirements.txt` and `pyproject.toml` disagree) | Manifest parsing |
| Undeclared imports (only present transitively) and declared-but-unused packages | AST + PyPI `requires_dist` |
| Private API use and monkeypatching of a dependency | AST |
| Deprecated APIs (`pkg_resources`, Pydantic v1 `validator` / `class Config`, ...) | AST + hints |
| Fails on Python 3.12 with the pinned version | Docker baseline run |

## The Dependency Exit Capsule

For every dependency: details, risk indicators with evidence links, usage locations (`file:line`), proposed replacement, migration steps, suggested tests, executed test results, compatibility gaps and open concerns. It also contains the run results, a unified `patch.diff`, raw install and test logs, JUnit XML, every Gemma prompt and response, and an honest **limitations** list.

Output: `capsule.json` (validated against `ai/schemas/capsule.schema.json`) and `CAPSULE.md`.

## How Gemma 4 is used (and verified)

| Step | Gemma 4 does | Deterministic code does |
|---|---|---|
| Propose | Chooses the strategy and replacement, writes steps, suggested tests and concerns, explains the risk and usage | Collects indicators, computes the 0-100 score, finds every usage by AST, supplies candidates with PyPI health, validates that the package exists and the specifier parses |
| Materialize | Writes the code edits for each affected source file (minimal search/replace) | Applies edits only on an exact match, rejects edits that don't compile or add unexpected imports, keeps manifests consistent with what landed, never edits tests |
| Compare | Explains each test gap and rates its severity | Parses JUnit, pairs tests, attributes gaps to dependencies |

If Gemma is unavailable the pipeline still finishes with deterministic fallbacks, and the capsule says so (`ai.fallback_used`, `provenance: "derived"`).

### Model, access and terms

- **Model:** Gemma 4 instruction-tuned: `gemma-4-26b-a4b-it` (primary) and `gemma-4-31b-it` (fallback when the primary is overloaded or unavailable). Configurable via `GEMMA_MODELS`.
- **Access:** hosted through the Google AI Studio Gemini API (`generateContent`). API keys go in `GEMINI_API_KEYS`.
- **Key rotation:** several keys can be listed. A key that hits its quota (HTTP 429) is cooled down and the next one is used. Rejected keys are retired. `.env` is re-read on change, so keys can be added without a restart.
- **Speed:** each call races both models and the first valid reply wins. Answers are cached by prompt (disclosed in the capsule as `ai.cached_calls`; switch off with `GEMMA_CACHE=0`).
- **Fallback chain with hard time limits:** every AI call goes to Gemma 4 first with 60% of its time budget (`GEMMA_BUDGET_SHARE`). Only if Gemma fails or runs out of time does it fall back to Gemini (`FALLBACK_MODELS`), then Groq (`GROQ_API_KEYS`), then xAI Grok (`XAI_API_KEYS`). Every answer records the model that produced it (`ai_calls.jsonl`, `replacement.model`, `capsule.ai.models_used`), plus a limitations line whenever a non-Gemma model answered.
- **Terms:** [Gemma Terms of Use](https://ai.google.dev/gemma/terms) and the [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms).

## Quick start

Requirements: Python 3.12, Go 1.22+, Node.js 20+ (for the dashboard), Docker Desktop (running), git.

```bash
cp .env.example .env      # then put your Google AI Studio key(s) in GEMINI_API_KEYS
```

**Windows**
```powershell
powershell -ExecutionPolicy Bypass -File run.ps1
```

**macOS / Linux**
```bash
make setup && make dev
```

Then either open the dashboard at `http://localhost:3000`, or use the API:

```bash
curl -X POST localhost:8080/api/analyses -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/rishrek/LinkWatch"}'
```

Follow progress at `GET /api/analyses/{id}/events` (SSE) and fetch `GET /api/analyses/{id}/capsule` when it is done. Everything for a run is kept in `data/<id>/`: stage JSON files, `patch.diff`, `runs/*/install.log|test.log|junit.xml`, and `ai/*.txt` prompts and replies.

### Dashboard
```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL="" npm run dev    # proxies /api to the Go API on :8080
```

## VS Code extension

Shows the capsule inside the editor. See [vscode-extension/README.md](vscode-extension/README.md).

- Diagnostics on every usage and manifest line of an at-risk dependency
- Hover cards with risk indicators, the Gemma proposal and measured test gaps
- Quick fix to replace a file with its Docker-verified migrated version (diff preview, then approval)
- **Apply All Migrations**: choose which changed files to apply and apply them in one undoable edit

To try it: open `vscode-extension/` in VS Code and press **F5**.

## Architecture

| Component | Port | Role |
|---|---|---|
| `backend/` (Go, standard library only) | 8080 | Pipeline orchestration, Docker sandbox, REST + SSE ([API contract](docs/API_CONTRACT.md)) |
| `ai/` (Python, FastAPI) | 8001 | Manifest and AST analysis, PyPI/OSV, Gemma 4, capsule ([AI service contract](docs/AI_SERVICE_CONTRACT.md)) |
| `frontend/` (Next.js) | 3000 | Dashboard ([frontend guide](docs/FRONTEND_GUIDE.md)) |
| `vscode-extension/` | - | Inline diagnostics and one-click migration from the capsule |

Sandbox: `python:3.12-slim`. Install runs with network access, **tests run with `--network none`**, with memory/CPU/PID limits, `no-new-privileges` and timeouts. Target code is never imported or executed on the host. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Configuration

Copy `.env.example` to `.env`. The main settings:

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEYS` | Google AI Studio keys (comma-separated, rotated automatically) |
| `GEMMA_MODELS` | Gemma models, tried in order |
| `FALLBACK_MODELS`, `GROQ_API_KEYS`, `XAI_API_KEYS` | Optional fallback providers |
| `SANDBOX_IMAGE`, `SANDBOX_TIMEOUT_S` | Docker sandbox image and timeout |
| `PORT`, `AI_SERVICE_URL`, `ALLOWED_ORIGINS` | Service wiring |

Never commit `.env`; it holds your API keys.

## Tests

```bash
make test                 # AI service (pytest)
cd backend && go test ./...
```

## Limitations

- Verification reaches only as far as the project's own tests. Untested paths can still break.
- Replacement choices and code edits are model-generated and need maintainer review.
- Python only. `requirements*.txt`, `pyproject.toml` (PEP 621) and `setup.cfg` are parsed. Poetry and `setup.py` `install_requires` are not.
- OSV data is as of analysis time. Unpinned dependencies are not checked for advisories.
- Tests run offline, so network-dependent behaviour is not exercised.

## License

MIT. See [LICENSE](LICENSE). Use of Gemma and Gemini models is subject to the terms linked above.
