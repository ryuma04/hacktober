# MVP_TASKS.md — 3-hour plan

Two lanes work **concurrently** and meet only at `API_CONTRACT.md` + `fixtures/`.
Tick boxes as you go. Each task has a **Done when** — don't move on until it's true (or consciously cut it).
Clock starts at T+0:00. Cut order if late is at the bottom.

---
## Lane A — Backend + AI (solo dev, Claude Code)

### A0 · Setup (T+0:00 → 0:20)
- [ ] Repo skeleton per `ARCHITECTURE.md §2`, `.gitignore` (`data/`, `.env`, `.venv`, `node_modules`), MIT `LICENSE`, `.env.example`.
- [x] `fixtures/` already created (capsule, job states, events, patch, logs) → **commit and push immediately so Lane B can start.**
- [ ] Gemma smoke test: list models, pick the `gemma-4-*` id, one `generateContent` call; note whether `systemInstruction` / JSON mode work → set `GEMMA_MODEL`.
- [ ] `docker pull python:3.12-slim` (background).
- **Done when:** fixtures pushed, Gemma replies "ok", image pulled.

### A1 · AI service: scan (T+0:20 → 0:50)
- [ ] `models.py` (pydantic mirror of API_CONTRACT §5), `manifests.py` (requirements with `-r`, pyproject, line numbers, drift).
- [ ] `scan.py`: AST imports → undeclared/unused; PyPI + OSV concurrent with disk cache; indicators + score.
- [ ] `/v1/health`, `/v1/scan`.
- **Done when:** `curl /v1/scan` on a cloned LinkWatch returns every declared dep + any undeclared import, with OSV hits and drift, in < 20 s.

### A2 · AI service: usage (T+0:50 → 1:05)
- [ ] `usage.py`: imports/aliases, calls, attributes, private API, monkeypatch, deprecated API hints.
- **Done when:** every dep has file:line locations; private-API and monkeypatch cases are flagged.

### A3 · Gemma + propose + materialize (T+1:05 → 1:35)
- [ ] `gemma.py` (client, JSON extract, retry, call log), `prompts.py`.
- [ ] Wire `risk_rationale` into scan and `usage_summary` into usage.
- [ ] `/v1/propose` (`decide` per dep), `/v1/materialize` (manifest rewrite + `rewrite_file` per file + compile check + diff).
- **Done when:** `runs/migrated/repo` exists, `patch.diff` is non-empty, rejected edits are recorded with a reason.

### A4 · Go API + sandbox (T+1:35 → 2:05)
- [ ] `go mod init depexit`, chi router, CORS, config from env.
- [ ] `jobs/store.go` + `events.go` (replay buffer + SSE), `pipeline.go` per `ARCHITECTURE.md §3` (baseline sandbox in parallel with scan).
- [ ] `sandbox/docker.go`: install + offline test + volume cleanup + timeout + `result.json`.
- [ ] All endpoints of `API_CONTRACT.md §2` (files served straight from `data/<job>/`).
- **Done when:** `POST /api/analyses` → SSE shows all stages → both runs have `junit.xml` or a recorded install failure.

### A5 · Compare + capsule (T+2:05 → 2:25)
- [ ] `/v1/compare` (JUnit parse, gaps, attribution, sandbox indicators, `explain_gaps`).
- [ ] `/v1/capsule` (merge, rescore, verdict, limitations, schema validate, `CAPSULE.md`).
- [ ] `schemas/capsule.schema.json` (generate from pydantic `Capsule.model_json_schema()`).
- **Done when:** full run on LinkWatch produces a valid `capsule.json` + readable `CAPSULE.md` covering **all** at-risk deps.

### A6 · Hardening + docs (T+2:25 → 2:50)
- [ ] Run end-to-end twice from a clean `data/`. Fix crashes; never fix by hardcoding LinkWatch answers.
- [ ] Kill Gemma key → confirm fallback path still completes with `fallback_used: true`.
- [ ] 3–5 unit tests for the tool (`manifests`, `usage` on a tiny fixture repo, scoring).
- [ ] `README.md`: what/why, architecture image (ascii ok), quickstart (`.env`, `run.ps1`/`make dev`), **Gemma 4 model id + Google AI Studio access + Gemma Terms link**, sample capsule excerpt from the real run, evaluation mapping, limitations, license.
- [ ] `run.ps1` / `Makefile`: start AI service, Go API, frontend in one command.
- **Done when:** a stranger can run it from README in < 5 min.

### A7 · Demo (T+2:50 → 3:00)
- [ ] Start a fresh analysis live; while it runs, show a finished capsule from an earlier run (clearly labelled as an earlier real run).
- [ ] Show: risk table → one dep's evidence → Gemma decision → diff → baseline vs migrated tests → gaps → limitations.

### Stretch (only if A5 done before T+2:15)
1. `options.isolated_runs`: one migrated run per at-risk dep (max 3 concurrent) for exact attribution.
2. `options.repair`: one Gemma repair pass + `sandbox_migrated_r1`.
3. `GET /bundle.zip`.

---
## Lane B — UI (teammate, Antigravity)

**Start with `FRONTEND_GUIDE.md`.** It is the full spec (screens, API calls, mock mapping, acceptance checklist). The tasks below are the timeline.
**Inputs:** `FRONTEND_GUIDE.md`, `API_CONTRACT.md` (types §2.3, §5), `fixtures/*`, `docs/design.md` (§9 ignored).
**Stack:** Next.js (App Router) *or* Vite + React, TypeScript, Tailwind (tokens from `design.md §10`), Recharts optional. Port 3000. Env `NEXT_PUBLIC_API_URL` (default `http://localhost:8080`), `NEXT_PUBLIC_MOCK=1` → read fixtures and replay `events.ndjson` with 400 ms delay.
**Override `design.md §9`** (that mapping is from another app) with the mapping below. Everything else in design.md applies.

### B0 · Setup (T+0:20 → 0:40)
- [ ] Scaffold, Tailwind tokens, fonts, base components: `Card`, `FeatureCard`, `Button` (primary/secondary), `Badge`, `Chip`, `Tabs`, `CodeChip`.
- [ ] `lib/api.ts`: typed client (copy TS types from API_CONTRACT §5 verbatim into `lib/types.ts`), mock switch, `useAnalysisEvents(id)` hook (EventSource + polling fallback).
- [ ] `RiskBadge`: critical = `danger` fill-tint + border, high = `coral`, medium = `butter`, low = `sky`, none = `mint`.
- [ ] `ProvenanceTag`: `ai` → lavender chip with sparkle "Gemma 4"; `evidence` → mint chip "Evidence"; `derived` → white chip "Computed".

### B1 · Home `/` (T+0:40 → 1:00)
- [ ] Hero: eyebrow "DEPENDENCY RESILIENCE", heading with marker swipe "Exit risky dependencies **with proof**", subtitle.
- [ ] Repo URL input (prefilled `https://github.com/rishrek/LinkWatch`), primary button "Analyze" → `POST /api/analyses` → route `/analyses/{id}`.
- [ ] Health strip from `/api/health`: Docker · AI service · Gemma model (chips, red if down).
- [ ] Recent analyses list (`GET /api/analyses`) as list rows with status badge.

### B2 · Run view `/analyses/[id]` while running (T+1:00 → 1:25)
- [ ] Vertical stage timeline (9 stages, labels from API_CONTRACT §2.3): pending (white) / running (butter + spinner) / completed (mint + check + duration) / failed (danger + error text) / skipped (muted).
- [ ] Live log panel (mono, last 200 `log` events, autoscroll).
- [ ] "Gemma 4 calls" counter from `ai_call` events (lavender FeatureCard).
- [ ] On `job_completed` → fetch capsule and switch to capsule view on the same page.

### B3 · Capsule dashboard (T+1:25 → 2:20) — the money screen
- [ ] **Header:** repo + commit chip, verdict sticker (`safe_to_migrate` mint "SAFE!", `migrate_with_care` butter "CAREFUL!", `blocked` coral "BLOCKED!"), headline text, download buttons: JSON · Markdown · Patch.
- [ ] **KPI tiles (4 FeatureCards):** Dependencies scanned (sky) · At risk (coral) · Tests baseline → migrated pass count (mint) · Compatibility gaps regressed/still failing (butter).
- [ ] **Test comparison card:** two columns Baseline vs Migrated with totals bars (passed/failed/errors/skipped), status badge, links to install/test logs; table of tests with outcome per run and change badge (fixed/regressed/still_failing).
- [ ] **Dependency table:** name, pinned → latest, risk badge + score, indicator codes as small chips, strategy chip (`replace → pkg`), migration applied ✓/✗. Sort by score; filter chips by level. At-risk rows: 3px danger border per design.md.
- [ ] **Dependency detail drawer/page** (click row) with sections in capsule order: Details · Risk indicators (each with evidence link: OSV id → osv.dev, PyPI → pypi.org, AST → `file:line`, sandbox → log) · Usage locations (`file:line` + code line, kind chip; private_api/monkeypatch highlighted coral) · Proposed replacement (strategy, package, spec, confidence bar, rationale, alternatives) · Migration steps (numbered) · Suggested tests (collapsible code blocks) · Executed test results · Compatibility gaps · Open concerns. Every AI-written block shows `ProvenanceTag`.
- [ ] **Patch viewer:** fetch `patch.diff`, render with red/green line colouring (simple custom renderer is fine; `react-diff-view` optional).
- [ ] **Limitations card** (cream-yellow notice banner style) + **AI disclosure** (model, provider, calls, failed calls, fallback used, terms link).

### B4 · Integration + polish (T+2:20 → 2:50)
- [ ] Switch off mock, run against live backend, fix shape mismatches **by checking the contract** (if backend is wrong, tell Lane A; don't hack around it).
- [ ] Empty/error states: backend down, job failed, capsule 409 (show "still running").
- [ ] Responsive check at 375 px.

### Lane B cut order
Patch viewer colouring → filters/sorting → health strip → recent list. Never cut: run timeline, KPI tiles, dependency table, detail sections, limitations.

---
## Integration checkpoints
| Time | Check |
|---|---|
| T+0:20 | Fixtures pushed; Lane B unblocked |
| T+1:35 | AI endpoints work via curl on LinkWatch |
| T+2:05 | Live `POST /api/analyses` + SSE visible in UI |
| T+2:25 | Real capsule rendered in UI |
| T+2:50 | Code freeze; README done; demo rehearsed once |

## Lane A cut order (if behind)
1. Stretch items → 2. SSE (UI polls `GET /api/analyses/{id}`) → 3. `usage_summary` Gemma call (derived text) → 4. `rewrite_file` for tests/ files → 5. tool unit tests to 2.
**Never cut:** Docker baseline vs migrated runs, Gemma `decide` + `rewrite_file`, capsule with all 9 sections, limitations, README Gemma disclosure.
