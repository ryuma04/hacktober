"use client";

import React, { useState } from "react";
import type { CapsuleSummary, Run, Gap, TestCase } from "@/lib/types";
import { FeatureCard, Card, CodeChip, Button } from "./ui/Base";
import { ExternalLink, Check, AlertCircle, FileText, X } from "lucide-react";
import { getLog } from "@/lib/api";

export function KpiTiles({ summary }: { summary: CapsuleSummary }) {
  const { dependencies_total, at_risk, by_level, baseline, migrated, gaps } = summary;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* 1. Dependencies Scanned (Sky) */}
      <FeatureCard
        pastel="sky"
        pillLabel="INVENTORY"
        title={`${dependencies_total} Scanned`}
        subtitle="Total packages declared & undeclared"
      >
        <div className="flex items-center gap-2 mt-2">
          <span className="text-xs font-semibold text-[#17151F]/70">
            AST & Manifests parsed
          </span>
        </div>
      </FeatureCard>

      {/* 2. At Risk (Coral) */}
      <FeatureCard
        pastel="coral"
        pillLabel="RISK SIGNALS"
        title={`${at_risk} At Risk`}
        subtitle="Vulnerabilities, Py3.12 rot, drift"
      >
        <div className="flex flex-wrap gap-1.5 mt-2">
          {by_level.critical > 0 && (
            <span className="text-[11px] font-bold bg-[#FDECEC] text-[#D64545] border border-[#D64545] px-2 py-0.5 rounded-full">
              {by_level.critical} Crit
            </span>
          )}
          {by_level.high > 0 && (
            <span className="text-[11px] font-bold bg-white/80 text-[#17151F] px-2 py-0.5 rounded-full">
              {by_level.high} High
            </span>
          )}
          {by_level.medium > 0 && (
            <span className="text-[11px] font-semibold bg-white/60 text-[#17151F] px-2 py-0.5 rounded-full">
              {by_level.medium} Med
            </span>
          )}
          {by_level.low > 0 && (
            <span className="text-[11px] font-semibold bg-white/40 text-[#17151F] px-2 py-0.5 rounded-full">
              {by_level.low} Low
            </span>
          )}
        </div>
      </FeatureCard>

      {/* 3. Tests Passing (Mint) */}
      <FeatureCard
        pastel="mint"
        pillLabel="SANDBOX VERIFICATION"
        title={`${baseline.passed} → ${migrated.passed} of ${baseline.total}`}
        subtitle="Pytest passing in Docker sandbox"
      >
        <div className="mt-2 text-xs font-bold text-[#17151F]">
          {migrated.passed > baseline.passed ? (
            <span className="text-[#17151F] flex items-center gap-1">
              ✓ +{migrated.passed - baseline.passed} test(s) resolved after migration
            </span>
          ) : (
            <span>Verified across clean containers</span>
          )}
        </div>
      </FeatureCard>

      {/* 4. Compatibility Gaps (Butter) */}
      <FeatureCard
        pastel="butter"
        pillLabel="A/B DIFF GAPS"
        title={`${gaps.regressed} Regressed`}
        subtitle={`${gaps.fixed} fixed · ${gaps.still_failing} still failing`}
      >
        <div className="mt-2 flex gap-2 text-xs font-semibold">
          <span className="bg-white/80 px-2 py-0.5 rounded-full">
            {gaps.fixed} Fixed
          </span>
          <span className="bg-white/80 px-2 py-0.5 rounded-full">
            {gaps.still_failing} Remaining
          </span>
        </div>
      </FeatureCard>
    </div>
  );
}

export function TestComparison({
  runs,
  analysisId,
}: {
  runs: Run[];
  analysisId: string;
}) {
  const [activeLog, setActiveLog] = useState<{
    title: string;
    content: string;
    loading: boolean;
  } | null>(null);

  const baselineRun = runs.find((r) => r.kind === "baseline") || runs[0];
  const migratedRun = runs.find((r) => r.kind === "migrated") || runs[1];

  const openLog = async (runId: string, stream: "install" | "test") => {
    setActiveLog({
      title: `${runId.toUpperCase()} ${stream.toUpperCase()} LOG`,
      content: "",
      loading: true,
    });
    try {
      const text = await getLog(analysisId, runId, stream);
      setActiveLog({
        title: `${runId.toUpperCase()} ${stream.toUpperCase()} LOG`,
        content: text,
        loading: false,
      });
    } catch (err: any) {
      setActiveLog({
        title: `${runId.toUpperCase()} ${stream.toUpperCase()} LOG`,
        content: `Failed to load log: ${err.message}`,
        loading: false,
      });
    }
  };

  // Build joined list of tests
  const testMap = new Map<
    string,
    { id: string; baseline?: TestCase["outcome"]; migrated?: TestCase["outcome"] }
  >();

  if (baselineRun?.tests) {
    baselineRun.tests.forEach((t) => {
      testMap.set(t.id, { id: t.id, baseline: t.outcome });
    });
  }

  if (migratedRun?.tests) {
    migratedRun.tests.forEach((t) => {
      const existing = testMap.get(t.id) || { id: t.id };
      testMap.set(t.id, { ...existing, migrated: t.outcome });
    });
  }

  const allTests = Array.from(testMap.values());

  const renderStackedBar = (totals: Run["totals"]) => {
    const { passed, failed, errors, skipped, total } = totals;
    if (total === 0) return null;

    const pPct = (passed / total) * 100;
    const fPct = (failed / total) * 100;
    const ePct = (errors / total) * 100;
    const sPct = (skipped / total) * 100;

    return (
      <div className="h-5 w-full bg-gray-200 rounded-full overflow-hidden flex border-2 border-[#17151F]">
        {pPct > 0 && (
          <div
            style={{ width: `${pPct}%` }}
            title={`Passed: ${passed}`}
            className="bg-[#B9E4A1] h-full"
          />
        )}
        {fPct > 0 && (
          <div
            style={{ width: `${fPct}%` }}
            title={`Failed: ${failed}`}
            className="bg-[#F2A58B] h-full"
          />
        )}
        {ePct > 0 && (
          <div
            style={{ width: `${ePct}%` }}
            title={`Errors: ${errors}`}
            className="bg-[#D64545] h-full"
          />
        )}
        {sPct > 0 && (
          <div
            style={{ width: `${sPct}%` }}
            title={`Skipped: ${skipped}`}
            className="bg-[#5A5870]/40 h-full"
          />
        )}
      </div>
    );
  };

  return (
    <Card className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 border-b border-[#17151F]/15">
        <div>
          <h3 className="font-display font-extrabold text-2xl text-[#17151F]">
            Test Suite Comparison (Docker A/B Runs)
          </h3>
          <p className="text-sm text-[#5A5870]">
            Executed in isolated <CodeChip>python:3.12-slim</CodeChip> containers with offline tests
          </p>
        </div>
      </div>

      {/* Two Columns: Baseline vs Migrated */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Baseline Column */}
        {baselineRun && (
          <div className="p-5 rounded-2xl border-[3px] border-[#17151F] bg-[#F5F1E8]/50 shadow-[3px_3px_0_0_#17151F]">
            <div className="flex items-center justify-between mb-3">
              <span className="font-display font-extrabold text-lg text-[#17151F]">
                Baseline (Original Deps)
              </span>
              <span
                className={`text-xs font-bold px-2.5 py-1 rounded-full border border-[#17151F]/40 ${
                  baselineRun.status === "passed"
                    ? "bg-[#B9E4A1]"
                    : "bg-[#FDECEC] text-[#D64545]"
                }`}
              >
                {baselineRun.status.replace("_", " ").toUpperCase()}
              </span>
            </div>

            <div className="mb-4">
              <div className="text-sm font-semibold mb-1 flex justify-between">
                <span>{baselineRun.totals.passed} / {baselineRun.totals.total} Passed</span>
                <span className="font-mono text-xs text-[#5A5870]">
                  {baselineRun.duration_s?.toFixed(1)}s
                </span>
              </div>
              {renderStackedBar(baselineRun.totals)}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => openLog(baselineRun.id, "install")}
                className="text-xs font-semibold bg-white border border-[#17151F] rounded-full px-3 py-1.5 shadow-xs hover:bg-[#F9D56E] transition cursor-pointer flex items-center gap-1"
              >
                <FileText className="w-3.5 h-3.5" /> install log
              </button>
              <button
                onClick={() => openLog(baselineRun.id, "test")}
                className="text-xs font-semibold bg-white border border-[#17151F] rounded-full px-3 py-1.5 shadow-xs hover:bg-[#F9D56E] transition cursor-pointer flex items-center gap-1"
              >
                <FileText className="w-3.5 h-3.5" /> test log
              </button>
            </div>
          </div>
        )}

        {/* Migrated Column */}
        {migratedRun && (
          <div className="p-5 rounded-2xl border-[3px] border-[#17151F] bg-[#B9E4A1]/20 shadow-[3px_3px_0_0_#17151F]">
            <div className="flex items-center justify-between mb-3">
              <span className="font-display font-extrabold text-lg text-[#17151F]">
                Migrated (AI Replacement)
              </span>
              <span
                className={`text-xs font-bold px-2.5 py-1 rounded-full border border-[#17151F]/40 ${
                  migratedRun.status === "passed"
                    ? "bg-[#B9E4A1]"
                    : "bg-[#F9D56E] text-[#17151F]"
                }`}
              >
                {migratedRun.status.replace("_", " ").toUpperCase()}
              </span>
            </div>

            <div className="mb-4">
              <div className="text-sm font-semibold mb-1 flex justify-between">
                <span>{migratedRun.totals.passed} / {migratedRun.totals.total} Passed</span>
                <span className="font-mono text-xs text-[#5A5870]">
                  {migratedRun.duration_s?.toFixed(1)}s
                </span>
              </div>
              {renderStackedBar(migratedRun.totals)}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => openLog(migratedRun.id, "install")}
                className="text-xs font-semibold bg-white border border-[#17151F] rounded-full px-3 py-1.5 shadow-xs hover:bg-[#F9D56E] transition cursor-pointer flex items-center gap-1"
              >
                <FileText className="w-3.5 h-3.5" /> install log
              </button>
              <button
                onClick={() => openLog(migratedRun.id, "test")}
                className="text-xs font-semibold bg-white border border-[#17151F] rounded-full px-3 py-1.5 shadow-xs hover:bg-[#F9D56E] transition cursor-pointer flex items-center gap-1"
              >
                <FileText className="w-3.5 h-3.5" /> test log
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Test Case Outcomes Joined Table */}
      {allTests.length > 0 && (
        <div className="mt-4">
          <h4 className="font-bold text-sm text-[#17151F] mb-3 uppercase tracking-wider">
            Test Case Differential
          </h4>
          <div className="overflow-x-auto rounded-xl border-2 border-[#17151F]">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#17151F] text-white">
                <tr>
                  <th className="p-2.5 font-bold">Test Identifier</th>
                  <th className="p-2.5 font-bold w-28">Baseline</th>
                  <th className="p-2.5 font-bold w-28">Migrated</th>
                  <th className="p-2.5 font-bold w-32">Delta Change</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white font-mono">
                {allTests.map((t) => {
                  let changeBadge = null;
                  if (
                    (t.baseline === "failed" || t.baseline === "error") &&
                    t.migrated === "passed"
                  ) {
                    changeBadge = (
                      <span className="bg-[#B9E4A1] text-[#17151F] border border-[#17151F]/30 px-2 py-0.5 rounded-full font-bold">
                        fixed ✓
                      </span>
                    );
                  } else if (
                    t.baseline === "passed" &&
                    (t.migrated === "failed" || t.migrated === "error")
                  ) {
                    changeBadge = (
                      <span className="bg-[#FDECEC] text-[#D64545] border border-[#D64545] px-2 py-0.5 rounded-full font-bold">
                        regressed ✗
                      </span>
                    );
                  } else if (
                    (t.baseline === "failed" || t.baseline === "error") &&
                    (t.migrated === "failed" || t.migrated === "error")
                  ) {
                    changeBadge = (
                      <span className="bg-[#F2A58B] text-[#17151F] border border-[#17151F]/30 px-2 py-0.5 rounded-full font-bold">
                        still failing
                      </span>
                    );
                  } else {
                    changeBadge = (
                      <span className="text-[#5A5870]/60">unchanged</span>
                    );
                  }

                  return (
                    <tr key={t.id} className="hover:bg-amber-50/50">
                      <td className="p-2.5 text-[#17151F] break-all">{t.id}</td>
                      <td className="p-2.5">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                            t.baseline === "passed"
                              ? "bg-[#B9E4A1]/60 text-[#17151F]"
                              : "bg-[#FDECEC] text-[#D64545]"
                          }`}
                        >
                          {t.baseline || "—"}
                        </span>
                      </td>
                      <td className="p-2.5">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                            t.migrated === "passed"
                              ? "bg-[#B9E4A1]/60 text-[#17151F]"
                              : "bg-[#FDECEC] text-[#D64545]"
                          }`}
                        >
                          {t.migrated || "—"}
                        </span>
                      </td>
                      <td className="p-2.5">{changeBadge}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Log Modal */}
      {activeLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
          <div className="bg-[#17151F] text-white border-[3px] border-[#17151F] rounded-[28px] shadow-[8px_8px_0_0_#17151F] w-full max-w-3xl flex flex-col max-h-[80vh] overflow-hidden">
            <div className="p-4 border-b border-white/20 flex items-center justify-between">
              <span className="font-display font-bold text-base tracking-wide">
                {activeLog.title}
              </span>
              <button
                onClick={() => setActiveLog(null)}
                className="text-white/60 hover:text-white p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 overflow-y-auto font-mono text-xs text-[#F5F1E8] flex-1 leading-relaxed whitespace-pre-wrap select-text">
              {activeLog.loading ? "Loading logs..." : activeLog.content}
            </div>
            <div className="p-3 border-t border-white/20 flex justify-end">
              <Button
                variant="secondary"
                onClick={() => {
                  navigator.clipboard.writeText(activeLog.content);
                }}
              >
                Copy Log
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

export function LimitationsCard({ limitations }: { limitations: string[] }) {
  return (
    <div className="bg-[#FDF1D0] border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-6">
      <div className="flex items-center gap-3 mb-3">
        <span className="text-2xl">⚠️</span>
        <h3 className="font-display font-extrabold text-xl text-[#17151F]">
          Honest Limitations & Open Boundaries
        </h3>
        <span className="ml-auto text-xs font-bold text-[#5A5870] uppercase tracking-wider bg-white px-3 py-1 rounded-full border border-[#17151F]/20">
          Evaluated
        </span>
      </div>
      <ul className="space-y-2 mt-4 text-sm font-medium text-[#17151F]">
        {limitations.map((item, idx) => (
          <li key={idx} className="flex items-start gap-2.5">
            <span className="text-xs font-bold font-mono bg-white px-2 py-0.5 rounded-full border border-[#17151F]/20 mt-0.5">
              {idx + 1}
            </span>
            <span className="leading-snug">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AiDisclosure({
  ai,
}: {
  ai: {
    provider: string;
    model: string;
    calls: number;
    failed_calls: number;
    fallback_used: boolean;
    terms_url: string;
  };
}) {
  return (
    <Card className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 text-sm">
      <div className="flex items-center gap-3">
        <span className="text-2xl">✨</span>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-display font-extrabold text-base text-[#17151F]">
              AI Attribution:
            </span>
            <CodeChip className="font-bold">{ai.model}</CodeChip>
            <span className="text-xs text-[#5A5870]">via {ai.provider}</span>
          </div>
          <div className="flex items-center gap-2 mt-1 text-xs text-[#5A5870]">
            <span>{ai.calls} inference calls ({ai.failed_calls} failed)</span>
            {ai.fallback_used && (
              <span className="bg-[#F2A58B] text-[#17151F] font-bold px-2 py-0.2 rounded-full">
                Fallback Used
              </span>
            )}
          </div>
        </div>
      </div>

      <a
        href={ai.terms_url}
        target="_blank"
        rel="noopener noreferrer"
        className="btn-secondary text-xs! py-2! px-4! self-start sm:self-center inline-flex items-center gap-1.5"
      >
        <span>Gemma Terms of Use</span>
        <ExternalLink className="w-3.5 h-3.5" />
      </a>
    </Card>
  );
}
