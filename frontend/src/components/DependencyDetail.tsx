"use client";

import React, { useState } from "react";
import type { Dependency, Run } from "@/lib/types";
import { RiskBadge, ProvenanceTag, StrategyChip } from "./Shared";
import { CodeChip, Button } from "./ui/Base";
import {
  X,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  AlertOctagon,
  FileCode2,
  CheckCircle,
  XCircle,
  HelpCircle,
} from "lucide-react";

export function DependencyDetail({
  dependency,
  runs,
  onClose,
  onOpenLog,
}: {
  dependency: Dependency;
  runs: Run[];
  onClose: () => void;
  onOpenLog?: (runId: string, stream: "install" | "test") => void;
}) {
  const [openTests, setOpenTests] = useState<Record<string, boolean>>({});

  const toggleTest = (name: string) => {
    setOpenTests((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const baselineRun = runs.find((r) => r.kind === "baseline");
  const migratedRun = runs.find((r) => r.kind === "migrated");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-3 md:p-6 overflow-y-auto">
      <div className="bg-[#F5F1E8] border-[3px] border-[#17151F] rounded-[28px] shadow-[8px_8px_0_0_#17151F] w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden my-auto">
        {/* Modal Header */}
        <div className="bg-white p-5 border-b-[3px] border-[#17151F] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="font-display font-extrabold text-2xl text-[#17151F]">
              {dependency.name}
            </h2>
            <RiskBadge
              level={dependency.risk.level}
              score={dependency.risk.score}
            />
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-full hover:bg-gray-100 border-2 border-transparent hover:border-[#17151F] transition cursor-pointer"
          >
            <X className="w-5 h-5 text-[#17151F]" />
          </button>
        </div>

        {/* Modal Body - 9 Canonical Sections in exact order */}
        <div className="p-5 md:p-6 overflow-y-auto space-y-8 select-text">
          {/* SECTION 1: Details */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-3">
            <h3 className="font-display font-extrabold text-lg text-[#17151F] border-b border-[#17151F]/15 pb-2">
              1. Package Details
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs md:text-sm">
              <div>
                <p className="text-[#5A5870] font-semibold">Import Names:</p>
                <div className="flex flex-wrap gap-1 mt-1">
                  {dependency.import_names && dependency.import_names.length > 0 ? (
                    dependency.import_names.map((name) => (
                      <CodeChip key={name}>{name}</CodeChip>
                    ))
                  ) : (
                    <span className="text-[#5A5870] italic">None identified</span>
                  )}
                </div>
              </div>

              <div>
                <p className="text-[#5A5870] font-semibold">Declared In:</p>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {dependency.declared && dependency.declared.length > 0 ? (
                    dependency.declared.map((decl, i) => (
                      <CodeChip key={i}>
                        {decl.file}:{decl.line} ({decl.spec})
                      </CodeChip>
                    ))
                  ) : (
                    <span className="bg-[#F9D56E] text-[#17151F] text-xs font-bold px-2 py-0.5 rounded-full border border-[#17151F]/30">
                      Undeclared dependency
                    </span>
                  )}
                </div>
              </div>

              <div>
                <p className="text-[#5A5870] font-semibold">Versions:</p>
                <p className="font-mono text-xs mt-1">
                  Pinned: {dependency.pinned_version || "none"} · Latest:{" "}
                  {dependency.latest_version || "unknown"} (
                  {dependency.latest_release_date || "date n/a"})
                </p>
              </div>

              <div>
                <p className="text-[#5A5870] font-semibold">Environment & Links:</p>
                <div className="flex items-center gap-2 mt-1">
                  {dependency.requires_python && (
                    <span className="text-xs font-mono">
                      Python: {dependency.requires_python}
                    </span>
                  )}
                  {dependency.homepage && (
                    <a
                      href={dependency.homepage}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs font-bold text-[#6E56D9] underline flex items-center gap-1"
                    >
                      Homepage <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* SECTION 2: Risk Indicators */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-4">
            <div className="flex items-center justify-between border-b border-[#17151F]/15 pb-2">
              <h3 className="font-display font-extrabold text-lg text-[#17151F]">
                2. Risk Indicators & Evidence Trail
              </h3>
              <RiskBadge
                level={dependency.risk.level}
                score={dependency.risk.score}
              />
            </div>

            {/* AI/Derived Rationale */}
            <div className="bg-[#F5F1E8] p-3.5 rounded-xl border border-[#17151F]/20">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-extrabold uppercase tracking-wider text-[#5A5870]">
                  Risk Evaluation Rationale
                </span>
                <ProvenanceTag provenance={dependency.risk.rationale_provenance} />
              </div>
              <p className="text-sm font-medium text-[#17151F] leading-relaxed">
                {dependency.risk.rationale}
              </p>
            </div>

            {/* Indicators List */}
            <div className="space-y-3">
              {dependency.risk.indicators.map((ind, i) => (
                <div
                  key={i}
                  className="p-3 rounded-xl border border-[#17151F]/20 bg-amber-50/30 flex flex-col gap-2"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <CodeChip className="font-bold bg-[#17151F] text-white">
                      {ind.code}
                    </CodeChip>
                    <RiskBadge level={ind.severity} />
                    <ProvenanceTag provenance={ind.provenance} />
                  </div>

                  <p className="text-sm text-[#17151F] font-medium">{ind.detail}</p>

                  {/* Evidence links */}
                  {ind.evidence && ind.evidence.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-[#17151F]/10">
                      <span className="text-xs text-[#5A5870] font-semibold">
                        Evidence:
                      </span>
                      {ind.evidence.map((ev, eIdx) => {
                        if (ev.source === "osv" && ev.url) {
                          return (
                            <a
                              key={eIdx}
                              href={ev.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs font-mono bg-white border border-[#17151F]/20 px-2 py-0.5 rounded-full text-[#6E56D9] underline flex items-center gap-1"
                            >
                              OSV ({ev.ref}) <ExternalLink className="w-2.5 h-2.5" />
                            </a>
                          );
                        }
                        if (ev.source === "pypi" && ev.url) {
                          return (
                            <a
                              key={eIdx}
                              href={ev.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs font-mono bg-white border border-[#17151F]/20 px-2 py-0.5 rounded-full text-[#6E56D9] underline flex items-center gap-1"
                            >
                              PyPI Release <ExternalLink className="w-2.5 h-2.5" />
                            </a>
                          );
                        }
                        if (ev.source === "ast" && ev.ref) {
                          return (
                            <CodeChip key={eIdx}>
                              AST ref: {ev.ref}
                            </CodeChip>
                          );
                        }
                        if (ev.source === "sandbox") {
                          return (
                            <span
                              key={eIdx}
                              className="text-xs font-mono bg-white border border-[#17151F]/20 px-2 py-0.5 rounded-full text-[#17151F]"
                            >
                              Sandbox run: {ev.detail || ev.ref}
                            </span>
                          );
                        }
                        if (ev.source === "manifest" && ev.ref) {
                          return (
                            <CodeChip key={eIdx}>
                              Manifest: {ev.ref}
                            </CodeChip>
                          );
                        }
                        return (
                          <span
                            key={eIdx}
                            className="text-xs text-[#5A5870] font-mono"
                          >
                            {ev.detail || ev.source}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* SECTION 3: Usage Locations */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-3">
            <div className="flex items-center justify-between border-b border-[#17151F]/15 pb-2">
              <h3 className="font-display font-extrabold text-lg text-[#17151F]">
                3. AST Usage Mapping
              </h3>
              <ProvenanceTag provenance={dependency.usage.summary_provenance} />
            </div>

            {/* Usage Summary */}
            <p className="text-sm text-[#17151F] font-medium leading-relaxed bg-[#F5F1E8] p-3 rounded-xl border border-[#17151F]/15">
              {dependency.usage.summary || "Not imported anywhere in the target repository."}
            </p>

            {/* Locations Table */}
            {dependency.usage.locations && dependency.usage.locations.length > 0 ? (
              <div className="overflow-x-auto rounded-xl border border-[#17151F]/20">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-[#17151F] text-white">
                    <tr>
                      <th className="p-2 font-bold w-44">Location</th>
                      <th className="p-2 font-bold w-32">Kind</th>
                      <th className="p-2 font-bold">Code</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {dependency.usage.locations.map((loc, i) => {
                      const isDanger =
                        loc.kind === "private_api" || loc.kind === "monkeypatch";

                      return (
                        <tr
                          key={i}
                          className={isDanger ? "bg-[#F2A58B]/30 font-bold" : "hover:bg-gray-50"}
                        >
                          <td className="p-2 text-[#17151F] whitespace-nowrap">
                            <CodeChip>
                              {loc.file}:{loc.line}
                            </CodeChip>
                          </td>
                          <td className="p-2">
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                                isDanger
                                  ? "bg-[#D64545] text-white"
                                  : "bg-gray-200 text-[#17151F]"
                              }`}
                            >
                              {loc.kind}
                            </span>
                          </td>
                          <td className="p-2 text-[#17151F] truncate max-w-md">
                            <code>{loc.code}</code>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-[#5A5870] italic">
                Not imported anywhere.
              </p>
            )}
          </section>

          {/* SECTION 4: Proposed Replacement */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-4">
            <div className="flex items-center justify-between border-b border-[#17151F]/15 pb-2">
              <h3 className="font-display font-extrabold text-lg text-[#17151F]">
                4. Proposed Replacement & Strategy
              </h3>
              {dependency.replacement && (
                <ProvenanceTag provenance={dependency.replacement.provenance} />
              )}
            </div>

            {dependency.replacement ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  <StrategyChip
                    strategy={dependency.replacement.strategy}
                    packageTarget={dependency.replacement.package}
                  />
                  {dependency.replacement.version_spec && (
                    <CodeChip className="font-bold">
                      {dependency.replacement.version_spec}
                    </CodeChip>
                  )}
                  <div className="ml-auto flex items-center gap-2">
                    <span className="text-xs font-semibold text-[#5A5870]">
                      Confidence:
                    </span>
                    <div className="w-24 h-3 bg-gray-200 rounded-full overflow-hidden border border-[#17151F]">
                      <div
                        style={{
                          width: `${Math.round(dependency.replacement.confidence * 100)}%`,
                        }}
                        className="bg-[#B9E4A1] h-full"
                      />
                    </div>
                    <span className="font-mono text-xs font-bold">
                      {(dependency.replacement.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>

                <div className="bg-[#F5F1E8] p-3 rounded-xl border border-[#17151F]/20 text-sm font-medium">
                  <p>{dependency.replacement.rationale}</p>
                </div>

                {/* Alternatives considered */}
                {dependency.replacement.alternatives &&
                  dependency.replacement.alternatives.length > 0 && (
                    <div>
                      <p className="text-xs font-bold uppercase tracking-wider text-[#5A5870] mb-2">
                        Rejected Alternatives:
                      </p>
                      <div className="space-y-1.5">
                        {dependency.replacement.alternatives.map((alt, i) => (
                          <div
                            key={i}
                            className="text-xs bg-gray-50 p-2.5 rounded-lg border border-gray-200 flex items-start gap-2"
                          >
                            <CodeChip className="shrink-0">{alt.package}</CodeChip>
                            <span className="text-[#5A5870]">
                              rejected: {alt.reason_rejected}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
              </div>
            ) : (
              <p className="text-xs text-[#5A5870] italic">Not applicable</p>
            )}
          </section>

          {/* SECTION 5: Migration Steps */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-3">
            <div className="flex items-center justify-between border-b border-[#17151F]/15 pb-2">
              <h3 className="font-display font-extrabold text-lg text-[#17151F]">
                5. Migration Steps & Applied Status
              </h3>
              {dependency.migration && (
                <ProvenanceTag provenance={dependency.migration.provenance} />
              )}
            </div>

            {dependency.migration ? (
              <div className="space-y-3">
                {/* Applied status banner */}
                <div
                  className={`p-3 rounded-xl border flex items-center justify-between text-xs font-bold ${
                    dependency.migration.applied
                      ? "bg-[#B9E4A1]/40 border-[#17151F] text-[#17151F]"
                      : "bg-[#FDECEC] border-[#D64545] text-[#D64545]"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {dependency.migration.applied ? (
                      <CheckCircle className="w-4 h-4 text-[#17151F]" />
                    ) : (
                      <XCircle className="w-4 h-4 text-[#D64545]" />
                    )}
                    <span>
                      {dependency.migration.applied
                        ? "Migration patch applied & python-compiled successfully"
                        : "Migration patch NOT applied"}
                    </span>
                  </div>
                  {dependency.migration.not_applied_reason && (
                    <span className="font-mono text-[11px] font-normal">
                      Reason: {dependency.migration.not_applied_reason}
                    </span>
                  )}
                </div>

                {/* Steps list */}
                {dependency.migration.steps && dependency.migration.steps.length > 0 && (
                  <ol className="list-decimal list-inside space-y-1.5 text-xs md:text-sm font-medium text-[#17151F] bg-gray-50 p-3 rounded-xl border border-gray-200">
                    {dependency.migration.steps.map((st, i) => (
                      <li key={i} className="leading-relaxed">
                        {st}
                      </li>
                    ))}
                  </ol>
                )}

                {/* Files changed */}
                {dependency.migration.files_changed &&
                  dependency.migration.files_changed.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <span className="text-xs font-bold text-[#5A5870]">
                        Files Modified:
                      </span>
                      {dependency.migration.files_changed.map((f) => (
                        <CodeChip key={f}>{f}</CodeChip>
                      ))}
                    </div>
                  )}
              </div>
            ) : (
              <p className="text-xs text-[#5A5870] italic">Not applicable</p>
            )}
          </section>

          {/* SECTION 6: Suggested Tests */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-3">
            <div className="flex items-center justify-between border-b border-[#17151F]/15 pb-2">
              <h3 className="font-display font-extrabold text-lg text-[#17151F]">
                6. Suggested Test Coverage
              </h3>
              <span className="text-xs font-bold text-[#5A5870]">
                {dependency.suggested_tests?.length || 0} proposals
              </span>
            </div>

            {dependency.suggested_tests && dependency.suggested_tests.length > 0 ? (
              <div className="space-y-3">
                {dependency.suggested_tests.map((st, i) => (
                  <div
                    key={i}
                    className="border border-[#17151F]/20 rounded-xl overflow-hidden bg-white"
                  >
                    <div
                      onClick={() => toggleTest(st.name)}
                      className="p-3 bg-gray-50 flex items-center justify-between cursor-pointer hover:bg-gray-100 transition"
                    >
                      <div className="flex items-center gap-2">
                        <FileCode2 className="w-4 h-4 text-[#17151F]" />
                        <span className="font-mono text-xs font-bold text-[#17151F]">
                          {st.name}
                        </span>
                        <span className="text-xs text-[#5A5870] hidden sm:inline">
                          — {st.purpose}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <ProvenanceTag provenance={st.provenance} />
                        {openTests[st.name] ? (
                          <ChevronUp className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4" />
                        )}
                      </div>
                    </div>

                    {openTests[st.name] && st.code && (
                      <div className="p-3 bg-[#17151F] text-[#F5F1E8] font-mono text-xs overflow-x-auto whitespace-pre">
                        {st.code}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[#5A5870] italic">Not applicable</p>
            )}
          </section>

          {/* SECTION 7: Executed Test Results */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-3">
            <div className="flex items-center justify-between border-b border-[#17151F]/15 pb-2">
              <h3 className="font-display font-extrabold text-lg text-[#17151F]">
                7. Executed Test Results (Attributed)
              </h3>
              {dependency.test_results && (
                <span
                  className={`text-xs font-bold px-3 py-1 rounded-full border border-[#17151F]/30 uppercase ${
                    dependency.test_results.status === "pass"
                      ? "bg-[#B9E4A1] text-[#17151F]"
                      : dependency.test_results.status === "fail"
                      ? "bg-[#FDECEC] text-[#D64545]"
                      : "bg-[#F9D56E] text-[#17151F]"
                  }`}
                >
                  {dependency.test_results.status}
                </span>
              )}
            </div>

            {dependency.test_results ? (
              <div className="space-y-3">
                <p className="text-xs font-semibold text-[#5A5870]">
                  Affected test suites touching files that import this dependency:
                </p>
                {dependency.test_results.affected_tests &&
                dependency.test_results.affected_tests.length > 0 ? (
                  <div className="space-y-1.5 font-mono text-xs">
                    {dependency.test_results.affected_tests.map((testId, i) => {
                      const bTest = baselineRun?.tests?.find((t) => t.id === testId);
                      const mTest = migratedRun?.tests?.find((t) => t.id === testId);

                      return (
                        <div
                          key={i}
                          className="p-2.5 rounded-lg border border-[#17151F]/15 bg-gray-50 flex items-center justify-between"
                        >
                          <span className="text-[#17151F] font-semibold">{testId}</span>
                          <div className="flex items-center gap-2">
                            <span className="text-[11px] text-[#5A5870]">
                              Baseline:{" "}
                              <strong className="text-[#17151F]">
                                {bTest?.outcome || "n/a"}
                              </strong>
                            </span>
                            <span>→</span>
                            <span className="text-[11px] text-[#5A5870]">
                              Migrated:{" "}
                              <strong className="text-[#17151F]">
                                {mTest?.outcome || "n/a"}
                              </strong>
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-[#5A5870] italic">
                    No specific tests directly touched files using this dependency.
                  </p>
                )}
              </div>
            ) : (
              <p className="text-xs text-[#5A5870] italic">Not applicable</p>
            )}
          </section>

          {/* SECTION 8: Compatibility Gaps */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-3">
            <h3 className="font-display font-extrabold text-lg text-[#17151F] border-b border-[#17151F]/15 pb-2">
              8. Compatibility Gaps
            </h3>

            {dependency.compatibility_gaps && dependency.compatibility_gaps.length > 0 ? (
              <div className="space-y-3">
                {dependency.compatibility_gaps.map((gap, i) => (
                  <div
                    key={i}
                    className="p-4 rounded-xl border-2 border-[#D64545] bg-[#FDECEC]/30 space-y-2"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <CodeChip className="font-bold">{gap.test_id || "Global Install"}</CodeChip>
                      <div className="flex items-center gap-2">
                        <span className="bg-[#D64545] text-white text-[10px] font-bold px-2 py-0.5 rounded-full uppercase">
                          {gap.change}
                        </span>
                        <RiskBadge level={gap.severity} />
                        <ProvenanceTag provenance={gap.provenance} />
                      </div>
                    </div>

                    <div className="text-xs font-mono text-[#5A5870]">
                      Baseline: <strong>{gap.baseline}</strong> → Migrated:{" "}
                      <strong>{gap.migrated}</strong>
                    </div>

                    <p className="text-sm text-[#17151F] font-medium leading-snug">
                      {gap.explanation}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[#5A5870] italic">
                None identified. All baseline tests pass on migrated code.
              </p>
            )}
          </section>

          {/* SECTION 9: Open Concerns */}
          <section className="bg-white p-5 rounded-2xl border-[3px] border-[#17151F] shadow-[3px_3px_0_0_#17151F] space-y-3">
            <h3 className="font-display font-extrabold text-lg text-[#17151F] border-b border-[#17151F]/15 pb-2">
              9. Open Concerns & Residual Risks
            </h3>

            {dependency.open_concerns && dependency.open_concerns.length > 0 ? (
              <ul className="space-y-2">
                {dependency.open_concerns.map((oc, i) => (
                  <li
                    key={i}
                    className="flex items-start justify-between gap-3 text-sm font-medium text-[#17151F] bg-gray-50 p-3 rounded-xl border border-gray-200"
                  >
                    <div className="flex items-start gap-2">
                      <span className="text-[#D64545] mt-0.5">⚠️</span>
                      <span>{oc.text}</span>
                    </div>
                    <ProvenanceTag provenance={oc.provenance} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-[#5A5870] italic">
                No open concerns noted.
              </p>
            )}
          </section>
        </div>

        {/* Modal Footer */}
        <div className="bg-white p-4 border-t-[3px] border-[#17151F] flex justify-end shrink-0">
          <Button variant="secondary" onClick={onClose}>
            Close Detail View
          </Button>
        </div>
      </div>
    </div>
  );
}
