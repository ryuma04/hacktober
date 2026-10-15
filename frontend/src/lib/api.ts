import { API, IS_MOCK } from "./url";
import type {
  Health,
  AnalysesListResponse,
  CreateAnalysisResponse,
  Job,
  Capsule,
  ApiError,
} from "./types";

export class ApiRequestError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string = "unknown", status: number = 500) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.status = status;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errBody: ApiError | null = null;
    try {
      errBody = await res.json();
    } catch {
      // not JSON
    }
    const message = errBody?.error?.message || `Request failed with status ${res.status}`;
    const code = errBody?.error?.code || `status_${res.status}`;
    throw new ApiRequestError(message, code, res.status);
  }
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<Health> {
  if (IS_MOCK) {
    const res = await fetch("/fixtures/health.json");
    return handleResponse<Health>(res);
  }
  const res = await fetch(`${API}/api/health`);
  return handleResponse<Health>(res);
}

export async function listAnalyses(): Promise<AnalysesListResponse> {
  if (IS_MOCK) {
    const res = await fetch("/fixtures/analyses_list.json");
    return handleResponse<AnalysesListResponse>(res);
  }
  const res = await fetch(`${API}/api/analyses`);
  return handleResponse<AnalysesListResponse>(res);
}

export async function createAnalysis(
  repo_url: string,
  ref: string = "main",
  options?: { isolated_runs?: boolean; repair?: boolean; max_dependencies?: number }
): Promise<CreateAnalysisResponse> {
  if (IS_MOCK) {
    const res = await fetch("/fixtures/created.json");
    return handleResponse<CreateAnalysisResponse>(res);
  }
  const res = await fetch(`${API}/api/analyses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url, ref, options }),
  });
  return handleResponse<CreateAnalysisResponse>(res);
}

export async function getJob(id: string): Promise<Job> {
  if (IS_MOCK) {
    if (id === "dx_fail01") {
      const res = await fetch("/fixtures/job_failed.json");
      return handleResponse<Job>(res);
    }
    const res = await fetch("/fixtures/job_completed.json");
    return handleResponse<Job>(res);
  }
  const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}`);
  return handleResponse<Job>(res);
}

export async function getCapsule(id: string): Promise<Capsule> {
  if (IS_MOCK) {
    const res = await fetch("/fixtures/capsule.json");
    return handleResponse<Capsule>(res);
  }
  const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}/capsule`);
  return handleResponse<Capsule>(res);
}

export async function getCapsuleMd(id: string): Promise<string> {
  if (IS_MOCK) {
    const res = await fetch("/fixtures/capsule.md");
    if (!res.ok) throw new ApiRequestError("Failed to fetch capsule markdown", "fetch_error", res.status);
    return res.text();
  }
  const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}/capsule.md`);
  if (!res.ok) throw new ApiRequestError("Failed to fetch capsule markdown", "fetch_error", res.status);
  return res.text();
}

export async function getPatch(id: string): Promise<string> {
  if (IS_MOCK) {
    const res = await fetch("/fixtures/patch.diff");
    if (!res.ok) throw new ApiRequestError("Failed to fetch patch", "fetch_error", res.status);
    return res.text();
  }
  const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}/patch.diff`);
  if (!res.ok) throw new ApiRequestError("Failed to fetch patch", "fetch_error", res.status);
  return res.text();
}

export async function getLog(id: string, run: string, stream: "install" | "test"): Promise<string> {
  if (IS_MOCK) {
    const res = await fetch(`/fixtures/logs/${run}-${stream}.log`);
    if (!res.ok) throw new ApiRequestError(`Log not found for ${run} (${stream})`, "not_found", res.status);
    return res.text();
  }
  const res = await fetch(
    `${API}/api/analyses/${encodeURIComponent(id)}/runs/${encodeURIComponent(run)}/log?stream=${stream}`
  );
  if (!res.ok) throw new ApiRequestError(`Log not found for ${run} (${stream})`, "not_found", res.status);
  return res.text();
}
