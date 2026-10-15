# API_CONTRACT.md — Go API ↔ UI

> **Frozen at T+0:20.** Changing anything here requires updating this file *and* `fixtures/` in the same commit and telling the other lane.
> The **Capsule types in §5 are canonical** — `ai/schemas/capsule.schema.json` must match them.

Base URL: `http://localhost:8080` (UI env `NEXT_PUBLIC_API_URL` / `VITE_API_URL`).
JSON everywhere, `snake_case` keys, timestamps RFC 3339 UTC. CORS allows `ALLOWED_ORIGINS`.

> **Relative URLs:** every URL the API returns that starts with `/` (`links.*`, `run.log_urls.*`, `run.junit_url`, `patch.url`, evidence `url`) is relative to the **API base URL**, not the frontend origin. Clients must prefix it: `apiUrl(u) = u.startsWith("http") ? u : API_BASE + u`. Absolute URLs (osv.dev, pypi.org, terms) are used as-is.

## 1. Error format (all non-2xx)
```json
{ "error": { "code": "not_found", "message": "analysis dx_7f3a not found" } }
```
Codes: `bad_request` (400), `not_found` (404), `conflict` (409, e.g. capsule not ready), `unavailable` (503, docker/AI down), `internal` (500).

## 2. Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | service status |
| POST | `/api/analyses` | start an analysis |
| GET | `/api/analyses` | list analyses (newest first) |
| GET | `/api/analyses/{id}` | job status + stages + summary |
| GET | `/api/analyses/{id}/events` | **SSE** live progress |
| GET | `/api/analyses/{id}/capsule` | `capsule.json` (409 until ready) |
| GET | `/api/analyses/{id}/capsule.md` | `CAPSULE.md` (`text/markdown`) |
| GET | `/api/analyses/{id}/patch.diff` | unified diff (`text/x-diff`) |
| GET | `/api/analyses/{id}/runs/{run_id}/log?stream=install\|test` | raw log (`text/plain`) |
| GET | `/api/analyses/{id}/runs/{run_id}/junit` | raw JUnit XML |
| GET | `/api/analyses/{id}/bundle.zip` | *(stretch)* whole capsule folder |

### 2.1 `GET /api/health` → 200
```json
{ "status": "ok", "docker": true, "sandbox_image_ready": true,
  "ai_service": true, "gemma": { "configured": true, "model": "gemma-4-…", "reachable": true },
  "version": "0.1.0" }
```

### 2.2 `POST /api/analyses`
Request (all optional except `repo_url`):
```json
{ "repo_url": "https://github.com/rishrek/LinkWatch", "ref": "main",
  "options": { "isolated_runs": false, "repair": false, "max_dependencies": 20 } }
```
Response **202**:
```json
{ "id": "dx_7f3a9c", "status": "queued", "created_at": "2026-10-15T10:00:00Z",
  "links": { "self": "/api/analyses/dx_7f3a9c", "events": "/api/analyses/dx_7f3a9c/events" } }
```
Validation: `repo_url` must be `https://github.com/<owner>/<repo>` (optionally `.git`) → else 400.

### 2.3 `GET /api/analyses/{id}` → 200 (`Job`)
```ts
type JobStatus = "queued" | "running" | "completed" | "completed_with_errors" | "failed";
type StageId = "clone" | "scan" | "usage" | "propose" | "materialize"
             | "sandbox_baseline" | "sandbox_migrated" | "compare" | "capsule"
             | `sandbox_isolated:${string}` | "repair" | "sandbox_migrated_r1";
type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

interface Stage { id: StageId; label: string; status: StageStatus;
  started_at?: string; finished_at?: string; duration_s?: number; error?: string; }

interface Job {
  id: string; repo_url: string; ref: string; commit?: string;
  status: JobStatus; created_at: string; finished_at?: string;
  stages: Stage[];                 // fixed order as in ARCHITECTURE.md §3
  summary?: CapsuleSummary;        // present once capsule exists (see §5)
  error?: string;
}
```
Stage labels (UI shows these): `clone` "Cloning repository" · `scan` "Scanning dependencies" · `usage` "Mapping usage" · `propose` "Gemma 4: proposing replacements" · `materialize` "Building migrated workspace" · `sandbox_baseline` "Testing original dependencies" · `sandbox_migrated` "Testing replacements" · `compare` "Gemma 4: analysing gaps" · `capsule` "Generating Exit Capsule".

### 2.4 `GET /api/analyses` → 200
```json
{ "items": [ { "id": "dx_7f3a9c", "repo_url": "…", "status": "completed", "created_at": "…",
               "summary": { "dependencies_total": 14, "at_risk": 9 } } ] }
```

### 2.5 `GET /api/analyses/{id}/events` — Server-Sent Events
On connect the server **replays all past events** for the job, then streams live. Heartbeat comment `: ping` every 15 s. Stream closes after `job_completed`/`job_failed`.
```
event: stage_started
data: {"seq":3,"ts":"…","stage":"scan"}

event: log
data: {"seq":4,"ts":"…","stage":"scan","level":"info","message":"jinja2==2.11.3: 2 OSV advisories"}

event: stage_completed
data: {"seq":9,"ts":"…","stage":"scan","duration_s":6.2,"stats":{"dependencies":14,"at_risk":9}}

event: stage_failed
data: {"seq":20,"ts":"…","stage":"sandbox_migrated","error":"install timeout after 300s"}

event: job_completed
data: {"seq":40,"ts":"…","status":"completed","summary":{…CapsuleSummary}}
```
Event types: `job_started`, `stage_started`, `stage_completed`, `stage_failed`, `stage_skipped`, `log`, `ai_call` (`{stage, purpose, model, latency_ms, ok}`), `job_completed`, `job_failed`.
UI fallback if SSE breaks: poll `GET /api/analyses/{id}` every 2 s.

## 3. Status codes summary
`capsule`, `capsule.md`, `patch.diff` → **409 `conflict`** while job not finished; 404 if the job finished without producing it.

## 4. Provenance
Any object may carry `"provenance": "evidence" | "ai" | "derived"`.
- `evidence` — fetched/observed (PyPI, OSV, AST, test run). UI: plain / green check icon.
- `ai` — written by Gemma 4. UI: sparkle icon + "Gemma 4" chip.
- `derived` — computed by deterministic code from evidence (scores, diffs).

## 5. Capsule (canonical types)
```ts
type RiskLevel = "critical" | "high" | "medium" | "low" | "none";
type Strategy  = "replace" | "upgrade" | "remove" | "stdlib" | "declare" | "keep";  // declare = add missing declaration
type IndicatorCode =
  | "KNOWN_VULNERABILITY" | "DEPRECATED_PACKAGE" | "STDLIB_REPLACEMENT_AVAILABLE"
  | "MAJOR_VERSIONS_BEHIND" | "OUTDATED" | "UNMAINTAINED" | "PY312_INCOMPATIBLE"
  | "MANIFEST_DRIFT" | "UNDECLARED" | "DECLARED_UNUSED" | "UNPINNED"
  | "PRIVATE_API_USE" | "MONKEYPATCH" | "DEPRECATED_API_USE" | "YANKED";

interface Evidence { source: "pypi" | "osv" | "ast" | "manifest" | "sandbox" | "knowledge";
                     ref?: string; url?: string; detail?: string; }

interface Indicator { code: IndicatorCode; severity: RiskLevel; detail: string;
                      evidence: Evidence[]; provenance: "evidence" | "derived"; }

interface Declaration { file: string; line: number; spec: string; }  // e.g. requirements.txt:5 "Jinja2==2.11.3"

interface UsageLocation { file: string; line: number; col?: number; code: string;   // source line
  kind: "import" | "from_import" | "call" | "attribute" | "private_api" | "monkeypatch" | "subclass" | "decorator";
  symbol?: string; }

interface Dependency {
  name: string;                       // normalized (PEP 503)
  import_names: string[];             // e.g. ["jinja2"]
  declared: Declaration[];            // empty => undeclared
  pinned_version?: string; latest_version?: string; latest_release_date?: string;
  last_release_of_pinned?: string; requires_python?: string; homepage?: string;
  risk: { level: RiskLevel; score: number /*0-100*/; indicators: Indicator[];
          rationale: string; rationale_provenance: "ai" | "derived"; };
  usage: { locations: UsageLocation[]; files: string[]; summary: string;
           summary_provenance: "ai" | "derived"; };
  replacement?: { strategy: Strategy; package?: string; version_spec?: string;
                  rationale: string; confidence: number /*0-1*/;
                  alternatives: { package: string; reason_rejected: string }[];
                  provenance: "ai" | "derived"; };
  migration?: { steps: string[]; files_changed: string[]; applied: boolean;
                not_applied_reason?: string; provenance: "ai"; };
  suggested_tests: { name: string; purpose: string; code?: string; provenance: "ai" }[];
  test_results?: { run_ids: string[]; affected_tests: string[];       // tests touching files that use this dep
                   status: "pass" | "fail" | "mixed" | "not_run"; };
  compatibility_gaps: Gap[];
  open_concerns: { text: string; provenance: "ai" | "derived" }[];
}

interface TestCase { id: string;            // "tests/test_config.py::test_load"
  outcome: "passed" | "failed" | "error" | "skipped"; message?: string; duration_s?: number; }

interface Run {
  id: string;                         // "baseline" | "migrated" | "isolated-jinja2" | "migrated_r1"
  kind: "baseline" | "migrated" | "isolated" | "repair";
  dependency?: string; image: string; command: string[];
  status: "passed" | "tests_failed" | "install_failed" | "timeout" | "error";
  install_exit_code?: number; test_exit_code?: number; duration_s: number;
  totals: { passed: number; failed: number; errors: number; skipped: number; total: number };
  tests: TestCase[];
  log_urls: { install: string; test: string }; junit_url?: string;
}

interface Gap {
  test_id: string | null;             // null for install-level gaps
  baseline: TestCase["outcome"] | "not_run" | "install_failed";
  migrated: TestCase["outcome"] | "not_run" | "install_failed";
  change: "fixed" | "regressed" | "still_failing" | "install_regressed" | "install_fixed";
  dependencies: string[];             // suspected deps
  explanation: string; severity: RiskLevel; provenance: "ai" | "derived";
}

interface CapsuleSummary {
  dependencies_total: number; at_risk: number;
  by_level: Record<RiskLevel, number>;
  baseline: Run["totals"] & { status: Run["status"] };
  migrated: Run["totals"] & { status: Run["status"] };
  gaps: { fixed: number; regressed: number; still_failing: number };
  verdict: "safe_to_migrate" | "migrate_with_care" | "blocked";   // derived
  headline: string;                   // one sentence, ai or derived
}

interface Capsule {
  schema_version: "1.0";
  capsule_id: string; generated_at: string;
  tool: { name: "DepExit"; version: string };
  target: { repo_url: string; ref: string; commit: string; python_version: string;
            manifests: string[]; };
  ai: { provider: "Google AI Studio (Gemini API)"; model: string; calls: number;
        failed_calls: number; fallback_used: boolean; terms_url: string; };
  summary: CapsuleSummary;
  dependencies: Dependency[];         // ALL declared + undeclared deps; sorted by risk score desc
  runs: Run[];
  patch: { url: string; files_changed: number; insertions: number; deletions: number };
  limitations: string[];              // honest list, always non-empty
}
```

## 6. Example (illustrative fixture — NOT real tool output)
The full mock set already exists in `fixtures/` (capsule with 8 deps and 2 runs, job states, SSE replay, patch, logs). See `FRONTEND_GUIDE.md §5` for the mapping. The short excerpt below shows the shape; values are invented for layout only.
```json
{
  "schema_version": "1.0",
  "capsule_id": "dx_demo01",
  "generated_at": "2026-10-15T10:04:12Z",
  "tool": { "name": "DepExit", "version": "0.1.0" },
  "target": { "repo_url": "https://github.com/example/demo", "ref": "main", "commit": "abc1234",
              "python_version": "3.12", "manifests": ["requirements.txt", "pyproject.toml"] },
  "ai": { "provider": "Google AI Studio (Gemini API)", "model": "gemma-4-example", "calls": 11,
          "failed_calls": 0, "fallback_used": false, "terms_url": "https://ai.google.dev/gemma/terms" },
  "summary": {
    "dependencies_total": 3, "at_risk": 2,
    "by_level": { "critical": 1, "high": 1, "medium": 0, "low": 0, "none": 1 },
    "baseline": { "passed": 2, "failed": 0, "errors": 3, "skipped": 0, "total": 5, "status": "tests_failed" },
    "migrated": { "passed": 4, "failed": 1, "errors": 0, "skipped": 0, "total": 5, "status": "tests_failed" },
    "gaps": { "fixed": 3, "regressed": 0, "still_failing": 1 },
    "verdict": "migrate_with_care",
    "headline": "Migration fixes 3 collection errors; 1 test still fails after the config library swap."
  },
  "dependencies": [
    {
      "name": "templatelib", "import_names": ["templatelib"],
      "declared": [{ "file": "requirements.txt", "line": 4, "spec": "templatelib==1.0.0" }],
      "pinned_version": "1.0.0", "latest_version": "3.1.0", "latest_release_date": "2025-03-01",
      "risk": {
        "level": "critical", "score": 88,
        "indicators": [
          { "code": "KNOWN_VULNERABILITY", "severity": "high", "detail": "2 advisories affect 1.0.0",
            "evidence": [{ "source": "osv", "ref": "GHSA-xxxx-xxxx-xxxx", "url": "https://osv.dev/vulnerability/GHSA-xxxx-xxxx-xxxx" }],
            "provenance": "evidence" },
          { "code": "PY312_INCOMPATIBLE", "severity": "critical", "detail": "ImportError during test collection",
            "evidence": [{ "source": "sandbox", "ref": "baseline", "detail": "ImportError: cannot import name 'x'" }],
            "provenance": "evidence" }
        ],
        "rationale": "Pinned two majors behind with known advisories and fails to import on 3.12.",
        "rationale_provenance": "ai"
      },
      "usage": {
        "locations": [{ "file": "demo/report.py", "line": 3, "kind": "from_import",
                        "code": "from templatelib import Environment", "symbol": "Environment" }],
        "files": ["demo/report.py"], "summary": "Used only to render one HTML template.", "summary_provenance": "ai"
      },
      "replacement": { "strategy": "upgrade", "package": "templatelib", "version_spec": ">=3.1,<4",
        "rationale": "Same API surface for the features used; upgrade beats replacement.", "confidence": 0.85,
        "alternatives": [{ "package": "othertpl", "reason_rejected": "Different template syntax" }], "provenance": "ai" },
      "migration": { "steps": ["Bump pin to >=3.1,<4", "Replace removed helper with stdlib equivalent"],
        "files_changed": ["requirements.txt", "demo/report.py"], "applied": true, "provenance": "ai" },
      "suggested_tests": [{ "name": "test_report_escapes_html", "purpose": "Autoescape still on after upgrade",
        "code": "def test_report_escapes_html(): ...", "provenance": "ai" }],
      "test_results": { "run_ids": ["baseline", "migrated"], "affected_tests": ["tests/test_report.py::test_render"], "status": "pass" },
      "compatibility_gaps": [],
      "open_concerns": [{ "text": "Custom filters not covered by tests.", "provenance": "ai" }]
    }
  ],
  "runs": [
    { "id": "baseline", "kind": "baseline", "image": "python:3.12-slim",
      "command": ["python", "-m", "pytest", "-q"], "status": "tests_failed",
      "install_exit_code": 0, "test_exit_code": 2, "duration_s": 41.2,
      "totals": { "passed": 2, "failed": 0, "errors": 3, "skipped": 0, "total": 5 },
      "tests": [{ "id": "tests/test_report.py::test_render", "outcome": "error", "message": "ImportError …" }],
      "log_urls": { "install": "/api/analyses/dx_demo01/runs/baseline/log?stream=install",
                    "test": "/api/analyses/dx_demo01/runs/baseline/log?stream=test" },
      "junit_url": "/api/analyses/dx_demo01/runs/baseline/junit" }
  ],
  "patch": { "url": "/api/analyses/dx_demo01/patch.diff", "files_changed": 3, "insertions": 18, "deletions": 11 },
  "limitations": [
    "Test suite covers 4 of 9 modules; untested behaviour changes cannot be detected.",
    "Replacement choices are model-generated and should be reviewed by a maintainer."
  ]
}
```
`fixtures/events.ndjson` holds one SSE `data` object per line, with an extra `"event"` field naming the SSE event type, for UI replay.
