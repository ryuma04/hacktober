"use client";

import React, { useEffect, useRef } from "react";
import type { Stage, StageStatus } from "@/lib/types";
import type { LogItem, AiCallItem } from "@/lib/useAnalysis";
import { Card, CodeChip } from "./ui/Base";
import { Loader2, CheckCircle2, XCircle, Clock, Sparkles } from "lucide-react";

export function StageTimeline({ stages }: { stages: Stage[] }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-display font-extrabold text-xl text-[#17151F]">
          Execution Pipeline
        </h3>
        <span className="text-xs font-semibold text-[#5A5870] bg-white px-3 py-1 rounded-full border border-[#17151F]/20 shadow-xs">
          9 Stages (Parallel Sandbox Baseline)
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {stages.map((stage, idx) => {
          const status = stage.status;
          const isBaseline = stage.id === "sandbox_baseline";

          return (
            <div
              key={stage.id}
              className={`p-4 rounded-2xl border-[3px] transition-all duration-200 flex flex-col justify-between ${
                status === "running"
                  ? "bg-[#F9D56E] border-[#17151F] shadow-[4px_4px_0_0_#17151F]"
                  : status === "completed"
                  ? "bg-[#B9E4A1] border-[#17151F] shadow-[3px_3px_0_0_#17151F]"
                  : status === "failed"
                  ? "bg-[#FDECEC] border-[#D64545] text-[#D64545] shadow-[3px_3px_0_0_#D64545]"
                  : status === "skipped"
                  ? "bg-white/60 border-dashed border-[#17151F]/30 text-[#5A5870]"
                  : "bg-white border-[#17151F]/20 text-[#5A5870]"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold opacity-60">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <span
                    className={`font-bold text-sm leading-tight ${
                      status === "skipped" ? "line-through" : "text-[#17151F]"
                    }`}
                  >
                    {stage.label}
                  </span>
                </div>

                <div className="shrink-0">
                  {status === "running" && (
                    <Loader2 className="w-4 h-4 animate-spin text-[#17151F]" />
                  )}
                  {status === "completed" && (
                    <CheckCircle2 className="w-4 h-4 text-[#17151F]" />
                  )}
                  {status === "failed" && (
                    <XCircle className="w-4 h-4 text-[#D64545]" />
                  )}
                  {status === "pending" && (
                    <Clock className="w-4 h-4 text-[#5A5870]/50" />
                  )}
                </div>
              </div>

              <div className="mt-2 flex items-center justify-between text-xs">
                {isBaseline && (
                  <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-white/70 text-[#17151F]">
                    Parallel lane
                  </span>
                )}
                {stage.duration_s !== undefined && (
                  <span className="font-mono font-semibold ml-auto text-[#17151F]">
                    {stage.duration_s.toFixed(1)}s
                  </span>
                )}
                {stage.error && (
                  <p className="text-xs text-[#D64545] font-semibold mt-1 truncate">
                    {stage.error}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function LogPanel({ logs }: { logs: LogItem[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="bg-[#17151F] text-[#F5F1E8] border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-5 flex flex-col h-[320px]">
      <div className="flex items-center justify-between pb-3 border-b border-white/10 mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-[#B9E4A1] animate-ping" />
          <span className="font-display font-bold text-sm tracking-wide text-white">
            LIVE RUN LOGS
          </span>
          <span className="font-mono text-xs text-white/50 bg-white/10 px-2 py-0.5 rounded-full">
            {logs.length} lines
          </span>
        </div>
        <span className="font-mono text-xs text-white/40">autoscroll on</span>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-1 font-mono text-xs pr-2 select-text"
      >
        {logs.length === 0 ? (
          <div className="text-white/40 italic py-8 text-center">
            Waiting for pipeline events...
          </div>
        ) : (
          logs.map((log) => {
            const levelColor =
              log.level === "warn"
                ? "text-[#F9D56E]"
                : log.level === "error"
                ? "text-[#F2A58B]"
                : "text-[#F5F1E8]/90";

            return (
              <div key={log.seq} className="leading-relaxed flex gap-2">
                <span className="text-white/30 shrink-0">
                  [{log.stage || "job"}]
                </span>
                <span className={levelColor}>{log.message}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export function GemmaActivityCard({ aiCalls }: { aiCalls: AiCallItem[] }) {
  const total = aiCalls.length;
  const failed = aiCalls.filter((c) => !c.ok).length;
  const recentCalls = aiCalls.slice(-5).reverse();

  return (
    <Card pastel="lavender" className="flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">✨</span>
            <h3 className="font-display font-extrabold text-xl text-[#17151F]">
              Gemma 4 Activity
            </h3>
          </div>
          <span className="bg-white text-[#17151F] font-mono text-xs font-bold px-2.5 py-1 rounded-full shadow-xs">
            Google AI Studio
          </span>
        </div>

        <div className="flex items-baseline gap-2 mb-4">
          <span className="font-display font-extrabold text-3xl text-[#17151F]">
            {total}
          </span>
          <span className="text-sm font-semibold text-[#17151F]/70">
            calls completed
          </span>
          {failed > 0 && (
            <span className="ml-auto bg-[#FDECEC] text-[#D64545] border border-[#D64545] text-xs font-bold px-2 py-0.5 rounded-full">
              {failed} failed (fallback used)
            </span>
          )}
        </div>

        <div className="space-y-2">
          <p className="text-xs uppercase font-extrabold tracking-wider text-[#17151F]/70">
            Recent Inferences:
          </p>
          {recentCalls.length === 0 ? (
            <p className="text-xs text-[#17151F]/60 italic">
              Awaiting model requests...
            </p>
          ) : (
            recentCalls.map((call) => (
              <div
                key={call.seq}
                className="bg-white/80 p-2.5 rounded-xl border border-[#17151F]/20 flex items-center justify-between text-xs"
              >
                <div className="flex items-center gap-1.5 truncate mr-2">
                  <span className={call.ok ? "text-[#17151F]" : "text-[#D64545]"}>
                    {call.ok ? "⚡" : "⚠️"}
                  </span>
                  <span className="font-mono font-medium text-[#17151F] truncate">
                    {call.purpose}
                  </span>
                </div>
                <div className="shrink-0 flex items-center gap-1.5 font-mono text-[11px] text-[#5A5870]">
                  <span>{(call.latency_ms / 1000).toFixed(1)}s</span>
                  {call.error && (
                    <span className="text-[#D64545] font-bold">(timeout)</span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </Card>
  );
}
