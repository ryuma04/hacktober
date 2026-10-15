"use client";

import React, { useState } from "react";
import type { Dependency, RiskLevel } from "@/lib/types";
import { RiskBadge, StrategyChip } from "./Shared";
import { CodeChip } from "./ui/Base";
import { ChevronRight, Filter, AlertTriangle } from "lucide-react";

export function DependencyTable({
  dependencies,
  onSelectDependency,
}: {
  dependencies: Dependency[];
  onSelectDependency: (dep: Dependency) => void;
}) {
  const [filterLevel, setFilterLevel] = useState<RiskLevel | "all">("all");

  const filtered = dependencies
    .filter((d) => (filterLevel === "all" ? true : d.risk.level === filterLevel))
    .sort((a, b) => b.risk.score - a.risk.score);

  return (
    <div className="bg-white border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-6 space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-3 border-b border-[#17151F]/15">
        <div>
          <h3 className="font-display font-extrabold text-2xl text-[#17151F]">
            Evaluated Dependencies
          </h3>
          <p className="text-sm text-[#5A5870]">
            Ranked by deterministic risk score · Click any row for evidence trail & migration steps
          </p>
        </div>

        {/* Risk Level Filter Chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-bold text-[#17151F] mr-1 flex items-center gap-1">
            <Filter className="w-3.5 h-3.5" /> Filter:
          </span>
          {(["all", "critical", "high", "medium", "low", "none"] as const).map((lvl) => (
            <button
              key={lvl}
              onClick={() => setFilterLevel(lvl)}
              className={`px-3 py-1 text-xs font-bold rounded-full transition cursor-pointer ${
                filterLevel === lvl
                  ? "bg-[#17151F] text-white shadow-xs"
                  : "bg-[#F5F1E8] text-[#17151F] border border-[#17151F]/20 hover:bg-[#F9D56E]"
              }`}
            >
              {lvl.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-xs md:text-sm">
          <thead>
            <tr className="border-b-2 border-[#17151F] text-[#5A5870] font-bold uppercase tracking-wider text-[11px]">
              <th className="py-3 px-3">Dependency</th>
              <th className="py-3 px-3">Version Shift</th>
              <th className="py-3 px-3">Risk Level</th>
              <th className="py-3 px-3">Indicators</th>
              <th className="py-3 px-3">Proposed Action</th>
              <th className="py-3 px-3 text-center">Applied</th>
              <th className="py-3 px-3 text-center">Gaps</th>
              <th className="py-3 px-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#17151F]/10">
            {filtered.map((dep) => {
              const isHighRisk = dep.risk.level === "critical" || dep.risk.level === "high";
              const isUndeclared = dep.declared.length === 0;
              const hasGaps = dep.compatibility_gaps && dep.compatibility_gaps.length > 0;

              return (
                <tr
                  key={dep.name}
                  onClick={() => onSelectDependency(dep)}
                  className={`group transition hover:bg-[#FDF1D0]/60 cursor-pointer ${
                    isHighRisk
                      ? "border-l-[4px] border-l-[#D64545] bg-[#FDECEC]/20"
                      : ""
                  }`}
                >
                  {/* Name */}
                  <td className="py-3 px-3 font-bold text-[#17151F]">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-sm">{dep.name}</span>
                      {isUndeclared && (
                        <span className="text-[10px] bg-[#F9D56E] text-[#17151F] font-extrabold px-1.5 py-0.2 rounded-full border border-[#17151F]/30">
                          undeclared
                        </span>
                      )}
                    </div>
                  </td>

                  {/* Version */}
                  <td className="py-3 px-3 font-mono text-xs">
                    {dep.pinned_version ? (
                      <div className="flex items-center gap-1">
                        <span>{dep.pinned_version}</span>
                        {dep.latest_version && (
                          <span className="text-[#5A5870]">→ {dep.latest_version}</span>
                        )}
                      </div>
                    ) : dep.declared.length > 0 ? (
                      <div className="flex items-center gap-1">
                        <span className="text-[#5A5870] italic">unpinned</span>
                        {dep.latest_version && (
                          <span className="text-[#5A5870]">→ {dep.latest_version}</span>
                        )}
                      </div>
                    ) : (
                      <span className="text-[#5A5870] italic">undeclared</span>
                    )}
                  </td>

                  {/* Risk */}
                  <td className="py-3 px-3">
                    <RiskBadge level={dep.risk.level} score={dep.risk.score} />
                  </td>

                  {/* Indicators chips */}
                  <td className="py-3 px-3">
                    <div className="flex flex-wrap gap-1 max-w-xs">
                      {dep.risk.indicators.slice(0, 3).map((ind, i) => (
                        <span
                          key={i}
                          title={ind.detail}
                          className="font-mono text-[10px] bg-white border border-[#17151F]/20 px-1.5 py-0.5 rounded-full text-[#17151F]"
                        >
                          {ind.code}
                        </span>
                      ))}
                      {dep.risk.indicators.length > 3 && (
                        <span className="text-[10px] text-[#5A5870] font-bold px-1">
                          +{dep.risk.indicators.length - 3}
                        </span>
                      )}
                    </div>
                  </td>

                  {/* Proposal */}
                  <td className="py-3 px-3">
                    {dep.replacement ? (
                      <StrategyChip
                        strategy={dep.replacement.strategy}
                        packageTarget={dep.replacement.package}
                      />
                    ) : (
                      <span className="text-xs text-[#5A5870] italic">None</span>
                    )}
                  </td>

                  {/* Applied */}
                  <td className="py-3 px-3 text-center">
                    {dep.migration?.proposed_only ? (
                      <span
                        title={dep.migration.not_applied_reason || "Proposed only (scan-only)"}
                        className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#FDF1D0] text-[#17151F] border border-[#17151F]/30"
                      >
                        Proposed
                      </span>
                    ) : dep.migration ? (
                      dep.migration.applied ? (
                        <span
                          title="Patch successfully applied and compiled"
                          className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[#B9E4A1] text-[#17151F] font-extrabold border border-[#17151F]/40"
                        >
                          ✓
                        </span>
                      ) : (
                        <span
                          title={dep.migration.not_applied_reason || "Migration rejected"}
                          className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[#FDECEC] text-[#D64545] font-extrabold border border-[#D64545]"
                        >
                          ✗
                        </span>
                      )
                    ) : (
                      <span className="text-xs text-[#5A5870]">—</span>
                    )}
                  </td>

                  {/* Gaps count */}
                  <td className="py-3 px-3 text-center">
                    {hasGaps ? (
                      <span className="inline-flex items-center gap-1 font-bold text-xs bg-[#F9D56E] text-[#17151F] px-2 py-0.5 rounded-full border border-[#17151F]/30">
                        <AlertTriangle className="w-3 h-3 text-[#17151F]" />
                        {dep.compatibility_gaps.length}
                      </span>
                    ) : (
                      <span className="text-xs text-[#5A5870]">0</span>
                    )}
                  </td>

                  {/* Action arrow */}
                  <td className="py-3 px-2 text-right">
                    <ChevronRight className="w-4 h-4 text-[#5A5870] group-hover:translate-x-1 group-hover:text-[#17151F] transition" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
