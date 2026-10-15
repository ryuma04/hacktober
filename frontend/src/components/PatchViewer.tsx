"use client";

import React, { useState, useEffect } from "react";
import { Card, CodeChip, Button } from "./ui/Base";
import { getPatch } from "@/lib/api";
import { apiUrl } from "@/lib/url";
import { Download, ChevronDown, ChevronRight, FileDiff, Copy, Check } from "lucide-react";

interface FileDiffChunk {
  fileName: string;
  lines: string[];
}

export function PatchViewer({
  analysisId,
  patchStats,
}: {
  analysisId: string;
  patchStats?: { url: string; files_changed: number; insertions: number; deletions: number };
}) {
  const [diffText, setDiffText] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsedFiles, setCollapsedFiles] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    let isCancelled = false;
    setLoading(true);

    getPatch(analysisId)
      .then((txt) => {
        if (!isCancelled) {
          setDiffText(txt);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          setError(err.message || "Failed to load patch");
          setLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [analysisId]);

  // Parse diffText into files split by "--- a/" or "diff --git"
  const parseDiffFiles = (text: string): FileDiffChunk[] => {
    if (!text.trim()) return [];

    const lines = text.split("\n");
    const files: FileDiffChunk[] = [];
    let currentFile: FileDiffChunk | null = null;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      if (line.startsWith("--- a/")) {
        const fileName = line.replace("--- a/", "");
        currentFile = { fileName, lines: [line] };
        files.push(currentFile);
      } else if (line.startsWith("diff --git a/")) {
        const parts = line.split(" ");
        const fileName = parts[2]?.replace("a/", "") || "file";
        currentFile = { fileName, lines: [line] };
        files.push(currentFile);
      } else if (currentFile) {
        currentFile.lines.push(line);
      }
    }

    // Fallback if no header split was found
    if (files.length === 0) {
      return [{ fileName: "patch.diff", lines }];
    }

    return files;
  };

  const fileDiffs = parseDiffFiles(diffText);

  const toggleCollapse = (name: string) => {
    setCollapsedFiles((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(diffText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadUrl = apiUrl(patchStats?.url || `/api/analyses/${analysisId}/patch.diff`);

  return (
    <Card className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-3 border-b border-[#17151F]/15">
        <div>
          <div className="flex items-center gap-2">
            <FileDiff className="w-6 h-6 text-[#17151F]" />
            <h3 className="font-display font-extrabold text-2xl text-[#17151F]">
              Unified Migration Patch
            </h3>
          </div>
          <p className="text-sm text-[#5A5870]">
            Generated code & manifest edits validated via <CodeChip>compile()</CodeChip> before materialization
          </p>
        </div>

        {/* Patch stats & buttons */}
        <div className="flex items-center gap-2">
          {patchStats && (
            <div className="flex items-center gap-2 font-mono text-xs mr-2">
              <span className="font-bold bg-[#B9E4A1] text-[#17151F] px-2 py-0.5 rounded-full border border-[#17151F]/30">
                +{patchStats.insertions}
              </span>
              <span className="font-bold bg-[#F2A58B] text-[#17151F] px-2 py-0.5 rounded-full border border-[#17151F]/30">
                -{patchStats.deletions}
              </span>
              <span className="text-[#5A5870] font-semibold">
                {patchStats.files_changed} files
              </span>
            </div>
          )}

          <button
            onClick={handleCopy}
            className="btn-secondary text-xs! py-2! px-3.5! flex items-center gap-1.5 cursor-pointer"
          >
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>

          <a
            href={downloadUrl}
            download="patch.diff"
            className="btn-primary text-xs! py-2! px-4! flex items-center gap-1.5 cursor-pointer"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download Diff</span>
          </a>
        </div>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm font-semibold text-[#5A5870]">
          Loading patch diff...
        </div>
      ) : error ? (
        <div className="p-4 bg-[#FDECEC] text-[#D64545] rounded-xl text-xs font-mono font-bold">
          {error}
        </div>
      ) : fileDiffs.length === 0 ? (
        <div className="p-8 text-center text-sm italic text-[#5A5870]">
          No code changes were produced for this migration.
        </div>
      ) : (
        <div className="space-y-4">
          {fileDiffs.map((fd, idx) => {
            const isCollapsed = collapsedFiles[fd.fileName];

            return (
              <div
                key={idx}
                className="border-2 border-[#17151F] rounded-2xl overflow-hidden shadow-xs bg-white"
              >
                {/* File Header */}
                <div
                  onClick={() => toggleCollapse(fd.fileName)}
                  className="bg-[#F5F1E8] px-4 py-3 flex items-center justify-between cursor-pointer hover:bg-[#F9D56E]/40 transition border-b-2 border-[#17151F]"
                >
                  <div className="flex items-center gap-2">
                    {isCollapsed ? (
                      <ChevronRight className="w-4 h-4 text-[#17151F]" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-[#17151F]" />
                    )}
                    <span className="font-mono text-xs md:text-sm font-bold text-[#17151F]">
                      {fd.fileName}
                    </span>
                  </div>
                  <span className="text-[11px] font-mono text-[#5A5870]">
                    {fd.lines.length} diff lines
                  </span>
                </div>

                {/* Diff Lines Body */}
                {!isCollapsed && (
                  <div className="overflow-x-auto p-2 font-mono text-[13px] leading-relaxed bg-[#FAFAFA] select-text">
                    {fd.lines.map((line, lIdx) => {
                      let lineClass = "text-[#17151F] px-2 py-0.5";
                      if (line.startsWith("+") && !line.startsWith("+++")) {
                        lineClass =
                          "bg-[#B9E4A1]/40 text-[#17151F] font-semibold px-2 py-0.5 rounded-xs";
                      } else if (line.startsWith("-") && !line.startsWith("---")) {
                        lineClass =
                          "bg-[#F2A58B]/40 text-[#D64545] font-semibold px-2 py-0.5 rounded-xs";
                      } else if (line.startsWith("@@")) {
                        lineClass =
                          "bg-[#A8CCF4]/40 text-[#17151F] font-bold px-2 py-0.5 rounded-xs my-1";
                      }

                      return (
                        <div key={lIdx} className={lineClass}>
                          {line || " "}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
