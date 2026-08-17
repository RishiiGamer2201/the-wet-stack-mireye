import { FileText, Globe2, MapPin, UserCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import {
  EVIDENCE_STATUS_LABEL,
  EVIDENCE_STATUS_STYLE,
  fmtTime,
  titleize,
} from "../lib/format";
import type { Evidence } from "../lib/types";
import { Badge, Drawer, EmptyState, ErrorState, Spinner, cx, inputClass } from "./ui";

const SOURCE_ICON: Record<string, typeof FileText> = {
  mireye: Globe2,
  project_document: FileText,
  manufacturer_document: FileText,
  user_input: UserCheck,
};

export function EvidenceRow({ item }: { item: Evidence }) {
  const Icon = SOURCE_ICON[item.source.source_type] ?? FileText;
  return (
    <li className="rounded-lg border border-ink-200 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink-900">{item.claim}</p>
            <p className="tabular text-sm text-ink-700">
              {item.value === null || item.value === undefined ? (
                <span className="italic text-rose-700">no value — not substituted</span>
              ) : (
                <>
                  {String(item.value)} {item.unit ?? ""}
                </>
              )}
            </p>
          </div>
        </div>
        <Badge className={EVIDENCE_STATUS_STYLE[item.status]}>
          {EVIDENCE_STATUS_LABEL[item.status]}
        </Badge>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-ink-600 sm:grid-cols-3">
        <div>
          <dt className="text-ink-400">Source</dt>
          <dd className="truncate" title={item.source.source_name}>
            {titleize(item.source.source_type)} · {item.source.source_name}
          </dd>
        </div>
        {item.source.page != null && (
          <div>
            <dt className="text-ink-400">Location in source</dt>
            <dd>
              page {item.source.page}
              {item.source.span ? ` · chars ${item.source.span.start}–${item.source.span.end}` : ""}
            </dd>
          </div>
        )}
        {item.source.endpoint && (
          <div>
            <dt className="text-ink-400">Endpoint</dt>
            <dd>{item.source.endpoint}</dd>
          </div>
        )}
        <div>
          <dt className="text-ink-400">Retrieved</dt>
          <dd>{fmtTime(item.retrieved_at)}</dd>
        </div>
        {item.observed_at && (
          <div>
            <dt className="text-ink-400">Observed</dt>
            <dd>{fmtTime(item.observed_at)}</dd>
          </div>
        )}
        <div>
          <dt className="text-ink-400">Confidence</dt>
          <dd className="tabular">{(item.confidence * 100).toFixed(0)}%</dd>
        </div>
        {item.latitude != null && (
          <div>
            <dt className="text-ink-400">Location</dt>
            <dd className="tabular inline-flex items-center gap-1">
              <MapPin aria-hidden className="h-3 w-3" />
              {item.latitude.toFixed(4)}, {item.longitude?.toFixed(4)}
              {item.location_resolution ? ` (${item.location_resolution})` : ""}
            </dd>
          </div>
        )}
        <div>
          <dt className="text-ink-400">Verification</dt>
          <dd>{titleize(item.verification)}</dd>
        </div>
      </dl>

      {item.stale_reason && (
        <p className="mt-2 rounded bg-orange-50 px-2 py-1 text-[11px] text-orange-900">
          {item.stale_reason}
        </p>
      )}
      {item.superseded_by && (
        <p className="mt-2 text-[11px] text-violet-800">
          Superseded by a later, user-confirmed value ({item.superseded_by}).
        </p>
      )}
      {item.source.notes && (
        <p className="mt-2 text-[11px] text-ink-500">{item.source.notes}</p>
      )}
    </li>
  );
}

export function EvidenceDrawer({
  open,
  onClose,
  projectId,
  subjectId,
  fieldKey,
  title,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  subjectId?: string;
  fieldKey?: string;
  title: string;
}) {
  const [items, setItems] = useState<Evidence[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!open) return;
    setItems(null);
    setError(null);
    const params: Record<string, string> = {};
    if (subjectId) params.subject_id = subjectId;
    if (fieldKey) params.field_key = fieldKey;
    api.evidence(projectId, params).then(setItems).catch(setError);
  }, [open, projectId, subjectId, fieldKey]);

  const visible = (items ?? []).filter((e) =>
    filter
      ? `${e.claim} ${e.field_key ?? ""} ${e.source.source_name}`
          .toLowerCase()
          .includes(filter.toLowerCase())
      : true,
  );

  return (
    <Drawer open={open} onClose={onClose} title={title}>
      <label htmlFor="evidence-filter" className="sr-only">
        Filter evidence
      </label>
      <input
        id="evidence-filter"
        className={cx(inputClass, "mb-3")}
        placeholder="Filter by claim, field or source…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {error ? <ErrorState error={error} /> : null}
      {!items && !error && <Spinner label="Loading evidence…" />}
      {items && visible.length === 0 && (
        <EmptyState
          title="No evidence recorded yet"
          detail="Run an investigation to collect evidence for this subject."
        />
      )}
      <ul className="flex flex-col gap-2">
        {visible.map((item) => (
          <EvidenceRow key={item.id} item={item} />
        ))}
      </ul>
    </Drawer>
  );
}
