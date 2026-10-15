"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { API, IS_MOCK } from "./url";
import { getJob, getCapsule, ApiRequestError } from "./api";
import type {
  Job,
  Stage,
  StageId,
  StageStatus,
  Capsule,
  SSEEventData,
} from "./types";

export interface LogItem {
  seq: number;
  ts: string;
  stage?: StageId;
  level: "info" | "warn" | "error";
  message: string;
}

export interface AiCallItem {
  seq: number;
  ts: string;
  stage?: StageId;
  purpose: string;
  model: string;
  latency_ms: number;
  ok: boolean;
  error?: string;
}

export const STAGE_ORDER: { id: StageId; label: string }[] = [
  { id: "clone", label: "Cloning repository" },
  { id: "scan", label: "Scanning dependencies" },
  { id: "usage", label: "Mapping usage" },
  { id: "propose", label: "Gemma 4: proposing replacements" },
  { id: "materialize", label: "Building migrated workspace" },
  { id: "sandbox_baseline", label: "Testing original dependencies" },
  { id: "sandbox_migrated", label: "Testing replacements" },
  { id: "compare", label: "Gemma 4: analysing gaps" },
  { id: "capsule", label: "Generating Exit Capsule" },
];

function initStages(): Stage[] {
  return STAGE_ORDER.map((s) => ({
    id: s.id,
    label: s.label,
    status: "pending" as StageStatus,
  }));
}

export function useAnalysis(id: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [stages, setStages] = useState<Stage[]>(initStages);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [aiCalls, setAiCalls] = useState<AiCallItem[]>([]);
  const [capsule, setCapsule] = useState<Capsule | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isReplaying, setIsReplaying] = useState<boolean>(false);

  const seenSeqs = useRef<Set<number>>(new Set());
  const esRef = useRef<EventSource | null>(null);
  const replayTimerRef = useRef<NodeJS.Timeout | null>(null);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const errorCountRef = useRef<number>(0);

  const applyStageEvent = useCallback(
    (stageId: StageId, status: StageStatus, duration_s?: number, err?: string) => {
      setStages((prev) =>
        prev.map((s) => {
          if (s.id === stageId) {
            return {
              ...s,
              status,
              ...(duration_s !== undefined ? { duration_s } : {}),
              ...(err ? { error: err } : {}),
              ...(status === "running" && !s.started_at ? { started_at: new Date().toISOString() } : {}),
              ...(status === "completed" || status === "failed" ? { finished_at: new Date().toISOString() } : {}),
            };
          }
          return s;
        })
      );
    },
    []
  );

  const processEventData = useCallback(
    (eventType: string, data: SSEEventData) => {
      if (seenSeqs.current.has(data.seq)) return;
      seenSeqs.current.add(data.seq);

      switch (eventType) {
        case "job_started": {
          setJob((prev) => ({
            id,
            repo_url: data.repo_url || prev?.repo_url || "https://github.com/rishrek/LinkWatch",
            ref: "main",
            status: "running",
            created_at: data.ts,
            stages: initStages(),
          }));
          break;
        }
        case "stage_started": {
          if (data.stage) {
            applyStageEvent(data.stage, "running");
          }
          break;
        }
        case "stage_completed": {
          if (data.stage) {
            applyStageEvent(data.stage, "completed", data.duration_s);
          }
          break;
        }
        case "stage_failed": {
          if (data.stage) {
            applyStageEvent(data.stage, "failed", undefined, data.error);
          }
          break;
        }
        case "stage_skipped": {
          if (data.stage) {
            applyStageEvent(data.stage, "skipped");
          }
          break;
        }
        case "log": {
          setLogs((prev) => {
            const next = [
              ...prev,
              {
                seq: data.seq,
                ts: data.ts,
                stage: data.stage,
                level: data.level || "info",
                message: data.message || "",
              },
            ];
            return next.slice(-200);
          });
          break;
        }
        case "ai_call": {
          setAiCalls((prev) => [
            ...prev,
            {
              seq: data.seq,
              ts: data.ts,
              stage: data.stage,
              purpose: data.purpose || "Gemma 4 inference",
              model: data.model || "gemma-4",
              latency_ms: data.latency_ms || 0,
              ok: data.ok ?? true,
              error: data.error,
            },
          ]);
          break;
        }
        case "job_completed": {
          setJob((prev) =>
            prev
              ? {
                  ...prev,
                  status: (data.status as any) || "completed",
                  finished_at: data.ts,
                  summary: (data.summary as any) || prev.summary,
                }
              : null
          );
          setIsReplaying(false);
          getCapsule(id)
            .then((cap) => setCapsule(cap))
            .catch((e) => console.error("Failed to load capsule after completion:", e));
          break;
        }
        case "job_failed": {
          setJob((prev) =>
            prev
              ? {
                  ...prev,
                  status: "failed",
                  finished_at: data.ts,
                  error: data.error,
                }
              : null
          );
          setIsReplaying(false);
          setError(data.error || "Job failed");
          break;
        }
      }
    },
    [id, applyStageEvent]
  );

  // Fast skip mock replay
  const skipToCompleted = useCallback(async () => {
    if (replayTimerRef.current) clearInterval(replayTimerRef.current);
    try {
      const finishedJob = await getJob(id);
      setJob(finishedJob);
      if (finishedJob.stages) setStages(finishedJob.stages);
      if (finishedJob.status === "completed" || finishedJob.status === "completed_with_errors") {
        const cap = await getCapsule(id);
        setCapsule(cap);
      }
      setIsReplaying(false);
    } catch (e: any) {
      setError(e.message || "Failed to load job");
    }
  }, [id]);

  useEffect(() => {
    let isCancelled = false;
    seenSeqs.current.clear();
    setLogs([]);
    setAiCalls([]);
    setError(null);
    setCapsule(null);
    setLoading(true);

    async function run() {
      try {
        if (id === "dx_fail01") {
          const failJob = await getJob("dx_fail01");
          if (!isCancelled) {
            setJob(failJob);
            if (failJob.stages) setStages(failJob.stages);
            setError(failJob.error || "clone failed: repository not found");
            setLoading(false);
          }
          return;
        }

        if (id === "dx_demo00") {
          const completedJob = await getJob("dx_demo01");
          if (!isCancelled) {
            setJob({ ...completedJob, id: "dx_demo00", status: "completed_with_errors" });
            if (completedJob.stages) setStages(completedJob.stages);
            const cap = await getCapsule(id);
            setCapsule(cap);
            setLoading(false);
          }
          return;
        }

        if (id === "dx_demo01" && IS_MOCK) {
          setIsReplaying(true);
          const res = await fetch("/fixtures/events.ndjson");
          const text = await res.text();
          const lines = text
            .split("\n")
            .map((l) => l.trim())
            .filter(Boolean);

          let lineIdx = 0;
          setLoading(false);

          replayTimerRef.current = setInterval(() => {
            if (isCancelled || lineIdx >= lines.length) {
              if (replayTimerRef.current) clearInterval(replayTimerRef.current);
              setIsReplaying(false);
              return;
            }
            try {
              const parsed = JSON.parse(lines[lineIdx]);
              const eventType = parsed.event || "log";
              processEventData(eventType, parsed);
            } catch (err) {
              console.error("Error parsing replay event:", err);
            }
            lineIdx++;
          }, 400);

          return;
        }

        // Live Mode
        const initialJob = await getJob(id);
        if (isCancelled) return;
        setJob(initialJob);
        if (initialJob.stages) setStages(initialJob.stages);
        setLoading(false);

        // If job already ended:
        if (
          initialJob.status === "completed" ||
          initialJob.status === "completed_with_errors"
        ) {
          try {
            const cap = await getCapsule(id);
            if (!isCancelled) setCapsule(cap);
          } catch (e: any) {
            console.error("Failed fetching capsule:", e);
          }
          return;
        }

        if (initialJob.status === "failed") {
          setError(initialJob.error || "Analysis failed");
          return;
        }

        // Setup SSE
        const eventSourceUrl = `${API}/api/analyses/${encodeURIComponent(id)}/events`;
        const es = new EventSource(eventSourceUrl);
        esRef.current = es;

        const eventNames: SSEEventData["event"][] = [
          "job_started",
          "stage_started",
          "stage_completed",
          "stage_failed",
          "stage_skipped",
          "log",
          "ai_call",
          "job_completed",
          "job_failed",
        ];

        eventNames.forEach((name) => {
          if (!name) return;
          es.addEventListener(name, (evt: MessageEvent) => {
            try {
              const data = JSON.parse(evt.data);
              processEventData(name, data);
            } catch (e) {
              console.error(`Error parsing SSE event ${name}:`, e);
            }
          });
        });

        es.onerror = () => {
          errorCountRef.current++;
          if (errorCountRef.current >= 2) {
            es.close();
            // Start polling fallback every 2s
            pollTimerRef.current = setInterval(async () => {
              try {
                const j = await getJob(id);
                setJob(j);
                if (j.stages) setStages(j.stages);
                if (j.status === "completed" || j.status === "completed_with_errors") {
                  if (pollTimerRef.current) clearInterval(pollTimerRef.current);
                  const cap = await getCapsule(id);
                  setCapsule(cap);
                } else if (j.status === "failed") {
                  if (pollTimerRef.current) clearInterval(pollTimerRef.current);
                  setError(j.error || "Analysis failed");
                }
              } catch (e) {
                console.error("Polling error:", e);
              }
            }, 2000);
          }
        };
      } catch (err: any) {
        if (!isCancelled) {
          setError(err.message || "Failed to load analysis");
          setLoading(false);
        }
      }
    }

    run();

    return () => {
      isCancelled = true;
      if (esRef.current) esRef.current.close();
      if (replayTimerRef.current) clearInterval(replayTimerRef.current);
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [id, processEventData]);

  return {
    job,
    stages,
    logs,
    aiCalls,
    capsule,
    loading,
    error,
    isReplaying,
    skipToCompleted,
  };
}
