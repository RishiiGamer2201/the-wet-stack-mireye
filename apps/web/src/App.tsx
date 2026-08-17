import { Building2, Database, FlaskConical, HardHat, Layers, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, ErrorState, Spinner, Tabs, cx, inputClass } from "./components/ui";
import { BeforeConstruction } from "./features/BeforeConstruction";
import { DuringConstruction } from "./features/DuringConstruction";
import { api } from "./lib/api";
import type { Meta, Project, ProjectDetail, SearchResponse } from "./lib/types";

type WorkflowId = "before" | "during" | "knowledge";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [workflow, setWorkflow] = useState<WorkflowId>("before");
  const [error, setError] = useState<unknown>(null);
  const [seeding, setSeeding] = useState(false);

  const bootstrap = useCallback(async () => {
    setError(null);
    try {
      const [metaResponse, projectList] = await Promise.all([api.meta(), api.projects()]);
      setMeta(metaResponse);
      setProjects(projectList);
      setProjectId((current) => current ?? projectList[0]?.id ?? null);
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
    if (projectId) loadProject(projectId);
  }, [projectId, loadProject]);

  async function seed() {
    setSeeding(true);
    try {
      const result = await api.seed();
      await bootstrap();
      setProjectId(result.project_id);
      await loadProject(result.project_id);
    } catch (e) {
      setError(e);
    } finally {
      setSeeding(false);
    }
  }

  return (
    <div className="min-h-full">
      <header className="border-b border-ink-200 bg-ink-900 text-white">
        <div className="mx-auto flex max-w-[110rem] flex-wrap items-center gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <Layers aria-hidden className="h-5 w-5 text-signal-500" />
            <div>
              <p className="text-sm font-semibold leading-tight">The Wet Stack — Mireye</p>
              <p className="text-[11px] text-ink-300">
                Data-center construction &amp; EPC intelligence
              </p>
            </div>
          </div>

          <div className="ml-auto flex min-w-0 flex-wrap items-center gap-2">
            <label htmlFor="project-select" className="sr-only">
              Project
            </label>
            {/* A long project name must not stretch the header past the viewport. */}
            <select
              id="project-select"
              className="max-w-[min(20rem,60vw)] truncate rounded-lg border border-ink-600 bg-ink-800 px-2.5 py-1.5 text-sm text-white"
              value={projectId ?? ""}
              onChange={(e) => setProjectId(e.target.value)}
            >
              {projects.length === 0 && <option value="">No project</option>}
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <Button size="sm" onClick={seed} loading={seeding}>
              <RefreshCw aria-hidden className="h-3.5 w-3.5" /> Reseed demo
            </Button>
          </div>
        </div>

        {meta?.demo_mode && (
          <div className="border-t border-ink-700 bg-amber-500/15 px-4 py-1.5">
            <div className="mx-auto flex max-w-[110rem] flex-wrap items-center gap-2 text-[11px] text-amber-100">
              <FlaskConical aria-hidden className="h-3.5 w-3.5" />
              <span className="font-semibold">Demo mode</span>
              <span>
                Mireye: {meta.services.mireye} · graph: {meta.services.graph} · vector:{" "}
                {meta.services.vector} · store: {meta.services.store} · LLM: {meta.services.llm}
              </span>
              {/* With a live adapter configured the analysis is a mix, so the
                  blanket "everything is synthetic" claim would be false. Each
                  value still carries its own status badge either way. */}
              <span className="hidden md:inline">
                {meta.services.mireye === "mock"
                  ? "— all site, equipment and document values shown are synthetic and clearly labelled."
                  : meta.services.mireye === "degraded_fallback"
                    ? "— live Mireye is configured but failing; site values are local stand-ins badged “fallback”, never live."
                    : "— mixed: site values come from live Mireye and are badged individually; equipment and document values remain synthetic."}
              </span>
            </div>
          </div>
        )}
      </header>

      <main className="mx-auto max-w-[110rem] px-4 py-4">
        {error ? <ErrorState error={error} onRetry={bootstrap} /> : null}
        {!meta && !error && <Spinner label="Connecting to the API…" />}

        {meta && projects.length === 0 && (
          <Card>
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <Database aria-hidden className="h-6 w-6 text-ink-400" />
              <p className="text-sm font-medium">No project yet</p>
              <p className="max-w-md text-xs text-ink-500">
                Seed the demonstration project to load five synthetic candidate sites, three
                synthetic equipment change cases and three synthetic source documents.
              </p>
              <Button variant="primary" onClick={seed} loading={seeding}>
                Seed demo data
              </Button>
            </div>
          </Card>
        )}

        {meta && detail && (
          <>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="text-lg font-semibold tracking-tight">{detail.project.name}</h1>
                <p className="text-xs text-ink-500">
                  {detail.project.client} · {detail.sites.length} sites ·{" "}
                  {detail.documents.length} documents · {detail.requirement_count} requirements ·{" "}
                  {detail.evidence_count} evidence items ·{" "}
                  <span className={cx(detail.open_gap_count > 0 && "text-amber-700")}>
                    {detail.open_gap_count} open gaps
                  </span>
                </p>
              </div>
              {detail.project.synthetic && (
                <Badge className="border-amber-300 bg-amber-100 text-amber-900">
                  synthetic demonstration project
                </Badge>
              )}
            </div>

            <Tabs<WorkflowId>
              label="Workflow"
              value={workflow}
              onChange={setWorkflow}
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

            {/* Keyed on the project: switching or reseeding must drop the previous
                project's ranking, investigation and selected change rather than
                leaving stale results on screen. */}
            <div className="mt-4">
              {workflow === "before" && (
                <BeforeConstruction
                  key={detail.project.id}
                  detail={detail}
                  meta={meta}
                  onProjectChanged={() => loadProject(detail.project.id)}
                />
              )}
              {workflow === "during" && (
                <DuringConstruction key={detail.project.id} detail={detail} />
              )}
              {workflow === "knowledge" && <KnowledgePanel key={detail.project.id} detail={detail} />}
            </div>

            <footer className="mt-8 border-t border-ink-200 pt-3 text-[11px] text-ink-500">
              {meta.disclaimer}
            </footer>
          </>
        )}
      </main>
    </div>
  );
}

function KnowledgePanel({ detail }: { detail: ProjectDetail }) {
  const [query, setQuery] = useState("minimum circuit ampacity");
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [answer, setAnswer] = useState<{ answer: string; disclaimer: string; mode: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResults(await api.search(detail.project.id, query));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function ask() {
    setBusy(true);
    try {
      setAnswer(await api.ask(detail.project.id, query));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Documents" subtitle="Ingested sources backing every extracted requirement">
        <ul className="flex flex-col gap-2">
          {detail.documents.map((document) => (
            <li key={document.id} className="rounded-lg border border-ink-200 p-2.5 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-ink-900">{document.filename}</span>
                <div className="flex gap-1">
                  <Badge className="border-ink-300 bg-ink-100 text-ink-700">{document.kind}</Badge>
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

