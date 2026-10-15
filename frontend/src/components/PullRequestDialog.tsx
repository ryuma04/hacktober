"use client";

import React, { useEffect, useState } from "react";
import { Check, Copy, ExternalLink, GitBranch, GitPullRequest, KeyRound, Loader2, Terminal, X } from "lucide-react";
import {
  createPullRequest,
  getPullRequest,
  previewPullRequest,
  type PullRequestPlan,
  type PullRequestResult,
} from "@/lib/api";
import { apiUrl } from "@/lib/url";

type Tab = "pr" | "local";

function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative group">
      <pre className="bg-[#17151F] text-[#E8E6F0] rounded-xl px-4 py-3 pr-12 text-xs font-mono overflow-x-auto whitespace-pre">{text}</pre>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
        className="absolute top-2 right-2 p-1.5 rounded-lg bg-white/10 text-white hover:bg-white/20"
        aria-label="Copy"
      >
        {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      </button>
    </div>
  );
}

/**
 * Deliver the tested migration: as a GitHub pull request (branch from the analysed commit, files byte-for-byte from
 * the migrated workspace that passed in Docker, capsule as the description) or as a patch to apply locally.
 */
export function PullRequestDialog({ analysisId, repoUrl, onClose }: { analysisId: string; repoUrl: string; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("pr");
  const [plan, setPlan] = useState<PullRequestPlan | null>(null);
  const [existing, setExisting] = useState<PullRequestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [draft, setDraft] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [showBody, setShowBody] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const prev = await getPullRequest(analysisId);
        if (cancelled) return;
        if (prev) setExisting(prev);
        const p = await previewPullRequest(analysisId);
        if (!cancelled) setPlan(p);
      } catch (e: any) {
        if (!cancelled) setError(e.message || "Could not prepare the pull request");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [analysisId]);

  // close on Escape
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await createPullRequest(analysisId, token.trim(), draft);
      setExisting(res);
    } catch (e: any) {
      setError(e.message || "GitHub refused the request");
    } finally {
      setToken(""); // never keep the token around
      setSubmitting(false);
    }
  };

  const patchUrl = apiUrl(`/api/analyses/${analysisId}/patch.diff`);
  const repoName = repoUrl.replace(/^https:\/\/github\.com\//, "").replace(/\.git$/, "");
  const localCmd = plan
    ? `git clone ${repoUrl} && cd ${repoName.split("/")[1] ?? "repo"}\n` +
      `git checkout -b ${plan.branch} ${plan.base_commit.slice(0, 12)}\n` +
      `curl -sL "${patchUrl}" | git apply\n` +
      `python -m pip install -r requirements.txt && python -m pytest`
    : "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#17151F]/50" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Deliver the migration"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-3xl max-h-[90vh] flex flex-col bg-[#F5F1E8] border-[3px] border-[#17151F] rounded-[28px] shadow-[8px_8px_0_0_#17151F] overflow-hidden"
      >
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-b-[3px] border-[#17151F] bg-white">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-[#5A5870]">Deliver the tested migration</p>
            <h2 className="font-display font-extrabold text-xl text-[#17151F]">Apply these fixes to {repoName}</h2>
          </div>
          <button type="button" onClick={onClose} className="p-2 rounded-full hover:bg-[#F5F1E8]" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex gap-2 px-6 pt-4">
          {([
            { k: "pr", label: "Open pull request", Icon: GitPullRequest },
            { k: "local", label: "Apply locally", Icon: Terminal },
          ] as const).map((t) => (
            <button
              key={t.k}
              type="button"
              onClick={() => setTab(t.k)}
              className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full border-2 border-[#17151F] text-xs font-bold transition ${
                tab === t.k ? "bg-[#F9D56E] shadow-[2px_2px_0_0_#17151F]" : "bg-white"
              }`}
            >
              <t.Icon className="w-3.5 h-3.5" /> {t.label}
            </button>
          ))}
        </div>

        <div className="overflow-y-auto px-6 py-4 space-y-4">
          {loading && (
            <p className="text-sm text-[#5A5870] flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" /> Preparing the change set…
            </p>
          )}
          {error && (
            <p className="text-sm font-semibold text-[#D64545] bg-[#FDECEC] border-2 border-[#D64545] rounded-2xl px-4 py-2">{error}</p>
          )}

          {plan && (
            <div className="bg-white border-2 border-[#17151F] rounded-2xl p-4 space-y-2 text-sm">
              <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                <GitBranch className="w-4 h-4" />
                <span className="bg-[#F5F1E8] rounded px-2 py-0.5">{plan.owner}/{plan.repo}</span>
                <span className="text-[#5A5870]">from analysed commit</span>
                <span className="bg-[#F5F1E8] rounded px-2 py-0.5">{plan.base_commit.slice(0, 10)}</span>
                <span className="text-[#5A5870]">→</span>
                <span className="bg-[#F9D56E] rounded px-2 py-0.5">{plan.branch}</span>
              </div>
              <p className="text-xs text-[#5A5870]">
                {plan.files_changed.length} files, byte-for-byte the migrated workspace that passed the Docker tests. Nothing is
                regenerated. One commit per file:
              </p>
              <ul className="space-y-1">
                {plan.commits.map((c) => (
                  <li key={c.message} className="text-xs font-mono flex gap-2">
                    <span className="text-[#6E56D9]">●</span>
                    <span className="break-all">{c.message.split("\n")[0]}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {tab === "pr" && plan && (
            <>
              <div className="bg-white border-2 border-[#17151F] rounded-2xl p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-bold text-[#17151F]">{plan.title}</p>
                  <button type="button" onClick={() => setShowBody((v) => !v)} className="text-xs font-bold text-[#6E56D9]">
                    {showBody ? "Hide" : "Preview"} description
                  </button>
                </div>
                <p className="text-xs text-[#5A5870]">
                  The description is the Exit Capsule: verdict, tests before/after, every change with its risk and the model that
                  decided it, compatibility gaps and limitations.
                </p>
                {showBody && (
                  <pre className="bg-[#F5F1E8] rounded-xl p-3 text-[11px] font-mono whitespace-pre-wrap max-h-72 overflow-y-auto">{plan.body}</pre>
                )}
              </div>

              {existing ? (
                <div className="bg-[#B9E4A1] border-2 border-[#17151F] rounded-2xl p-4 space-y-1">
                  <p className="font-bold text-[#17151F] flex items-center gap-2">
                    <Check className="w-4 h-4" /> Pull request #{existing.number} is open
                  </p>
                  <p className="text-xs text-[#17151F]">
                    Branch <span className="font-mono">{existing.head}</span>
                    {existing.forked ? " (pushed to your fork — you had no write access to the repository)" : ""} ·{" "}
                    {existing.commits} commits
                  </p>
                  <a href={existing.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm font-bold text-[#17151F] underline">
                    Open on GitHub <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>
              ) : (
                <div className="bg-white border-2 border-[#17151F] rounded-2xl p-4 space-y-3">
                  <label className="block text-xs font-bold text-[#17151F]" htmlFor="gh-token">
                    <span className="flex items-center gap-1.5">
                      <KeyRound className="w-3.5 h-3.5" /> GitHub token
                    </span>
                  </label>
                  <input
                    id="gh-token"
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="github_pat_…"
                    className="w-full rounded-xl border-2 border-[#17151F] px-3 py-2 font-mono text-sm bg-[#F5F1E8] focus:outline-none focus:ring-2 focus:ring-[#6E56D9]"
                  />
                  <p className="text-[11px] text-[#5A5870] leading-relaxed">
                    Use a fine-grained token with <b>Contents: read &amp; write</b> and <b>Pull requests: read &amp; write</b>. If
                    it cannot push to {plan.owner}/{plan.repo}, DepExit forks the repository to your account and opens the PR from
                    there. The token is sent once for this request; it is not stored by DepExit.
                  </p>
                  <div className="flex items-center justify-between gap-3">
                    <label className="text-xs font-semibold text-[#17151F] flex items-center gap-2 cursor-pointer select-none">
                      <input type="checkbox" checked={draft} onChange={(e) => setDraft(e.target.checked)} /> Open as draft
                    </label>
                    <button
                      type="button"
                      disabled={!token.trim() || submitting}
                      onClick={submit}
                      className="btn-primary text-xs! py-2! px-4! flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitPullRequest className="w-3.5 h-3.5" />}
                      {submitting ? "Opening pull request…" : "Open pull request"}
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {tab === "local" && plan && (
            <div className="bg-white border-2 border-[#17151F] rounded-2xl p-4 space-y-3">
              <p className="text-sm text-[#17151F]">
                Apply the exact patch that passed the sandbox tests on a new branch from the analysed commit, then re-run the tests
                yourself:
              </p>
              <CopyBlock text={localCmd} />
              <p className="text-xs text-[#5A5870]">
                Prefer the editor? The DepExit VS Code extension offers the same change file by file as a quick fix.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
