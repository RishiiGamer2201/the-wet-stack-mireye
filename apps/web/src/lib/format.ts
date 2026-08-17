import type { CheckStatus, DecisionState, EvidenceStatus, Quantity, Severity } from "./types";

export const isQuantity = (v: unknown): v is Quantity =>
  typeof v === "object" && v !== null && "value" in v && "unit" in v;

/** Pint writes exponents as `m ** 2`; render them as `m²` for display only. */
const prettyUnit = (unit: string) =>
  unit.replace(/\s*\*\*\s*2\b/g, "²").replace(/\s*\*\*\s*3\b/g, "³").replace(/\s*\*\s*/g, "·");

export function fmtQuantity(value: Quantity | string | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (!isQuantity(value)) return String(value);
  const rounded =
    Math.abs(value.value) >= 1000 ? Math.round(value.value) : Number(value.value.toFixed(digits));
  return `${rounded.toLocaleString()} ${prettyUnit(value.unit)}`;
}

export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;

export const signedPct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

export const EVIDENCE_STATUS_LABEL: Record<EvidenceStatus, string> = {
  live: "Live",
  cached: "Cached",
  synthetic: "Synthetic demo",
  fallback: "Fallback (live failed)",
  user_confirmed: "User confirmed",
  missing: "Missing",
  stale: "Stale",
};

export const EVIDENCE_STATUS_STYLE: Record<EvidenceStatus, string> = {
  live: "bg-emerald-100 text-emerald-900 border-emerald-300",
  cached: "bg-sky-100 text-sky-900 border-sky-300",
  synthetic: "bg-amber-100 text-amber-900 border-amber-300",
  // Deliberately not the emerald of `live`: a stand-in must never read as data.
  fallback: "bg-fuchsia-100 text-fuchsia-900 border-fuchsia-300",
  user_confirmed: "bg-violet-100 text-violet-900 border-violet-300",
  missing: "bg-rose-100 text-rose-900 border-rose-300",
  stale: "bg-orange-100 text-orange-900 border-orange-300",
};

export const CHECK_STATUS_STYLE: Record<CheckStatus, string> = {
  CLOSED: "bg-emerald-100 text-emerald-900 border-emerald-300",
  OPEN: "bg-amber-100 text-amber-900 border-amber-300",
  TRIGGERED: "bg-rose-100 text-rose-900 border-rose-300",
  SKIPPED: "bg-ink-100 text-ink-600 border-ink-300",
};

export const SEVERITY_STYLE: Record<Severity, string> = {
  info: "bg-ink-100 text-ink-700 border-ink-300",
  low: "bg-sky-100 text-sky-900 border-sky-300",
  medium: "bg-amber-100 text-amber-900 border-amber-300",
  high: "bg-orange-100 text-orange-900 border-orange-300",
  critical: "bg-rose-100 text-rose-900 border-rose-300",
};

export const DECISION_STYLE: Record<DecisionState, string> = {
  "FIRST-PASS CHECKS CLOSED": "border-emerald-400 bg-emerald-50",
  "NEEDS INFORMATION": "border-amber-400 bg-amber-50",
  "ENGINEER REVIEW": "border-rose-400 bg-rose-50",
};

export const RISK_STYLE: Record<string, string> = {
  low: "bg-emerald-100 text-emerald-900 border-emerald-300",
  moderate: "bg-sky-100 text-sky-900 border-sky-300",
  elevated: "bg-amber-100 text-amber-900 border-amber-300",
  high: "bg-rose-100 text-rose-900 border-rose-300",
};

export const titleize = (s: string) =>
  s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const fmtTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";

export const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";
