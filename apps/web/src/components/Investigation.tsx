import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  CircleDashed,
  CircleSlash,
  Clock,
  Loader2,
  RefreshCw,
  ShieldQuestion,
} from "lucide-react";

import { DECISION_STYLE, fmtTime, titleize } from "../lib/format";
import type { Investigation, InvestigationStep, NextAction } from "../lib/types";
import { Badge, Card, EmptyState, cx } from "./ui";

const PHASES = ["understand", "plan", "evidence", "signals", "replan", "impact", "action"] as const;

const STEP_ICON: Record<InvestigationStep["status"], typeof CheckCircle2> = {
  completed: CheckCircle2,
  running: Loader2,
  planned: CircleDashed,
  blocked: ShieldQuestion,
  skipped: CircleSlash,
};

const STEP_COLOR: Record<InvestigationStep["status"], string> = {
  completed: "text-emerald-600",
  running: "text-sky-600 animate-spin",
  planned: "text-ink-400",
  blocked: "text-amber-600",
  skipped: "text-ink-300",
};

export function PhaseRail({ phase }: { phase: string }) {
  const current = PHASES.indexOf(phase as (typeof PHASES)[number]);
  const done = phase === "done";
  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label="Investigation phase">
      {PHASES.map((p, i) => {
        const state = done || i < current ? "done" : i === current ? "active" : "todo";
        return (
          <li key={p} className="flex items-center gap-1">
            <span
              aria-current={state === "active" ? "step" : undefined}
              className={cx(
                "rounded-md px-2 py-0.5 text-[11px] font-medium capitalize",
                state === "done" && "bg-emerald-100 text-emerald-900",
                state === "active" && "bg-ink-900 text-white",
                state === "todo" && "bg-ink-100 text-ink-500",
              )}
            >
              {p}
            </span>
            {i < PHASES.length - 1 && <span aria-hidden className="text-ink-300">›</span>}
          </li>
        );
      })}
    </ol>
  );
}

export function InvestigationTimeline({ investigation }: { investigation: Investigation }) {
  return (
    <Card
      title="Investigation activity"
      subtitle={`${investigation.orchestrator} · LLM mode: ${investigation.llm_mode} · started ${fmtTime(
        investigation.started_at,
      )}`}
      actions={<PhaseRail phase={investigation.phase} />}
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold text-ink-500 uppercase tracking-wide">
            Planned steps ({investigation.steps.length})
          </h3>
          <ol className="flex flex-col gap-2">
            {investigation.steps.map((step) => {
              const Icon = STEP_ICON[step.status];
              return (
                <li key={step.id} className="flex gap-2 rounded-lg border border-ink-200 p-2.5">
                  <Icon aria-hidden className={cx("mt-0.5 h-4 w-4 shrink-0", STEP_COLOR[step.status])} />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-ink-900">
                      {step.order}. {step.title}
                      {step.added_in_replan && (
                        <Badge className="ml-2 border-sky-300 bg-sky-100 text-sky-900">
                          <RefreshCw aria-hidden className="h-3 w-3" /> added in replan
                        </Badge>
                      )}
                    </p>
                    <p className="mt-0.5 text-xs text-ink-500">{step.rationale}</p>
                    {step.requested_fields.length > 0 && (
                      <p className="mt-1 text-[11px] text-ink-500">
                        Requested evidence:{" "}
                        <span className="font-mono">
                          {step.requested_fields.slice(0, 6).join(", ")}
                          {step.requested_fields.length > 6
                            ? ` +${step.requested_fields.length - 6} more`
                            : ""}
                        </span>
                      </p>
                    )}
                    {step.result_summary && (
                      <p className="mt-1 text-xs text-ink-700">{step.result_summary}</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          {investigation.replan_notes.length > 0 && (
            <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 p-2.5">
              <h4 className="text-xs font-semibold text-sky-900">Re-planning decisions</h4>
              <ul className="mt-1 list-disc pl-4 text-xs text-sky-900">
                {investigation.replan_notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold text-ink-500 uppercase tracking-wide">
            Agent &amp; tool events ({investigation.events.length})
          </h3>
          <ol className="flex max-h-[28rem] flex-col gap-1.5 overflow-y-auto pr-1">
            {investigation.events.map((event) => (
              <li
                key={event.id}
                className={cx(
                  "rounded-lg border p-2 text-xs",
                  event.ok ? "border-ink-200 bg-white" : "border-rose-300 bg-rose-50",
                )}
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <Activity aria-hidden className="h-3 w-3 text-ink-400" />
                  <span className="font-mono text-[11px] text-ink-600">{event.tool}</span>
                  <Badge className="border-ink-200 bg-ink-50 text-ink-600">{event.phase}</Badge>
                  {event.duration_ms != null && (
                    <span className="tabular inline-flex items-center gap-1 text-[11px] text-ink-400">
                      <Clock aria-hidden className="h-3 w-3" />
                      {event.duration_ms} ms
                    </span>
                  )}
                </div>
                <p className="mt-1 text-ink-800">{event.summary}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </Card>
  );
}

export function DecisionCard({ investigation }: { investigation: Investigation }) {
  const state = investigation.decision_state;
  const rec = investigation.recommendation;
  if (!state || !rec) {
    return (
      <Card title="Decision">
        <EmptyState title="No decision yet" detail="Run the investigation to reach a decision state." />
      </Card>
    );
  }
  return (
    <Card
      title="Final decision"
      subtitle="One of three states, decided by deterministic rules"
      className={cx("border-2", DECISION_STYLE[state])}
    >
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-lg font-semibold tracking-tight text-ink-900">{state}</p>
        <Badge className="border-ink-300 bg-white text-ink-700">
          confidence {(rec.confidence * 100).toFixed(0)}%
        </Badge>
        {rec.generated_by === "llm" && (
          <Badge className="border-violet-300 bg-violet-100 text-violet-900">
            <BrainCircuit aria-hidden className="h-3 w-3" /> LLM explanation
          </Badge>
        )}
      </div>
      <p className="mt-2 text-sm font-medium text-ink-800">{rec.headline}</p>
      <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-sm text-ink-700">
        {rec.rationale.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
      {rec.caveats.length > 0 && (
        <div className="mt-3 rounded-lg border border-ink-200 bg-white/70 p-2.5">
          <h3 className="text-xs font-semibold text-ink-600">Limitations</h3>
          <ul className="mt-1 flex list-disc flex-col gap-1 pl-4 text-xs text-ink-600">
            {rec.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

export function NextActionPreview({ actions }: { actions: NextAction[] }) {
  if (actions.length === 0) {
    return (
      <Card title="Generated next action">
        <EmptyState title="No action generated" detail="Nothing is outstanding for this case." />
      </Card>
    );
  }
  return (
    <Card title="Generated next action" subtitle="Draft - review before sending">
      <div className="flex flex-col gap-3">
        {actions.map((action) => (
          <article key={action.id} className="rounded-lg border border-ink-200">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-3 py-2">
              <div>
                <Badge className="border-ink-300 bg-ink-100 text-ink-800">
                  {titleize(action.type)}
                </Badge>
                <p className="mt-1 text-sm font-medium text-ink-900">{action.title}</p>
                <p className="text-xs text-ink-500">
                  To: {action.recipient} · due in {action.due_in_days} days
                </p>
              </div>
            </header>
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap px-3 py-2 font-sans text-xs text-ink-700">
              {action.body}
            </pre>
          </article>
        ))}
      </div>
    </Card>
  );
}
