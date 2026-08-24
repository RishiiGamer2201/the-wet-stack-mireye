import { ChevronDown, ChevronUp, HelpCircle, Send } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import { SEVERITY_STYLE, titleize } from "../lib/format";
import type { InformationGap } from "../lib/types";
import { Badge, Button, Card, EmptyState } from "./ui";

export function GapPanel({
  projectId,
  gaps,
  onChanged,
  title = "Missing information",
  defaultExpanded = false,
}: {
  projectId: string;
  gaps: InformationGap[];
  onChanged?: () => void;
  title?: string;
  defaultExpanded?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [busy, setBusy] = useState<string | null>(null);
  const open = gaps.filter((g) => g.status !== "resolved");

  async function mark(gap: InformationGap, status: string) {
    setBusy(gap.id);
    try {
      await api.updateGap(projectId, gap.id, status);
      onChanged?.();
    } finally {
      setBusy(null);
    }
  }

  if (!isExpanded) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-ink-200 bg-ink-50/70 px-4 py-3 shadow-sm transition-all hover:bg-ink-100/50">
        <div className="flex items-center gap-3">
          <div>
            <h3 className="text-sm font-semibold text-ink-800">{title}</h3>
            <p className="text-xs text-ink-500">
              {open.length === 0
                ? "All requested fields are verified."
                : `${open.length} unconfirmed field(s) available for review.`}
            </p>
          </div>
          {open.length > 0 && (
            <Badge className={open.some((g) => g.blocking) ? SEVERITY_STYLE.high : SEVERITY_STYLE.info}>
              {open.length} open · {open.filter((g) => g.blocking).length} blocking
            </Badge>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setIsExpanded(true)}
          className="font-medium"
        >
          <ChevronDown aria-hidden className="mr-1.5 h-3.5 w-3.5 text-ink-500" />
          Show Details ({open.length})
        </Button>
      </div>
    );
  }

  return (
    <Card
      title={title}
      subtitle="Nothing here has been filled in with an assumed value"
      actions={
        <div className="flex items-center gap-2">
          <Badge className={open.some((g) => g.blocking) ? SEVERITY_STYLE.high : SEVERITY_STYLE.info}>
            {open.length} open · {open.filter((g) => g.blocking).length} blocking
          </Badge>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsExpanded(false)}
            className="text-ink-600 hover:text-ink-900"
          >
            <ChevronUp aria-hidden className="mr-1 h-3.5 w-3.5" />
            Hide
          </Button>
        </div>
      }
    >
      {open.length === 0 ? (
        <EmptyState title="No open information gaps" detail="Every requested field was available." />
      ) : (
        <ul className="flex flex-col gap-2">
          {open.map((gap) => (
            <li key={gap.id} className="rounded-lg border border-ink-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink-900">{gap.description}</p>
                  <p className="mt-0.5 flex items-start gap-1 text-xs text-ink-600">
                    <HelpCircle aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
                    {gap.why_it_matters}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <Badge className={SEVERITY_STYLE[gap.severity]}>{gap.severity}</Badge>
                  {gap.blocking && (
                    <Badge className="border-rose-300 bg-rose-100 text-rose-900">blocking</Badge>
                  )}
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
                <span className="font-mono">{gap.field_key}</span>
                <span>·</span>
                <span>expected from {titleize(gap.expected_source)}</span>
                <span>·</span>
                <span>suggested: {titleize(gap.suggested_action)}</span>
                {gap.feature_request_id && (
                  <Badge className="border-sky-300 bg-sky-100 text-sky-900">
                    Mireye feature request {gap.feature_request_id}
                  </Badge>
                )}
                <span className="grow" />
                <Button
                  size="sm"
                  variant="ghost"
                  loading={busy === gap.id}
                  onClick={() => mark(gap, gap.status === "open" ? "requested" : "resolved")}
                >
                  <Send aria-hidden className="h-3 w-3" />
                  {gap.status === "open" ? "Mark requested" : "Mark resolved"}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
