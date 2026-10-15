"""Pydantic mirror of the Capsule types in docs/API_CONTRACT.md §5 (source of schemas/capsule.schema.json)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["critical", "high", "medium", "low", "none"]
Prov = Literal["evidence", "ai", "derived"]
Outcome = Literal["passed", "failed", "error", "skipped"]


class Evidence(BaseModel):
    source: Literal["pypi", "osv", "ast", "manifest", "sandbox", "knowledge"]
    ref: str | None = None
    url: str | None = None
    detail: str | None = None


class Indicator(BaseModel):
    code: str
    severity: RiskLevel
    detail: str
    evidence: list[Evidence]
    provenance: Literal["evidence", "derived"]


class Declaration(BaseModel):
    file: str
    line: int
    spec: str


class UsageLocation(BaseModel):
    file: str
    line: int
    col: int | None = None
    code: str
    kind: Literal["import", "from_import", "call", "attribute", "private_api", "monkeypatch", "subclass", "decorator"]
    symbol: str | None = None


class Risk(BaseModel):
    level: RiskLevel
    score: int = Field(ge=0, le=100)
    indicators: list[Indicator]
    rationale: str
    rationale_provenance: Literal["ai", "derived"]


class Usage(BaseModel):
    locations: list[UsageLocation]
    files: list[str]
    summary: str
    summary_provenance: Literal["ai", "derived"]


class Alt(BaseModel):
    package: str
    reason_rejected: str


class Replacement(BaseModel):
    strategy: Literal["replace", "upgrade", "remove", "stdlib", "declare", "keep"]
    package: str | None = None
    version_spec: str | None = None
    rationale: str
    confidence: float = Field(ge=0, le=1)
    alternatives: list[Alt]
    provenance: Literal["ai", "derived"]


class Migration(BaseModel):
    steps: list[str]
    files_changed: list[str]
    applied: bool
    not_applied_reason: str | None = None
    provenance: Literal["ai", "derived"]


class SuggestedTest(BaseModel):
    name: str
    purpose: str
    code: str | None = None
    provenance: Literal["ai"]


class TestResults(BaseModel):
    run_ids: list[str]
    affected_tests: list[str]
    status: Literal["pass", "fail", "mixed", "not_run"]


class Gap(BaseModel):
    test_id: str | None
    baseline: str
    migrated: str
    change: Literal["fixed", "regressed", "still_failing", "install_regressed", "install_fixed"]
    dependencies: list[str]
    explanation: str
    severity: RiskLevel
    provenance: Literal["ai", "derived"]
    run_id: str | None = None


class Concern(BaseModel):
    text: str
    provenance: Literal["ai", "derived"]


class Dependency(BaseModel):
    name: str
    import_names: list[str]
    declared: list[Declaration]
    pinned_version: str | None = None
    latest_version: str | None = None
    latest_release_date: str | None = None
    last_release_of_pinned: str | None = None
    requires_python: str | None = None
    homepage: str | None = None
    risk: Risk
    usage: Usage
    replacement: Replacement | None = None
    migration: Migration | None = None
    suggested_tests: list[SuggestedTest]
    test_results: TestResults | None = None
    compatibility_gaps: list[Gap]
    open_concerns: list[Concern]


class TestCase(BaseModel):
    id: str
    outcome: Outcome
    message: str | None = None
    duration_s: float | None = None


class Totals(BaseModel):
    passed: int
    failed: int
    errors: int
    skipped: int
    total: int


class Run(BaseModel):
    id: str
    kind: Literal["baseline", "migrated", "isolated", "repair"]
    dependency: str | None = None
    image: str
    command: list[str]
    status: Literal["passed", "tests_failed", "install_failed", "timeout", "error"]
    install_exit_code: int | None = None
    test_exit_code: int | None = None
    duration_s: float
    totals: Totals
    tests: list[TestCase]
    log_urls: dict[str, str]
    junit_url: str | None = None


class RunSummary(Totals):
    status: str


class Summary(BaseModel):
    dependencies_total: int
    at_risk: int
    by_level: dict[str, int]
    baseline: RunSummary
    migrated: RunSummary
    gaps: dict[str, int]
    verdict: Literal["safe_to_migrate", "migrate_with_care", "blocked"]
    headline: str


class Capsule(BaseModel):
    schema_version: Literal["1.0"]
    capsule_id: str
    generated_at: str
    tool: dict
    target: dict
    ai: dict
    summary: Summary
    dependencies: list[Dependency]
    runs: list[Run]
    patch: dict
    limitations: list[str] = Field(min_length=1)
