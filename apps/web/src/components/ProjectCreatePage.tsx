import { ArrowLeft, ArrowRight, Layers, Sparkles, User } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import type { Project } from "../lib/types";
import { Button, Field } from "./ui";

interface ProjectCreatePageProps {
  onBack: () => void;
  onProjectCreated: (project: Project, personName: string) => void;
  onSeedDemo: () => Promise<void>;
  busy: boolean;
}

export function ProjectCreatePage({
  onBack,
  onProjectCreated,
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
  const [projectName, setProjectName] = useState("Aurora DC-2 — Hyperscale Campus");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmedPerson = personName.trim();
    const trimmedProject = projectName.trim();

    if (!trimmedPerson) {
      setError("Please enter your name.");
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

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-between selection:bg-emerald-500 selection:text-black">
      {/* Ambient background glow */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[40rem] h-[25rem] bg-emerald-500/10 rounded-full blur-[120px]" />
      </div>

      {/* Top Bar with Back action */}
      <header className="relative z-10 p-6 max-w-4xl mx-auto w-full flex items-center justify-between">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors bg-slate-900/80 hover:bg-slate-800 border border-slate-800 px-3.5 py-1.5 rounded-lg"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Overview
        </button>
        <span className="text-xs text-slate-500">Step 2 of 2 · Project Setup</span>
      </header>

      {/* Main Form Card */}
      <main className="relative z-10 max-w-xl mx-auto px-6 py-8 w-full flex-1 flex flex-col justify-center">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-8 shadow-2xl backdrop-blur-xl space-y-6">
          <div className="text-center space-y-2">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Layers className="h-6 w-6" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-white">Create Your Project</h1>
            <p className="text-xs text-slate-400">
              Enter your name and project title. All data will be persisted in SQLite (<code>wetstack.db</code>).
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
                {error}
              </div>
            )}

            <div className="space-y-4">
              <Field label="Your Name *" htmlFor="person-name">
                <div className="relative">
                  <User className="absolute left-3 top-2.5 h-4 w-4 text-slate-500 pointer-events-none" />
                  <input
                    id="person-name"
                    type="text"
                    required
                    placeholder="e.g. Alex Mercer"
                    className="w-full rounded-lg border border-slate-700 bg-slate-800/90 pl-9 pr-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    value={personName}
                    onChange={(e) => setPersonName(e.target.value)}
                  />
                </div>
              </Field>

              <Field label="Project Name *" htmlFor="project-name">
                <div className="relative">
                  <Layers className="absolute left-3 top-2.5 h-4 w-4 text-slate-500 pointer-events-none" />
                  <input
                    id="project-name"
                    type="text"
                    required
                    placeholder="e.g. Aurora DC-2 Campus"
                    className="w-full rounded-lg border border-slate-700 bg-slate-800/90 pl-9 pr-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                  />
                </div>
              </Field>
            </div>

            <Button
              type="submit"
              size="md"
              loading={submitting || busy}
              className="w-full py-3 text-sm font-bold bg-emerald-500 hover:bg-emerald-400 text-slate-950 rounded-xl shadow-md transition-all justify-center"
            >
              Start Project &amp; Launch Workflows
              <ArrowRight className="h-4 w-4 ml-1.5" />
            </Button>
          </form>

          {/* Quick Demo Option */}
          <div className="pt-4 border-t border-slate-800/80 text-center space-y-2">
            <p className="text-xs text-slate-500">Want to test with pre-filled sample data?</p>
            <button
              type="button"
              onClick={onSeedDemo}
              disabled={busy || submitting}
              className="inline-flex items-center gap-1.5 text-xs text-emerald-400 hover:text-emerald-300 transition-colors font-medium"
            >
              <Sparkles className="h-3.5 w-3.5" /> Load 48 MW Synthetic Demo Project (5 Sites)
            </button>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-slate-800/80 py-3 px-6 text-center text-xs text-slate-500">
        <p>The Wet Stack — Mireye · Data-Center Construction &amp; EPC Intelligence</p>
      </footer>
    </div>
  );
}
