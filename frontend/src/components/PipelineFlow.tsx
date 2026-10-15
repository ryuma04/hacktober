"use client";

import React, { useEffect, useMemo, useState } from "react";
import { ChevronDown, CheckCircle2, Circle, Clock, CornerDownRight, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { Stage, StageId, StageStatus } from "@/lib/types";
import type { AiCallItem, LogItem, SandboxLines } from "@/lib/useAnalysis";

/** The order the backend actually runs: a main lane, plus the baseline sandbox in a parallel lane. */
const MAIN: StageId[] = ["clone", "scan", "usage", "propose", "materialize", "sandbox_migrated", "compare", "capsule"];
const PARALLEL: StageId = "sandbox_baseline";

const SHORT: Partial<Record<StageId, string>> = {
  clone: "Clone",
  scan: "Scan",
  usage: "Map usage",
  propose: "Gemma 4: propose",
  materialize: "Build migration",
  sandbox_baseline: "Test original",
  sandbox_migrated: "Test migrated",
  compare: "Gemma 4: gaps",
  capsule: "Exit Capsule",
};

const ABOUT: Partial<Record<StageId, string>> = {
  clone: "Shallow-clones the repository at the requested branch and records the exact commit that is analysed.",
  scan: "Reads every manifest, queries PyPI and OSV for each dependency and scores the risk indicators (vulnerabilities, deprecation, drift, undeclared imports…).",
  usage: "Parses the code (AST) to find every import, call, private-API use and monkeypatch, and builds the blast radius through the project's own import graph.",
  propose: "Gemma 4 decides, per at-risk dependency, the exit strategy (replace / upgrade / stdlib / remove / declare), the migration steps and suggested tests.",
  materialize: "Copies the repository and applies the migration: manifests rewritten deterministically, code edits from Gemma 4 applied only if they match exactly and still compile.",
  sandbox_baseline: "Installs the ORIGINAL dependencies in a python:3.12-slim container and runs the test suite with the network disabled.",
  sandbox_migrated: "Installs the MIGRATED dependencies in a fresh container and runs the same tests on the migrated code, network disabled.",
  compare: "Pairs every test across both runs, classifies fixed / regressed / still failing, attributes each gap to a dependency and asks Gemma 4 to explain it.",
  capsule: "Assembles the Dependency Exit Capsule (JSON + Markdown), validates it against the schema and lists the honest limitations.",
};

const RELATION: Partial<Record<StageId, string>> = {
  clone: "First stage",
  scan: "Starts after Clone",
  usage: "Starts after Scan",
  propose: "Starts after Map usage",
  materialize: "Starts after Gemma 4: propose",
  sandbox_baseline: "Starts right after Clone · runs in parallel with Scan → Build migration",
  sandbox_migrated: "Starts after Build migration and after Test original finishes",
  compare: "Starts after both test runs",
  capsule: "Starts after Gemma 4: gaps",
};

const STATUS_TEXT: Record<StageStatus, string> = {
  pending: "Waiting",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  skipped: "Skipped",
};

function StatusIcon({ status, className = "w-4 h-4" }: { status: StageStatus; className?: string }) {
  if (status === "running") return <Loader2 className={`${className} animate-spin`} />;
  if (status === "completed") return <CheckCircle2 className={className} />;
  if (status === "failed") return <XCircle className={className} />;
  if (status === "skipped") return <MinusCircle className={className} />;
  return <Circle className={className} />;
}

const NODE: Record<StageStatus, string> = {
  pending: "bg-white border-[#17151F]/25 text-[#5A5870]",
  running: "bg-[#F9D56E] border-[#17151F] text-[#17151F] shadow-[3px_3px_0_0_#17151F]",
  completed: "bg-[#B9E4A1] border-[#17151F] text-[#17151F]",
  failed: "bg-[#FDECEC] border-[#D64545] text-[#D64545]",
  skipped: "bg-[#F5F1E8] border-[#17151F]/25 text-[#5A5870] line-through",
};

function fmtDuration(s?: number) {
  if (s == null) return "";
  return s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s.toFixed(1)}s`;
}

function fmtTime(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
}

function fmtStat(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${k.replace(/_/g, " ")} ${x}`)
      .join(" · ");
  }
  return String(v);
}

function Node({ stage, index, selected, onSelect }: { stage: Stage; index: number; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "step" : undefined}
      aria-label={`${stage.label}: ${STATUS_TEXT[stage.status]}`}
      title={stage.label}
      className={`flex items-center gap-2 rounded-2xl border-2 px-3 py-2 text-left transition-all hover:-translate-y-0.5 shrink-0 ${
        selected ? "bg-[#17151F] border-[#17151F] text-white shadow-[3px_3px_0_0_#6E56D9]" : NODE[stage.status]
      }`}
    >
      <StatusIcon status={stage.status} className={`w-4 h-4 shrink-0 ${selected ? "text-white" : ""}`} />
      <span>
        <span className="block text-[13px] font-bold leading-tight whitespace-nowrap">
          <span className={`font-mono mr-1 ${selected ? "text-white/60" : "opacity-60"}`}>{String(index).padStart(2, "0")}</span>
          {SHORT[stage.id] ?? stage.label}
        </span>
        <span className={`block text-[10px] leading-tight ${selected ? "text-white/70" : "opacity-70"}`}>
          {STATUS_TEXT[stage.status]}
          {stage.duration_s != null && stage.status !== "running" ? ` · ${fmtDuration(stage.duration_s)}` : ""}
        </span>
      </span>
    </button>
  );
}

function Arrow({ done }: { done: boolean }) {
  return (
    <span aria-hidden className="flex items-center shrink-0">
      <span className={`h-0.5 w-5 rounded ${done ? "bg-[#4E9A2E]" : "bg-[#17151F]/20"}`} />
      <span
        className={`w-0 h-0 border-y-[5px] border-y-transparent border-l-[7px] ${done ? "border-l-[#4E9A2E]" : "border-l-[#17151F]/20"}`}
      />
    </span>
  );
}

/**
 * The analysis pipeline as a connected, clickable flow (after tapu-sena's stage navigation and agent sequence):
 * every stage — finished, running or waiting — can be opened to see what it does, when it ran, what it found,
 * its Gemma 4 calls and its raw events.
 */
export function PipelineFlow({
  stages,
  logs,
  aiCalls,
  stageStats,
  sandbox,
}: {
  stages: Stage[];
  logs: LogItem[];
  aiCalls: AiCallItem[];
  stageStats: Partial<Record<StageId, Record<string, unknown>>>;
  sandbox?: SandboxLines;
}) {
  const byId = useMemo(() => new Map(stages.map((s) => [s.id, s])), [stages]);
  const order = useMemo(() => [...MAIN.slice(0, 1), PARALLEL, ...MAIN.slice(1)], []);
  const numberOf = (id: StageId) => order.indexOf(id) + 1;

  // follow the pipeline (running → failed → last finished) until the user picks a stage
  const auto = useMemo(() => {
    const seq = [...MAIN, PARALLEL];
    return (
      seq.find((id) => byId.get(id)?.status === "running") ??
      seq.find((id) => byId.get(id)?.status === "failed") ??
      [...MAIN].reverse().find((id) => byId.get(id)?.status === "completed") ??
      "clone"
    );
  }, [byId]);
  const [picked, setPicked] = useState<StageId | null>(null);
  const selected = picked ?? auto;
  const [showRaw, setShowRaw] = useState(false);
  useEffect(() => setShowRaw(false), [selected]);

  const stage = byId.get(selected);
  const stageLogs = logs.filter((l) => l.stage === selected);
  const stageCalls = aiCalls.filter((c) => c.stage === selected);
  const stats = stageStats[selected];
  const sandboxRun = selected === "sandbox_baseline" ? sandbox?.baseline : selected === "sandbox_migrated" ? sandbox?.migrated : undefined;
  const testSummary = sandboxRun ? [...sandboxRun.test].reverse().find((l) => /^=+ .*(passed|failed|error)/.test(l.line))?.line : undefined;
  const done = (id: StageId) => {
    const st = byId.get(id)?.status;
    return st === "completed" || st === "skipped";
  };

  if (!stages.length) return null;

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-display font-extrabold text-xl text-[#17151F]">Execution Pipeline</h3>
        <span className="text-[11px] font-bold text-[#5A5870] bg-white border-2 border-[#17151F]/15 rounded-full px-3 py-1">
          Click any stage for details
        </span>
      </div>

      <div className="bg-white border-[3px] border-[#17151F] rounded-[24px] shadow-[4px_4px_0_0_#17151F] p-4 space-y-3">
        {/* main lane */}
        <nav aria-label="Pipeline stages" className="overflow-x-auto pb-1">
          <ol className="flex items-center gap-1.5 min-w-max">
            {MAIN.map((id, i) => {
              const s = byId.get(id);
              if (!s) return null;
              return (
                <li key={id} className="flex items-center gap-1.5">
                  <Node stage={s} index={numberOf(id)} selected={selected === id} onSelect={() => setPicked(id)} />
                  {i < MAIN.length - 1 && <Arrow done={done(id)} />}
                </li>
              );
            })}
          </ol>
          {/* parallel lane: branches off after Clone, must finish before Test migrated */}
          {byId.get(PARALLEL) && (
            <div className="flex items-center gap-2 mt-2 pl-6 min-w-max">
              <CornerDownRight className="w-4 h-4 text-[#5A5870] shrink-0" />
              <span className="text-[10px] font-bold uppercase tracking-wider text-[#5A5870] shrink-0">Parallel lane after Clone</span>
              <span aria-hidden className="h-0.5 w-6 bg-[#17151F]/20 rounded shrink-0" />
              <Node stage={byId.get(PARALLEL)!} index={numberOf(PARALLEL)} selected={selected === PARALLEL} onSelect={() => setPicked(PARALLEL)} />
              <Arrow done={done(PARALLEL)} />
              <span className="text-[10px] font-bold uppercase tracking-wider text-[#5A5870] shrink-0">joins before Test migrated</span>
            </div>
          )}
        </nav>

        {/* details of the selected stage */}
        {stage && (
          <div className="border-t-2 border-[#17151F]/10 pt-3" aria-live="polite">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <p className="font-display font-extrabold text-lg text-[#17151F]">
                <span className="font-mono text-[#5A5870] mr-1.5">{String(numberOf(selected)).padStart(2, "0")}</span>
                {stage.label}
              </p>
              <span
                className={`text-xs font-bold ${
                  stage.status === "failed" ? "text-[#D64545]" : stage.status === "running" ? "text-[#6E56D9]" : stage.status === "completed" ? "text-[#4E9A2E]" : "text-[#5A5870]"
                }`}
              >
                {STATUS_TEXT[stage.status]}
              </span>
              {(stage.started_at || stage.duration_s != null) && (
                <span className="inline-flex items-center gap-1 text-[11px] text-[#5A5870]">
                  <Clock className="w-3 h-3" />
                  {fmtTime(stage.started_at)}
                  {stage.duration_s != null ? ` · ${fmtDuration(stage.duration_s)}` : ""}
                </span>
              )}
              {picked && (
                <button type="button" onClick={() => setPicked(null)} className="text-[11px] font-bold text-[#6E56D9]">
                  follow live progress
                </button>
              )}
            </div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-[#5A5870] mt-0.5">{RELATION[selected]}</p>
            <p className="text-sm text-[#17151F]/80 mt-1.5">{ABOUT[selected]}</p>

            <div className="mt-3 space-y-2 border-l-2 border-[#17151F]/15 pl-3">
              {stage.error && (
                <p role="alert" className="text-sm font-semibold text-[#D64545]">
                  {stage.error}
                </p>
              )}
              {stats && Object.keys(stats).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(stats).map(([k, v]) => (
                    <span key={k} className="text-[11px] font-mono bg-[#F5F1E8] border border-[#17151F]/15 rounded-full px-2.5 py-0.5">
                      <b>{k.replace(/_/g, " ")}</b> {fmtStat(v)}
                    </span>
                  ))}
                </div>
              )}
              {testSummary && <p className="text-xs font-mono text-[#17151F]">pytest: {testSummary.replace(/=/g, "").trim()}</p>}
              {stageCalls.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-[#5A5870]">
                    Gemma 4 calls ({stageCalls.length}, {stageCalls.filter((c) => !c.ok).length} fell back)
                  </p>
                  <ul className="flex flex-wrap gap-1.5">
                    {stageCalls.slice(-12).map((c) => (
                      <li
                        key={c.seq}
                        className={`text-[11px] font-mono rounded-full px-2.5 py-0.5 border ${
                          c.ok ? "bg-[#C3B1F5]/40 border-[#6E56D9]/30" : "bg-[#FDECEC] border-[#D64545]/40"
                        }`}
                        title={c.error ?? c.model}
                      >
                        {c.purpose} · {(c.latency_ms / 1000).toFixed(1)}s{c.ok ? "" : " · fallback"}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {stageLogs.length > 0 ? (
                <ul className="space-y-0.5">
                  {stageLogs.slice(-5).map((l) => (
                    <li
                      key={l.seq}
                      className={`text-xs ${l.level === "error" ? "text-[#D64545] font-semibold" : l.level === "warn" ? "text-[#8a5a00]" : "text-[#17151F]"}`}
                    >
                      {l.message}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-[#5A5870] italic">
                  {stage.status === "pending"
                    ? "Nothing reported yet: this stage has not started."
                    : stage.status === "running"
                      ? "Running. No findings reported yet."
                      : stage.status === "skipped"
                        ? "This stage did not run."
                        : "Finished without further notes."}
                </p>
              )}
            </div>

            {stageLogs.length > 5 && (
              <>
                <button
                  type="button"
                  aria-expanded={showRaw}
                  onClick={() => setShowRaw((o) => !o)}
                  className="mt-2 inline-flex items-center gap-1 text-[11px] font-bold text-[#6E56D9]"
                >
                  <ChevronDown className={`w-3 h-3 transition-transform ${showRaw ? "rotate-180" : ""}`} />
                  {showRaw ? "Hide" : "Show"} all {stageLogs.length} events
                </button>
                {showRaw && (
                  <ul className="mt-1 max-h-60 overflow-auto rounded-xl bg-[#17151F] p-3 font-mono text-[11px] leading-5 text-white/90 space-y-0.5">
                    {stageLogs.map((l) => (
                      <li key={l.seq}>
                        <span className="text-white/40">{fmtTime(l.ts)}</span> {l.message}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
