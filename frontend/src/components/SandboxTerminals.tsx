"use client";

import React, { useEffect, useRef, useState } from "react";
import { Terminal } from "lucide-react";
import type { Stage } from "@/lib/types";
import type { SandboxLine, SandboxLines, SandboxRun, SandboxStream } from "@/lib/useAnalysis";

const PANES: { run: SandboxRun; title: string; subtitle: string; stage: string }[] = [
  { run: "baseline", title: "Baseline", subtitle: "original dependencies", stage: "sandbox_baseline" },
  { run: "migrated", title: "Migrated", subtitle: "Gemma 4's replacements", stage: "sandbox_migrated" },
];

/** Colour a terminal line by what it says (pytest verdicts, exit codes, commands, pip results). */
function lineClass(line: string): string {
  if (line.startsWith("$ ")) return "text-[#9a98a8] font-bold";
  if (line.startsWith("[depexit]")) return "text-[#F9D56E]";
  if (/^exit code: 0\b/.test(line)) return "text-[#B9E4A1] font-bold";
  if (/^exit code: /.test(line)) return "text-[#F2A58B] font-bold";
  if (/\bPASSED\b/.test(line) || /^Successfully installed/.test(line)) return "text-[#B9E4A1]";
  if (/\b(FAILED|ERROR)\b/.test(line) || /^E\s/.test(line) || /Error:/.test(line)) return "text-[#F2A58B]";
  if (/^=+ .*(passed|failed|error).* =+$/.test(line))
    return /failed|error/.test(line) ? "text-[#F2A58B] font-bold" : "text-[#B9E4A1] font-bold";
  if (/\bSKIPPED\b|\bwarning/i.test(line)) return "text-[#F9D56E]";
  return "text-[#E8E6F0]";
}

function statusOf(stages: Stage[], id: string) {
  return stages.find((s) => s.id === id);
}

function Pane({
  title,
  subtitle,
  lines,
  stage,
  waiting,
}: {
  title: string;
  subtitle: string;
  lines: Record<SandboxStream, SandboxLine[]>;
  stage?: Stage;
  waiting: string;
}) {
  const [tab, setTab] = useState<SandboxStream>("install");
  const [userPicked, setUserPicked] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // follow new output unless the user scrolled up

  // Jump to the test tab as soon as pytest starts (unless the user chose a tab).
  useEffect(() => {
    if (!userPicked && lines.test.length > 0) setTab("test");
  }, [lines.test.length, userPicked]);

  const shown = lines[tab];
  useEffect(() => {
    const el = bodyRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [shown.length, tab]);

  const status = stage?.status ?? "pending";
  const dot =
    status === "running" ? "bg-[#F9D56E] animate-pulse" :
    status === "completed" ? "bg-[#B9E4A1]" :
    status === "failed" ? "bg-[#D64545]" : "bg-[#5A5870]";
  const exitLine = [...lines.test].reverse().find((l) => l.line.startsWith("exit code:"));
  const summary = [...lines.test].reverse().find((l) => /^=+ .*(passed|failed|error)/.test(l.line));

  return (
    <div className="flex flex-col rounded-2xl border-[3px] border-[#17151F] bg-[#17151F] overflow-hidden shadow-[4px_4px_0_0_#17151F] min-w-0">
      <div className="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-white/10">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${dot}`} />
          <span className="font-display font-extrabold text-white text-sm">{title}</span>
          <span className="text-[11px] text-[#9a98a8] truncate">{subtitle}</span>
        </div>
        <div className="flex rounded-full bg-white/10 p-0.5 shrink-0">
          {(["install", "test"] as SandboxStream[]).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => {
                setTab(s);
                setUserPicked(true);
                stick.current = true;
              }}
              className={`px-3 py-0.5 rounded-full text-[11px] font-bold font-mono transition ${
                tab === s ? "bg-[#F9D56E] text-[#17151F]" : "text-[#9a98a8] hover:text-white"
              }`}
            >
              {s}
              <span className="ml-1 opacity-60">{lines[s].length}</span>
            </button>
          ))}
        </div>
      </div>
      <div
        ref={bodyRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="h-[340px] overflow-auto px-4 py-3 font-mono text-[12px] leading-[1.55]"
        role="log"
        aria-live="polite"
        aria-label={`${title} ${tab} output`}
      >
        {shown.length === 0 ? (
          <p className="text-[#9a98a8] italic">
            {status === "skipped"
              ? `Not run: ${stage?.error || "this sandbox run was skipped"}.`
              : status === "pending"
                ? waiting
                : tab === "test" && lines.install.length > 0
                  ? "Installing dependencies — tests start when the install finishes…"
                  : "Waiting for Docker output…"}
          </p>
        ) : (
          shown.map((l) => (
            <div key={l.seq} className={`whitespace-pre w-max min-w-full ${lineClass(l.line)}`}>
              {l.line || " "}
            </div>
          ))
        )}
      </div>
      <div className="flex items-center justify-between gap-2 px-4 py-1.5 border-t border-white/10 text-[11px] font-mono text-[#9a98a8]">
        <span className="truncate">{summary ? summary.line.replace(/=/g, "").trim() : status === "running" ? "running…" : ""}</span>
        {exitLine && <span className={lineClass(exitLine.line)}>{exitLine.line}</span>}
      </div>
    </div>
  );
}

/** Live Docker output for both sandbox runs, side by side. */
/** Why a pane has no output yet, from the real stage states (the migrated run starts after the baseline run). */
function waitingReason(run: SandboxRun, stages: Stage[]): string {
  if (run === "baseline") return "Waiting for the repository clone…";
  const mat = statusOf(stages, "materialize")?.status;
  const base = statusOf(stages, "sandbox_baseline")?.status;
  if (mat !== "completed" && mat !== "failed" && mat !== "skipped") return "Waiting for Gemma 4 to build the migrated workspace…";
  if (base === "running" || base === "pending") return "Migrated workspace ready — queued until the baseline run finishes…";
  return "Starting Docker…";
}

export function SandboxTerminals({ sandbox, stages }: { sandbox: SandboxLines; stages: Stage[] }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-2">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-[#5A5870] flex items-center gap-1.5">
            <Terminal className="w-3.5 h-3.5" /> Sandbox telemetry
          </p>
          <h2 className="font-display font-extrabold text-2xl text-[#17151F]">Docker, live</h2>
        </div>
        <p className="text-xs text-[#5A5870] max-w-md">
          python:3.12-slim · install with network, tests with <span className="font-mono">--network none</span>. Same tests, original vs migrated dependencies.
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {PANES.map((p) => (
          <Pane key={p.run} title={p.title} subtitle={p.subtitle} lines={sandbox[p.run]} stage={statusOf(stages, p.stage)}
            waiting={waitingReason(p.run, stages)} />
        ))}
      </div>
    </section>
  );
}
