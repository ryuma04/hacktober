"use client";

import React, { useMemo, useState } from "react";
import { Network } from "lucide-react";
import type { BlastRadius, Dependency } from "@/lib/types";
import { BlastRadiusGraph } from "./BlastRadiusGraph";
import { ProvenanceTag } from "./Shared";

const AT_RISK = new Set(["critical", "high", "medium"]);

/** Merge per-dependency blast radii into one repo-wide graph (nodes/edges de-duplicated). */
function mergeBlast(deps: Dependency[]): BlastRadius | null {
  const withBlast = deps.filter((d) => d.blast_radius);
  if (withBlast.length === 0) return null;
  const nodes = new Map<string, BlastRadius["nodes"][number]>();
  const edges = new Map<string, BlastRadius["edges"][number]>();
  const direct = new Map<string, BlastRadius["direct"][number]>();
  const indirect = new Map<string, BlastRadius["indirect"][number]>();
  const tests = new Map<string, BlastRadius["tests"][number]>();
  let totalTests = 0;
  for (const d of withBlast) {
    const b = d.blast_radius!;
    totalTests = Math.max(totalTests, b.stats.total_test_files);
    for (const n of b.nodes) {
      const prev = nodes.get(n.id);
      // a file that one dependency uses directly stays "direct" even if another only reaches it indirectly
      if (!prev || (n.impact === "direct" && prev.impact !== "direct")) {
        nodes.set(n.id, { ...n, lines: n.impact === "direct" ? (prev?.impact === "direct" ? (prev.lines ?? 0) : 0) + (n.lines ?? 0) : n.lines });
      } else if (n.impact === "direct" && prev.impact === "direct") {
        nodes.set(n.id, { ...prev, lines: (prev.lines ?? 0) + (n.lines ?? 0) });
      }
    }
    for (const e of b.edges) edges.set(`${e.from}->${e.to}`, e);
    for (const f of b.direct) {
      const cur = direct.get(f.file);
      direct.set(f.file, cur ? { file: f.file, lines: [...cur.lines, ...f.lines].sort((a, z) => a.line - z.line) } : f);
    }
    for (const x of b.indirect) if (!indirect.has(x.file)) indirect.set(x.file, x);
    for (const x of b.tests) if (!tests.has(x.file)) tests.set(x.file, x);
  }
  // a module that is direct for some dependency is not listed as indirect
  for (const f of direct.keys()) indirect.delete(f);
  const directList = [...direct.values()];
  return {
    direct: directList,
    indirect: [...indirect.values()],
    tests: [...tests.values()],
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    stats: {
      direct_files: directList.length,
      lines: directList.reduce((n, f) => n + f.lines.length, 0),
      indirect_files: indirect.size,
      test_files: tests.size,
      total_test_files: totalTests,
    },
    provenance: "evidence",
  };
}

/**
 * Repo-wide blast map: every at-risk dependency → the files that use it → the modules importing those → the tests
 * that reach them. Built from the AST + the project's own import graph (evidence). Click any node to trace it.
 */
export function BlastMap({ dependencies }: { dependencies: Dependency[] }) {
  const [onlyAtRisk, setOnlyAtRisk] = useState(true);
  const deps = useMemo(
    () => dependencies.filter((d) => d.blast_radius && (!onlyAtRisk || AT_RISK.has(d.risk.level))),
    [dependencies, onlyAtRisk]
  );
  const merged = useMemo(() => mergeBlast(deps), [deps]);
  // which dependencies use a given (directly affected) file — names the end of an import chain
  const usersOf = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const d of deps) for (const f of d.blast_radius!.direct) m.set(f.file, [...(m.get(f.file) ?? []), d.name]);
    return m;
  }, [deps]);

  if (!dependencies.some((d) => d.blast_radius)) return null;

  return (
    <section className="bg-white border-[3px] border-[#17151F] rounded-[28px] shadow-[6px_6px_0_0_#17151F] p-6 space-y-4">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-[#5A5870] flex items-center gap-1.5">
            <Network className="w-3.5 h-3.5" /> Blast map
          </p>
          <h2 className="font-display font-extrabold text-2xl text-[#17151F]">What breaks if these dependencies go</h2>
          <p className="text-sm text-[#5A5870] mt-1">
            Exact code paths from each dependency to the project files and tests that rely on it — from the AST and the
            project&apos;s own import graph, not text search. Click a node to trace its chain.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <ProvenanceTag provenance="evidence" />
          <div className="flex rounded-full border-2 border-[#17151F] bg-white p-0.5 text-xs font-bold">
            {[
              { v: true, label: "At-risk only" },
              { v: false, label: "All" },
            ].map((o) => (
              <button
                key={o.label}
                type="button"
                onClick={() => setOnlyAtRisk(o.v)}
                className={`px-3 py-1 rounded-full transition ${onlyAtRisk === o.v ? "bg-[#F9D56E] text-[#17151F]" : "text-[#5A5870]"}`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {merged ? (
        <BlastRadiusGraph
          key={onlyAtRisk ? "risk" : "all"}
          blast={merged}
          depName="dependencies"
          depOf={(file) => (usersOf.get(file) ?? ["?"]).join(", ")}
          summary={
            <p className="text-sm text-[#17151F]">
              <b>{deps.length}</b> dependenc{deps.length === 1 ? "y" : "ies"} touch <b>{merged.stats.lines}</b> line
              {merged.stats.lines === 1 ? "" : "s"} in <b>{merged.stats.direct_files}</b> file
              {merged.stats.direct_files === 1 ? "" : "s"} · <b>{merged.stats.indirect_files}</b> more module
              {merged.stats.indirect_files === 1 ? "" : "s"} import those · <b>{merged.stats.test_files}</b> of{" "}
              {merged.stats.total_test_files} test files are exposed.
            </p>
          }
        />
      ) : (
        <p className="text-sm text-[#5A5870] italic">No imported dependencies match this filter.</p>
      )}
    </section>
  );
}
