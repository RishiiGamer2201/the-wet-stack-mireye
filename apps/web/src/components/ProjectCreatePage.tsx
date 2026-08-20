import { ArrowLeft, ArrowRight, Layers, Sparkles, User } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import type { Project } from "../lib/types";
import { Button, Field, inputClass } from "./ui";

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
    <div className="min-h-screen bg-ink-50 text-ink-900 flex flex-col justify-between">
      {/* Ambient background lighting */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[40rem] h-[25rem] bg-signal-500/10 rounded-full blur-[140px]" />
      </div>

      {/* Top Bar with Back action */}
      <header className="relative z-10 p-6 max-w-4xl mx-auto w-full flex items-center justify-between">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-xs text-ink-600 hover:text-ink-900 transition-colors bg-white hover:bg-ink-100 border border-ink-200 px-3.5 py-1.5 rounded-lg shadow-2xs"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Overview
        </button>
        <span className="text-xs text-ink-500 font-medium">Step 2 of 2 · Project Setup</span>
      </header>

      {/* Main Form Card */}
      <main className="relative z-10 max-w-lg mx-auto px-6 py-8 w-full flex-1 flex flex-col justify-center">
        <div className="rounded-2xl border border-ink-200 bg-white p-8 shadow-sm space-y-6">
          <div className="text-center space-y-2">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-signal-500/10 text-signal-600 border border-signal-500/20">
              <Layers className="h-6 w-6" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-ink-900">Create Your Project</h1>
            <p className="text-xs text-ink-500">
              Enter your name and project title. All data will be persisted in SQLite (<code>wetstack.db</code>).
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">
                {error}
              </div>
            )}

            <div className="space-y-4">
              <Field label="Your Name *" htmlFor="person-name">
                <div className="relative">
                  <User className="absolute left-3 top-2.5 h-4 w-4 text-ink-400 pointer-events-none" />
                  <input
                    id="person-name"
                    type="text"
                    required
                    placeholder="e.g. Alex Mercer"
                    className={`${inputClass} pl-9`}
                    value={personName}
                    onChange={(e) => setPersonName(e.target.value)}
                  />
                </div>
              </Field>

              <Field label="Project Name *" htmlFor="project-name">
                <div className="relative">
                  <Layers className="absolute left-3 top-2.5 h-4 w-4 text-ink-400 pointer-events-none" />
                  <input
                    id="project-name"
                    type="text"
                    required
                    placeholder="e.g. Aurora DC-2 Campus"
                    className={`${inputClass} pl-9`}
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                  />
                </div>
              </Field>
            </div>

            <Button
              type="submit"
              size="md"
              variant="primary"
              loading={submitting || busy}
              className="w-full py-3 text-sm font-bold bg-ink-900 hover:bg-signal-600 text-white rounded-xl shadow-xs transition-all justify-center"
            >
              Start Project &amp; Launch Workflows
              <ArrowRight className="h-4 w-4 ml-1.5" />
            </Button>
          </form>

          {/* Quick Demo Option */}
          <div className="pt-4 border-t border-ink-100 text-center space-y-2">
            <p className="text-xs text-ink-500">Want to test with pre-filled sample data?</p>
            <button
              type="button"
              onClick={onSeedDemo}
              disabled={busy || submitting}
              className="inline-flex items-center gap-1.5 text-xs text-signal-600 hover:text-signal-700 transition-colors font-semibold"
            >
              <Sparkles className="h-3.5 w-3.5" /> Load 48 MW Synthetic Demo Project (5 Sites)
            </button>
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
