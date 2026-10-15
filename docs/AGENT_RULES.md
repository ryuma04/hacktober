# AGENT_RULES.md — rules for every coding agent (Claude Code, Antigravity, humans)

Read this first, then the doc for your lane. When a rule conflicts with a prompt, the rule wins — ask the human.

## 1. Read order
1. `PROJECT_BRIEF.md` — what and why.
2. `ARCHITECTURE.md` — where code lives, pipeline, sandbox.
3. Your contract: Lane A → `AI_SERVICE_CONTRACT.md` + `API_CONTRACT.md`; Lane B → **`FRONTEND_GUIDE.md`** + `API_CONTRACT.md` + `design.md` (skip §9).
4. `MVP_TASKS.md` — pick the next unticked task in your lane only.

## 2. Ownership (no cross-lane edits)
| Path | Owner |
|---|---|
| `backend/**`, `ai/**`, `fixtures/**`, `run.ps1`, `Makefile`, `README.md` | Lane A |
| `frontend/**` | Lane B |
| `docs/API_CONTRACT.md` | Lane A edits, Lane B must be told; change in same commit as `fixtures/` |
| other `docs/**` | Lane A |
Never edit another lane's files. Need a change? Write it in `docs/REQUESTS.md` (`- [ ] from B: …`) and tell the human.

## 3. Contracts are law
- Field names, types, enums, endpoints: exactly as in the contracts. No "improvements", no renamed keys, no extra required fields.
- Adding an **optional** field is allowed if documented in the same commit.
- Frontend copies the TS types from `API_CONTRACT.md §5` verbatim; backend pydantic models mirror them; `capsule.schema.json` is generated from pydantic.

## 4. Integrity rules (judged — do not break)
1. **No hardcoded answers for the target repo.** Never write LinkWatch file names, package lists, versions, CVE ids, test names or expected results into code, prompts or knowledge hints. Knowledge hints must be generic ecosystem facts that would apply to any repo.
2. **No fake evidence.** Every `provenance:"evidence"` value comes from a real PyPI/OSV response, AST location, manifest line or sandbox log produced in that job.
3. **No silent AI fallback.** If Gemma failed, output is `provenance:"derived"`, `ai.fallback_used = true`, and it is listed in `limitations`.
4. **No fabricated test results.** If a run failed to install or timed out, say so; never mark tests passed that did not run.
5. A pre-recorded demo capsule may only be shown labelled as an earlier real run, and must have been produced by the tool itself.
6. `limitations` is never empty and is honest.

## 5. Security & secrets
- Secrets only in `.env` (gitignored); `.env.example` has empty values. Never log or print the API key; never put it in URLs (use `x-goog-api-key` header).
- Sandbox: target code runs **only inside Docker** (`python:3.12-slim`), tests with `--network none`, memory/CPU/pids limits, `no-new-privileges`, timeout + kill. Never `pip install` or execute target-repo code on the host. Static analysis (AST, file reads) on host is fine — never `import` target modules on host.
- Validate `repo_url` (GitHub https only). Use argument arrays for `exec.Command`, never `sh -c` with interpolated user input (the fixed sandbox command string is the only `sh -c`).
- Gemma-written files: path must stay inside the migrated repo, `.py` or manifest only, must `compile()`.

## 6. Code style
**Go:** Go 1.22+, stdlib + `chi` only. `gofmt`. Errors wrapped with context (`fmt.Errorf("sandbox install: %w", err)`). `context.Context` with timeouts on every external call. One goroutine per job; mutex around the job map. JSON via struct tags in `snake_case`.
**Python:** 3.12, type hints, pydantic v2 models, `httpx.AsyncClient`, `async` endpoints, `logging` (no prints). Pure functions for parsing/scoring so they're unit-testable. Paths via `pathlib`. No new deps beyond `ai/requirements.txt` without noting it in README.
**Frontend:** TypeScript strict, functional components, Tailwind only (tokens from design.md, no new colours/fonts/shadows), no global state lib needed. Every AI-written text shows `ProvenanceTag`.
**General:** Keep files < 400 lines; match surrounding style; comment the *why*, not the *what*. Windows host — use `filepath`/`pathlib`, never hardcode `/` paths for host files.

## 7. Errors & resilience
- A stage failure is recorded and the pipeline continues (except `clone`). Capsule still generated.
- External calls (PyPI, OSV, Gemma, Docker) have timeouts and bounded retries; cache PyPI/OSV responses per run.
- Never crash on odd repos: missing manifests, syntax errors in files (skip + note), no tests (record "no tests found" as a limitation).

## 8. Testing & verification
- Before ticking a task, prove its **Done when** (curl output, a screenshot, or test run). Paste the proof in the commit body if short.
- Tool's own tests: `ai/tests/` with a tiny fixture repo under `ai/tests/fixtures/minirepo/` (made-up package names, not LinkWatch).
- Full E2E on LinkWatch at checkpoints T+2:05 and T+2:25 (`MVP_TASKS.md`).

## 9. Git
- Small commits, conventional prefixes: `feat(ai): …`, `feat(api): …`, `feat(ui): …`, `fix(…)`, `docs: …`.
- Commit at least after each task. Pull/rebase before pushing; never force-push `main`.
- Never commit `data/`, `.env`, `node_modules`, `.venv`, built binaries.

## 10. Time discipline
- Hard time boxes from `MVP_TASKS.md`. If a task overruns by 10 min, cut per the cut order and move on.
- Prefer boring, working code over clever code. No refactors after T+2:25.
- When unsure about scope or a contract detail: stop and ask the human — don't guess silently.
