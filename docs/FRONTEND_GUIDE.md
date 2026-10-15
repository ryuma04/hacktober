# FRONTEND_GUIDE.md — everything the UI builder needs

> For the UI teammate (Antigravity). This is the **single entry point** for the frontend. Read it fully, then use
> `API_CONTRACT.md` for exact types and `design.md` §1–8 + §10 for looks.
> **Ignore `design.md` §9** — it belongs to a different app. Use the screen mapping in this file instead.
> You own only `frontend/**`. Rules for all agents: `AGENT_RULES.md`.

## 1. What the app is (30 seconds)
DepExit analyses a GitHub Python repo: it finds risky dependencies, shows where they're used, asks **Gemma 4** for a replacement and code changes, runs the tests **before (baseline) and after (migrated)** in Docker, and produces a **Dependency Exit Capsule**. The UI has 3 jobs:
1. Start an analysis.
2. Show live progress.
3. Present the capsule so a judge can follow the evidence: risk → where it's used → AI proposal → patch → test results → gaps → limitations.

## 2. Stack & setup
- Next.js 14+ (App Router) **or** Vite + React 18 + React Router. TypeScript strict. Tailwind with the tokens and classes from `design.md §10`.
- Fonts (Google): Bricolage Grotesque 800, Outfit 400/500/600, JetBrains Mono 400.
- Icons: `lucide-react`. Charts are optional; plain CSS bars are fine.
- Port **3000** (the backend allows CORS for `http://localhost:3000` and `:5173`).
- Env vars (`frontend/.env.local`):
```
NEXT_PUBLIC_API_URL=http://localhost:8080   # or VITE_API_URL
NEXT_PUBLIC_MOCK=1                          # 1 = use /fixtures, 0 = live backend
```
- Copy the repo's `fixtures/` folder into `frontend/public/fixtures/` (or symlink it) so mock mode can `fetch("/fixtures/...")`.

## 3. Folder layout (suggested)
```
frontend/src/
  lib/types.ts          ← copy API_CONTRACT §2.3 + §5 TypeScript VERBATIM
  lib/api.ts            ← all HTTP calls + mock switch (§5)
  lib/useAnalysis.ts    ← job + events hook (§6)
  lib/url.ts            ← apiUrl() helper (§4)
  components/ui/        ← Card, FeatureCard, Button, Badge, Chip, Tabs, CodeChip, Sticker, NoticeBanner
  components/           ← RiskBadge, ProvenanceTag, StageTimeline, LogPanel, KpiTiles, TestComparison,
                           DependencyTable, DependencyDetail, PatchViewer, LimitationsCard, AiDisclosure
  app/page.tsx                    ← Home
  app/analyses/[id]/page.tsx      ← Run + Capsule (same route)
  app/analyses/[id]/deps/[name]/page.tsx  ← optional; a drawer is fine instead
```

## 4. Relative URLs — IMPORTANT
Every URL **inside API responses** (`links.*`, `run.log_urls.*`, `run.junit_url`, `patch.url`, and evidence `url`s that start with `/`) is **relative to the API base**, not the frontend. Always wrap them:
```ts
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
export const apiUrl = (u: string) => /^https?:\/\//.test(u) ? u : `${API}${u}`;
```
Absolute URLs (osv.dev, pypi.org, `terms_url`) are used as-is and open in a new tab.
In mock mode, map them to fixture files (see §5).

## 5. API calls per screen + mock mapping
| Function in `api.ts` | Live request | Mock source |
|---|---|---|
| `getHealth()` | `GET /api/health` | `/fixtures/health.json` |
| `listAnalyses()` | `GET /api/analyses` | `/fixtures/analyses_list.json` |
| `createAnalysis(repo_url)` | `POST /api/analyses` body `{repo_url}` | `/fixtures/created.json` |
| `getJob(id)` | `GET /api/analyses/{id}` | `job_failed.json` if id = `dx_fail01`; during replay `job_running.json`, after replay `job_completed.json` |
| `subscribe(id)` | `EventSource(GET /api/analyses/{id}/events)` | replay `/fixtures/events.ndjson`, one line every 400 ms |
| `getCapsule(id)` | `GET /api/analyses/{id}/capsule` (409 = not ready) | `/fixtures/capsule.json` |
| `getCapsuleMd(id)` | `GET /api/analyses/{id}/capsule.md` | `/fixtures/capsule.md` |
| `getPatch(id)` | `GET /api/analyses/{id}/patch.diff` | `/fixtures/patch.diff` |
| `getLog(id, run, stream)` | `GET /api/analyses/{id}/runs/{run}/log?stream=install\|test` | `/fixtures/logs/{run}-{stream}.log` |

Errors: non-2xx returns `{error:{code,message}}`. Show `message` in a coral notice. Treat `409` on capsule as "still running", not as an error.

Downloads (JSON / Markdown / Patch buttons): plain `<a href={apiUrl(...)} download>` links.

## 6. Live progress logic (`useAnalysis(id)`)
1. `getJob(id)`. If the status is `completed`, `completed_with_errors` or `failed`, skip to step 4.
2. Open the `EventSource`. Listen to the named events: `stage_started`, `stage_completed`, `stage_failed`, `stage_skipped`, `log`, `ai_call`, `job_completed`, `job_failed` (use `es.addEventListener(name, …)`, because these are not default `message` events). Each `data` is JSON with `seq`, and the server replays past events on connect, so **dedupe by `seq`**.
3. Update local stage state from the events. Push `log` events into the log panel (keep the last 200). Count `ai_call` events and note failed ones (`ok:false`).
4. On `job_completed`, or when the job is already finished: `getCapsule(id)` and show the Capsule view. On `job_failed`: show the failed stage error plus a "Try again" button that goes back to Home.
5. Fallback: if `EventSource` errors twice, close it and poll `getJob(id)` every 2 s until the job finishes.

## 7. Screens
### 7.1 Home `/`
- Hero (2 columns): eyebrow `DEPENDENCY RESILIENCE` · H1 "Exit risky dependencies **with proof**" (marker swipe on "with proof") · subtitle "Gemma 4 proposes the migration. Docker proves it." Right column: a lavender FeatureCard with 3 bullets: Scan → Migrate → Verify.
- Search-bar style input, prefilled `https://github.com/rishrek/LinkWatch`, with the primary button **Analyze** → `createAnalysis` → navigate to `/analyses/{id}`. Validate the `https://github.com/owner/repo` format on the client too.
- Health strip: chips "Docker ✓", "AI service ✓", "Gemma 4: {model}" (mint when OK, danger when down). If Gemma isn't configured, show a notice that results will use the fallback.
- "Recent analyses": list rows (repo, time, status badge, at-risk count) linking to `/analyses/{id}`.

### 7.2 Analysis `/analyses/[id]`, running state
- Header: repo URL + commit chip + status badge.
- **StageTimeline**: the 9 stages in this order: `clone, scan, usage, propose, materialize, sandbox_baseline, sandbox_migrated, compare, capsule`, with labels from `API_CONTRACT §2.3`. `sandbox_baseline` runs in parallel with scan/usage/propose, so several stages can be "running" at once. Show it as a parallel lane or just let two rows spin.
  - pending = white card, muted text · running = butter + spinner · completed = mint + check + `duration_s` · failed = danger border + error text · skipped = muted + strikethrough.
- **LogPanel**: mono, dark ink background, `[stage] message`, warns in butter text; auto-scroll.
- **Gemma 4 activity card** (lavender): "N calls · M failed" plus the last 5 `ai_call` purposes with latency.

### 7.3 Analysis `/analyses/[id]`, capsule state (main screen)
Top to bottom:
1. **Header row:** repo + commit, verdict **Sticker** (`safe_to_migrate` → mint "SAFE!", `migrate_with_care` → butter "CAREFUL!", `blocked` → coral "BLOCKED!"), `summary.headline`, buttons: Download JSON · Markdown · Patch.
2. **KPI tiles** (4 FeatureCards): Dependencies scanned `dependencies_total` (sky) · At risk `at_risk` + mini breakdown by level (coral) · Tests passing `baseline.passed → migrated.passed` of `total` (mint) · Gaps `regressed` regressed / `still_failing` still failing / `fixed` fixed (butter).
3. **TestComparison card:** columns Baseline | Migrated. Each has a status badge, a stacked bar (passed mint / failed coral / errors danger / skipped muted) and "install log" / "test log" links (open in a modal with mono text). Below it, a table of every test id with the outcome in each run and a change badge: fixed (mint), regressed (danger), still_failing (coral), unchanged (none). Join the two runs' `tests` by `id`.
4. **DependencyTable:** columns: Name · Version (`pinned_version → latest_version`, or "undeclared") · Risk (RiskBadge + score) · Indicators (small chips with the codes, max 3 then "+n") · Proposal (strategy chip + package, e.g. `replace → platdirs`, `stdlib → tomllib`, `remove`, `declare`) · Applied (✓ mint / ✗ coral with tooltip `not_applied_reason`) · Gaps count. Sorted by score descending, with filter chips for level. Rows with level ≥ high get the 3px danger border from design.md. Clicking a row opens DependencyDetail.
5. **PatchViewer:** card with a file list and a diff body. Lines starting with `+` get a mint background, `-` coral, `@@` sky. Mono 13px. Collapsible per file (split on `--- a/`).
6. **LimitationsCard:** cream-yellow notice banner with the `limitations[]` bullet list. Never hide it.
7. **AiDisclosure:** small white card: provider, model (CodeChip), calls, failed_calls, fallback_used (badge), terms link.

### 7.4 DependencyDetail (drawer or page)
Sections in **exactly this order** (they match the problem statement):
1. **Details:** name, import names, declared at (`file:line` CodeChips + spec), pinned / latest / latest release date / requires_python, homepage link.
2. **Risk indicators:** RiskBadge + score; `rationale` with its ProvenanceTag; a list of indicators: code chip, severity badge, detail, and evidence links (`osv` → url, `pypi` → url, `ast` → `ref` as a CodeChip, `sandbox` → log modal, `manifest` → `ref` CodeChip, `knowledge` → detail text).
3. **Usage locations:** table `file:line` · kind chip · code (mono). Highlight `private_api` and `monkeypatch` rows in coral. Show `summary` + ProvenanceTag above it. Empty → "Not imported anywhere".
4. **Proposed replacement:** strategy chip, package + version_spec, confidence bar (0–1), rationale, alternatives list ("rejected: reason"). ProvenanceTag.
5. **Migration steps:** numbered list, `files_changed` chips, applied ✓/✗ + `not_applied_reason` in a coral notice.
6. **Suggested tests:** collapsible mono code blocks with name + purpose.
7. **Executed test results:** `status` badge + `affected_tests` with their outcome in each run (look them up in `capsule.runs`).
8. **Compatibility gaps:** cards: test id, `baseline → migrated`, change badge, severity badge, explanation + ProvenanceTag.
9. **Open concerns:** bullets with ProvenanceTag.
If any optional field is missing (`replacement`, `migration`, `test_results`), show "Not applicable" in muted text. Never crash.

### 7.5 Sandbox terminals (live telemetry)
- Two dark terminal panes side by side: **Baseline (original deps)** | **Migrated (replacements)**. Each has tabs `install` / `test` (auto-switch to `test` when its first line arrives).
- Feed: `sandbox_log` events (`run`, `stream`, `line`), deduped by `seq`, appended in order, autoscroll, monospace 12px. Colour lines containing `PASSED` mint, `FAILED`/`ERROR` coral/danger, `exit code: 0` mint, other exit codes danger; lines starting with `$` muted bold.
- Show on the running view (under the stage timeline) and keep it on the capsule view (collapsed by default). For finished jobs the events replay from the start, so the panes fill instantly.
- Empty state: "Waiting for Docker…" (the migrated pane fills only after `materialize`; say so).
- Mock: `fixtures/events.ndjson` contains `sandbox_log` lines.

> **Implemented:** `components/BlastRadiusGraph.tsx` (7.6, in DependencyDetail) and `components/CodeDiffViewer.tsx` (Monaco diff of `/files` + `/original/{path}` vs `/migrated/{path}`, on the capsule page). Still open: 7.5 sandbox terminals.

### 7.6 Blast radius (per dependency)
- In DependencyDetail, a new section **Blast radius** right after **Usage locations**: headline from `stats`: "`lines` lines in `direct_files` files use it · `indirect_files` modules import those · `test_files`/`total_test_files` test files reach it".
- Graph: render `nodes`/`edges` as 3 columns, left to right: dependency (coral) → direct modules (butter, show line count) → indirect modules (sky) → tests (mint). Draw `edges` as lines (SVG); `kind: conftest` edges dashed. A clean Tailwind column layout with connector lines is enough; no graph library required.
- Below: per direct file, the exact lines (`line`, `kinds` chips, `code` mono); per indirect file/test, the `via` chain as `a → b → c` CodeChips. `provenance` is always evidence (mint "Evidence" tag).
- Optional: a capsule-level "Blast map" card listing the top 5 dependencies by `stats.test_files` then `stats.lines`.
- `blast_radius` is `null` for dependencies that are not imported (e.g. unused ones) — show "Not imported anywhere".

## 8. Shared components
| Component | Spec |
|---|---|
| `RiskBadge` | critical → danger text on `#FDECEC` + 2px danger border · high → coral · medium → butter · low → sky · none → mint. Text = level uppercase. |
| `ProvenanceTag` | `ai` → lavender chip with ✨ "Gemma 4" · `evidence` → mint chip "Evidence" · `derived` → white chip "Computed". Tooltip explains each. |
| `StrategyChip` | replace (sky), upgrade (mint), stdlib (lavender), remove (coral), declare (butter), keep (white). |
| `CodeChip` | JetBrains Mono 12px, white pill, for `file:line`, versions, commit. |
| `Sticker` | starburst per design.md, rotated -6deg, max 1 per screen (the verdict). |
| Empty/error | Backend down → coral notice "Backend not reachable at {API}" + retry. 404 → "Analysis not found". |

## 9. Acceptance checklist (UI is done when…)
- [ ] With `MOCK=1`: Home → Analyze → timeline animates through all 9 stages from `events.ndjson` → capsule view renders every section from `capsule.json` without console errors.
- [ ] `dx_fail01` from the recent list shows the failed state.
- [ ] All 8 fixture dependencies open in the detail view; `compatsix` (no usage), `certstore` (undeclared) and `richout` (no migration) render without crashing.
- [ ] `httpkit` shows "not applied" with its reason; `valimodel` shows the regressed gap.
- [ ] Log modals and the patch viewer load their fixture files.
- [ ] Every AI-written text block shows a ProvenanceTag.
- [ ] With `MOCK=0` against the live backend, the same flow works with no code changes; any mismatch is reported to the backend owner, not patched around.
- [ ] Layout works at 375px width.

## 10. Do not
- Rename or reshape API fields, or add required fields. If you need something new, ask the backend owner (`docs/REQUESTS.md`).
- Hardcode any LinkWatch-specific text, package names or results in components. Everything comes from the API or fixtures.
- Add colours, fonts or shadows beyond `design.md`, or dark mode.
