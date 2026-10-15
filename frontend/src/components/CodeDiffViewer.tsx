"use client";

import React, { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { FileCode2, FileDiff, FilePlus2, FileMinus2, FolderOpen, Loader2 } from "lucide-react";
import { getWorkspaceFile, getWorkspaceFiles } from "@/lib/api";
import type { Run, WorkspaceFile, WorkspaceFilesResponse } from "@/lib/types";

// Monaco (VS Code's editor) only runs in the browser — load it client-side, like tapu-sena's code editor.
const DiffEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.DiffEditor), {
  ssr: false,
  loading: () => <EditorPlaceholder text="Loading editor…" />,
});

const LANGUAGES: Record<string, string> = {
  py: "python", toml: "ini", cfg: "ini", ini: "ini", txt: "plaintext", md: "markdown", json: "json",
  yaml: "yaml", yml: "yaml", j2: "html", html: "html", sh: "shell", xml: "xml",
};

export function languageFor(path: string): string {
  if (/requirements.*\.txt$/.test(path)) return "plaintext";
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return LANGUAGES[ext] ?? "plaintext";
}

const STATUS_STYLE: Record<WorkspaceFile["status"], { label: string; cls: string; Icon: typeof FileCode2 }> = {
  modified: { label: "M", cls: "bg-[#F9D56E] text-[#17151F]", Icon: FileDiff },
  added: { label: "A", cls: "bg-[#B9E4A1] text-[#17151F]", Icon: FilePlus2 },
  removed: { label: "D", cls: "bg-[#F2A58B] text-[#17151F]", Icon: FileMinus2 },
  unchanged: { label: "", cls: "", Icon: FileCode2 },
};

function EditorPlaceholder({ text }: { text: string }) {
  return (
    <div className="h-full w-full flex items-center justify-center bg-[#1e1e1e] text-[#9a98a8] text-xs font-mono gap-2">
      <Loader2 className="w-4 h-4 animate-spin" /> {text}
    </div>
  );
}

/**
 * The exact code that ran in the Docker sandbox: original clone (left) vs the migrated workspace (right),
 * read-only, so what you see is what the tests executed.
 */
export function CodeDiffViewer({ analysisId, runs }: { analysisId: string; runs: Run[] }) {
  const [tree, setTree] = useState<WorkspaceFilesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [changedOnly, setChangedOnly] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<{ path: string; original: string; migrated: string } | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia?.("(max-width: 900px)");
    if (!mq) return;
    setNarrow(mq.matches);
    const on = (e: MediaQueryListEvent) => setNarrow(e.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);

  useEffect(() => {
    let cancelled = false;
    getWorkspaceFiles(analysisId)
      .then((t) => {
        if (cancelled) return;
        setTree(t);
        const first = t.files.find((f) => f.status !== "unchanged" && f.path.endsWith(".py")) ??
          t.files.find((f) => f.status !== "unchanged") ?? t.files[0];
        if (first) setSelected(first.path);
        if (!t.changed) setChangedOnly(false);
      })
      .catch((e) => !cancelled && setError(e.message || "Could not load the workspace"));
    return () => {
      cancelled = true;
    };
  }, [analysisId]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setLoadingFile(true);
    Promise.all([
      getWorkspaceFile(analysisId, "original", selected),
      tree?.migrated_available ? getWorkspaceFile(analysisId, "migrated", selected) : Promise.resolve(null),
    ])
      .then(([o, m]) => {
        if (cancelled) return;
        setContent({ path: selected, original: o ?? "", migrated: m ?? (tree?.migrated_available ? "" : o ?? "") });
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoadingFile(false));
    return () => {
      cancelled = true;
    };
  }, [analysisId, selected, tree?.migrated_available]);

  const visible = useMemo(
    () => (tree?.files ?? []).filter((f) => !changedOnly || f.status !== "unchanged"),
    [tree, changedOnly]
  );
  const groups = useMemo(() => {
    const g = new Map<string, WorkspaceFile[]>();
    for (const f of visible) {
      const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : ".";
      if (!g.has(dir)) g.set(dir, []);
      g.get(dir)!.push(f);
    }
    return [...g.entries()].sort(([a], [b]) => (a === "." ? -1 : b === "." ? 1 : a.localeCompare(b)));
  }, [visible]);

  const migrated = runs.find((r) => r.id === "migrated");
  const baseline = runs.find((r) => r.id === "baseline");
  const selectedFile = tree?.files.find((f) => f.path === selected);

  return (
    <section className="bg-white border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-6 space-y-4">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-[#5A5870]">Sandbox workspace</p>
          <h2 className="font-display font-extrabold text-2xl text-[#17151F]">Code that ran in Docker</h2>
          <p className="text-sm text-[#5A5870] mt-1">
            Original clone (left) vs the migrated workspace (right). Read-only: these are the exact files the tests executed.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-bold">
          {baseline && (
            <span className="px-3 py-1 rounded-full border-2 border-[#17151F] bg-white">
              Baseline: {baseline.totals.passed}/{baseline.totals.total} passed
            </span>
          )}
          {migrated && (
            <span className={`px-3 py-1 rounded-full border-2 border-[#17151F] ${migrated.status === "passed" ? "bg-[#B9E4A1]" : "bg-[#F2A58B]"}`}>
              Migrated: {migrated.totals.passed}/{migrated.totals.total} passed
            </span>
          )}
          {tree && <span className="px-3 py-1 rounded-full border-2 border-[#17151F] bg-[#F9D56E]">{tree.changed} files changed</span>}
        </div>
      </div>

      {error && (
        <p className="text-sm font-semibold text-[#D64545] bg-[#FDECEC] border-2 border-[#D64545] rounded-2xl px-4 py-2">{error}</p>
      )}
      {tree && !tree.migrated_available && (
        <p className="text-sm text-[#5A5870] bg-[#FDF1D0] rounded-2xl px-4 py-2">
          The migrated workspace was not built for this analysis — showing the original code only.
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
        {/* File tree */}
        <div className="border-[3px] border-[#17151F] rounded-2xl overflow-hidden flex flex-col max-h-[560px]">
          <div className="flex items-center justify-between px-3 py-2 border-b-2 border-[#17151F] bg-[#F5F1E8]">
            <span className="text-xs font-bold uppercase tracking-wider text-[#17151F] flex items-center gap-1.5">
              <FolderOpen className="w-3.5 h-3.5" /> Files
            </span>
            <label className="text-[11px] font-semibold text-[#5A5870] flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} />
              changed only
            </label>
          </div>
          <div className="overflow-y-auto p-2 space-y-2">
            {!tree && !error && <p className="text-xs text-[#5A5870] p-2">Loading files…</p>}
            {tree && visible.length === 0 && <p className="text-xs text-[#5A5870] p-2">No files.</p>}
            {groups.map(([dir, files]) => (
              <div key={dir}>
                <p className="text-[10px] font-bold uppercase tracking-wider text-[#5A5870] px-2 py-1 font-mono">{dir === "." ? "/" : `${dir}/`}</p>
                {files.map((f) => {
                  const s = STATUS_STYLE[f.status];
                  const on = f.path === selected;
                  return (
                    <button
                      key={f.path}
                      type="button"
                      disabled={!f.viewable}
                      onClick={() => setSelected(f.path)}
                      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-xl text-left font-mono text-xs transition ${
                        on ? "bg-[#17151F] text-white" : "hover:bg-[#F5F1E8] text-[#17151F]"
                      } ${!f.viewable ? "opacity-40 cursor-not-allowed" : ""}`}
                      title={f.viewable ? f.path : `${f.path} (too large to view)`}
                    >
                      <s.Icon className="w-3.5 h-3.5 shrink-0" />
                      <span className="truncate flex-1">{f.path.split("/").pop()}</span>
                      {s.label && (
                        <span className={`text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center border border-[#17151F] ${s.cls}`}>
                          {s.label}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        {/* Diff editor */}
        <div className="border-[3px] border-[#17151F] rounded-2xl overflow-hidden flex flex-col min-h-[420px]">
          <div className="flex items-center justify-between gap-2 px-4 py-2 bg-[#17151F] text-white text-xs font-mono">
            <span className="truncate">{selected ?? "Select a file"}</span>
            <span className="flex items-center gap-3 shrink-0 text-[#9a98a8]">
              {selectedFile && selectedFile.status !== "unchanged" && (
                <span className="text-[#F9D56E] font-bold uppercase">{selectedFile.status}</span>
              )}
              <span>original</span>
              <span>→</span>
              <span>migrated (tested)</span>
            </span>
          </div>
          <div className="h-[480px] relative">
            {!content ? (
              <EditorPlaceholder text={selected ? `Loading ${selected}…` : "Select a file"} />
            ) : (
              // One editor stays mounted; each file gets its own model paths. Remounting the DiffEditor (or letting
              // it dispose its models) throws "TextModel got disposed before DiffEditorWidget model got reset".
              <DiffEditor
                height="100%"
                language={languageFor(content.path)}
                original={content.original}
                modified={content.migrated}
                originalModelPath={`original/${content.path}`}
                modifiedModelPath={`migrated/${content.path}`}
                keepCurrentOriginalModel
                keepCurrentModifiedModel
                theme="vs-dark"
                options={{
                  readOnly: true,
                  originalEditable: false,
                  renderSideBySide: !narrow,
                  fontSize: narrow ? 12 : 13,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  renderOverviewRuler: true,
                  wordWrap: "off",
                }}
              />
            )}
            {content && loadingFile && (
              <div className="absolute top-2 right-3 text-[11px] font-mono text-[#9a98a8] flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin" /> loading {selected}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
