import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Database,
  ExternalLink,
  FileCheck,
  FileCode,
  FileText,
  FileUp,
  Globe,
  HardHat,
  Layers,
  Lightbulb,
  Loader2,
  MapPin,
  RefreshCw,
  Send,
  Server,
  ShieldAlert,
  Sparkles,
  Terminal,
  User,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge, Button, Card, Spinner, cx, inputClass } from "../components/ui";
import { api } from "../lib/api";
import type {
  Citation,
  MCPTool,
  ProjectDetail,
  ProjectDocument,
  RetrievedChunk,
  TellMeInsights,
  ToolExecutionTrace,
} from "../lib/types";

interface AgentMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  toolTraces?: ToolExecutionTrace[];
  tellMe?: TellMeInsights;
  citations?: Citation[];
  mode?: string;
  siteName?: string;
  timestamp: string;
}

export function ProjectKnowledgeAgent({
  detail,
  onProjectChanged,
}: {
  detail: ProjectDetail;
  onProjectChanged: () => void;
}) {
  const locatedSites = detail.sites.filter((s) => s.latitude !== null && s.longitude !== null);
  const [selectedSiteId, setSelectedSiteId] = useState<string>(locatedSites[0]?.id ?? detail.sites[0]?.id ?? "");

  // Tool Toggles
  const [enabledTools, setEnabledTools] = useState<{
    documents: boolean;
    web: boolean;
    mireye: boolean;
    project: boolean;
  }>({
    documents: true,
    web: true,
    mireye: true,
    project: true,
  });

  // Query & Chat State
  const [inputQuery, setInputQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [activeTraces, setActiveTraces] = useState<ToolExecutionTrace[]>([]);
  const [liveTokenText, setLiveTokenText] = useState("");

  // Suggestions
  const [suggestions, setSuggestions] = useState<string[]>([]);

  // MCP Tools Modal
  const [mcpModalOpen, setMcpModalOpen] = useState(false);
  const [mcpToolsList, setMcpToolsList] = useState<MCPTool[]>([]);
  const [mcpLoading, setMcpLoading] = useState(false);

  // Document Management & Inspection
  const [docKind, setDocKind] = useState("specification");
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [inspectDoc, setInspectDoc] = useState<ProjectDocument | null>(null);
  const [docChunks, setDocChunks] = useState<RetrievedChunk[]>([]);
  const [loadingChunks, setLoadingChunks] = useState(false);

  // Conversation history
  const [messages, setMessages] = useState<AgentMessage[]>([
    {
      id: "welcome-1",
      role: "agent",
      content: `**Welcome to Project Knowledge Autonomous Research Agent.**\n\nI am equipped with multi-modal research tools to investigate your engineering submittals, external engineering codes, and real-time physical telemetry:\n\n* **📁 Ingested Documents:** Hybrid ChromaDB vector & BM25 lexical search across uploaded specifications and drawings.\n* **🌐 Web & Technical Standards:** Real-time lookup for ASHRAE TC 9.9, ASCE 7-22, IEEE 1584, NFPA, and FEMA flood standards.\n* **🛰️ Mireye API & MCP:** Live physical site telemetry (elevation, slope, seismic PGA, flood zone BFE, water stress, grid proximity).\n* **📊 Project DB Inspector:** In-depth review of candidate sites, stored physical evidence, and open gaps.`,
      tellMe: {
        key_findings: [
          "Multi-tool RAG and MCP server are active and connected.",
          "ChromaDB and BM25 indexing ready for uploaded specifications.",
        ],
        risks_identified: [
          "Verify unconfirmed OCR submittal data against manufacturer cut sheets.",
          "Ensure finished floor elevations comply with FEMA 500-yr BFE + 3ft.",
        ],
        standards_compliance: [
          "ASHRAE TC 9.9 2023: Mission-critical thermal envelope guidelines.",
          "ASCE 7-22 Chapter 13 & 15: Risk Category IV seismic anchorage.",
        ],
        actionable_mitigations: [
          "Drop a PDF specification to index searchable chunks with page citations.",
          "Run an engineering inquiry below to execute autonomous tool reasoning.",
        ],
      },
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  const chatEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, liveTokenText, activeTraces]);

  // Load suggestions
  useEffect(() => {
    async function loadSuggestions() {
      try {
        const res = await api.knowledgeSuggestions(detail.project.id);
        if (res.suggestions) setSuggestions(res.suggestions);
      } catch {
        // Fallback default suggestions
        setSuggestions([
          "Analyze chiller cooling capacity against site wet-bulb temperatures.",
          "Verify seismic anchorage specs for Cascadia site against ASCE 7-22.",
          "Check FEMA base flood elevation and finished floor height requirements.",
          "Search ASHRAE TC 9.9 thermal operating envelope guidelines for Class A1.",
        ]);
      }
    }
    void loadSuggestions();
  }, [detail.project.id]);

  // Load MCP Tools
  async function openMcpModal() {
    setMcpModalOpen(true);
    setMcpLoading(true);
    try {
      const tools = await api.mcpTools();
      setMcpToolsList(tools);
    } catch {
      setMcpToolsList([]);
    } finally {
      setMcpLoading(false);
    }
  }

  // Load chunks when inspecting document
  async function handleInspectDoc(doc: ProjectDocument) {
    setInspectDoc(doc);
    setLoadingChunks(true);
    try {
      const res = await fetch(`/api/projects/${detail.project.id}/documents/${doc.id}/chunks`);
      if (res.ok) {
        const data = await res.json();
        setDocChunks(data);
      }
    } catch {
      setDocChunks([]);
    } finally {
      setLoadingChunks(false);
    }
  }

  // Upload handler
  async function handleUpload(file: File) {
    setUploading(true);
    setUploadMessage(null);
    try {
      const result = await api.uploadDocument(detail.project.id, file, docKind);
      setUploadMessage({
        type: "success",
        text: `Successfully ingested "${result.document.filename}": ${result.document.page_count} page(s), ${result.chunk_count} chunk(s) indexed in ChromaDB + BM25.${
          result.warning ? ` (Note: ${result.warning})` : ""
        }`,
      });
      onProjectChanged();
    } catch (err: any) {
      setUploadMessage({
        type: "error",
        text: err?.message || "Document upload failed.",
      });
    } finally {
      setUploading(false);
    }
  }

  // Send query to Knowledge Agent
  async function handleSend(queryText?: string) {
    const text = (queryText ?? inputQuery).trim();
    if (!text || isStreaming) return;

    setInputQuery("");
    setStreamError(null);
    setIsStreaming(true);
    setActiveTraces([]);
    setLiveTokenText("");

    const stamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const userMsgId = `user-${Date.now()}`;

    // Add user message
    const userMsg: AgentMessage = {
      id: userMsgId,
      role: "user",
      content: text,
      timestamp: stamp,
    };
    setMessages((prev) => [...prev, userMsg]);

    const toolList = Object.entries(enabledTools)
      .filter(([_, enabled]) => enabled)
      .map(([tool]) => tool);

    let incomingTokens = "";
    let incomingTellMe: TellMeInsights | undefined;
    let incomingCitations: Citation[] = [];
    const collectedTraces: ToolExecutionTrace[] = [];

    const historyPayload = messages.slice(-4).map((m) => ({
      role: m.role === "user" ? "user" : "assistant",
      content: m.content,
    }));

    try {
      await api.knowledgeAgentStream(
        detail.project.id,
        {
          message: text,
          site_id: selectedSiteId || undefined,
          enabled_tools: toolList,
          history: historyPayload,
        },
        {
          onToolStart: (tool) => {
            setActiveTraces((prev) => [
              ...prev,
              {
                tool: tool.tool,
                title: tool.title,
                input_params: tool.input || {},
                output_summary: "Running tool...",
                duration_ms: 0,
                ok: true,
              },
            ]);
          },
          onToolFinish: (finish) => {
            setActiveTraces((prev) =>
              prev.map((t) =>
                t.tool === finish.tool
                  ? { ...t, output_summary: finish.output_summary, duration_ms: finish.duration_ms }
                  : t,
              ),
            );
            collectedTraces.push({
              tool: finish.tool,
              title: finish.tool.replace(/_/g, " "),
              input_params: {},
              output_summary: finish.output_summary,
              duration_ms: finish.duration_ms,
              ok: true,
            });
          },
          onToken: (tok) => {
            incomingTokens += tok;
            setLiveTokenText(incomingTokens);
          },
          onTellMe: (tellMe) => {
            incomingTellMe = tellMe;
          },
          onCitations: (cites) => {
            incomingCitations = cites;
          },
          onDone: (done) => {
            const agentMsg: AgentMessage = {
              id: `agent-${Date.now()}`,
              role: "agent",
              content: incomingTokens || "Analysis complete.",
              tellMe: incomingTellMe,
              citations: incomingCitations,
              toolTraces: done.traces && done.traces.length > 0 ? done.traces : collectedTraces,
              siteName: done.site_name,
              mode: done.mode,
              timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            };
            setMessages((prev) => [...prev, agentMsg]);
            setLiveTokenText("");
            setActiveTraces([]);
          },
          onError: (err) => {
            setStreamError(err.message || "Knowledge agent execution error.");
          },
        },
      );
    } catch (err: any) {
      setStreamError(err?.message || "Failed to communicate with Knowledge Agent.");
    } finally {
      setIsStreaming(false);
    }
  }

  const activeSite = detail.sites.find((s) => s.id === selectedSiteId);

  return (
    <div className="space-y-4">
      {/* Top Banner: Agent Control Center */}
      <div className="rounded-xl border border-ink-800 bg-gradient-to-r from-ink-950 via-ink-900 to-ink-950 p-4 text-white shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/20 text-amber-400 ring-1 ring-amber-500/40">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold tracking-tight text-white">
                  Project Knowledge &amp; Research Agent
                </h1>
                <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-mono font-medium text-emerald-300 border border-emerald-500/30 flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  ChromaDB + BM25
                </span>
              </div>
              <p className="text-xs text-ink-300">
                Autonomous multi-tool intelligence across project documents, live web standards, and Mireye MCP telemetry.
              </p>
            </div>
          </div>

          {/* Right Controls: Site Selector & MCP Pill */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-900/80 px-2.5 py-1 text-xs">
              <MapPin className="h-3.5 w-3.5 text-amber-400" />
              <label htmlFor="site-select" className="text-ink-400">
                Site:
              </label>
              <select
                id="site-select"
                value={selectedSiteId}
                onChange={(e) => setSelectedSiteId(e.target.value)}
                className="bg-transparent font-medium text-white focus:outline-none cursor-pointer"
              >
                {detail.sites.map((s) => (
                  <option key={s.id} value={s.id} className="bg-ink-900 text-white">
                    {s.name} {s.latitude ? `(${s.latitude.toFixed(2)}, ${s.longitude?.toFixed(2)})` : "(no coords)"}
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={openMcpModal}
              className="flex items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-xs font-medium text-sky-300 hover:bg-sky-500/20 transition cursor-pointer"
              title="Inspect Model Context Protocol (MCP) server tools"
            >
              <Server className="h-3.5 w-3.5 text-sky-400" />
              <span>MCP: Mireye Connected</span>
              <span className="rounded bg-sky-500/20 px-1 text-[10px] font-mono">6 tools</span>
            </button>
          </div>
        </div>

        {/* Tool Toggles Bar */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-800/80 pt-3 text-xs">
          <span className="text-ink-400 font-medium flex items-center gap-1">
            <Wrench className="h-3.5 w-3.5 text-ink-500" /> Active Tools:
          </span>

          <label className={cx(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-md border cursor-pointer transition select-none",
            enabledTools.documents ? "bg-amber-500/15 border-amber-500/40 text-amber-200" : "bg-ink-900 border-ink-700 text-ink-500"
          )}>
            <input
              type="checkbox"
              checked={enabledTools.documents}
              onChange={(e) => setEnabledTools((p) => ({ ...p, documents: e.target.checked }))}
              className="sr-only"
            />
            <FileText className="h-3.5 w-3.5" />
            <span>ChromaDB Docs ({detail.documents.length})</span>
          </label>

          <label className={cx(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-md border cursor-pointer transition select-none",
            enabledTools.web ? "bg-sky-500/15 border-sky-500/40 text-sky-200" : "bg-ink-900 border-ink-700 text-ink-500"
          )}>
            <input
              type="checkbox"
              checked={enabledTools.web}
              onChange={(e) => setEnabledTools((p) => ({ ...p, web: e.target.checked }))}
              className="sr-only"
            />
            <Globe className="h-3.5 w-3.5" />
            <span>Web Standards (ASHRAE/ASCE)</span>
          </label>

          <label className={cx(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-md border cursor-pointer transition select-none",
            enabledTools.mireye ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-200" : "bg-ink-900 border-ink-700 text-ink-500"
          )}>
            <input
              type="checkbox"
              checked={enabledTools.mireye}
              onChange={(e) => setEnabledTools((p) => ({ ...p, mireye: e.target.checked }))}
              className="sr-only"
            />
            <Zap className="h-3.5 w-3.5" />
            <span>Mireye MCP Telemetry</span>
          </label>

          <label className={cx(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-md border cursor-pointer transition select-none",
            enabledTools.project ? "bg-purple-500/15 border-purple-500/40 text-purple-200" : "bg-ink-900 border-ink-700 text-ink-500"
          )}>
            <input
              type="checkbox"
              checked={enabledTools.project}
              onChange={(e) => setEnabledTools((p) => ({ ...p, project: e.target.checked }))}
              className="sr-only"
            />
            <Database className="h-3.5 w-3.5" />
            <span>Project DB Inspector</span>
          </label>
        </div>
      </div>

      {/* Main Grid: Document Hub + Agent Chat Workspace */}
      <div className="grid gap-4 lg:grid-cols-12">
        {/* Left Column (4 cols): Ingested Documents Hub */}
        <div className="lg:col-span-4 space-y-4">
          <Card
            title="Ingested Project Documents"
            subtitle="Extracted PDF submittals, specifications & drawings indexed into ChromaDB"
          >
            {/* Drag & Drop Upload Zone */}
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const file = e.dataTransfer.files?.[0];
                if (file) void handleUpload(file);
              }}
              className={cx(
                "rounded-lg border-2 border-dashed p-3 text-xs transition",
                dragging ? "border-amber-500 bg-amber-50" : "border-ink-200 bg-ink-50/50",
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <FileUp aria-hidden className="h-4 w-4 text-ink-500" />
                <span className="text-ink-600 font-medium">Drop a PDF here, or</span>
                <label className="cursor-pointer rounded border border-ink-300 bg-white px-2 py-1 font-medium text-ink-900 hover:bg-ink-100 shadow-sm">
                  choose file
                  <input
                    type="file"
                    accept="application/pdf,.pdf"
                    className="sr-only"
                    disabled={uploading}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void handleUpload(file);
                      e.target.value = "";
                    }}
                  />
                </label>
                <select
                  value={docKind}
                  onChange={(e) => setDocKind(e.target.value)}
                  className={cx(inputClass, "w-auto py-1 text-xs")}
                >
                  <option value="specification">specification</option>
                  <option value="submittal">submittal</option>
                  <option value="datasheet">datasheet</option>
                  <option value="drawing">drawing</option>
                  <option value="report">report</option>
                  <option value="other">other</option>
                </select>
                {uploading && <Spinner label="Extracting & Vectorizing…" />}
              </div>

              <p className="mt-1.5 text-[11px] text-ink-500">
                PDF text is extracted, chunked, and indexed with embeddings in ChromaDB + BM25.
                Pages without digital text layers are processed via Tesseract OCR.
              </p>

              {uploadMessage && (
                <div
                  className={cx(
                    "mt-2 rounded-lg border p-2 text-[11px]",
                    uploadMessage.type === "success"
                      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                      : "border-rose-200 bg-rose-50 text-rose-900",
                  )}
                >
                  {uploadMessage.text}
                </div>
              )}
            </div>

            {/* Document Catalog */}
            <div className="mt-3">
              <div className="flex items-center justify-between pb-1 text-xs font-semibold text-ink-700 border-b border-ink-100">
                <span>Ingested Catalog ({detail.documents.length})</span>
                <span className="text-[11px] text-ink-500 font-normal">ChromaDB + SQLite</span>
              </div>

              {detail.documents.length === 0 ? (
                <p className="mt-3 text-xs text-ink-500 text-center py-4">
                  No documents ingested yet. Upload a submittal or specification PDF above.
                </p>
              ) : (
                <ul className="mt-2 divide-y divide-ink-100 max-h-[420px] overflow-y-auto pr-1">
                  {detail.documents.map((doc) => (
                    <li key={doc.id} className="py-2.5 hover:bg-ink-50/60 rounded px-1.5 transition">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="font-semibold text-xs text-ink-900 truncate" title={doc.filename}>
                            {doc.filename}
                          </p>
                          <p className="text-[11px] text-ink-500 mt-0.5">
                            {doc.kind} · {doc.page_count} page(s) · {(doc.size_bytes / 1024).toFixed(0)} kB
                          </p>
                        </div>
                        <div className="flex flex-col items-end gap-1">
                          <div className="flex gap-1">
                            {doc.synthetic ? (
                              <Badge className="border-amber-300 bg-amber-50 text-amber-800 text-[10px]">
                                demo
                              </Badge>
                            ) : (
                              <Badge className="border-sky-300 bg-sky-50 text-sky-800 text-[10px]">
                                upload
                              </Badge>
                            )}
                            <Badge
                              className={cx(
                                "text-[10px]",
                                doc.extraction_status === "extracted"
                                  ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                                  : "border-rose-300 bg-rose-50 text-rose-800",
                              )}
                            >
                              {doc.extraction_status}
                            </Badge>
                          </div>
                          {doc.ocr_pages && doc.ocr_pages.length > 0 && (
                            <Badge className="border-violet-300 bg-violet-50 text-violet-800 text-[10px]">
                              OCR ×{doc.ocr_pages.length}
                            </Badge>
                          )}
                        </div>
                      </div>

                      <div className="mt-2 flex items-center justify-between">
                        <button
                          onClick={() => handleInspectDoc(doc)}
                          className="text-[11px] font-medium text-signal-600 hover:text-signal-800 flex items-center gap-1 cursor-pointer"
                        >
                          <Layers className="h-3 w-3" /> Inspect chunks
                        </button>
                        <span className="text-[10px] text-ink-400 font-mono">
                          {new Date(doc.uploaded_at).toLocaleDateString()}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Card>

          {/* Inspect Chunk Drawer if Selected */}
          {inspectDoc && (
            <Card
              title={
                <div className="flex items-center justify-between">
                  <span className="truncate text-xs">Chunks: {inspectDoc.filename}</span>
                  <button
                    onClick={() => setInspectDoc(null)}
                    className="text-ink-400 hover:text-ink-700"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              }
              subtitle={`${docChunks.length} searchable chunk(s) indexed in ChromaDB`}
            >
              {loadingChunks ? (
                <div className="py-4 text-center">
                  <Spinner label="Loading chunks..." />
                </div>
              ) : (
                <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
                  {docChunks.map((chunk, idx) => (
                    <div key={chunk.chunk_id || idx} className="rounded border border-ink-200 bg-ink-50/40 p-2 text-xs">
                      <div className="flex items-center justify-between text-[11px] text-ink-500 font-mono mb-1">
                        <span>Page {chunk.page}</span>
                        {chunk.ocr && (
                          <span className="bg-violet-100 text-violet-800 px-1 rounded text-[10px]">OCR</span>
                        )}
                      </div>
                      <p className="text-ink-800 line-clamp-3 font-mono text-[11px] leading-relaxed">
                        {chunk.text}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}
        </div>

        {/* Right Column (8 cols): Interactive Knowledge Agent Chat Workspace */}
        <div className="lg:col-span-8 flex flex-col h-[760px] rounded-xl border border-ink-200 bg-white shadow-sm overflow-hidden">
          {/* Workspace Header */}
          <div className="border-b border-ink-100 bg-ink-50/70 px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-500 text-white shadow-sm">
                <Bot className="h-4 w-4" />
              </div>
              <div>
                <h3 className="text-xs font-bold text-ink-900">
                  Autonomous EPC Research Console
                </h3>
                <p className="text-[11px] text-ink-500">
                  Target Site: <span className="font-semibold text-ink-700">{activeSite?.name || detail.project.name}</span>
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() =>
                  setMessages([
                    {
                      id: "welcome-reset",
                      role: "agent",
                      content: "Session reset. Ready for a new engineering investigation.",
                      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                    },
                  ])
                }
                className="rounded border border-ink-200 bg-white px-2 py-1 text-[11px] font-medium text-ink-600 hover:bg-ink-100 flex items-center gap-1 shadow-sm cursor-pointer"
                title="Clear conversation"
              >
                <RefreshCw className="h-3 w-3" /> Clear
              </button>
            </div>
          </div>

          {/* Quick Prompt Chips */}
          {suggestions.length > 0 && (
            <div className="border-b border-ink-100 bg-amber-50/30 px-3 py-2 flex items-center gap-1.5 overflow-x-auto text-[11px]">
              <Sparkles className="h-3.5 w-3.5 text-amber-600 flex-shrink-0" />
              <span className="text-ink-500 font-medium flex-shrink-0">Suggested inquiries:</span>
              {suggestions.slice(0, 3).map((sugg, i) => (
                <button
                  key={i}
                  onClick={() => handleSend(sugg)}
                  className="rounded-full border border-amber-300/80 bg-white px-2.5 py-0.5 text-ink-800 hover:border-amber-500 hover:bg-amber-100/50 whitespace-nowrap transition cursor-pointer flex-shrink-0 text-[11px]"
                >
                  {sugg.length > 55 ? `${sugg.slice(0, 55)}…` : sugg}
                </button>
              ))}
            </div>
          )}

          {/* Messages Scroll Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cx("flex flex-col gap-1.5", msg.role === "user" ? "items-end" : "items-start")}
              >
                <div className="flex items-center gap-1.5 text-[11px] text-ink-400">
                  {msg.role === "user" ? (
                    <>
                      <span>You</span>
                      <User className="h-3 w-3" />
                      <span>·</span>
                      <span>{msg.timestamp}</span>
                    </>
                  ) : (
                    <>
                      <Bot className="h-3 w-3 text-amber-600" />
                      <span className="font-semibold text-ink-700">Senior Civil &amp; EPC AI Agent</span>
                      <span>·</span>
                      <span>{msg.timestamp}</span>
                      {msg.mode && (
                        <span className="rounded bg-ink-100 px-1 text-[10px] font-mono text-ink-600">
                          {msg.mode}
                        </span>
                      )}
                    </>
                  )}
                </div>

                <div
                  className={cx(
                    "rounded-xl p-3.5 max-w-[92%] text-xs leading-relaxed shadow-sm",
                    msg.role === "user"
                      ? "bg-ink-900 text-white rounded-br-none"
                      : "bg-ink-50/90 text-ink-900 border border-ink-200 rounded-bl-none",
                  )}
                >
                  {/* Tool Execution Traces for Agent Messages */}
                  {msg.toolTraces && msg.toolTraces.length > 0 && (
                    <div className="mb-3 rounded-lg border border-ink-200 bg-white p-2.5 space-y-2">
                      <div className="flex items-center gap-1.5 text-[11px] font-bold text-ink-700 border-b border-ink-100 pb-1">
                        <Terminal className="h-3.5 w-3.5 text-amber-600" />
                        <span>Agent Execution Steps ({msg.toolTraces.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {msg.toolTraces.map((t, idx) => (
                          <div key={idx} className="rounded bg-ink-50 px-2 py-1.5 text-[11px] border border-ink-200/60">
                            <div className="flex items-center justify-between font-semibold text-ink-800">
                              <span className="flex items-center gap-1">
                                {t.tool.includes("doc") ? (
                                  <FileText className="h-3 w-3 text-amber-600" />
                                ) : t.tool.includes("web") ? (
                                  <Globe className="h-3 w-3 text-sky-600" />
                                ) : t.tool.includes("mireye") ? (
                                  <Zap className="h-3 w-3 text-emerald-600" />
                                ) : (
                                  <Database className="h-3 w-3 text-purple-600" />
                                )}
                                {t.title}
                              </span>
                              <span className="font-mono text-[10px] text-ink-500">
                                {t.duration_ms} ms
                              </span>
                            </div>
                            <p className="mt-0.5 text-ink-600 text-[10px] font-mono">
                              {t.output_summary}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Message Body Content */}
                  <div className="whitespace-pre-wrap leading-relaxed space-y-2">
                    {msg.content}
                  </div>

                  {/* Dedicated "Tell Me / Deep Insights" Card */}
                  {msg.tellMe && (
                    <div className="mt-4 rounded-xl border-2 border-amber-300 bg-gradient-to-br from-amber-50/80 via-white to-amber-50/40 p-3.5 shadow-sm text-ink-900">
                      <div className="flex items-center gap-2 border-b border-amber-200 pb-2 mb-2.5">
                        <div className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-white">
                          <Lightbulb className="h-3.5 w-3.5" />
                        </div>
                        <h4 className="text-xs font-bold text-amber-950 uppercase tracking-wider">
                          Tell Me: Key Engineering Insights &amp; Recommendations
                        </h4>
                      </div>

                      <div className="grid gap-3 sm:grid-cols-2">
                        {/* Key Findings */}
                        <div className="space-y-1">
                          <h5 className="text-[11px] font-bold text-ink-800 flex items-center gap-1">
                            <CheckCircle2 className="h-3 w-3 text-emerald-600" /> Key Takeaways
                          </h5>
                          <ul className="list-disc list-inside space-y-0.5 text-[11px] text-ink-700 pl-1">
                            {msg.tellMe.key_findings.map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>

                        {/* Identified Risks */}
                        <div className="space-y-1">
                          <h5 className="text-[11px] font-bold text-ink-800 flex items-center gap-1">
                            <ShieldAlert className="h-3 w-3 text-rose-600" /> Identified Risks
                          </h5>
                          <ul className="list-disc list-inside space-y-0.5 text-[11px] text-ink-700 pl-1">
                            {msg.tellMe.risks_identified.map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>

                        {/* Standards Compliance */}
                        <div className="space-y-1">
                          <h5 className="text-[11px] font-bold text-ink-800 flex items-center gap-1">
                            <FileCheck className="h-3 w-3 text-sky-600" /> Standards Compliance
                          </h5>
                          <ul className="list-disc list-inside space-y-0.5 text-[11px] text-ink-700 pl-1">
                            {msg.tellMe.standards_compliance.map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>

                        {/* Actionable Mitigations */}
                        <div className="space-y-1">
                          <h5 className="text-[11px] font-bold text-ink-800 flex items-center gap-1">
                            <HardHat className="h-3 w-3 text-amber-600" /> Actionable Mitigations
                          </h5>
                          <ul className="list-disc list-inside space-y-0.5 text-[11px] text-ink-700 pl-1">
                            {msg.tellMe.actionable_mitigations.map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Citations Drawer / Bar */}
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="mt-3 border-t border-ink-200 pt-2">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-ink-500 mb-1.5 flex items-center gap-1">
                        <FileCode className="h-3 w-3 text-ink-400" /> Verified Evidence Citations ({msg.citations.length})
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {msg.citations.map((c, i) => (
                          <span
                            key={i}
                            className={cx(
                              "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium border shadow-2xs",
                              c.source_type === "document"
                                ? "bg-amber-50 border-amber-200 text-amber-900"
                                : c.source_type === "web"
                                ? "bg-sky-50 border-sky-200 text-sky-900"
                                : "bg-emerald-50 border-emerald-200 text-emerald-900"
                            )}
                          >
                            {c.source_type === "document" ? (
                              <FileText className="h-3 w-3 text-amber-600" />
                            ) : c.source_type === "web" ? (
                              <Globe className="h-3 w-3 text-sky-600" />
                            ) : (
                              <Zap className="h-3 w-3 text-emerald-600" />
                            )}
                            <span className="font-semibold">{c.title}</span>
                            <span>·</span>
                            <span>{c.detail}</span>
                            {c.url && (
                              <a
                                href={c.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-sky-600 hover:text-sky-800"
                              >
                                <ExternalLink className="h-2.5 w-2.5" />
                              </a>
                            )}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* Live Streaming State with Active Tool Execution Traces */}
            {isStreaming && (
              <div className="flex flex-col items-start gap-1.5">
                <div className="flex items-center gap-1.5 text-[11px] text-ink-400">
                  <Bot className="h-3 w-3 text-amber-600 animate-spin" />
                  <span className="font-semibold text-ink-700">Senior Civil &amp; EPC AI Agent</span>
                  <span>·</span>
                  <span>thinking and executing tools…</span>
                </div>

                <div className="rounded-xl rounded-bl-none border border-amber-200 bg-amber-50/40 p-3.5 max-w-[92%] text-xs shadow-sm space-y-3 w-full">
                  {/* Live Active Tool Traces */}
                  {activeTraces.length > 0 && (
                    <div className="rounded-lg border border-amber-200 bg-white p-2.5 space-y-2">
                      <div className="flex items-center gap-1.5 text-[11px] font-bold text-amber-900 border-b border-amber-100 pb-1">
                        <Terminal className="h-3.5 w-3.5 text-amber-600" />
                        <span>Live Tool Execution Steps</span>
                      </div>
                      <div className="space-y-1.5">
                        {activeTraces.map((t, idx) => (
                          <div key={idx} className="rounded bg-amber-50/60 px-2 py-1.5 text-[11px] border border-amber-200/60 flex items-center justify-between">
                            <span className="flex items-center gap-1.5 font-medium text-ink-800">
                              <Loader2 className="h-3 w-3 text-amber-600 animate-spin" />
                              {t.title}
                            </span>
                            <span className="text-[10px] text-amber-800 font-mono">
                              {t.output_summary}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Live Token Streaming Output */}
                  {liveTokenText ? (
                    <div className="whitespace-pre-wrap leading-relaxed text-ink-900">
                      {liveTokenText}
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-xs text-ink-600 py-1">
                      <Spinner label="Executing tools across ChromaDB, Web Standards, and Mireye MCP..." />
                    </div>
                  )}
                </div>
              </div>
            )}

            {streamError && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-rose-600 flex-shrink-0" />
                <span>{streamError}</span>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Query Input Box */}
          <div className="border-t border-ink-100 bg-white p-3">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void handleSend();
              }}
              className="flex gap-2"
            >
              <div className="relative flex-1">
                <input
                  type="text"
                  value={inputQuery}
                  onChange={(e) => setInputQuery(e.target.value)}
                  placeholder="Ask the Knowledge Agent (e.g. 'Analyze chiller specs against site wet-bulb and ASCE 7-22 seismic requirements')..."
                  disabled={isStreaming}
                  className={cx(
                    inputClass,
                    "pr-10 py-2.5 text-xs shadow-xs focus:ring-amber-500 focus:border-amber-500",
                  )}
                />
              </div>

              <Button
                type="submit"
                variant="primary"
                loading={isStreaming}
                disabled={!inputQuery.trim()}
                className="bg-ink-900 hover:bg-amber-600 text-white font-medium px-4 text-xs shadow-sm transition"
              >
                <Send className="h-3.5 w-3.5 mr-1" />
                <span>Investigate</span>
              </Button>
            </form>
          </div>
        </div>
      </div>

      {/* Model Context Protocol (MCP) Tools Modal */}
      {mcpModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
          <div className="w-full max-w-2xl rounded-xl border border-ink-700 bg-ink-900 text-white shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between border-b border-ink-800 px-5 py-3.5 bg-ink-950">
              <div className="flex items-center gap-2">
                <Server className="h-4 w-4 text-sky-400" />
                <h3 className="text-sm font-bold text-white">
                  Model Context Protocol (MCP) Server Tools
                </h3>
              </div>
              <button
                onClick={() => setMcpModalOpen(false)}
                className="text-ink-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto text-xs">
              <p className="text-ink-300">
                The platform exposes an MCP server compliant with standard Model Context Protocol specifications (`/api/mcp/tools` &amp; `/api/mcp/rpc`).
              </p>

              {mcpLoading ? (
                <div className="py-8 text-center">
                  <Spinner label="Querying MCP tool schema..." />
                </div>
              ) : (
                <div className="space-y-3">
                  {mcpToolsList.map((tool) => (
                    <div
                      key={tool.name}
                      className="rounded-lg border border-ink-800 bg-ink-950/70 p-3 space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono font-bold text-amber-400 text-xs">
                          {tool.name}
                        </span>
                        <span className="rounded bg-sky-500/20 text-sky-300 px-1.5 py-0.5 text-[10px] font-mono">
                          MCP tool
                        </span>
                      </div>
                      <p className="text-ink-300 text-[11px] leading-relaxed">
                        {tool.description}
                      </p>
                      {tool.inputSchema && (
                        <div className="mt-1 rounded bg-ink-900/90 p-2 font-mono text-[10px] text-ink-400 overflow-x-auto">
                          Required: {JSON.stringify(tool.inputSchema.required || [])}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="border-t border-ink-800 bg-ink-950 px-5 py-3 flex justify-end">
              <Button onClick={() => setMcpModalOpen(false)}>Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
