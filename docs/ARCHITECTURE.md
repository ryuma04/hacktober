# ARCHITECTURE.md — DepExit

## 1. System overview
```
┌──────────────────────────┐        REST + SSE (API_CONTRACT.md)
│ UI  :3000 (Lane B)       │ ─────────────────────────────────────┐
│ React/Next + Tailwind    │                                      │
└──────────────────────────┘                                      ▼
                                              ┌───────────────────────────────────┐
                                              │ Go API  :8080  (conductor)         │
                                              │  • job store (in-memory + JSON)    │
                                              │  • pipeline runner (goroutine/job) │
                                              │  • SSE event hub                   │
                                              │  • Docker sandbox (docker CLI)     │
                                              └──────┬───────────────────┬─────────┘
                        HTTP JSON (AI_SERVICE_CONTRACT.md)               │ docker run
                                                     ▼                   ▼
                              ┌──────────────────────────────┐  ┌──────────────────────┐
                              │ FastAPI AI service :8001     │  │ python:3.12-slim     │
                              │  scan · usage · propose ·    │  │  install (network)   │
                              │  materialize · compare ·     │  │  pytest (--network   │
                              │  capsule                     │  │  none) → junit.xml   │
                              │  Gemma 4 client (AI Studio)  │  └──────────────────────┘
                              └──────────────┬───────────────┘
                                             │ HTTPS
                              PyPI JSON · OSV API · Gemini API (Gemma 4)

Shared filesystem: DATA_DIR (default ./data) — both Go and FastAPI run on the HOST and read/write the same paths.
```
No Postgres, no Redis. State = in-memory map in Go, mirrored to `data/<job_id>/job.json` after every stage so a crash/restart can still serve finished capsules.

## 2. Repository layout (hacktober)
```
hacktober/
├── backend/                     # Go 1.22+ (Lane A) — single package, standard library only (net/http patterns)
│   ├── go.mod                   # module depexit; no third-party deps
│   ├── main.go                  # wiring, image pre-pull, start
│   ├── config.go                # env + repo-root .env
│   ├── api.go                   # REST + SSE handlers, CORS
│   ├── store.go                 # Job/Stage/Event, in-memory map, job.json + events.ndjson (replay)
│   ├── pipeline.go              # stage orchestration
│   ├── aiclient.go              # calls to FastAPI
│   └── sandbox.go               # docker run wrapper (install + offline test)
├── ai/                          # Python 3.12 FastAPI (Lane A)
│   ├── requirements.txt         # fastapi uvicorn httpx pydantic>=2 packaging jsonschema
│   ├── app/main.py              # routes
│   ├── app/models.py            # pydantic models = contract
│   ├── app/manifests.py         # parse requirements*.txt / pyproject.toml / setup.cfg
│   ├── app/scan.py              # PyPI + OSV + indicators + score
│   ├── app/usage.py             # AST: imports, calls, private API, monkeypatch
│   ├── app/knowledge.py         # candidate-replacement HINTS (generic, not repo-specific)
│   ├── app/gemma.py             # Gemma 4 client, JSON extraction, retries, call log
│   ├── app/prompts.py           # all prompt templates
│   ├── app/propose.py           # replacement + migration via Gemma
│   ├── app/materialize.py       # build migrated workspace, validate, diff
│   ├── app/compare.py           # JUnit parse + diff + Gemma gap explanation
│   ├── app/capsule.py           # assemble, validate, render CAPSULE.md
│   ├── schemas/capsule.schema.json
│   └── tests/                   # pytest for the tool itself (small)
├── frontend/                    # Lane B
├── fixtures/                    # example JSON for UI mock mode (from API_CONTRACT.md)
├── data/                        # runtime, gitignored
├── docs/
├── .env.example
├── Makefile / run.ps1           # one-command start
├── LICENSE (MIT)
└── README.md
```

## 3. Pipeline (one job)
| # | Stage id | Owner | Action | Output file in `data/<job>/` |
|---|---|---|---|---|
| 1 | `clone` | Go | `git clone --depth 1 <url> repo` (+ `git rev-parse HEAD`) | `repo/` |
| 2 | `scan` | AI `/v1/scan` | manifests, PyPI, OSV, AST imports → dependencies + indicators + score + Gemma rationale | `scan.json` |
| 3 | `usage` | AI `/v1/usage` | AST locations per dep + Gemma summary | `usage.json` |
| 4 | `propose` | AI `/v1/propose` | Gemma picks replacement, steps, file edits, suggested tests (per at-risk dep) | `proposals.json` |
| 5 | `materialize` | AI `/v1/materialize` | copy repo → `runs/migrated/repo`, apply validated edits, rewrite manifests, unified diff | `patch.diff`, `materialize.json` |
| 6 | `sandbox_baseline` | Go | Docker install + pytest on original `repo/` | `runs/baseline/{install.log,test.log,junit.xml,result.json}` |
| 7 | `sandbox_migrated` | Go | same on `runs/migrated/repo` | `runs/migrated/...` |
| 8 | `compare` | AI `/v1/compare` | JUnit diff + Gemma explanation per gap | `compare.json` |
| 9 | `capsule` | AI `/v1/capsule` | assemble + validate schema + render md | `capsule.json`, `CAPSULE.md` |

Stages 6 can start right after stage 1 (parallel with 2–5) — do this, it saves ~1 min.
Stretch stages: `sandbox_isolated:<dep>` (one migrated run per dependency, max 3 concurrent) and `repair` (one Gemma fix attempt, then `sandbox_migrated_r1`).

**Failure policy:** a stage failure never kills the job unless it is `clone`. Record `stage.status = "failed"` + error, continue with what exists; the capsule lists it under `limitations`. Job ends `completed` or `completed_with_errors`; `failed` only if clone fails.

## 4. Docker sandbox design
Two containers per run so tests run **without network**, sharing a named volume for the venv (fast on Windows; avoids bind-mount venv I/O):
```
# 1) install (network allowed)
docker run --rm --name dx-<job>-<run>-install \
  --memory 2g --cpus 2 --pids-limit 512 --security-opt no-new-privileges \
  -v <abs run repo path>:/work -v dx-<job>-<run>-venv:/venv -w /work \
  python:3.12-slim sh -c "python -m venv /venv && /venv/bin/pip install -q --disable-pip-version-check -r requirements.txt -r requirements-dev.txt"

# 2) test (no network)
docker run --rm --name dx-<job>-<run>-test --network none \
  --memory 2g --cpus 2 --pids-limit 512 --security-opt no-new-privileges \
  -v <abs run repo path>:/work -v dx-<job>-<run>-venv:/venv -w /work \
  python:3.12-slim sh -c "mkdir -p .depexit && /venv/bin/python -m pytest -q -p no:cacheprovider --junitxml=.depexit/junit.xml"

# 3) cleanup
docker volume rm dx-<job>-<run>-venv
```
- Requirement files to install are discovered by the AI scan (`scan.install_files`), Go just passes them; fallback `requirements.txt`.
- Timeouts: install 900 s, test 900 s (`SANDBOX_TIMEOUT_S`; heavy ML/video dependencies can take several minutes to download). On timeout: `docker kill`, mark run `timeout`.
- If install fails, **still** record it — an install failure on Python 3.12 is evidence. Test step is skipped, `result.json.status = "install_failed"`.
- Windows: pass absolute paths (`filepath.Abs`), Docker Desktop accepts `D:\...`.
- Image pre-pull at startup (`docker pull python:3.12-slim` in background) and `GET /api/health` reports docker availability.
- `result.json`: `{run_id, kind, image, install_exit_code, test_exit_code, status, duration_s, started_at, finished_at}`; JUnit parsing is done by the AI service in `compare`.

## 5. Configuration (`.env.example`)
```
# shared
DATA_DIR=./data
# Go
PORT=8080
AI_SERVICE_URL=http://localhost:8001
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
SANDBOX_IMAGE=python:3.12-slim
SANDBOX_TIMEOUT_S=900
DEFAULT_REPO_URL=https://github.com/rishrek/LinkWatch
# AI service
GEMINI_API_KEYS=           # comma-separated Google AI Studio keys; next key used automatically on quota/auth errors
GEMMA_MODELS=gemma-4-26b-a4b-it,gemma-4-31b-it   # tried in order when a model is overloaded
XAI_API_KEYS=              # optional last-resort fallback (xAI Grok), only when every Gemma key/model fails
GEMMA_TIMEOUT_S=90
GEMMA_MAX_CONCURRENCY=3
OSV_URL=https://api.osv.dev/v1/query
PYPI_URL=https://pypi.org/pypi
```

## 6. Key design decisions
| Decision | Why |
|---|---|
| Go conducts, Python thinks | Go: concurrency, Docker, SSE. Python: AST, packaging, Gemma ecosystem. |
| No DB/queue | 3-hour budget; JSON files are the evidence trail anyway. |
| Docker CLI, not SDK | ~150 LOC, no heavy deps, easy to debug by copy-pasting the command (logged in `result.json.command`). |
| Gemma returns **full file content**, not diffs | LLM diffs are frequently malformed; LinkWatch files are small. Diff is computed by `difflib`. |
| Edits validated before use | `compile()` each edited file; reject edits that add unexpected imports or change size > 2x; test files are never edited. |
| Baseline runs on a copy | `runs/baseline/repo` so pytest side effects never leak into the migrated workspace. |
| Deterministic score + AI rationale | Scores are reproducible; AI explains, does not invent risk. |
| Provenance on every field | Judges can see what is evidence vs model opinion. |
| Install + test split, test offline | Tests prove behaviour of code, not network luck. |

## 7. Sequence (happy path)
```
UI → POST /api/analyses {repo_url}            → 202 {id}
UI → GET  /api/analyses/{id}/events (SSE)     ← stage_started/stage_completed/log …
Go: clone → (go sandbox_baseline) ∥ scan → usage → propose → materialize → sandbox_migrated → compare → capsule
Go → SSE "job_completed"
UI → GET /api/analyses/{id}/capsule           ← capsule.json
```
