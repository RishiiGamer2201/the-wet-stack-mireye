import { ArrowLeft, ArrowRight, Edit2, FolderOpen, Layers, Plus, Sparkles, User } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import type { Project } from "../lib/types";
import { Badge, Button, Field, inputClass } from "./ui";

interface ProjectCreatePageProps {
  projects: Project[];
  onBack: () => void;
  onProjectCreated: (project: Project, personName: string) => void;
  onSelectProject: (projectId: string) => void;
  onSeedDemo: () => Promise<void>;
  busy: boolean;
}

export function ProjectCreatePage({
  projects,
  onBack,
  onProjectCreated,
  onSelectProject,
  onSeedDemo,
  busy,
}: ProjectCreatePageProps) {
  const [personName, setPersonName] = useState(() => {
    try {
      const raw = localStorage.getItem("wetstack_user_profile");
      return raw ? JSON.parse(raw).name || "" : "";
    } catch {
      return "";
    }
  });
  const [isEditingName, setIsEditingName] = useState(!personName);

  // Project Name starts empty with NO pre-defined value
  const [projectName, setProjectName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleCreateProject(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmedPerson = personName.trim();
    const trimmedProject = projectName.trim();

    if (!trimmedPerson) {
      setError("Please enter your name.");
      setIsEditingName(true);
      return;
    }
    if (!trimmedProject) {
      setError("Please enter a project name.");
      return;
    }

    setSubmitting(true);
    try {
      // Create project in SQLite database via backend API
      const project = await api.createProject({
        name: trimmedProject,
        client: trimmedPerson,
        description: `Project initialized by ${trimmedPerson}`,
      });

      // Save user session
      try {
        localStorage.setItem(
          "wetstack_user_profile",
          JSON.stringify({
            name: trimmedPerson,
            role: "EPC Lead Engineer",
            organization: "Infrastructure Group",
          }),
        );
      } catch (err) {
        console.warn("Could not save to localStorage", err);
      }

      onProjectCreated(project, trimmedPerson);
    } catch (err: any) {
      setError(err?.message || "Failed to create project in SQLite.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleSaveNameOnly(e: React.FormEvent) {
    e.preventDefault();
    if (personName.trim()) {
      try {
        localStorage.setItem(
          "wetstack_user_profile",
          JSON.stringify({
            name: personName.trim(),
            role: "EPC Lead Engineer",
            organization: "Infrastructure Group",
          }),
        );
      } catch (err) {
        console.warn("Could not save to localStorage", err);
      }
      setIsEditingName(false);
    }
  }

  return (
    <div className="min-h-screen bg-ink-50 text-ink-900 flex flex-col justify-between">
      {/* Ambient background lighting */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[40rem] h-[25rem] bg-signal-500/10 rounded-full blur-[140px]" />
      </div>

      {/* Top Bar with Back action */}
      <header className="relative z-10 p-6 max-w-5xl mx-auto w-full flex items-center justify-between">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-xs text-ink-600 hover:text-ink-900 transition-colors bg-white hover:bg-ink-100 border border-ink-200 px-3.5 py-1.5 rounded-lg shadow-2xs font-medium"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Overview
        </button>
        <span className="text-xs text-ink-500 font-medium">Project Workspace Setup</span>
      </header>

      {/* Main Container */}
      <main className="relative z-10 max-w-5xl mx-auto px-6 py-6 w-full flex-1 flex flex-col justify-center space-y-6">
        {/* User Identity Banner (Asked once, editable on demand) */}
        <div className="rounded-2xl border border-ink-200 bg-white p-5 shadow-xs flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-signal-500/10 text-signal-600 border border-signal-500/20">
              <User className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs font-bold text-ink-500 uppercase tracking-wider">User Identity</p>
              {isEditingName ? (
                <form onSubmit={handleSaveNameOnly} className="flex items-center gap-2 mt-1">
                  <input
                    type="text"
                    required
                    placeholder="Enter your name (e.g. Alex Mercer)"
                    className={`${inputClass} max-w-xs py-1 text-xs`}
                    value={personName}
                    onChange={(e) => setPersonName(e.target.value)}
                    autoFocus
                  />
                  <Button type="submit" size="sm" variant="primary" className="text-xs py-1">
                    Save Name
                  </Button>
                </form>
              ) : (
                <p className="text-sm font-bold text-ink-900 flex items-center gap-2 mt-0.5">
                  <span>{personName}</span>
                  <Badge className="border-signal-500/30 bg-signal-500/10 text-signal-700 text-[10px]">
                    Active Engineer
                  </Badge>
                </p>
              )}
            </div>
          </div>

          {!isEditingName && (
            <button
              type="button"
              onClick={() => setIsEditingName(true)}
              className="inline-flex items-center gap-1 text-xs text-ink-500 hover:text-signal-600 transition-colors font-medium"
            >
              <Edit2 className="h-3 w-3" /> Change Name
            </button>
          )}
        </div>

        {/* Dual Layout: Create New Project + Existing Projects */}
        <div className="grid md:grid-cols-2 gap-6 items-start">
          {/* Section 1: Create New Project */}
          <div className="rounded-2xl border border-ink-200 bg-white p-6 sm:p-7 shadow-xs space-y-5">
            <div className="flex items-center gap-2.5 border-b border-ink-100 pb-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-signal-500/10 text-signal-600 font-bold text-xs">
                <Plus className="h-4 w-4" />
              </div>
              <div>
                <h2 className="text-base font-bold text-ink-900">Create New Project</h2>
                <p className="text-xs text-ink-500">Add a new project to SQLite (<code>wetstack.db</code>)</p>
              </div>
            </div>

            <form onSubmit={handleCreateProject} className="space-y-4">
              {error && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-800">
                  {error}
                </div>
              )}

              {isEditingName && (
                <Field label="Your Name *" htmlFor="person-name-input">
                  <div className="relative">
                    <User className="absolute left-3 top-2.5 h-4 w-4 text-ink-400 pointer-events-none" />
                    <input
                      id="person-name-input"
                      type="text"
                      required
                      placeholder="e.g. Alex Mercer"
                      className={`${inputClass} pl-9`}
                      value={personName}
                      onChange={(e) => setPersonName(e.target.value)}
                    />
                  </div>
                </Field>
              )}

              <Field label="Project Name *" htmlFor="project-name-input">
                <div className="relative">
                  <Layers className="absolute left-3 top-2.5 h-4 w-4 text-ink-400 pointer-events-none" />
                  <input
                    id="project-name-input"
                    type="text"
                    required
                    placeholder="e.g. Phoenix Hyperscale Campus"
                    className={`${inputClass} pl-9`}
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                  />
                </div>
              </Field>

              <Button
                type="submit"
                size="md"
                variant="primary"
                loading={submitting || busy}
                className="w-full py-2.5 text-sm font-bold bg-ink-900 hover:bg-signal-600 text-white rounded-xl shadow-xs transition-all justify-center"
              >
                Create Project &amp; Launch
                <ArrowRight className="h-4 w-4 ml-1.5" />
              </Button>
            </form>

            <div className="pt-3 border-t border-ink-100 text-center">
              <button
                type="button"
                onClick={onSeedDemo}
                disabled={busy || submitting}
                className="inline-flex items-center gap-1.5 text-xs text-signal-600 hover:text-signal-700 transition-colors font-semibold"
              >
                <Sparkles className="h-3.5 w-3.5" /> Or Load 48 MW Synthetic Demo (5 Sites)
              </button>
            </div>
          </div>

          {/* Section 2: Existing Projects Stored in SQLite */}
          <div className="rounded-2xl border border-ink-200 bg-white p-6 sm:p-7 shadow-xs space-y-4">
            <div className="flex items-center justify-between border-b border-ink-100 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-50 text-sky-600 font-bold text-xs">
                  <FolderOpen className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-ink-900">Existing Projects</h2>
                  <p className="text-xs text-ink-500">Stored in SQLite workspace ({projects.length})</p>
                </div>
              </div>
            </div>

            {projects.length === 0 ? (
              <div className="text-center py-8 space-y-2 border border-dashed border-ink-200 rounded-xl p-4">
                <p className="text-xs text-ink-500 font-medium">No existing projects found in SQLite.</p>
                <p className="text-[11px] text-ink-400">
                  Create your first project on the left or click above to load demo data.
                </p>
              </div>
            ) : (
              <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
                {projects.map((p) => (
                  <div
                    key={p.id}
                    className="group rounded-xl border border-ink-200 hover:border-signal-500/60 p-3.5 transition-all bg-white hover:bg-ink-50/50 flex items-center justify-between gap-3 shadow-2xs"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-bold text-ink-900 truncate group-hover:text-signal-600 transition-colors">
                        {p.name}
                      </p>
                      <p className="text-xs text-ink-500 truncate mt-0.5">
                        {p.client || "Self"} · {p.region || "Global"}
                      </p>
                    </div>

                    <Button
                      size="sm"
                      onClick={() => onSelectProject(p.id)}
                      className="shrink-0 text-xs py-1 px-3 bg-ink-100 hover:bg-signal-600 hover:text-white border-ink-200 transition"
                    >
                      Open <ArrowRight className="h-3 w-3 ml-1" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-ink-200 bg-white py-3 px-6 text-center text-xs text-ink-500">
        <p>The Wet Stack — Mireye · Data-Center Construction &amp; EPC Intelligence</p>
      </footer>
    </div>
  );
}
