/** Typed API client. No secrets live here: the browser only ever talks to our
 *  own backend, which holds the Mireye / LLM credentials. */

import type {
  ChangeDetail,
  ClimateStationInfo,
  Evidence,
  ImpactGraph,
  InformationGap,
  Investigation,
  Meta,
  Project,
  ProjectDetail,
  ReferenceSpec,
  Requirement,
  RequirementTargets,
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
  createProject: (body: {
    name: string;
    client?: string;
    description?: string;
    region?: string;
    targets?: RequirementTargets;
    dimension_weights?: Record<string, number>;
  }) => post<Project>("/projects", body),
  updateProject: (id: string, body: unknown) => patch<Project>(`/projects/${id}`, body),
  seed: () => post<{ project_id: string; project_name: string; message: string }>("/admin/seed"),
  reset: () => post<{ project_id: string; project_name: string; message: string }>("/admin/reset"),

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
  climateStation: (projectId: string, changeId: string) =>
    request<ClimateStationInfo>(`/projects/${projectId}/changes/${changeId}/climate-station`),
  referenceSpecs: (equipmentTag: string) =>
    request<ReferenceSpec>(`/during/reference-specs/${encodeURIComponent(equipmentTag)}`),
  autofillFromReference: (projectId: string, changeId: string) =>
    post<Investigation>(`/projects/${projectId}/changes/${changeId}/autofill-from-reference`),

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
  advisorChat: (projectId: string, payload: { message: string; site_id?: string | null; site_context?: Record<string, any> | null; history?: Array<{ role: string; content: string }> | null }) =>
    post<import("./types").AdvisorChatResponse>(`/projects/${projectId}/advisor/chat`, payload),
  advisorChatStream: async (
    projectId: string,
    payload: { message: string; site_id?: string | null; site_context?: Record<string, any> | null; history?: Array<{ role: string; content: string }> | null },
    onChunk: (chunk: string) => void,
    onDone: (meta: { improvements: string[]; mode: string }) => void,
  ) => {
    const res = await fetch(`${BASE}/api/projects/${projectId}/advisor/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Advisor stream error: ${res.statusText}`);
    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    if (!reader) return;

    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.chunk) onChunk(data.chunk);
            if (data.done) onDone({ improvements: data.improvements || [], mode: data.mode || "llm" });
          } catch {}
        }
      }
    }
  },
  mireyeFields: () =>
    request<{ mode: string; count: number; fields: { key: string; label: string; unit?: string }[] }>(
      "/mireye/fields",
    ),

  // Autonomous Project Knowledge Agent & MCP
  knowledgeAgentChat: (projectId: string, payload: import("./types").KnowledgeAgentRequest) =>
    post<import("./types").KnowledgeAgentResponse>(`/projects/${projectId}/knowledge/agent/chat`, payload),

  knowledgeAgentStream: async (
    projectId: string,
    payload: import("./types").KnowledgeAgentRequest,
    callbacks: {
      onToolStart?: (tool: { tool: string; title: string; input?: any }) => void;
      onToolFinish?: (finish: { tool: string; output_summary: string; duration_ms: number }) => void;
      onToken?: (token: string) => void;
      onTellMe?: (tellMe: import("./types").TellMeInsights) => void;
      onCitations?: (citations: import("./types").Citation[]) => void;
      onDone?: (done: { site_name?: string; mode: string; traces: import("./types").ToolExecutionTrace[] }) => void;
      onError?: (err: Error) => void;
    },
  ) => {
    try {
      const res = await fetch(`${BASE}/api/projects/${projectId}/knowledge/agent/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let errDetail = res.statusText;
        try {
          const errJson = await res.json();
          errDetail = errJson.detail || errJson.error || res.statusText;
        } catch {}
        throw new Error(`Agent stream error: ${errDetail}`);
      }
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) return;

      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.event === "tool_start" && callbacks.onToolStart) {
                callbacks.onToolStart(data);
              } else if (data.event === "tool_finish" && callbacks.onToolFinish) {
                callbacks.onToolFinish(data);
              } else if (data.event === "token" && callbacks.onToken && data.chunk) {
                callbacks.onToken(data.chunk);
              } else if (data.event === "tell_me" && callbacks.onTellMe && data.data) {
                callbacks.onTellMe(data.data);
              } else if (data.event === "citations" && callbacks.onCitations && data.data) {
                callbacks.onCitations(data.data);
              } else if (data.event === "done" && callbacks.onDone) {
                callbacks.onDone(data);
              }
            } catch {}
          }
        }
      }
    } catch (err: any) {
      if (callbacks.onError) callbacks.onError(err);
      else throw err;
    }
  },

  knowledgeSuggestions: (projectId: string) =>
    request<{ suggestions: string[] }>(`/projects/${projectId}/knowledge/suggestions`),

  mcpTools: () => request<import("./types").MCPTool[]>("/mcp/tools"),
  mcpRpc: (method: string, params: Record<string, any> = {}) =>
    post<{ jsonrpc: string; id?: string | number; result?: any; error?: any }>("/mcp/rpc", {
      jsonrpc: "2.0",
      id: String(Date.now()),
      method,
      params,
    }),

  // AI-Powered Change Intelligence Platform API
  constructionPlan: (
    projectId: string,
    payload: {
      site_id: string;
      it_load_mw: number;
      redundancy: "N" | "N+1" | "2N";
      target_pue: number;
      utilization_pct: number;
      annual_operating_hours: number;
      electricity_rate_usd_kwh: number;
      cooling_strategy: "water_cooled" | "hybrid_economizer";
      voltage_v: number;
      budget_usd?: number | null;
      contingency_pct: number;
      requirements_note?: string | null;
    },
  ) =>
    post<import("./types").ConstructionPlanResponse>(
      `/projects/${projectId}/construction-plan`,
      payload,
    ),

  parseRequirements: (projectId: string, prompt: string, equipmentType?: string) =>
    post<import("./types").StructuredRequirementSet>(`/projects/${projectId}/requirements/parse`, {
      prompt,
      equipment_type: equipmentType,
    }),

  searchRecommendations: (
    projectId: string,
    payload: {
      equipment_type: string;
      constraints?: any[];
      weights?: Record<string, number>;
      site_id?: string | null;
    },
  ) =>
    post<import("./types").ProductRecommendationResult>(`/projects/${projectId}/recommendations/search`, payload),

  applyRecommendation: (
    projectId: string,
    payload: {
      equipment_tag: string;
      candidate_product_id: string;
      title?: string;
      reason?: string;
      site_id?: string | null;
      existing_change_id?: string | null;
    },
  ) =>
    post<import("./types").Investigation>(`/projects/${projectId}/recommendations/apply-change`, payload),

  catalogModels: (equipmentType?: string) =>
    request<import("./types").ReferenceSpec[]>(
      equipmentType ? `/catalog/models?equipment_type=${encodeURIComponent(equipmentType)}` : "/catalog/models",
    ),

  changeMargins: (projectId: string, changeId: string) =>
    request<import("./types").DesignMargin[]>(`/projects/${projectId}/changes/${changeId}/margins`),

  changeLineage: (projectId: string, changeId: string) =>
    request<import("./types").DecisionLineageRecord[]>(`/projects/${projectId}/changes/${changeId}/lineage`),

  changeCostSchedule: (projectId: string, changeId: string) =>
    request<import("./types").CostScheduleImpact>(`/projects/${projectId}/changes/${changeId}/cost-schedule`),

  cascadeAnalysis: (projectId: string, changeIds?: string[]) =>
    post<import("./types").CascadeImpactSummary>(`/projects/${projectId}/cascade-analysis`, {
      change_ids: changeIds,
    }),

  generateActionPackage: (
    projectId: string,
    payload: {
      change_id: string;
      action_type: string;
      recipient?: string;
      notes?: string;
    },
  ) =>
    post<import("./types").ActionPackageResponse>(`/projects/${projectId}/actions/generate`, payload),
};

