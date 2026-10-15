"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, FeatureCard, Button, CodeChip, NoticeBanner } from "@/components/ui/Base";
import { getHealth, listAnalyses, createAnalysis } from "@/lib/api";
import type { Health, AnalysesListItem } from "@/lib/types";
import {
  ArrowRight,
  Search,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  ShieldAlert,
  Terminal,
  Cpu,
} from "lucide-react";

export default function HomePage() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("https://github.com/rishrek/LinkWatch");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [recentAnalyses, setRecentAnalyses] = useState<AnalysesListItem[]>([]);
  const [loadingHealth, setLoadingHealth] = useState(true);

  useEffect(() => {
    getHealth()
      .then((h) => setHealth(h))
      .catch((e) => console.error("Health check error:", e))
      .finally(() => setLoadingHealth(false));

    listAnalyses()
      .then((res) => setRecentAnalyses(res.items || []))
      .catch((e) => console.error("Recent analyses error:", e));
  }, []);

  const validateUrl = (url: string) => {
    const ghRegex = /^https:\/\/github\.com\/[\w-.]+\/[\w-.]+(\.git)?$/i;
    return ghRegex.test(url.trim());
  };

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateUrl(repoUrl)) {
      setUrlError("Please enter a valid GitHub repository URL (e.g. https://github.com/owner/repo)");
      return;
    }
    setUrlError(null);
    setIsSubmitting(true);

    try {
      const res = await createAnalysis(repoUrl.trim());
      router.push(`/analyses/${res.id}`);
    } catch (err: any) {
      setUrlError(err.message || "Failed to start analysis. Check backend connectivity.");
      setIsSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen px-4 py-8 md:py-12 max-w-6xl mx-auto space-y-10">
      {/* Navigation Pill */}
      <header className="flex items-center justify-between bg-white border-[3px] border-[#17151F] rounded-full px-6 py-3 shadow-[0_4px_0_0_#17151F]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-[#17151F] flex items-center justify-center text-white font-display font-extrabold text-sm">
            DX
          </div>
          <span className="font-display font-extrabold text-xl text-[#17151F] tracking-tight">
            DepExit
          </span>
          <span className="hidden sm:inline-block font-mono text-[11px] bg-[#C3B1F5] text-[#17151F] font-bold px-2 py-0.5 rounded-full border border-[#17151F]/30">
            Track 1: Gemma 4
          </span>
        </div>

        <div className="flex items-center gap-3">
          <a
            href="https://ai.google.dev/gemma/terms"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-semibold text-[#5A5870] hover:text-[#17151F] hidden md:inline-flex items-center gap-1"
          >
            Gemma Terms <ExternalLink className="w-3 h-3" />
          </a>
          <span className="font-mono text-xs bg-[#B9E4A1] text-[#17151F] px-2.5 py-1 rounded-full border border-[#17151F]/30 font-bold">
            v0.1.0
          </span>
        </div>
      </header>

      {/* Hero Section (2 Columns) */}
      <section className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        {/* Left Column: Heading, Eyebrow & Form */}
        <div className="lg:col-span-7 space-y-6">
          <div className="space-y-3">
            <span className="text-xs font-extrabold uppercase tracking-widest text-[#5A5870] bg-white px-3 py-1 rounded-full border border-[#17151F]/20 shadow-xs inline-block">
              DEPENDENCY RESILIENCE
            </span>
            <h1 className="font-display font-extrabold text-4xl sm:text-5xl md:text-6xl text-[#17151F] leading-[1.08] tracking-tight">
              Exit risky dependencies{" "}
              <span className="marker-swipe">with proof</span>
            </h1>
            <p className="text-base sm:text-lg text-[#5A5870] font-medium leading-relaxed max-w-xl">
              Gemma 4 proposes the migration. Docker proves it. Inspect live
              vulnerabilities, AST usage, safe code patches, and clean A/B test
              execution in an immutable Dependency Exit Capsule.
            </p>
          </div>

          {/* Search-Bar Style Input Form */}
          <form onSubmit={handleAnalyze} className="space-y-2">
            <div className="bg-white border-[3px] border-[#17151F] rounded-full p-2 pl-5 shadow-[6px_6px_0_0_#17151F] flex items-center justify-between gap-2 transition hover:-translate-x-[1px] hover:-translate-y-[1px]">
              <Search className="w-5 h-5 text-[#5A5870] shrink-0" />
              <input
                type="url"
                value={repoUrl}
                onChange={(e) => {
                  setRepoUrl(e.target.value);
                  if (urlError) setUrlError(null);
                }}
                placeholder="https://github.com/rishrek/LinkWatch"
                className="w-full bg-transparent text-[#17151F] font-mono text-sm sm:text-base outline-none font-medium placeholder:text-[#5A5870]/60"
              />
              <Button
                type="submit"
                disabled={isSubmitting}
                className="shrink-0"
                icon={<ArrowRight className="w-4 h-4" />}
              >
                {isSubmitting ? "Starting..." : "Analyze"}
              </Button>
            </div>

            {urlError && (
              <div className="p-3 bg-[#FDECEC] border-2 border-[#D64545] rounded-xl text-xs font-bold text-[#D64545]">
                {urlError}
              </div>
            )}
          </form>
        </div>

        {/* Right Column: Lavender FeatureCard */}
        <div className="lg:col-span-5">
          <FeatureCard
            pastel="lavender"
            pillLabel="AUTOMATED WORKFLOW"
            title="Scan → Migrate → Verify"
            subtitle="Connects LLM intelligence to strict container execution"
            className="p-8!"
          >
            <div className="space-y-4 pt-2">
              <div className="flex items-start gap-3 bg-white/70 p-3 rounded-2xl border border-[#17151F]/15">
                <div className="w-7 h-7 rounded-full bg-[#17151F] text-white flex items-center justify-center font-bold text-xs shrink-0 mt-0.5">
                  1
                </div>
                <div>
                  <h4 className="font-bold text-sm text-[#17151F]">
                    Deterministic Risk Scan
                  </h4>
                  <p className="text-xs text-[#5A5870]">
                    PyPI advisories, OSV CVEs, manifest drift, and exact AST file:line calls.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 bg-white/70 p-3 rounded-2xl border border-[#17151F]/15">
                <div className="w-7 h-7 rounded-full bg-[#6E56D9] text-white flex items-center justify-center font-bold text-xs shrink-0 mt-0.5">
                  2
                </div>
                <div>
                  <h4 className="font-bold text-sm text-[#17151F]">
                    Gemma 4 Migration Edits
                  </h4>
                  <p className="text-xs text-[#5A5870]">
                    AI selects vetted alternatives and rewrites full file content safely.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 bg-white/70 p-3 rounded-2xl border border-[#17151F]/15">
                <div className="w-7 h-7 rounded-full bg-[#17151F] text-white flex items-center justify-center font-bold text-xs shrink-0 mt-0.5">
                  3
                </div>
                <div>
                  <h4 className="font-bold text-sm text-[#17151F]">
                    Docker A/B Pytest Isolation
                  </h4>
                  <p className="text-xs text-[#5A5870]">
                    Baseline vs migrated suites run with offline network; JUnit diff recorded.
                  </p>
                </div>
              </div>
            </div>
          </FeatureCard>
        </div>
      </section>

      {/* Health Strip */}
      <section className="bg-white border-[3px] border-[#17151F] rounded-2xl p-4 shadow-[4px_4px_0_0_#17151F] flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-[#17151F]" />
          <span className="font-bold uppercase tracking-wider text-[#5A5870]">
            System Environment:
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Docker chip */}
          <span
            className={`px-3 py-1 rounded-full font-bold border flex items-center gap-1.5 ${
              health?.docker
                ? "bg-[#B9E4A1] text-[#17151F] border-[#17151F]/30"
                : "bg-[#FDECEC] text-[#D64545] border-[#D64545]"
            }`}
          >
            <span>Docker Sandbox</span>
            <span>{health?.docker ? "✓" : "✗"}</span>
          </span>

          {/* AI Service chip */}
          <span
            className={`px-3 py-1 rounded-full font-bold border flex items-center gap-1.5 ${
              health?.ai_service
                ? "bg-[#B9E4A1] text-[#17151F] border-[#17151F]/30"
                : "bg-[#FDECEC] text-[#D64545] border-[#D64545]"
            }`}
          >
            <span>FastAPI AI Service</span>
            <span>{health?.ai_service ? "✓" : "✗"}</span>
          </span>

          {/* Gemma 4 Model chip */}
          <span
            className={`px-3 py-1 rounded-full font-bold border flex items-center gap-1.5 ${
              health?.gemma?.reachable
                ? "bg-[#C3B1F5] text-[#17151F] border-[#17151F]/30"
                : "bg-[#FDECEC] text-[#D64545] border-[#D64545]"
            }`}
          >
            <span>✨ Gemma 4: {health?.gemma?.model || "gemma-4"}</span>
            <span>{health?.gemma?.reachable ? "✓" : "✗"}</span>
          </span>
        </div>

        {!health?.gemma?.configured && !loadingHealth && (
          <span className="text-xs text-[#D64545] font-semibold">
            Gemma not configured — fallback will be used
          </span>
        )}
      </section>

      {/* Recent Analyses List */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-display font-extrabold text-2xl text-[#17151F]">
            Recent Analyses
          </h2>
          <span className="text-xs text-[#5A5870] font-semibold">
            Click to inspect timeline & capsule
          </span>
        </div>

        <div className="space-y-3">
          {recentAnalyses.length === 0 ? (
            <div className="p-8 text-center text-sm font-semibold text-[#5A5870] bg-white rounded-2xl border-2 border-dashed border-[#17151F]/20">
              No previous analyses found.
            </div>
          ) : (
            recentAnalyses.map((item) => {
              const statusColor =
                item.status === "completed"
                  ? "bg-[#B9E4A1] text-[#17151F]"
                  : item.status === "completed_with_errors"
                  ? "bg-[#F9D56E] text-[#17151F]"
                  : item.status === "failed"
                  ? "bg-[#FDECEC] text-[#D64545] border-[#D64545]"
                  : "bg-white text-[#17151F]";

              return (
                <div
                  key={item.id}
                  onClick={() => router.push(`/analyses/${item.id}`)}
                  className="bg-white border-[3px] border-[#17151F] rounded-2xl p-4 shadow-[4px_4px_0_0_#17151F] hover:-translate-x-[2px] hover:-translate-y-[2px] hover:shadow-[6px_6px_0_0_#17151F] transition cursor-pointer flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-[#F5F1E8] border-2 border-[#17151F] flex items-center justify-center font-bold text-xs shrink-0">
                      📦
                    </div>
                    <div>
                      <h4 className="font-mono text-sm font-bold text-[#17151F] flex items-center gap-2">
                        <span>{item.repo_url}</span>
                        <CodeChip>{item.id}</CodeChip>
                      </h4>
                      <p className="text-xs text-[#5A5870] font-medium mt-0.5">
                        Initiated {new Date(item.created_at).toLocaleString()}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 self-end sm:self-center">
                    {item.summary && (
                      <span className="text-xs font-semibold text-[#17151F] bg-[#F5F1E8] px-2.5 py-1 rounded-full border border-[#17151F]/20">
                        {item.summary.at_risk} of {item.summary.dependencies_total} at risk
                      </span>
                    )}
                    <span
                      className={`text-xs font-bold px-3 py-1 rounded-full border border-[#17151F]/30 uppercase tracking-wider ${statusColor}`}
                    >
                      {item.status.replace("_", " ")}
                    </span>
                    <ArrowRight className="w-4 h-4 text-[#5A5870]" />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>
    </main>
  );
}
