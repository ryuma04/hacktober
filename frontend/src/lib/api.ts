import { API, IS_MOCK } from "./url";
import type {
  Health,
  AnalysesListResponse,
  CreateAnalysisResponse,
  Job,
  Capsule,
  ApiError,
  WorkspaceFilesResponse,
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
  const res = await fetch(`${API}/api/analyses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url, ref, options }),
  });
  return handleResponse<CreateAnalysisResponse>(res);
}

export async function getJob(id: string): Promise<Job> {
  if (id === "dx_fail01") {
    const res = await fetch("/fixtures/job_failed.json");
    return handleResponse<Job>(res);
  }
  if (id === "dx_demo01" && IS_MOCK) {
    const res = await fetch("/fixtures/job_completed.json");
    return handleResponse<Job>(res);
  }
  try {
    const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}`);
    return await handleResponse<Job>(res);
  } catch (err) {
    if (id === "dx_demo01") {
      const res = await fetch("/fixtures/job_completed.json");
      return handleResponse<Job>(res);
    }
    throw err;
  }
}

export async function getCapsule(id: string): Promise<Capsule> {
  if (id === "dx_demo01" && IS_MOCK) {
    const res = await fetch("/fixtures/capsule.json");
    return handleResponse<Capsule>(res);
  }
  try {
    const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}/capsule`);
    return await handleResponse<Capsule>(res);
  } catch (err) {
    if (id === "dx_demo01") {
      const res = await fetch("/fixtures/capsule.json");
      return handleResponse<Capsule>(res);
    }
    throw err;
  }
}

export async function getCapsuleMd(id: string): Promise<string> {
  try {
    const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}/capsule.md`);
    if (res.ok) return await res.text();
  } catch {}
  if (id === "dx_demo01" || IS_MOCK) {
    const res = await fetch("/fixtures/capsule.md");
    if (!res.ok) throw new ApiRequestError("Failed to fetch capsule markdown", "fetch_error", res.status);
    return res.text();
  }
  throw new ApiRequestError("Failed to fetch capsule markdown", "fetch_error", 404);
}

export async function getPatch(id: string): Promise<string> {
  try {
    const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}/patch.diff`);
    if (res.ok) return await res.text();
  } catch {}
  if (id === "dx_demo01" || IS_MOCK) {
    const res = await fetch("/fixtures/patch.diff");
    if (!res.ok) throw new ApiRequestError("Failed to fetch patch", "fetch_error", res.status);
    return res.text();
  }
  throw new ApiRequestError("Failed to fetch patch", "fetch_error", 404);
}

export async function getLog(id: string, run: string, stream: "install" | "test"): Promise<string> {
  try {
    const res = await fetch(
      `${API}/api/analyses/${encodeURIComponent(id)}/runs/${encodeURIComponent(run)}/log?stream=${stream}`
    );
    if (res.ok) return await res.text();
  } catch {}
  if (id === "dx_demo01" || IS_MOCK) {
    const res = await fetch(`/fixtures/logs/${run}-${stream}.log`);
    if (res.ok) return await res.text();
  }
  throw new ApiRequestError(`Log not found for ${run} (${stream})`, "not_found", 404);
}

/** Original clone vs the migrated workspace that ran in Docker (read-only evidence). */
export async function getWorkspaceFiles(id: string): Promise<WorkspaceFilesResponse> {
  if (IS_MOCK) {
    const res = await fetch("/fixtures/workspace/files.json");
    return handleResponse<WorkspaceFilesResponse>(res);
  }
  const res = await fetch(`${API}/api/analyses/${encodeURIComponent(id)}/files`);
  return handleResponse<WorkspaceFilesResponse>(res);
}

export async function getWorkspaceFile(id: string, side: "original" | "migrated", path: string): Promise<string | null> {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  const url = IS_MOCK
    ? `/fixtures/workspace/${side}/${encoded}`
    : `${API}/api/analyses/${encodeURIComponent(id)}/${side}/${encoded}`;
  const res = await fetch(url);
  if (res.status === 404) return null; // file does not exist on this side (added / removed)
  if (!res.ok) throw new ApiRequestError(`Failed to load ${path} (${side})`, "fetch_error", res.status);
  return res.text();
}
