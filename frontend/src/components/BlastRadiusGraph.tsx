"use client";

import React, { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { BlastRadius } from "@/lib/types";

type Node = BlastRadius["nodes"][number];

const COLUMNS = [
  { key: "dep", title: "Dependency" },
  { key: "direct", title: "Uses it directly" },
  { key: "indirect", title: "Imports affected code" },
  { key: "tests", title: "Tests that reach it" },
] as const;

const NODE_STYLE: Record<string, string> = {
  dep: "bg-[#F2A58B] border-[#17151F]",
  direct: "bg-[#F9D56E] border-[#17151F]",
  indirect: "bg-[#A8CCF4] border-[#17151F]",
  tests: "bg-[#B9E4A1] border-[#17151F]",
};

function columnOf(n: Node): (typeof COLUMNS)[number]["key"] {
  if (n.type === "dependency") return "dep";
  if (n.impact === "direct") return "direct";
  if (n.type === "test" && !n.id.endsWith("conftest.py")) return "tests";
  return "indirect"; // project modules and conftest.py (pytest loads it for every test in its folder)
}

/** Everything connected to `id` along dependency chains: what it depends on and what depends on it. */
function chainOf(id: string, edges: BlastRadius["edges"]): Set<string> {
  const out = new Set([id]);
  const walk = (start: string, dir: "down" | "up") => {
    const stack = [start];
    while (stack.length) {
      const cur = stack.pop()!;
      for (const e of edges) {
        const next = dir === "down" ? (e.from === cur ? e.to : null) : (e.to === cur ? e.from : null);
        if (next && !out.has(next)) {
          out.add(next);
          stack.push(next);
        }
      }
    }
  };
  walk(id, "down");
  walk(id, "up");
  return out;
}

/**
 * Blast radius: which project files break if this dependency goes away, computed from the AST and the project's
 * own import graph (evidence, not AI). Click a node to highlight its chain; the panel shows the exact lines.
 */
export function BlastRadiusGraph({
  blast,
  depName,
  summary,
  depOf,
}: {
  blast: BlastRadius;
  depName: string;
  summary?: React.ReactNode; // replaces the per-dependency headline (used by the repo-wide map)
  depOf?: (fileId: string) => string; // which dependency a chain ends at (repo-wide map)
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<string, HTMLDivElement>());
  const [lines, setLines] = useState<{ from: string; to: string; kind: string; d: string }[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });

  const columns = useMemo(() => {
    const cols: Record<string, Node[]> = { dep: [], direct: [], indirect: [], tests: [] };
    for (const n of blast.nodes) cols[columnOf(n)].push(n);
    for (const k of Object.keys(cols)) cols[k].sort((a, b) => a.label.localeCompare(b.label));
    return cols;
  }, [blast.nodes]);

  const near = useMemo(() => (selected ? chainOf(selected, blast.edges) : null), [selected, blast.edges]);

  // Measure node boxes and draw curved connectors (from right edge of the target to left edge of the dependant).
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const draw = () => {
      const b = box.getBoundingClientRect();
      const out: typeof lines = [];
      for (const e of blast.edges) {
        const from = nodeRefs.current.get(e.from);
        const to = nodeRefs.current.get(e.to);
        if (!from || !to) continue;
        const f = from.getBoundingClientRect();
        const t = to.getBoundingClientRect();
        // the dependant (from) sits to the right of what it depends on (to)
        const x1 = t.right - b.left, y1 = t.top + t.height / 2 - b.top;
        const x2 = f.left - b.left, y2 = f.top + f.height / 2 - b.top;
        const mid = (x1 + x2) / 2;
        out.push({ from: e.from, to: e.to, kind: e.kind, d: `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}` });
      }
      setLines(out);
      setSize({ w: b.width, h: b.height });
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(box);
    return () => ro.disconnect();
  }, [blast.edges, columns]);

  const sel = selected ? blast.nodes.find((n) => n.id === selected) : null;
  const directFile = sel ? blast.direct.find((d) => d.file === sel.id) : null;
  const chain = sel ? [...blast.indirect, ...blast.tests].find((x) => x.file === sel.id) : null;
  const s = blast.stats;

  return (
    <div className="space-y-3">
      {summary ?? <p className="text-sm text-[#17151F]">
        <b>{s.lines}</b> line{s.lines === 1 ? "" : "s"} in <b>{s.direct_files}</b> file{s.direct_files === 1 ? "" : "s"} use{" "}
        <code className="font-mono">{depName}</code> directly · <b>{s.indirect_files}</b> more module
        {s.indirect_files === 1 ? "" : "s"} import those · <b>{s.test_files}</b> of {s.total_test_files} test file
        {s.total_test_files === 1 ? "" : "s"} reach it.
      </p>}

      <div ref={boxRef} className="relative overflow-x-auto overflow-y-hidden rounded-2xl border-2 border-[#17151F]/15 bg-[#F5F1E8] p-4 pb-6">
        <svg className="absolute inset-0 pointer-events-none" width={size.w} height={size.h} aria-hidden>
          {lines.map((l) => {
            const on = !near || (near.has(l.from) && near.has(l.to));
            return (
              <path
                key={`${l.from}->${l.to}`}
                d={l.d}
                fill="none"
                stroke={on && near ? "#6E56D9" : "#17151F"}
                strokeOpacity={on ? (near ? 0.9 : 0.35) : 0.08}
                strokeWidth={on && near ? 2.5 : 1.5}
                strokeDasharray={l.kind === "conftest" ? "5 4" : undefined}
              />
            );
          })}
        </svg>
        <div className="relative grid grid-cols-4 gap-6 min-w-[720px]">
          {COLUMNS.map((c) => (
            <div key={c.key} className="space-y-2">
              <p className="text-[10px] font-bold uppercase tracking-widest text-[#5A5870]">{c.title}</p>
              {columns[c.key].length === 0 && <p className="text-xs italic text-[#5A5870]">none</p>}
              {columns[c.key].map((n) => {
                const on = selected === n.id;
                const faded = !!near && !near.has(n.id);
                return (
                  <div
                    key={n.id}
                    ref={(el) => {
                      if (el) nodeRefs.current.set(n.id, el);
                      else nodeRefs.current.delete(n.id);
                    }}
                    role="button"
                    tabIndex={0}
                    aria-pressed={on}
                    onClick={() => setSelected(on ? null : n.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelected(on ? null : n.id);
                      }
                    }}
                    className={`cursor-pointer rounded-xl border-2 px-2.5 py-1.5 text-xs font-mono transition ${NODE_STYLE[c.key]} ${
                      on ? "ring-4 ring-[#6E56D9]/40 shadow-[3px_3px_0_0_#17151F]" : "hover:-translate-y-0.5"
                    } ${faded ? "opacity-30" : ""}`}
                    title={n.label}
                  >
                    <span className="block truncate font-bold">{c.key === "dep" ? n.label : n.label.split("/").pop()}</span>
                    {c.key !== "dep" && <span className="block truncate text-[10px] opacity-70">{n.label}</span>}
                    {n.lines ? <span className="text-[10px] font-bold">{n.lines} line{n.lines === 1 ? "" : "s"}</span> : null}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-3 text-[11px] text-[#5A5870]">
        <span>Solid line: imports / uses</span>
        <span>Dashed line: loaded via pytest conftest.py</span>
        <span>Click a node to trace its chain</span>
      </div>

      {sel && (
        <div className="rounded-2xl border-2 border-[#17151F] bg-white p-3 space-y-2">
          <p className="text-xs font-bold text-[#17151F] font-mono">{sel.label}</p>
          {directFile &&
            directFile.lines.map((l) => (
              <div key={l.line} className="flex items-start gap-2 text-xs font-mono">
                <span className="text-[#5A5870] w-10 shrink-0 text-right">{l.line}</span>
                <code className="flex-1 bg-[#F5F1E8] rounded px-2 py-0.5 overflow-x-auto whitespace-pre">{l.code}</code>
                <span className="flex gap-1 shrink-0">
                  {l.kinds.map((k) => (
                    <span
                      key={k}
                      className={`px-1.5 rounded-full border text-[10px] ${
                        k === "private_api" || k === "monkeypatch" ? "bg-[#F2A58B] border-[#17151F]" : "bg-white border-[#17151F]/30"
                      }`}
                    >
                      {k}
                    </span>
                  ))}
                </span>
              </div>
            ))}
          {chain && (
            <p className="text-xs font-mono text-[#17151F] flex flex-wrap items-center gap-1">
              {chain.via.map((v, i) => (
                <React.Fragment key={v + i}>
                  {i > 0 && <span className="text-[#5A5870]">→</span>}
                  <span className="bg-[#F5F1E8] rounded px-1.5 py-0.5">{v}</span>
                </React.Fragment>
              ))}
              <span className="text-[#5A5870]">→</span>
              <span className="bg-[#F2A58B] rounded px-1.5 py-0.5">{depOf ? depOf(chain.via[chain.via.length - 1]) : depName}</span>
            </p>
          )}
          {sel.type === "dependency" && <p className="text-xs text-[#5A5870]">Select a file to see its lines or import chain.</p>}
        </div>
      )}
    </div>
  );
}
