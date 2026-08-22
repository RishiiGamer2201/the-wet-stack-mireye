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

import { EngineeringAdvisorChat } from "./components/EngineeringAdvisorChat";
import { HeroPage } from "./components/HeroPage";
import { ProjectCreatePage } from "./components/ProjectCreatePage";
import { Badge, Button, ErrorState, Spinner, Tabs, cx } from "./components/ui";
import { BeforeConstruction } from "./features/BeforeConstruction";
import { DuringConstruction } from "./features/DuringConstruction";
import { ProjectKnowledgeAgent } from "./features/ProjectKnowledgeAgent";
import { api } from "./lib/api";
import type { Meta, Project, ProjectDetail } from "./lib/types";

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
  // The advisor lives here rather than inside one workflow: the same engineer is
  // worth asking from the site table, the change log and the document library.
  const [advisorOpen, setAdvisorOpen] = useState(false);
  const [advisorSiteId, setAdvisorSiteId] = useState<string | null>(null);
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
                      onOpenAdvisor={(siteId) => {
                        setAdvisorSiteId(siteId);
                        setAdvisorOpen(true);
                      }}
                      onAdvisorSiteChange={setAdvisorSiteId}
                    />
                  )}
                  {view === "during" && (
                    <DuringConstruction key={detail.project.id} detail={detail} />
                  )}
                  {view === "knowledge" && (
                    <ProjectKnowledgeAgent
                      key={detail.project.id}
                      detail={detail}
                      onProjectChanged={() => loadProject(detail.project.id)}
                    />
                  )}
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

          {/* Senior Civil EPC Advisor — available on every workflow */}
          {detail && (
            <>
              <EngineeringAdvisorChat
                detail={detail}
                activeSiteId={advisorSiteId}
                isOpen={advisorOpen}
                onClose={() => setAdvisorOpen(false)}
                onProjectChanged={() => loadProject(detail.project.id)}
              />
              {!advisorOpen && (
                <button
                  onClick={() => setAdvisorOpen(true)}
                  className="fixed bottom-6 right-6 z-40 flex items-center gap-2 bg-ink-900 hover:bg-signal-600 text-white px-4 py-2.5 rounded-full shadow-xl border border-ink-700 transition-all scale-100 hover:scale-105 font-bold text-xs"
                  title="Consult Senior Civil & Structural EPC Engineer AI Advisor"
                >
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/30 text-amber-400">
                    <HardHat className="h-3.5 w-3.5" />
                  </div>
                  <span>Senior Civil EPC Advisor</span>
                  <span className="bg-amber-500/20 text-amber-300 text-[10px] px-1.5 py-0.5 rounded font-mono">
                    AI
                  </span>
                </button>
              )}
            </>
          )}

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
