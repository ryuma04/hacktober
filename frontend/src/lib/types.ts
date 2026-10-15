// Canonical types from API_CONTRACT.md §2.3, §5 and endpoints

export type JobStatus = "queued" | "running" | "completed" | "completed_with_errors" | "failed";
export type StageId = "clone" | "scan" | "usage" | "propose" | "materialize"
             | "sandbox_baseline" | "sandbox_migrated" | "compare" | "capsule"
             | `sandbox_isolated:${string}` | "repair" | "sandbox_migrated_r1";
export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface Stage {
  id: StageId;
  label: string;
  status: StageStatus;
  started_at?: string;
  finished_at?: string;
  duration_s?: number;
  error?: string;
}

export interface Job {
  id: string;
  repo_url: string;
  ref: string;
  commit?: string;
  status: JobStatus;
  created_at: string;
  finished_at?: string;
  stages: Stage[];                 // fixed order as in ARCHITECTURE.md §3
  summary?: CapsuleSummary;        // present once capsule exists (see §5)
  error?: string;
}

export type RiskLevel = "critical" | "high" | "medium" | "low" | "none";
export type Strategy = "replace" | "upgrade" | "remove" | "stdlib" | "declare" | "keep";

export type IndicatorCode =
  | "KNOWN_VULNERABILITY" | "DEPRECATED_PACKAGE" | "STDLIB_REPLACEMENT_AVAILABLE"
  | "MAJOR_VERSIONS_BEHIND" | "OUTDATED" | "UNMAINTAINED" | "PY312_INCOMPATIBLE"
  | "MANIFEST_DRIFT" | "UNDECLARED" | "DECLARED_UNUSED" | "UNPINNED"
  | "PRIVATE_API_USE" | "MONKEYPATCH" | "DEPRECATED_API_USE" | "YANKED";

export interface Evidence {
  source: "pypi" | "osv" | "ast" | "manifest" | "sandbox" | "knowledge";
  ref?: string;
  url?: string;
  detail?: string;
}

export interface Indicator {
  code: IndicatorCode;
  severity: RiskLevel;
  detail: string;
  evidence: Evidence[];
  provenance: "evidence" | "derived";
}

export interface Declaration {
  file: string;
  line: number;
  spec: string;
}

export interface UsageLocation {
  file: string;
  line: number;
  col?: number;
  code: string;
  kind: "import" | "from_import" | "call" | "attribute" | "private_api" | "monkeypatch" | "subclass" | "decorator";
  symbol?: string;
}

export interface BlastRadius {
  direct: { file: string; lines: { line: number; kinds: UsageLocation["kind"][]; code: string }[] }[];
  indirect: { file: string; via: string[] }[];
  tests: { file: string; via: string[] }[];
  nodes: { id: string; type: "dependency" | "module" | "test"; label: string; impact?: "direct" | "indirect"; lines?: number }[];
  edges: { from: string; to: string; kind: "uses" | "imports" | "conftest" }[];
  stats: { direct_files: number; lines: number; indirect_files: number; test_files: number; total_test_files: number };
  provenance: "evidence";
}

export interface WorkspaceFile {
  path: string;
  status: "unchanged" | "modified" | "added" | "removed";
  size_original?: number;
  size_migrated?: number;
  viewable: boolean;
}

export interface WorkspaceFilesResponse {
  files: WorkspaceFile[];
  changed: number;
  migrated_available: boolean;
}

export interface Dependency {
  name: string;                       // normalized (PEP 503)
  import_names: string[];             // e.g. ["jinja2"]
  declared: Declaration[];            // empty => undeclared
  pinned_version?: string;
  latest_version?: string;
  latest_release_date?: string;
  last_release_of_pinned?: string;
  requires_python?: string;
  homepage?: string;
  risk: {
    level: RiskLevel;
    score: number /*0-100*/;
    indicators: Indicator[];
    rationale: string;
    rationale_provenance: "ai" | "derived";
  };
  usage: {
    locations: UsageLocation[];
    files: string[];
    summary: string;
    summary_provenance: "ai" | "derived";
  };
  blast_radius?: BlastRadius | null;
  replacement?: {
    strategy: Strategy;
    package?: string;
    version_spec?: string;
    rationale: string;
    confidence: number /*0-1*/;
    alternatives: { package: string; reason_rejected: string }[];
    provenance: "ai" | "derived";
    model?: string | null;
  };
  migration?: {
    steps: string[];
    files_changed: string[];
    applied: boolean;
    not_applied_reason?: string;
    provenance: "ai";
  };
  suggested_tests: {
    name: string;
    purpose: string;
    code?: string;
    provenance: "ai";
  }[];
  test_results?: {
    run_ids: string[];
    affected_tests: string[];       // tests touching files that use this dep
    status: "pass" | "fail" | "mixed" | "not_run";
  };
  compatibility_gaps: Gap[];
  open_concerns: {
    text: string;
    provenance: "ai" | "derived";
  }[];
}

export interface TestCase {
  id: string;            // "tests/test_config.py::test_load"
  outcome: "passed" | "failed" | "error" | "skipped";
  message?: string;
  duration_s?: number;
}

export interface Run {
  id: string;                         // "baseline" | "migrated" | "isolated-jinja2" | "migrated_r1"
  kind: "baseline" | "migrated" | "isolated" | "repair";
  dependency?: string;
  image: string;
  command: string[];
  status: "passed" | "tests_failed" | "install_failed" | "timeout" | "error";
  install_exit_code?: number;
  test_exit_code?: number;
  duration_s: number;
  totals: { passed: number; failed: number; errors: number; skipped: number; total: number };
  tests: TestCase[];
  log_urls: { install: string; test: string };
  junit_url?: string;
}

export interface Gap {
  test_id: string | null;             // null for install-level gaps
  baseline: TestCase["outcome"] | "not_run" | "install_failed";
  migrated: TestCase["outcome"] | "not_run" | "install_failed";
  change: "fixed" | "regressed" | "still_failing" | "install_regressed" | "install_fixed";
  dependencies: string[];             // suspected deps
  explanation: string;
  severity: RiskLevel;
  provenance: "ai" | "derived";
}

export interface CapsuleSummary {
  dependencies_total: number;
  at_risk: number;
  by_level: Record<RiskLevel, number>;
  baseline: Run["totals"] & { status: Run["status"] };
  migrated: Run["totals"] & { status: Run["status"] };
  gaps: { fixed: number; regressed: number; still_failing: number };
  verdict: "safe_to_migrate" | "migrate_with_care" | "blocked";   // derived
  headline: string;                   // one sentence, ai or derived
}

export interface Capsule {
  schema_version: "1.0";
  capsule_id: string;
  generated_at: string;
  tool: { name: "DepExit"; version: string };
  target: {
    repo_url: string;
    ref: string;
    commit: string;
    python_version: string;
    manifests: string[];
  };
  ai: {
    provider: "Google AI Studio (Gemini API)";
    model: string;
    calls: number;
    failed_calls: number;
    fallback_used: boolean;
    terms_url: string;
  };
  summary: CapsuleSummary;
  dependencies: Dependency[];         // ALL declared + undeclared deps; sorted by risk score desc
  runs: Run[];
  patch: { url: string; files_changed: number; insertions: number; deletions: number };
  limitations: string[];              // honest list, always non-empty
}

export interface Health {
  status: string;
  docker: boolean;
  sandbox_image_ready: boolean;
  ai_service: boolean;
  gemma: { configured: boolean; model: string; reachable: boolean };
  version: string;
}

export interface CreateAnalysisRequest {
  repo_url: string;
  ref?: string;
  options?: {
    isolated_runs?: boolean;
    repair?: boolean;
    max_dependencies?: number;
  };
}

export interface CreateAnalysisResponse {
  id: string;
  status: string;
  created_at: string;
  links: { self: string; events: string };
}

export interface AnalysesListItem {
  id: string;
  repo_url: string;
  status: JobStatus;
  created_at: string;
  summary?: { dependencies_total: number; at_risk: number };
}

export interface AnalysesListResponse {
  items: AnalysesListItem[];
}

export interface ApiError {
  error: {
    code: "bad_request" | "not_found" | "conflict" | "unavailable" | "internal" | string;
    message: string;
  };
}

export type SSEEventType =
  | "job_started"
  | "stage_started"
  | "stage_completed"
  | "stage_failed"
  | "stage_skipped"
  | "log"
  | "ai_call"
  | "sandbox_log"
  | "job_completed"
  | "job_failed";

export interface SSEEventData {
  event?: SSEEventType;
  seq: number;
  ts: string;
  stage?: StageId;
  repo_url?: string;
  status?: JobStatus;
  duration_s?: number;
  stats?: Record<string, unknown>;
  error?: string;
  level?: "info" | "warn" | "error";
  message?: string;
  purpose?: string;
  model?: string;
  latency_ms?: number;
  ok?: boolean;
  summary?: CapsuleSummary | { dependencies_total?: number; at_risk?: number; verdict?: string };
  // sandbox_log: one line of live Docker output
  run?: "baseline" | "migrated";
  stream?: "install" | "test";
  line?: string;
}
