/** Typed API client. No secrets live here: the browser only ever talks to our
 *  own backend, which holds the Mireye / LLM credentials. */

import type {
  ChangeDetail,
  Evidence,
  ImpactGraph,
  InformationGap,
  Investigation,
  Meta,
  Project,
  ProjectDetail,
  Requirement,
  SearchResponse,
  WhatIfResponse,
} from "./types";

/** The API origin comes from the environment and nowhere else.
 *
 *  Empty is correct in development: Vite proxies `/api` to the local backend.
 *  In a production build an empty value means `VITE_API_BASE_URL` was not set
 *  when the bundle was built, so every call would hit the static host and 404.
 *  Say that, rather than shipping a localhost address to a deployed user. */
const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

const UNREACHABLE = import.meta.env.DEV
  ? "Cannot reach the API. Is the backend running on http://127.0.0.1:8000?"
  : BASE
    ? `Cannot reach the API at ${BASE}. It may be starting up, or its CORS_ORIGINS may not include this site.`
    : "This build has no API origin configured. Set VITE_API_BASE_URL for the deployment and rebuild.";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/api${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(init?.headers ?? {}),
      },
    });
  } catch (cause) {
    throw new ApiError(UNREACHABLE, 0, cause);
  }
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    const message =
      (detail as { detail?: string })?.detail ??
      `${init?.method ?? "GET"} ${path} failed (${response.status})`;
    throw new ApiError(typeof message === "string" ? message : JSON.stringify(message), response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/meta"),
  ready: () => request<{ ready: boolean; checks: Record<string, string> }>("/ready"),
  projects: () => request<Project[]>("/projects"),
  project: (id: string) => request<ProjectDetail>(`/projects/${id}`),
  updateProject: (id: string, body: unknown) => patch<Project>(`/projects/${id}`, body),
  seed: () => post<{ project_id: string; project_name: string; message: string }>("/admin/seed"),

  // Before Construction
  createSite: (projectId: string, body: unknown) => post(`/projects/${projectId}/sites`, body),
  deleteSite: (projectId: string, siteId: string) =>
    request<void>(`/projects/${projectId}/sites/${siteId}`, { method: "DELETE" }),
  runSiteInvestigation: (projectId: string, body: unknown) =>
    post<Investigation>(`/projects/${projectId}/investigations/site`, body),
  ranking: (projectId: string, body: unknown) =>
    post<WhatIfResponse>(`/projects/${projectId}/ranking`, body),
  override: (projectId: string, siteId: string, body: unknown) =>
    post<WhatIfResponse>(`/projects/${projectId}/sites/${siteId}/override`, body),

  // During Construction
  changes: (projectId: string) => request<ChangeDetail["change"][]>(`/projects/${projectId}/changes`),
  change: (projectId: string, changeId: string) =>
    request<ChangeDetail>(`/projects/${projectId}/changes/${changeId}`),
  analyzeChange: (projectId: string, changeId: string) =>
    post<Investigation>(`/projects/${projectId}/changes/${changeId}/analyze`),
  impact: (changeId: string) => request<ImpactGraph>(`/impact/${changeId}`),

  // Shared knowledge
  investigations: (projectId: string, workflow?: string) =>
    request<Investigation[]>(
      `/projects/${projectId}/investigations${workflow ? `?workflow_filter=${workflow}` : ""}`,
    ),
  investigation: (projectId: string, id: string) =>
    request<Investigation>(`/projects/${projectId}/investigations/${id}`),
  evidence: (projectId: string, params: Record<string, string> = {}) =>
    request<Evidence[]>(
      `/projects/${projectId}/evidence?${new URLSearchParams(params).toString()}`,
    ),
  evidenceById: (id: string) => request<Evidence>(`/evidence/${id}`),
  gaps: (projectId: string) => request<InformationGap[]>(`/projects/${projectId}/gaps`),
  updateGap: (projectId: string, gapId: string, status: string) =>
    patch<InformationGap>(`/projects/${projectId}/gaps/${gapId}`, { status }),
  requirements: (projectId: string, tag?: string) =>
    request<Requirement[]>(
      `/projects/${projectId}/requirements${tag ? `?equipment_tag=${encodeURIComponent(tag)}` : ""}`,
    ),
  confirmRequirement: (projectId: string, id: string, body: unknown) =>
    patch<Requirement>(`/projects/${projectId}/requirements/${id}`, body),
  documents: (projectId: string) => request<ProjectDetail["documents"]>(`/projects/${projectId}/documents`),
  uploadDocument: (projectId: string, file: File, kind: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    return request<{
      document: ProjectDetail["documents"][number];
      chunk_count: number;
      requirements: Requirement[];
      warning?: string | null;
    }>(`/projects/${projectId}/documents`, { method: "POST", body: form });
  },
  search: (projectId: string, q: string) =>
    request<SearchResponse>(`/projects/${projectId}/search?q=${encodeURIComponent(q)}`),
  ask: (projectId: string, question: string, siteId?: string) =>
    post<{ answer: string; citations: unknown[]; confidence: number; mode: string; disclaimer: string }>(
      `/projects/${projectId}/ask`,
      { question, site_id: siteId },
    ),
  mireyeFields: () =>
    request<{ mode: string; count: number; fields: { key: string; label: string; unit?: string }[] }>(
      "/mireye/fields",
    ),
};
