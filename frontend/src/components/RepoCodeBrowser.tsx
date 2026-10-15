"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { OnMount } from "@monaco-editor/react";
import { AlertTriangle, FileCode2, FolderOpen, Loader2 } from "lucide-react";
import { getWorkspaceFile, getWorkspaceFiles } from "@/lib/api";
import type { Dependency, RiskLevel, WorkspaceFile } from "@/lib/types";
import { languageFor } from "./CodeDiffViewer";

const Editor = dynamic(() => import("@monaco-editor/react").then((m) => m.Editor), {
  ssr: false,
  loading: () => <Placeholder text="Loading editor…" />,
});

const LEVEL_ORDER: RiskLevel[] = ["critical", "high", "medium", "low", "none"];
const LEVEL_CHIP: Record<RiskLevel, string> = {
  critical: "bg-[#FDECEC] text-[#D64545] border-[#D64545]",
  high: "bg-[#F2A58B] text-[#17151F] border-[#17151F]",
  medium: "bg-[#F9D56E] text-[#17151F] border-[#17151F]",
  low: "bg-[#A8CCF4] text-[#17151F] border-[#17151F]/40",
  none: "bg-white text-[#5A5870] border-[#17151F]/20",
};
const CODE_FILE = /\.(py|[cm]?[jt]sx?|vue|svelte|css|scss|less|json|toml|cfg|txt|ya?ml|html|md)$/i;

interface Hit {
  dep: string;
  level: RiskLevel;
  line: number;
  kinds: string[];
}

function Placeholder({ text }: { text: string }) {
  return (
    <div className="h-full w-full flex items-center justify-center bg-[#1e1e1e] text-[#9a98a8] text-xs font-mono gap-2">
      <Loader2 className="w-4 h-4 animate-spin" /> {text}
    </div>
  );
}

/**
 * Read-only browser of the analysed repository (used when nothing was migrated, e.g. npm scan-only runs):
 * every line that imports a dependency is highlighted with that dependency's risk level, straight from the
 * AST/import evidence in the capsule.
 */
export function RepoCodeBrowser({ analysisId, dependencies }: { analysisId: string; dependencies: Dependency[] }) {
  const [files, setFiles] = useState<WorkspaceFile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<{ path: string; text: string } | null>(null);
  const [onlyWithHits, setOnlyWithHits] = useState(true);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = useRef<Parameters<OnMount>[1] | null>(null);
  const decorations = useRef<string[]>([]);

  // file -> highlighted lines, riskiest dependency first
  const hits = useMemo(() => {
    const m = new Map<string, Hit[]>();
    for (const d of dependencies) {
      for (const l of d.usage.locations) {
        const arr = m.get(l.file) ?? [];
        const same = arr.find((h) => h.dep === d.name && h.line === l.line);
        if (same) {
          if (!same.kinds.includes(l.kind)) same.kinds.push(l.kind);
        } else arr.push({ dep: d.name, level: d.risk.level, line: l.line, kinds: [l.kind] });
        m.set(l.file, arr);
      }
    }
    for (const arr of m.values())
      arr.sort((a, b) => LEVEL_ORDER.indexOf(a.level) - LEVEL_ORDER.indexOf(b.level) || a.line - b.line);
    return m;
  }, [dependencies]);

  const worstLevel = (file: string): RiskLevel | null => {
    const arr = hits.get(file);
    return arr && arr.length ? arr[0].level : null;
  };

  useEffect(() => {
    let cancelled = false;
    getWorkspaceFiles(analysisId)
      .then((t) => {
        if (cancelled) return;
        const list = t.files.filter((f) => f.viewable && CODE_FILE.test(f.path));
        setFiles(list);
        const first = [...hits.keys()].sort(
          (a, b) => LEVEL_ORDER.indexOf(worstLevel(a) ?? "none") - LEVEL_ORDER.indexOf(worstLevel(b) ?? "none")
        )[0];
        setSelected(first ?? list[0]?.path ?? null);
        if (!hits.size) setOnlyWithHits(false);
      })
      .catch((e) => !cancelled && setError(e.message || "Could not load the repository files"));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    getWorkspaceFile(analysisId, "original", selected)
      .then((text) => !cancelled && setContent({ path: selected, text: text ?? "" }))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [analysisId, selected]);

  // highlight the evidence lines of the open file
  const applyDecorations = () => {
    const ed = editorRef.current;
    const monaco = monacoRef.current;
    if (!ed || !monaco || !content) return;
    const fileHits = hits.get(content.path) ?? [];
    decorations.current = ed.deltaDecorations(
      decorations.current,
      fileHits.map((h) => ({
        range: new monaco.Range(h.line, 1, h.line, 1),
        options: {
          isWholeLine: true,
          className: `depexit-line-${h.level}`,
          glyphMarginClassName: `depexit-glyph-${h.level}`,
          hoverMessage: { value: `**${h.dep}** — ${h.level} risk · ${h.kinds.join(", ")}` },
        },
      }))
    );
  };
  useEffect(applyDecorations); // re-apply after every content change

  const shown = (files ?? []).filter((f) => !onlyWithHits || hits.has(f.path));
  const groups = useMemo(() => {
    const g = new Map<string, WorkspaceFile[]>();
    for (const f of shown) {
      const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : ".";
      g.set(dir, [...(g.get(dir) ?? []), f]);
    }
    return [...g.entries()].sort(([a], [b]) => (a === "." ? -1 : b === "." ? 1 : a.localeCompare(b)));
  }, [shown]);
  const fileHits = content ? hits.get(content.path) ?? [] : [];

  return (
    <section className="bg-white border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-6 space-y-4">
      {/* evidence-line colours (Monaco decorations) */}
      <style>{`
        .depexit-line-critical, .depexit-line-high { background: rgba(214, 69, 69, 0.22); }
        .depexit-line-medium { background: rgba(249, 213, 110, 0.20); }
        .depexit-line-low, .depexit-line-none { background: rgba(168, 204, 244, 0.14); }
        .depexit-glyph-critical, .depexit-glyph-high { background: #D64545; width: 5px !important; margin-left: 4px; }
        .depexit-glyph-medium { background: #F9D56E; width: 5px !important; margin-left: 4px; }
        .depexit-glyph-low, .depexit-glyph-none { background: #A8CCF4; width: 5px !important; margin-left: 4px; }
      `}</style>
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-[#5A5870]">Sandbox workspace · read-only</p>
          <h2 className="font-display font-extrabold text-2xl text-[#17151F]">Repository code (analysed, not executed)</h2>
          <p className="text-sm text-[#5A5870] mt-1">
            The exact files DepExit cloned and analysed. Highlighted lines are where a dependency is imported, coloured by
            its risk — evidence from the import analysis. Nothing was migrated or run for this project.
          </p>
        </div>
        <span className="text-xs font-bold px-3 py-1 rounded-full border-2 border-[#17151F] bg-[#F9D56E] shrink-0">
          {[...hits.values()].reduce((n, a) => n + a.length, 0)} evidence lines in {hits.size} files
        </span>
      </div>

      {error && (
        <p className="text-sm font-semibold text-[#D64545] bg-[#FDECEC] border-2 border-[#D64545] rounded-2xl px-4 py-2">{error}</p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
        <div className="border-[3px] border-[#17151F] rounded-2xl overflow-hidden flex flex-col max-h-[560px]">
          <div className="flex items-center justify-between px-3 py-2 border-b-2 border-[#17151F] bg-[#F5F1E8]">
            <span className="text-xs font-bold uppercase tracking-wider text-[#17151F] flex items-center gap-1.5">
              <FolderOpen className="w-3.5 h-3.5" /> Files
            </span>
            <label className="text-[11px] font-semibold text-[#5A5870] flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" checked={onlyWithHits} onChange={(e) => setOnlyWithHits(e.target.checked)} />
              with imports only
            </label>
          </div>
          <div className="overflow-y-auto p-2 space-y-2">
            {!files && !error && <p className="text-xs text-[#5A5870] p-2">Loading files…</p>}
            {files && shown.length === 0 && <p className="text-xs text-[#5A5870] p-2">No files.</p>}
            {groups.map(([dir, list]) => (
              <div key={dir}>
                <p className="text-[10px] font-bold uppercase tracking-wider text-[#5A5870] px-2 py-1 font-mono">{dir === "." ? "/" : `${dir}/`}</p>
                {list.map((f) => {
                  const on = f.path === selected;
                  const lvl = worstLevel(f.path);
                  return (
                    <button
                      key={f.path}
                      type="button"
                      onClick={() => setSelected(f.path)}
                      title={f.path}
                      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-xl text-left font-mono text-xs transition ${
                        on ? "bg-[#17151F] text-white" : "hover:bg-[#F5F1E8] text-[#17151F]"
                      }`}
                    >
                      <FileCode2 className="w-3.5 h-3.5 shrink-0" />
                      <span className="truncate flex-1">{f.path.split("/").pop()}</span>
                      {lvl && (
                        <span className={`text-[10px] font-bold px-1.5 rounded-full border ${LEVEL_CHIP[lvl]}`}>
                          {hits.get(f.path)!.length}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <div className="border-[3px] border-[#17151F] rounded-2xl overflow-hidden flex flex-col min-h-[420px]">
          <div className="flex flex-wrap items-center gap-2 px-4 py-2 bg-[#17151F] text-white text-xs font-mono">
            <span className="truncate mr-auto">{selected ?? "Select a file"}</span>
            {fileHits.map((h) => (
              <button
                key={`${h.dep}:${h.line}`}
                type="button"
                onClick={() => {
                  editorRef.current?.revealLineInCenter(h.line);
                  editorRef.current?.setSelection({ startLineNumber: h.line, startColumn: 1, endLineNumber: h.line, endColumn: 1 });
                }}
                className={`flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold ${LEVEL_CHIP[h.level]}`}
                title={`Jump to line ${h.line}`}
              >
                {(h.level === "critical" || h.level === "high") && <AlertTriangle className="w-3 h-3" />}
                {h.dep} · L{h.line}
              </button>
            ))}
          </div>
          <div className="h-[480px]">
            {!content ? (
              <Placeholder text={selected ? `Loading ${selected}…` : "Select a file"} />
            ) : (
              <Editor
                height="100%"
                path={`repo/${content.path}`}
                language={languageFor(content.path)}
                value={content.text}
                theme="vs-dark"
                onMount={(ed, monaco) => {
                  editorRef.current = ed;
                  monacoRef.current = monaco;
                  applyDecorations();
                }}
                options={{
                  readOnly: true,
                  domReadOnly: true,
                  glyphMargin: true,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  fontSize: 13,
                  renderLineHighlight: "none",
                }}
              />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
