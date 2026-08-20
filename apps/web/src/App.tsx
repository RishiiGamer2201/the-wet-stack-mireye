import {
  ArrowLeft,
  ArrowRight,
  Building2,
  CheckCircle2,
  HardHat,
  Layers,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  User,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { HeroPage } from "./components/HeroPage";
import { ProjectCreatePage } from "./components/ProjectCreatePage";
import { Badge, Button, Card, ErrorState, Spinner, Tabs, cx, inputClass } from "./components/ui";
import { BeforeConstruction } from "./features/BeforeConstruction";
import { DuringConstruction } from "./features/DuringConstruction";
import { api } from "./lib/api";
import type { Meta, Project, ProjectDetail, SearchResponse } from "./lib/types";

export type ViewMode = "hero" | "setup" | "portal" | "before" | "during" | "knowledge";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [personName, setPersonName] = useState<string>(() => {
    try {
      const raw = localStorage.getItem("wetstack_user_profile");
      return raw ? JSON.parse(raw).name || "" : "";
    } catch {
      return "";
    }
  });
  const [view, setView] = useState<ViewMode>("hero");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const bootstrap = useCallback(async () => {
    setError(null);
    try {
      const [metaResponse, projectList] = await Promise.all([api.meta(), api.projects()]);
      setMeta(metaResponse);
      setProjects(projectList);
      setProjectId((current) => (current && projectList.some((p) => p.id === current) ? current : projectList[0]?.id ?? null));
    } catch (e) {
      setError(e);
    }
  }, []);

  const loadProject = useCallback(async (id: string) => {
    try {
      setDetail(await api.project(id));
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (projectId) {
      loadProject(projectId);
    } else {
      setDetail(null);
    }
  }, [projectId, loadProject]);

  async function resetAllData() {
    if (!window.confirm("Are you sure you want to clear all data and start completely fresh?")) return;
    setBusy(true);
    try {
      await api.reset();
      await bootstrap();
      setProjectId(null);
      setDetail(null);
      setView("hero");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function seedDemoData() {
    setBusy(true);
    try {
      const result = await api.seed();
      await bootstrap();
      setProjectId(result.project_id);
      await loadProject(result.project_id);
      setPersonName("Demo Lead Engineer");
      setView("portal");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function handleSelectWorkflow(target: "before" | "during" | "knowledge") {
    setView(target);
  }

  return (
    <div className="min-h-screen flex flex-col bg-ink-50">
      {/* ─── PAGE 1: HERO OVERVIEW PAGE ─── */}
      {view === "hero" && (
        <HeroPage onStart={() => setView("setup")} />
      )}

      {/* ─── PAGE 2: PROJECT CREATION & LOGIN PAGE ─── */}
      {view === "setup" && (
        <ProjectCreatePage
          projects={projects}
          onBack={() => setView("hero")}
          onProjectCreated={async (newProject, creatorName) => {
            setPersonName(creatorName);
            await bootstrap();
            setProjectId(newProject.id);
            await loadProject(newProject.id);
            setView("portal");
          }}
          onSelectProject={async (selectedId) => {
            setProjectId(selectedId);
            await loadProject(selectedId);
            setView("portal");
          }}
          onSeedDemo={seedDemoData}
          busy={busy}
        />
      )}

      {/* ─── PAGE 3: WORKFLOW HUB & BEFORE/AFTER CONSTRUCTION PAGES ─── */}
      {view !== "hero" && view !== "setup" && (
        <div className="flex-1 flex flex-col">
          {/* Clean Modern In-Page Header */}
          <header className="bg-white border-b border-ink-200 sticky top-0 z-40 shadow-xs">
            <div className="mx-auto flex max-w-[110rem] flex-wrap items-center justify-between gap-3 px-6 py-3.5">
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setView("hero")}
                  className="flex items-center gap-2 text-left hover:opacity-80 transition"
                  title="Return to Home Overview"
                >
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-signal-500/10 text-signal-600 border border-signal-500/20">
                    <Layers className="h-5 w-5" />
                  </div>
                  <div>
                    <span className="text-sm font-bold text-ink-900 tracking-tight block leading-tight">
                      The Wet Stack <span className="text-signal-600">— Mireye</span>
                    </span>
                    <span className="text-[11px] text-ink-500 block">
                      Data-Center EPC Intelligence
                    </span>
                  </div>
                </button>

                <div className="h-4 w-px bg-ink-200 hidden sm:block" />

                <button
                  onClick={() => setView("hero")}
                  className="hidden sm:inline-flex items-center gap-1 text-xs text-ink-600 hover:text-ink-900 bg-ink-100 hover:bg-ink-200 px-2.5 py-1 rounded-md transition"
                >
                  <ArrowLeft className="h-3.5 w-3.5" /> Home
                </button>

                {view !== "portal" && (
                  <button
                    onClick={() => setView("portal")}
                    className="inline-flex items-center gap-1 text-xs text-ink-600 hover:text-ink-900 bg-ink-100 hover:bg-ink-200 px-2.5 py-1 rounded-md transition font-medium"
                  >
                    <ArrowLeft className="h-3.5 w-3.5" /> All Workflows
                  </button>
                )}
              </div>

              {/* Project & User Context Controls */}
              <div className="flex items-center gap-3 flex-wrap">
                {personName && (
                  <div className="hidden md:flex items-center gap-1.5 text-xs text-ink-700 bg-ink-100/80 px-2.5 py-1 rounded-md border border-ink-200">
                    <User className="h-3.5 w-3.5 text-signal-600" />
                    <span><strong>{personName}</strong></span>
                  </div>
                )}

                {projects.length > 0 && (
                  <div className="flex items-center gap-1.5">
                    <label htmlFor="project-select-inpage" className="text-xs text-ink-500 hidden sm:inline">
                      Project:
                    </label>
                    <select
                      id="project-select-inpage"
                      className="max-w-[min(18rem,45vw)] truncate rounded-lg border border-ink-300 bg-white px-2.5 py-1.5 text-xs text-ink-900 focus:border-signal-500 focus:outline-none"
                      value={projectId ?? ""}
                      onChange={(e) => setProjectId(e.target.value)}
                    >
                      {projects.map((project) => (
                        <option key={project.id} value={project.id}>
                          {project.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {projects.length > 0 && (
                  <Button size="sm" onClick={resetAllData} loading={busy} title="Clear all data">
                    <Trash2 aria-hidden className="h-3.5 w-3.5 text-rose-500" /> Clear Data
                  </Button>
                )}
              </div>
            </div>
          </header>

          {/* Main Content Area */}
          <main className="mx-auto max-w-[110rem] w-full px-4 py-6 flex-1">
            {error ? <ErrorState error={error} onRetry={bootstrap} /> : null}
            {!meta && !error && <Spinner label="Connecting to the API…" />}

            {/* ─── Workflow Selection Portal View ─── */}
            {meta && view === "portal" && (
              <div className="flex flex-col gap-8 max-w-6xl mx-auto py-4">
                {/* Hero Banner */}
                <div className="text-center space-y-3">
                  <div className="inline-flex items-center gap-2 rounded-full border border-signal-500/30 bg-signal-500/10 px-3 py-1 text-xs font-semibold text-signal-600">
                    <Sparkles className="h-3.5 w-3.5" /> Deterministic Data-Center Engineering Platform
                  </div>
                  <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-ink-900">
                    Select Your Engineering Workflow
                  </h1>
                  <p className="text-sm sm:text-base text-ink-500 max-w-2xl mx-auto">
                    Evaluate candidate sites with deterministic multi-criteria scoring, or verify in-flight equipment substitutions with rigorous engineering gates and impact analysis.
                  </p>
                  {detail && (
                    <p className="text-xs text-ink-600 font-medium">
                      Active Project: <span className="font-semibold text-ink-900">{detail.project.name}</span> ({detail.sites.length} sites, {detail.changes.length} changes)
                    </p>
                  )}
                </div>

                {/* Two Primary Choices */}
                <div className="grid md:grid-cols-2 gap-6 items-stretch">
                  {/* Option 1: Before Construction */}
                  <div className="relative group flex flex-col justify-between rounded-2xl border-2 border-ink-200 bg-white p-7 shadow-sm hover:shadow-md hover:border-signal-500/70 transition-all">
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-sky-50 text-sky-600 border border-sky-200">
                          <Building2 className="h-6 w-6" />
                        </div>
                        <Badge className="border-sky-300 bg-sky-50 text-sky-800 font-semibold px-2 py-0.5">
                          Phase 1 · Site Selection
                        </Badge>
                      </div>

                      <div>
                        <h2 className="text-xl font-bold text-ink-900 group-hover:text-signal-600 transition-colors">
                          Before Construction
                        </h2>
                        <p className="text-xs font-medium text-ink-500 mt-0.5">
                          Site Intelligence &amp; Multi-Dimensional Feasibility
                        </p>
                      </div>

                      <p className="text-xs text-ink-600 leading-relaxed">
                        Evaluate and rank candidate data center locations across 8 physical, environmental, and infrastructure dimensions backed by 34 Mireye catalog fields.
                      </p>

                      <div className="space-y-2 pt-2 border-t border-ink-100">
                        <p className="text-[11px] font-bold uppercase tracking-wider text-ink-400">Key Capabilities</p>
                        <ul className="space-y-1.5 text-xs text-ink-700">
                          <li className="flex items-start gap-2">
                            <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 mt-0.5 shrink-0" />
                            <span><strong>8 Site Dimensions:</strong> Power, Water, Connectivity, Terrain, Soil, Climate, Hazards &amp; Permitting</span>
                          </li>
                          <li className="flex items-start gap-2">
                            <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 mt-0.5 shrink-0" />
                            <span><strong>Interactive Leaflet Map:</strong> Geospatial coordinates &amp; candidate shortlist ranking</span>
                          </li>
                          <li className="flex items-start gap-2">
                            <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 mt-0.5 shrink-0" />
                            <span><strong>What-If Simulator:</strong> Real-time weight tuning &amp; certified user overrides</span>
                          </li>
                        </ul>
                      </div>
                    </div>

                    <div className="mt-8 pt-4 border-t border-ink-100">
                      <Button
                        variant="primary"
                        size="md"
                        className="w-full justify-center text-sm py-2.5 bg-ink-900 hover:bg-signal-600 text-white font-semibold transition"
                        onClick={() => handleSelectWorkflow("before")}
                      >
                        Open Before Construction <ArrowRight className="h-4 w-4 ml-1.5" />
                      </Button>
                    </div>
                  </div>

                  {/* Option 2: During / After Construction */}
                  <div className="relative group flex flex-col justify-between rounded-2xl border-2 border-ink-200 bg-white p-7 shadow-sm hover:shadow-md hover:border-signal-500/70 transition-all">
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-amber-50 text-amber-600 border border-amber-200">
                          <HardHat className="h-6 w-6" />
                        </div>
                        <Badge className="border-amber-300 bg-amber-50 text-amber-800 font-semibold px-2 py-0.5">
                          Phase 2 · Execution &amp; EPC
                        </Badge>
                      </div>

                      <div>
                        <h2 className="text-xl font-bold text-ink-900 group-hover:text-signal-600 transition-colors">
                          During Construction
                        </h2>
                        <p className="text-xs font-medium text-ink-500 mt-0.5">
                          Change Intelligence, Verification Gates &amp; Impact Graphs
                        </p>
                      </div>

                      <p className="text-xs text-ink-600 leading-relaxed">
                        Verify equipment substitution submittals, compute deterministic physical/electrical deltas with Pint units, and trace downstream impacts across 6 engineering disciplines.
                      </p>

                      <div className="space-y-2 pt-2 border-t border-ink-100">
                        <p className="text-[11px] font-bold uppercase tracking-wider text-ink-400">Key Capabilities</p>
                        <ul className="space-y-1.5 text-xs text-ink-700">
                          <li className="flex items-start gap-2">
                            <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 mt-0.5 shrink-0" />
                            <span><strong>9 Verification Gates:</strong> Model comparability, weight basis, Pint dimensional checks</span>
                          </li>
                          <li className="flex items-start gap-2">
                            <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 mt-0.5 shrink-0" />
                            <span><strong>13 Engineering Deltas:</strong> Weight, support loads, MCA, MOCP, FLA, power input &amp; refrigerant</span>
                          </li>
                          <li className="flex items-start gap-2">
                            <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 mt-0.5 shrink-0" />
                            <span><strong>Multi-Discipline Impact Graph:</strong> Structural, Electrical, Mechanical, BMS &amp; Commissioning</span>
                          </li>
                        </ul>
                      </div>
                    </div>

                    <div className="mt-8 pt-4 border-t border-ink-100">
                      <Button
                        variant="primary"
                        size="md"
                        className="w-full justify-center text-sm py-2.5 bg-ink-900 hover:bg-signal-600 text-white font-semibold transition"
                        onClick={() => handleSelectWorkflow("during")}
                      >
                        Open During Construction <ArrowRight className="h-4 w-4 ml-1.5" />
                      </Button>
                    </div>
                  </div>
                </div>

                {/* Quick Access to Knowledge Search & Setup */}
                <div className="rounded-xl border border-ink-200 bg-ink-100/50 p-4 flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white border border-ink-200 text-ink-700">
                      <Search className="h-4 w-4" />
                    </div>
                    <div>
                      <h3 className="text-xs font-bold text-ink-900">Project Knowledge &amp; Document Ingestion</h3>
                      <p className="text-[11px] text-ink-500">Upload project PDFs, search extracted specifications with page citations, or ask Mireye.</p>
                    </div>
                  </div>
                  <Button size="sm" onClick={() => handleSelectWorkflow("knowledge")}>
                    Open Knowledge Base <ArrowRight className="h-3.5 w-3.5 ml-1" />
                  </Button>
                </div>

                {/* Quick Sample Data Seeding Card if no project exists */}
                {projects.length === 0 && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4 flex flex-wrap items-center justify-between gap-4">
                    <div>
                      <h3 className="text-xs font-bold text-amber-900">No project configured yet</h3>
                      <p className="text-[11px] text-amber-700">You can create a new project above or load sample demonstration cases to explore both workflows.</p>
                    </div>
                    <Button size="sm" variant="secondary" onClick={seedDemoData} loading={busy}>
                      <RefreshCw className="h-3.5 w-3.5 mr-1" /> Load Sample Demonstration
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* ─── Active Workflow Execution View (Before / During / Knowledge) ─── */}
            {meta && view !== "portal" && detail && (
              <div className="space-y-4">
                {/* Workflow Navigation Subheader Tabs */}
                <div className="flex flex-wrap items-center justify-between gap-3 bg-white p-3 rounded-xl border border-ink-200 shadow-sm">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setView("portal")}
                      className="flex items-center gap-1.5 text-xs font-semibold text-ink-600 hover:text-ink-900 bg-ink-100 hover:bg-ink-200 px-3 py-1.5 rounded-lg transition"
                    >
                      <ArrowLeft className="h-3.5 w-3.5" /> Back to Workflows
                    </button>
                    <div className="h-4 w-px bg-ink-200" />
                    <div>
                      <h1 className="text-base font-bold tracking-tight text-ink-900 flex items-center gap-2">
                        {detail.project.name}
                        {detail.project.synthetic && (
                          <Badge className="border-amber-300 bg-amber-50 text-amber-800 text-[10px]">
                            sample demo
                          </Badge>
                        )}
                      </h1>
                      <p className="text-[11px] text-ink-500">
                        {detail.project.client || "Self"} · {detail.sites.length} sites ·{" "}
                        {detail.documents.length} documents · {detail.requirement_count} requirements ·{" "}
                        <span className={cx(detail.open_gap_count > 0 && "text-amber-700 font-medium")}>
                          {detail.open_gap_count} open gaps
                        </span>
                      </p>
                    </div>
                  </div>

                  <Tabs<ViewMode>
                    label="Workflow"
                    value={view}
                    onChange={setView}
                    tabs={[
                      {
                        id: "before",
                        label: (
                          <span className="inline-flex items-center gap-1.5">
                            <Building2 aria-hidden className="h-4 w-4" /> Before construction
                          </span>
                        ),
                      },
                      {
                        id: "during",
                        label: (
                          <span className="inline-flex items-center gap-1.5">
                            <HardHat aria-hidden className="h-4 w-4" /> During construction
                          </span>
                        ),
                        badge: (
                          <Badge className="border-ink-300 bg-ink-100 text-ink-700">
                            {detail.changes.length}
                          </Badge>
                        ),
                      },
                      {
                        id: "knowledge",
                        label: (
                          <span className="inline-flex items-center gap-1.5">
                            <Search aria-hidden className="h-4 w-4" /> Project knowledge
                          </span>
                        ),
                      },
                    ]}
                  />
                </div>

                {/* Active Workflow Component */}
                <div>
                  {view === "before" && (
                    <BeforeConstruction
                      key={detail.project.id}
                      detail={detail}
                      meta={meta}
                      onProjectChanged={() => loadProject(detail.project.id)}
                    />
                  )}
                  {view === "during" && (
                    <DuringConstruction key={detail.project.id} detail={detail} />
                  )}
                  {view === "knowledge" && <KnowledgePanel key={detail.project.id} detail={detail} />}
                </div>
              </div>
            )}

            {/* Empty state if user opened workflow with no project */}
            {meta && view !== "portal" && !detail && (
              <div className="mx-auto max-w-md py-12 text-center space-y-4">
                <h2 className="text-lg font-bold text-ink-900">No project active</h2>
                <p className="text-xs text-ink-500">Create a project or load sample data to access this workflow.</p>
                <div className="flex justify-center gap-2">
                  <Button variant="primary" onClick={() => setView("setup")}>
                    <Plus className="h-3.5 w-3.5 mr-1" /> Create Project
                  </Button>
                  <Button onClick={() => setView("portal")}>
                    Return to Selection
                  </Button>
                </div>
              </div>
            )}
          </main>

          {/* Footer */}
          {meta && (
            <footer className="border-t border-ink-200 bg-white py-3 px-4 text-center text-[11px] text-ink-500">
              <div className="mx-auto max-w-[110rem] flex flex-wrap items-center justify-between gap-2">
                <span>The Wet Stack — Mireye · Data-Center &amp; EPC Intelligence Platform</span>
                <span>{meta.disclaimer}</span>
              </div>
            </footer>
          )}
        </div>
      )}
    </div>
  );
}

function KnowledgePanel({ detail }: { detail: ProjectDetail }) {
  const [query, setQuery] = useState("chiller net cooling capacity requirement");
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [answer, setAnswer] = useState<{ answer: string; disclaimer: string; mode: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function search(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    setAnswer(null);
    try {
      setResults(await api.search(detail.project.id, query.trim()));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function ask() {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(await api.ask(detail.project.id, query.trim()));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card
        title="Ingested Project Documents"
        subtitle="Extracted PDF submittals, specifications, and manufacturer datasheets"
      >
        {detail.documents.length === 0 ? (
          <p className="text-xs text-ink-500">No documents ingested for this project yet.</p>
        ) : (
          <ul className="divide-y divide-ink-100 text-xs">
            {detail.documents.map((document) => (
              <li key={document.id} className="py-2">
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-ink-900">{document.filename}</p>
                  <div className="flex gap-1">
                    {document.synthetic && (
                      <Badge className="border-amber-300 bg-amber-100 text-amber-900">synthetic</Badge>
                    )}
                    <Badge
                      className={
                        document.extraction_status === "extracted"
                          ? "border-emerald-300 bg-emerald-100 text-emerald-900"
                          : "border-rose-300 bg-rose-100 text-rose-900"
                      }
                    >
                      {document.extraction_status}
                    </Badge>
                  </div>
                </div>
                <p className="mt-1 text-ink-500">
                  {document.page_count} page(s) · {(document.size_bytes / 1024).toFixed(0)} kB
                </p>
                {document.extraction_error && (
                  <p className="mt-1 text-rose-700">{document.extraction_error}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title="Retrieval over ingested documents"
        subtitle="Hybrid lexical + vector search with page citations"
      >
        <form onSubmit={search} className="flex gap-2">
          <label htmlFor="search-q" className="sr-only">
            Search documents
          </label>
          <input
            id="search-q"
            className={inputClass}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button type="submit" variant="primary" loading={busy}>
            Search
          </Button>
          <Button type="button" onClick={ask} loading={busy}>
            Ask Mireye
          </Button>
        </form>
        {error ? (
          <div className="mt-3">
            <ErrorState error={error} />
          </div>
        ) : null}
        {results && (
          <div className="mt-3">
            <p className="text-[11px] text-ink-500">backend: {results.backend}</p>
            <ul className="mt-1 flex flex-col gap-2">
              {results.results.map((chunk) => (
                <li key={chunk.chunk_id} className="rounded border border-ink-200 p-2 text-xs">
                  <p className="text-[11px] font-medium text-ink-600">
                    {chunk.document_name} · page {chunk.page} · {chunk.method} · score{" "}
                    {chunk.score.toFixed(3)}
                  </p>
                  <p className="mt-1 line-clamp-4 text-ink-700">{chunk.text}</p>
                </li>
              ))}
              {results.results.length === 0 && (
                <li className="text-xs text-ink-500">No chunk matched that query.</li>
              )}
            </ul>
          </div>
        )}
        {answer && (
          <div className="mt-3 rounded border border-sky-200 bg-sky-50 p-2 text-xs text-sky-900">
            <p className="font-medium">Exploratory answer ({answer.mode})</p>
            <p className="mt-1">{answer.answer}</p>
            <p className="mt-1 text-[11px] text-sky-700">{answer.disclaimer}</p>
          </div>
        )}
      </Card>
    </div>
  );
}
