"use client";

import React, { useState, use } from "react";
import { useRouter, useParams } from "next/navigation";
import { useAnalysis } from "@/lib/useAnalysis";
import { apiUrl } from "@/lib/url";
import type { Dependency } from "@/lib/types";
import { Card, CodeChip, Sticker, Button, NoticeBanner } from "@/components/ui/Base";
import { LogPanel, GemmaActivityCard } from "@/components/RunningView";
import {
  KpiTiles,
  TestComparison,
  LimitationsCard,
  AiDisclosure,
} from "@/components/CapsuleOverview";
import { DependencyTable } from "@/components/DependencyTable";
import { DependencyDetail } from "@/components/DependencyDetail";
import { PatchViewer } from "@/components/PatchViewer";
import { CodeDiffViewer } from "@/components/CodeDiffViewer";
import { SandboxTerminals } from "@/components/SandboxTerminals";
import { BlastMap } from "@/components/BlastMap";
import { PipelineFlow } from "@/components/PipelineFlow";
import { PullRequestDialog } from "@/components/PullRequestDialog";
import { GitPullRequest } from "lucide-react";
import {
  ArrowLeft,
  Download,
  FileCode,
  FileText,
  RotateCcw,
  Sparkles,
  FastForward,
  AlertOctagon,
  ShieldAlert,
} from "lucide-react";

export default function AnalysisPage() {
  const router = useRouter();
  const rawParams = useParams();
  const id = (rawParams?.id as string) || "dx_demo01";
  const {
    job,
    stages,
    logs,
    aiCalls,
    sandbox,
    stageStats,
    capsule,
    loading,
    error,
    isReplaying,
    skipToCompleted,
  } = useAnalysis(id);

  const [selectedDependency, setSelectedDependency] = useState<Dependency | null>(null);
  const [prOpen, setPrOpen] = useState(false);

  // If loading initial state
  if (loading && !job) {
    return (
      <main className="min-h-screen flex items-center justify-center p-6 text-center">
        <div className="card-brutal max-w-md w-full space-y-4">
          <div className="w-10 h-10 border-4 border-[#17151F] border-t-transparent rounded-full animate-spin mx-auto" />
          <h2 className="font-display font-extrabold text-xl text-[#17151F]">
            Connecting to DepExit Engine...
          </h2>
          <p className="text-xs text-[#5A5870] font-mono">
            Analysis ID: {id}
          </p>
        </div>
      </main>
    );
  }

  // If failed job state (e.g. dx_fail01)
  if (job?.status === "failed" || (error && !capsule && !isReplaying)) {
    return (
      <main className="min-h-screen px-4 py-8 max-w-5xl mx-auto space-y-6">
        <button
          onClick={() => router.push("/")}
          className="btn-secondary text-xs! py-2! px-4! flex items-center gap-1.5 cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" /> Back to Home
        </button>

        <div className="bg-[#FDECEC] border-[3px] border-[#D64545] rounded-[28px] shadow-[6px_6px_0_0_#D64545] p-6 md:p-8 space-y-4">
          <div className="flex items-center gap-3">
            <ShieldAlert className="w-8 h-8 text-[#D64545]" />
            <div>
              <h2 className="font-display font-extrabold text-2xl text-[#D64545]">
                Analysis Failed
              </h2>
              <p className="text-xs font-mono text-[#17151F]">
                Job {id} terminated with an unrecoverable stage error
              </p>
            </div>
          </div>

          <div className="bg-white p-4 rounded-xl border border-[#D64545]/40 font-mono text-sm text-[#D64545]">
            {error || job?.error || "Fatal execution error encountered."}
          </div>

          <div className="pt-2 flex justify-between items-center">
            <span className="text-xs text-[#5A5870]">
              Per integrity policy: a failure at clone terminates the job cleanly.
            </span>
            <Button variant="primary" onClick={() => router.push("/")}>
              Try Again with Another Repo
            </Button>
          </div>
        </div>

        {/* Failed stage timeline */}
        <PipelineFlow stages={stages} logs={logs} aiCalls={aiCalls} stageStats={stageStats} sandbox={sandbox} />
      </main>
    );
  }

  // Verdict Sticker Helper
  const renderVerdictSticker = (verdict: string) => {
    switch (verdict) {
      case "safe_to_migrate":
        return <Sticker variant="mint">SAFE TO MIGRATE!</Sticker>;
      case "migrate_with_care":
        return <Sticker variant="butter">MIGRATE WITH CARE!</Sticker>;
      case "blocked":
        return <Sticker variant="coral">BLOCKED!</Sticker>;
      default:
        return <Sticker variant="butter">{verdict.toUpperCase()}</Sticker>;
    }
  };

  const isCompleted =
    capsule !== null ||
    job?.status === "completed" ||
    job?.status === "completed_with_errors";

  return (
    <main className="min-h-screen px-4 py-8 max-w-6xl mx-auto space-y-8 pb-16">
      {/* Top Navigation Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <button
          onClick={() => router.push("/")}
          className="btn-secondary text-xs! py-2! px-4! flex items-center gap-1.5 self-start cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" /> Exit to Dashboard
        </button>

        {isReplaying && (
          <div className="flex items-center gap-2 self-start sm:self-center">
            <span className="text-xs font-semibold text-[#5A5870] bg-white px-3 py-1 rounded-full border border-[#17151F]/20">
              Replaying fixture events (400ms delay)...
            </span>
            <button
              onClick={skipToCompleted}
              className="btn-secondary text-xs! py-1.5! px-3! flex items-center gap-1 cursor-pointer bg-[#F9D56E]!"
            >
              <FastForward className="w-3.5 h-3.5" /> Skip to Capsule
            </button>
          </div>
        )}
      </div>

      {/* Main Analysis Header */}
      <div className="bg-white border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-6 space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-[#17151F]/15 pb-4">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-[#5A5870]">
                Repository:
              </span>
              <span className="font-mono text-base font-bold text-[#17151F]">
                {job?.repo_url || capsule?.target?.repo_url || "LinkWatch"}
              </span>
              <CodeChip>{id}</CodeChip>
              {(job?.commit || capsule?.target?.commit) && (
                <CodeChip>
                  commit: {job?.commit || capsule?.target?.commit}
                </CodeChip>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span
              className={`text-xs font-bold px-3 py-1 rounded-full border border-[#17151F]/30 uppercase tracking-wider ${
                isCompleted
                  ? "bg-[#B9E4A1] text-[#17151F]"
                  : "bg-[#F9D56E] text-[#17151F] animate-pulse"
              }`}
            >
              {isCompleted ? "COMPLETED" : "RUNNING PIPELINE"}
            </span>

            {/* Verdict sticker if completed */}
            {capsule?.summary?.verdict &&
              renderVerdictSticker(capsule.summary.verdict)}
          </div>
        </div>

        {/* Headline summary if ready */}
        {capsule?.summary?.headline ? (
          <div className="flex items-start gap-3 bg-[#F5F1E8] p-4 rounded-2xl border border-[#17151F]/20">
            <span className="text-xl">💡</span>
            <div>
              <p className="text-base font-semibold text-[#17151F] leading-snug">
                {capsule.summary.headline}
              </p>
            </div>
          </div>
        ) : (
          <div className="text-xs text-[#5A5870] font-mono">
            Pipeline is actively executing sandbox checks and requesting Gemma 4 inferences...
          </div>
        )}

        {/* Download Buttons Bar (Capsule State) */}
        {isCompleted && (
          <div className="flex flex-wrap items-center justify-end gap-2.5 pt-2">
            <a
              href={apiUrl(`/api/analyses/${id}/capsule`)}
              download={`${id}-capsule.json`}
              className="btn-secondary text-xs! py-2! px-3.5! flex items-center gap-1.5 cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" /> Download JSON
            </a>
            <a
              href={apiUrl(`/api/analyses/${id}/capsule.md`)}
              download={`${id}-CAPSULE.md`}
              className="btn-secondary text-xs! py-2! px-3.5! flex items-center gap-1.5 cursor-pointer"
            >
              <FileText className="w-3.5 h-3.5" /> Download Markdown
            </a>
            <a
              href={apiUrl(`/api/analyses/${id}/patch.diff`)}
              download={`${id}-patch.diff`}
              className="btn-primary text-xs! py-2! px-4! flex items-center gap-1.5 cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" /> Download Patch
            </a>
            <button
              type="button"
              onClick={() => setPrOpen(true)}
              className="btn-primary text-xs! py-2! px-4! flex items-center gap-1.5 cursor-pointer"
            >
              <GitPullRequest className="w-3.5 h-3.5" /> Apply fixes
            </button>
          </div>
        )}
        {prOpen && (
          <PullRequestDialog analysisId={id} repoUrl={job?.repo_url ?? capsule?.target?.repo_url ?? ""} onClose={() => setPrOpen(false)} />
        )}
      </div>

      {/* STATE 1: RUNNING VIEW */}
      {!isCompleted && (
        <div className="space-y-6">
          <PipelineFlow stages={stages} logs={logs} aiCalls={aiCalls} stageStats={stageStats} sandbox={sandbox} />

          <SandboxTerminals sandbox={sandbox} stages={stages} />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-8">
              <LogPanel logs={logs} />
            </div>
            <div className="lg:col-span-4">
              <GemmaActivityCard aiCalls={aiCalls} />
            </div>
          </div>
        </div>
      )}

      {/* STATE 2: CAPSULE VIEW (The Money Screen) */}
      {isCompleted && capsule && (
        <div className="space-y-8">
          {/* 1. KPI Tiles (4 FeatureCards) */}
          {/* How this capsule was made: the same clickable pipeline, kept after completion */}
          <PipelineFlow stages={stages} logs={logs} aiCalls={aiCalls} stageStats={stageStats} sandbox={sandbox} />

          <KpiTiles summary={capsule.summary} />

          {/* Repo-wide blast map (graph) */}
          <BlastMap dependencies={capsule.dependencies} />

          {/* 2. Test Comparison (Baseline vs Migrated) */}
          <TestComparison runs={capsule.runs} analysisId={id} />

          <SandboxTerminals sandbox={sandbox} stages={stages} />

          <CodeDiffViewer analysisId={id} runs={capsule.runs} />

          {/* 3. Evaluated Dependencies Table */}
          <DependencyTable
            dependencies={capsule.dependencies}
            onSelectDependency={(dep) => setSelectedDependency(dep)}
          />

          {/* 4. Unified Migration Patch Viewer */}
          <PatchViewer analysisId={id} patchStats={capsule.patch} />

          {/* 5. Limitations Card (Honest disclosure, never hidden!) */}
          <LimitationsCard limitations={capsule.limitations} />

          {/* 6. AI Disclosure Card */}
          <AiDisclosure ai={capsule.ai} />

          {/* Detail Drawer / Modal for selected dependency */}
          {selectedDependency && (
            <DependencyDetail
              dependency={selectedDependency}
              runs={capsule.runs}
              onClose={() => setSelectedDependency(null)}
            />
          )}
        </div>
      )}
    </main>
  );
}
