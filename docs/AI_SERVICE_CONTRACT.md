# AI_SERVICE_CONTRACT.md — Go ↔ FastAPI AI service (+ Gemma 4)

Base URL `http://localhost:8001` (`AI_SERVICE_URL`). Python 3.12, FastAPI, pydantic v2, httpx.
**File-based handoff:** every endpoint receives `job_dir` (absolute path `DATA_DIR/<job_id>`), reads earlier stage files from it, writes its own output file there, and returns the same JSON. Go only sequences calls and never transforms AI data.

Errors: HTTP 4xx/5xx with `{"error":{"code","message"}}`. A Gemma failure is **not** an HTTP error — the endpoint falls back to deterministic output and sets `provenance:"derived"` + increments `failed_calls`.
Every response includes `"ai_calls": [{ "purpose", "model", "latency_ms", "ok", "error?" }]` → Go forwards each as an SSE `ai_call` event and appends to `job_dir/ai_calls.jsonl`.

Timeout budget Go → AI per call: `scan` 60 s, `usage` 60 s, `propose` 180 s, `materialize` 180 s, `compare` 90 s, `capsule` 60 s.

## 1. Endpoints
### `GET /v1/health`
`{ "status":"ok", "gemma": { "configured": bool, "model": str, "reachable": bool } }` (reachable = cached result of a 1-token test call at startup).

### `POST /v1/scan` → writes `scan.json`
Req `{ "job_dir": str, "repo_dir": "…/repo", "python_version": "3.12" }`
1. Discover manifests: `requirements*.txt` (follow `-r`), `pyproject.toml` (`[project].dependencies`, `optional-dependencies`, `[build-system].requires` noted but not risk-scored), `setup.cfg`, `setup.py` (regex best-effort). Keep file + line for each spec; record commented-out specs as notes only.
2. Normalize names (PEP 503). Merge declarations per package; **MANIFEST_DRIFT** if specs across files are not compatible (e.g. `==1.10.13` vs `>=2`, use `packaging.specifiers`).
3. AST-walk all `*.py` (skip `.venv`, `build`, `.git`) → top-level imports. Drop stdlib (`sys.stdlib_module_names`) and local packages (top-level dirs/modules of the repo). Map import name → distribution via `knowledge.IMPORT_TO_DIST` then fallback same name. Import not declared → **UNDECLARED** (if a declared dep's PyPI `requires_dist` contains it, detail = "only available transitively via X"). Declared but never imported (and not a known plugin/tool like pytest, setuptools build use) → **DECLARED_UNUSED**.
4. PyPI `GET {PYPI_URL}/{name}/json` and `/{name}/{pinned}/json` (concurrent, cache in `DATA_DIR/_cache/pypi/`): latest version, release dates, `requires_python`, classifiers, `yanked`, project URLs, `Development Status :: 7 - Inactive`.
5. OSV `POST {OSV_URL}` `{"package":{"name":n,"ecosystem":"PyPI"},"version":pinned}` → vulns (id, aliases, summary, severity, fixed versions). Unpinned spec → query latest-allowed is unknowable; query only pinned, else note "not checked (unpinned)".
6. Indicators + score (§3). Python-version incompatibility from metadata only here (`requires_python` excludes 3.12, or pinned release older than 2 years with no 3.1x classifier → weak, severity `low`); strong evidence is added later from the sandbox in `compare`.
7. `risk.rationale` is deterministic here; Gemma's `risk_summary` from the per-dependency `decide` call replaces it in the capsule (one call per dependency instead of an extra batched call).

Res (`scan.json`):
```json
{ "manifests": ["requirements.txt","requirements-dev.txt","pyproject.toml"],
  "install_files": ["requirements.txt","requirements-dev.txt"],
  "local_packages": ["linkwatch"],
  "dependencies": [ /* Dependency objects (API_CONTRACT §5) with name, import_names, declared,
                       version fields, risk; usage/replacement/... not yet filled */ ],
  "notes": ["pyproject build-system requires setuptools>=61"],
  "ai_calls": [] }
```

### `POST /v1/usage` → writes `usage.json`
Req `{ "job_dir", "repo_dir" }` (reads `scan.json`).
AST per file, per dependency import names:
- `import x` / `import x.y as z` / `from x import a, b` → locations kind `import` / `from_import`; track aliases.
- Uses of aliased names: `Call` → `call`, `Attribute` → `attribute`, `ClassDef` bases → `subclass`, decorators → `decorator`.
- Attribute/name starting with `_` on a dep object or `from x.y import _z` → `private_api` + indicator **PRIVATE_API_USE**.
- Assignment whose target is an attribute of a dep (`requests.Session.request = …`) → `monkeypatch` + **MONKEYPATCH**.
- Known deprecated APIs from `knowledge.DEPRECATED_APIS` (e.g. module `pkg_resources`, pydantic v1 `validator`/`class Config`) → **DEPRECATED_API_USE** (evidence = location; detail from hint).
- `code` = stripped source line. Include `tests/` but mark files under tests.
Usage summary is deterministic here; Gemma's `usage_summary` from the `decide` call replaces it in the capsule.
Res: `{ "usage": { "<dep>": { "locations": [...], "files": [...], "summary": str, "summary_provenance": "ai|derived" } }, "extra_indicators": { "<dep>": [Indicator] }, "ai_calls": [] }`
(`extra_indicators` are merged and scores recomputed by `capsule`.)

### `POST /v1/propose` → writes `proposals.json`
Req `{ "job_dir", "repo_dir", "min_level": "medium" }`.
For each dep with level ≥ `min_level` (plus every UNDECLARED / DECLARED_UNUSED dep regardless of level), concurrency `GEMMA_MAX_CONCURRENCY`:
1. Build candidates: `knowledge.CANDIDATES.get(name, [])` + "upgrade to latest" + "stdlib" if hinted. Fetch PyPI health for each candidate (latest, last release, requires_python).
2. **Gemma call `decide`** (prompt §4.2) → strategy, package, version_spec, rationale, confidence, alternatives, steps, suggested_tests, open_concerns.
3. Validate: package exists on PyPI (unless strategy in `remove|stdlib|keep`), version_spec parses. Invalid → retry once with the error; still invalid → deterministic fallback (`upgrade` to latest major if not deprecated, else `keep` + concern).
Deps below `min_level` get deterministic `keep` (or `upgrade` if OUTDATED) with `provenance:"derived"`.
Res: `{ "proposals": { "<dep>": { "replacement": {...}, "migration": { "steps": [...], "provenance": "ai" }, "suggested_tests": [...], "open_concerns": [...] } }, "ai_calls": [] }`

### `POST /v1/materialize` → writes `materialize.json`, `patch.diff`, `runs/migrated/repo/`
Req `{ "job_dir", "repo_dir", "out_repo_dir": "…/runs/migrated/repo" }`.
1. Copy `repo_dir` → `out_repo_dir` (excluding `.git`).
2. **Manifests rewritten deterministically** from decisions: replace/stdlib/remove → drop old line; replace/upgrade/declare → write `package + version_spec`. Apply to every manifest that declared it (requirements*.txt, `[project].dependencies`). Preserve comments/order.
3. Group affected `.py` files = union of `usage.files` (non-test first; tests only if they import the dep directly) of deps whose strategy ∈ `replace|stdlib|remove|upgrade` *and* whose `steps` imply code changes.
4. **Gemma call `rewrite_file`** per file (prompt §4.3), concurrently: input = full file, the decisions for every dep used in that file, the relevant usage lines. Output = minimal search/replace `edits` (each `old` must match exactly once) + `changes`; edits are applied deterministically. After all files: a dependency whose edits did not land in every file keeps its original manifest line and its partial edits are reverted, so code and manifests stay consistent.
5. Validate each output: non-empty, `compile()` succeeds, no new imports of packages not in the new manifest/stdlib/local, file length within 0.5×–2× original. Fail → keep original file, mark dep migration `applied:false` + `not_applied_reason`.
6. Unified diff of all changed files (`difflib.unified_diff`, `a/` `b/` paths) → `patch.diff`.
Res: `{ "files": [{ "path", "status": "applied|rejected|unchanged", "reason?", "deps": [] }], "manifest_changes": [{ "file","before","after" }], "patch": { "files_changed","insertions","deletions" }, "ai_calls": [] }`

### `POST /v1/compare` → writes `compare.json`
Req `{ "job_dir", "run_ids": ["baseline","migrated", ...] }`. Reads `runs/<id>/result.json`, `junit.xml`, `install.log`, `test.log`.
1. Parse JUnit → `TestCase[]` (id = `classname`→path + `::name`; outcome from failure/error/skipped). Missing junit + install failed → `status:"install_failed"`, tests `[]`.
2. Pair baseline vs each other run by test id → `Gap` per test whose outcome differs or is still failing; install-level gap if install status differs.
3. Attribute suspected deps (derived): traceback/message mentions an import name → that dep; else test file's imports → local modules → deps used in those modules (from `usage.json`).
4. Sandbox indicators: baseline install failure or `ImportError/ModuleNotFoundError/AttributeError` in a dep's module path on python 3.12 → **PY312_INCOMPATIBLE** (`severity: critical`, evidence source `sandbox`, detail = the error line).
5. **Gemma call `explain_gaps`** (one call, all gaps + trimmed error messages ≤ 1500 chars each) → `explanation`, `severity` per gap, plus `headline`.
Res: `{ "runs": [Run], "gaps": [Gap], "sandbox_indicators": { "<dep>": [Indicator] }, "headline": str, "ai_calls": [] }`

### `POST /v1/capsule` → writes `capsule.json`, `CAPSULE.md`
Req `{ "job_dir", "target": { "repo_url","ref","commit","python_version" }, "stage_errors": { "<stage>": "msg" }, "base_url": "/api/analyses/<id>" }`.
Merge all stage files → `Capsule` (API_CONTRACT §5); merge extra + sandbox indicators and **recompute scores**; fill `test_results` per dep (runs + affected tests via usage files); summary + verdict (`blocked` if migrated install failed or regressions > 0 with critical severity; `safe_to_migrate` if migrated has 0 failures/errors and no regressions; else `migrate_with_care`); `limitations` = stage errors + fallback use + rejected edits + coverage notes + fixed list (§6). Validate with `schemas/capsule.schema.json` (jsonschema); if invalid, still write it but add the validation error to `limitations`.
Render `CAPSULE.md`: header, summary table, per-dependency sections in this order: Details · Risk indicators (with evidence links) · Usage locations · Proposed replacement · Migration steps · Suggested tests · Executed test results · Compatibility gaps · Open concerns; then Runs table, Patch stats, Limitations, AI disclosure (model, provider, calls, terms).

## 2. Gemma 4 client (`app/gemma.py`)
```
POST https://generativelanguage.googleapis.com/v1beta/models/{GEMMA_MODEL}:generateContent
Header: x-goog-api-key: {GEMINI_API_KEY}
Body: { "contents":[{"role":"user","parts":[{"text": SYSTEM + "\n\n" + USER}]}],
        "generationConfig": { "temperature": 0.2, "maxOutputTokens": 8192 } }
Text = concat of candidates[0].content.parts[*].text, skipping parts with "thought": true
```
- Put system instructions **inside the user turn** (portable across Gemma variants; do not rely on `systemInstruction` or `responseMimeType` support — verify at T+0 and enable if supported).
- `complete_json(purpose, prompt, schema: type[BaseModel]) -> (model | None, call_record)`: extract first JSON object/array (strip ```` ```json ```` fences), validate with pydantic; on failure retry **once** appending `"Your previous reply was invalid: <error>. Reply with ONLY the JSON."`.
- Retries on 429/5xx: 2 retries, backoff 2 s / 6 s. Semaphore `GEMMA_MAX_CONCURRENCY`.
- Log every call (purpose, latency, ok, prompt chars, output chars) to `job_dir/ai_calls.jsonl`; store raw prompt/response in `job_dir/ai/<n>_<purpose>.txt` (evidence for judges).
- Never send secrets: prompts contain only repo code/metadata.
- **Hedged requests:** each call starts on the first `GEMMA_MODELS` entry; if it has not answered after `GEMMA_HEDGE_AFTER_S` (default 30 s) or fails, the other models race it on other keys and the first valid reply wins. 500/503 get two short backoff retries.
- **Rate limits:** a 429 cools that key down for 60 s and the next key is used; if every key is briefly limited the call waits for the first one to recover (within its deadline). After 4 consecutive 429s a key is treated as out for the day; only when no key can recover is `ALL GEMINI API KEYS EXHAUSTED…` raised.
- **Provider chain:** `complete_json` tries Gemma 4 (`GEMMA_MODELS`, `GEMMA_BUDGET_SHARE` of the deadline, default 0.6), then Gemini `FALLBACK_MODELS`, then Groq (`GROQ_API_KEYS`, OpenAI-compatible), then xAI Grok. Each tier is cut off at its budget and abandoned without waiting for cancellation, so the deadline is hard. The answering model is logged per call, stored as `replacement.model`, and summarised in `capsule.ai.models_used` / `fallback_models_used` (+ a limitations line).
- **Answer cache:** valid replies are cached by sha256(schema + prompt) in `DATA_DIR/_cache/gemma/`; a hit is logged with `cached: true` and counted in `capsule.ai.cached_calls` + limitations. `GEMMA_CACHE=0` disables it.
- **Key exhaustion:** when no key is usable the error is `ALL GEMINI API KEYS EXHAUSTED…`; Go logs it at `error` level and `/v1/health` reports `keys.exhausted` with per-key state (last 4 chars only).

## 3. Risk scoring (deterministic, `scan.py`)
| Indicator | Points | Severity |
|---|---|---|
| KNOWN_VULNERABILITY | 30 first + 5 each extra (max 40) | high (critical if CVSS ≥ 9) |
| PY312_INCOMPATIBLE (sandbox) | 35 | critical |
| PY312_INCOMPATIBLE (metadata only) | 10 | low |
| YANKED | 25 | high |
| DEPRECATED_PACKAGE | 25 | high |
| DEPRECATED_API_USE | 20 | medium |
| UNMAINTAINED (latest release > 2 y ago) | 20 | medium |
| UNDECLARED | 20 | medium |
| MAJOR_VERSIONS_BEHIND (≥2 majors: 20, 1 major: 15) | 15–20 | medium |
| STDLIB_REPLACEMENT_AVAILABLE | 15 | medium |
| MANIFEST_DRIFT | 15 | medium |
| PRIVATE_API_USE | 15 | medium |
| MONKEYPATCH | 15 | medium |
| DECLARED_UNUSED | 10 | low |
| OUTDATED (minor/patch behind) | 5 | low |
| UNPINNED | 5 | low |
Score = min(100, Σ). Level: ≥70 critical · ≥45 high · ≥20 medium · >0 low · 0 none. "At risk" = medium or higher.

## 4. Prompts (`app/prompts.py`) — all demand JSON only
Shared system preamble:
> You are a senior Python maintainer helping migrate dependencies safely. Use ONLY the facts provided. If information is missing, say so in `open_concerns`; never invent versions, APIs or CVEs. Target runtime: Python {python_version}. Reply with a single JSON object and nothing else.

### 4.1 (retired) `risk_rationale` — folded into `decide` as `risk_summary`.

### 4.2 `decide` (per dependency)
Input: dependency facts, indicators, all usage locations (`file:line code`), candidate list with PyPI health, Python version, other deps in project.
Output schema:
```json
{ "strategy": "replace|upgrade|remove|stdlib|declare|keep",
  "package": "string|null", "version_spec": "string|null",
  "rationale": "why, citing usage and indicators",
  "confidence": 0.0,
  "alternatives": [{"package":"", "reason_rejected":""}],
  "steps": ["ordered, concrete, file-referencing migration steps"],
  "code_changes_needed": true,
  "suggested_tests": [{"name":"test_…","purpose":"","code":"pytest function"}],
  "open_concerns": ["behaviour differences, untested paths, risks"],
  "risk_summary": "≤2 sentences why it is risky", "usage_summary": "1 sentence how it is used" }
```
Rules in prompt: prefer the smallest safe change; prefer stdlib when it fully covers the used API; must cover every usage location; suggested tests must be runnable pytest functions using only the project's public API.

### 4.3 `rewrite_file` (per file)
Input: path, full original content, decisions for each dep used in the file (strategy, package, version_spec, steps), the usage lines in this file.
Output: `{ "path": "", "edits": [{"old": "<exact text>", "new": "<replacement>"}], "changes": ["line-level summary"] }`
Rules: change only what the migration requires; keep public function names/signatures and behaviour; no new third-party imports except the chosen replacements; keep comments; must be valid Python {python_version}.

### 4.4 (retired) `usage_summary` — folded into `decide` as `usage_summary`.

### 4.5 `explain_gaps` (batched)
Input: gaps (test id, baseline/migrated outcome, error excerpt, suspected deps, relevant diff hunk). Output: `{"headline":"", "items":[{"test_id","explanation","severity":"critical|high|medium|low"}]}` — explanation must say *cause* and *what a maintainer should do*.

### 4.6 (stretch) `repair`
Input: failing tests + error excerpts + current migrated file contents. Output: same as 4.3 for ≤ 3 files. Applied to `runs/migrated_r1/repo`, re-run sandbox once.

## 5. Knowledge hints (`app/knowledge.py`)
Generic, ecosystem-wide facts used as **candidate hints only** — Gemma makes the decision, the sandbox verifies it. Must not reference any specific target repo.
```python
IMPORT_TO_DIST = {"yaml": "PyYAML", "dateutil": "python-dateutil", "bs4": "beautifulsoup4",
                  "PIL": "Pillow", "sklearn": "scikit-learn", "pkg_resources": "setuptools", ...}
CANDIDATES = {"toml": ["tomllib (stdlib, read-only)", "tomli", "tomli-w"],
              "appdirs": ["platformdirs"], "six": ["(remove: py3-only)"],
              "chardet": ["charset-normalizer"], "nose": ["pytest"],
              "mock": ["unittest.mock (stdlib)"], "simplejson": ["json (stdlib)"], ...}
DEPRECATED_PACKAGES = {"nose", "appdirs", "toml", "six", "mock", ...}   # with reason strings
DEPRECATED_APIS = {"pkg_resources": "use importlib.resources / importlib.metadata",
                   "pydantic.validator": "pydantic v2: field_validator", ...}
```

## 6. Fixed limitations text (always appended)
- Behaviour is verified only as far as the project's own test suite reaches.
- Replacement choices and code edits are generated by Gemma 4 and must be reviewed by a maintainer.
- Vulnerability data comes from OSV at analysis time; unpinned dependencies are not checked.
- Tests run offline in `python:3.12-slim`; network-dependent behaviour is not exercised.
