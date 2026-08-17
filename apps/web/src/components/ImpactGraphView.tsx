import { ArrowRight, Network } from "lucide-react";
import { useMemo, useState } from "react";

import { titleize } from "../lib/format";
import type { ImpactGraph, ImpactNode } from "../lib/types";
import { Badge, Card, EmptyState, cx } from "./ui";

const COLUMNS: { kind: ImpactNode["kind"]; label: string }[] = [
  { kind: "change", label: "Change" },
  { kind: "assumption", label: "Stale assumption" },
  { kind: "discipline", label: "Discipline" },
  { kind: "activity", label: "Activity" },
  { kind: "commissioning", label: "Commissioning" },
];

const KIND_STYLE: Record<string, string> = {
  change: "border-ink-800 bg-ink-900 text-white",
  assumption: "border-orange-300 bg-orange-50 text-orange-900",
  discipline: "border-sky-300 bg-sky-50 text-sky-900",
  activity: "border-ink-200 bg-white text-ink-800",
  commissioning: "border-emerald-300 bg-emerald-50 text-emerald-900",
};

export function ImpactGraphView({ graph }: { graph: ImpactGraph | null }) {
  const [selected, setSelected] = useState<string | null>(null);

  const connected = useMemo(() => {
    if (!graph || !selected) return null;
    const keep = new Set<string>([selected]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const edge of graph.edges) {
        if (keep.has(edge.source) && !keep.has(edge.target)) {
          keep.add(edge.target);
          changed = true;
        }
        if (keep.has(edge.target) && !keep.has(edge.source)) {
          keep.add(edge.source);
          changed = true;
        }
      }
    }
    return keep;
  }, [graph, selected]);

  if (!graph || graph.nodes.length <= 1) {
    return (
      <Card title="Impact graph" subtitle="Change → Stale assumption → Discipline → Activity → Commissioning">
        <EmptyState
          title="No downstream impact"
          detail="No deterministic check was triggered by this change, so nothing downstream is affected."
        />
      </Card>
    );
  }

  const byKind = (kind: string) => graph.nodes.filter((n) => n.kind === kind);
  const dimmed = (id: string) => (connected ? !connected.has(id) : false);

  return (
    <Card
      title="Impact graph"
      subtitle="Traversed from the analysis result — select a node to isolate its dependency path"
      actions={
        <Badge className="border-ink-300 bg-ink-100 text-ink-700">
          <Network aria-hidden className="h-3 w-3" /> {graph.backend} · {graph.nodes.length} nodes ·{" "}
          {graph.edges.length} edges
        </Badge>
      }
    >
      <div className="overflow-x-auto">
        <div className="grid min-w-[56rem] grid-cols-5 gap-3">
          {COLUMNS.map((column) => (
            <div key={column.kind}>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                {column.label}
              </h3>
              <ul className="flex flex-col gap-2">
                {byKind(column.kind).map((node) => (
                  <li key={node.id}>
                    <button
                      onClick={() => setSelected(selected === node.id ? null : node.id)}
                      aria-pressed={selected === node.id}
                      className={cx(
                        "w-full rounded-lg border p-2 text-left text-xs transition-opacity",
                        KIND_STYLE[node.kind],
                        dimmed(node.id) && "opacity-25",
                        selected === node.id && "ring-2 ring-ink-900 ring-offset-1",
                      )}
                    >
                      <span className="block font-medium">{node.label}</span>
                      {node.status && (
                        <span className="mt-1 block text-[10px] uppercase tracking-wide opacity-80">
                          {node.status}
                        </span>
                      )}
                      {node.detail && (
                        <span className="mt-1 block text-[10px] opacity-80">{node.detail}</span>
                      )}
                    </button>
                  </li>
                ))}
                {byKind(column.kind).length === 0 && (
                  <li className="rounded-lg border border-dashed border-ink-200 p-2 text-[11px] text-ink-400">
                    none
                  </li>
                )}
              </ul>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4">
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
          Traced paths ({graph.paths.length})
        </h3>
        <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto text-xs">
          {graph.paths.slice(0, 40).map((path, i) => {
            const labels = path.map(
              (id) => graph.nodes.find((n) => n.id === id)?.label ?? id,
            );
            const relevant = !connected || path.some((id) => connected.has(id));
            return (
              <li
                key={i}
                className={cx(
                  "flex flex-wrap items-center gap-1 rounded border border-ink-100 px-2 py-1",
                  !relevant && "opacity-25",
                )}
              >
                {labels.map((label, j) => (
                  <span key={j} className="flex items-center gap-1">
                    <span className="text-ink-700">{label}</span>
                    {j < labels.length - 1 && (
                      <ArrowRight aria-hidden className="h-3 w-3 text-ink-300" />
                    )}
                  </span>
                ))}
              </li>
            );
          })}
        </ul>
      </div>
    </Card>
  );
}

export function ImpactList({
  impacts,
}: {
  impacts: { id: string; discipline: string; title: string; detail: string; severity: string;
    activities: string[]; commissioning: string[]; requires_human: boolean }[];
}) {
  if (impacts.length === 0) return null;
  return (
    <Card title="Downstream impacts" subtitle="Derived from triggered checks and deltas">
      <ul className="flex flex-col gap-3">
        {impacts.map((impact) => (
          <li key={impact.id} className="rounded-lg border border-ink-200 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="border-sky-300 bg-sky-100 text-sky-900">
                {titleize(impact.discipline)}
              </Badge>
              <p className="text-sm font-medium text-ink-900">{impact.title}</p>
              {impact.requires_human && (
                <Badge className="border-rose-300 bg-rose-100 text-rose-900">
                  human confirmation required
                </Badge>
              )}
            </div>
            <p className="mt-1 text-xs text-ink-600">{impact.detail}</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <div>
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                  Activities
                </h4>
                <ul className="mt-1 list-disc pl-4 text-xs text-ink-700">
                  {impact.activities.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                  Commissioning
                </h4>
                <ul className="mt-1 list-disc pl-4 text-xs text-ink-700">
                  {impact.commissioning.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
