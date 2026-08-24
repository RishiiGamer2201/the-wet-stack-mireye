import { AlertTriangle, MapPin, Play, Plus, RotateCcw, Sparkles, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EvidenceDrawer } from "../components/EvidencePanel";
import { GapPanel } from "../components/GapPanel";
import { DecisionCard, InvestigationTimeline, NextActionPreview } from "../components/Investigation";
import { SiteMap } from "../components/SiteMap";
import { SiteScoutModal } from "../components/SiteScoutModal";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Meter,
  Spinner,
  cx,
  inputClass,
} from "../components/ui";
import { api } from "../lib/api";
import {
  EVIDENCE_STATUS_LABEL,
  EVIDENCE_STATUS_STYLE,
  RISK_STYLE,
  pct,
} from "../lib/format";
import type {
  CandidateSite,
  InformationGap,
  Investigation,
  Meta,
  ProjectDetail,
  SiteRanking,
  SiteScore,
} from "../lib/types";

const RISK_COLOR: Record<string, string> = {
  low: "#059669",
  moderate: "#0284c7",
  elevated: "#d97706",
  high: "#e11d48",
};

// ─── Add Site Modal ────────────────────────────────────────────────────────────

interface AddSiteForm {
  name: string;
  address: string;
  latitude: string;
  longitude: string;
  area_hectares: string;
  notes: string;
}

function AddSiteModal({
  onSave,
  onCancel,
  saving,
  error,
}: {
  onSave: (form: AddSiteForm, runInvestigation?: boolean) => void;
  onCancel: () => void;
  saving: boolean;
  error: unknown;
}) {
  const [form, setForm] = useState<AddSiteForm>({
    name: "",
    address: "",
    latitude: "",
    longitude: "",
    area_hectares: "",
    notes: "",
  });

  const set =
    (field: keyof AddSiteForm) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }));

  const hasCoords = form.latitude !== "" || form.longitude !== "";
  const hasAddress = form.address !== "";

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onCancel} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add candidate site"
        className="relative w-full max-w-lg rounded-2xl border border-ink-200 bg-white shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-ink-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <MapPin className="h-4 w-4 text-emerald-600" aria-hidden />
            <h2 className="text-sm font-semibold text-ink-900">Add Candidate Site</h2>
          </div>
          <button
            onClick={onCancel}
            className="rounded-lg p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700 transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          id="add-site-form"
          onSubmit={(e) => { e.preventDefault(); onSave(form, true); }}
          className="flex flex-col gap-4 px-5 py-4"
        >
          {!!error && (
            <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>{error instanceof Error ? error.message : String(error)}</span>
            </div>
          )}

          <Field label="Site name *" htmlFor="modal-site-name">
            <input
              id="modal-site-name"
              required
              minLength={2}
              className={inputClass}
              value={form.name}
              onChange={set("name")}
              placeholder="e.g. North Valley Parcel"
              autoFocus
            />
          </Field>

          <div className="rounded-lg border border-ink-200 bg-ink-50 p-3">
            <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-500">
              Location - provide an address or coordinates
            </p>
            <div className="flex flex-col gap-3">
              <Field
                label="Address (geocoded via Mireye)"
                htmlFor="modal-site-address"
                hint={hasCoords ? "Coordinates will be used instead." : undefined}
              >
                <input
                  id="modal-site-address"
                  className={cx(inputClass, hasCoords && "opacity-50")}
                  disabled={hasCoords}
                  value={form.address}
                  onChange={set("address")}
                  placeholder="1400 Grant Rd, East Wenatchee, WA"
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Latitude" htmlFor="modal-site-lat">
                  <input
                    id="modal-site-lat"
                    className={cx(inputClass, hasAddress && !hasCoords && "opacity-50")}
                    inputMode="decimal"
                    value={form.latitude}
                    onChange={set("latitude")}
                    placeholder="47.4235"
                  />
                </Field>
                <Field label="Longitude" htmlFor="modal-site-lon">
                  <input
                    id="modal-site-lon"
                    className={cx(inputClass, hasAddress && !hasCoords && "opacity-50")}
                    inputMode="decimal"
                    value={form.longitude}
                    onChange={set("longitude")}
                    placeholder="-120.3103"
                  />
                </Field>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Area (hectares)" htmlFor="modal-site-area" hint="Optional">
              <input
                id="modal-site-area"
                className={inputClass}
                inputMode="decimal"
                value={form.area_hectares}
                onChange={set("area_hectares")}
                placeholder="25"
              />
            </Field>
            <Field label="Notes / Jurisdiction" htmlFor="modal-site-notes" hint="Optional">
              <input
                id="modal-site-notes"
                className={inputClass}
                value={form.notes}
                onChange={set("notes")}
                placeholder="Washington State"
              />
            </Field>
          </div>
        </form>

        <div className="flex items-center justify-between border-t border-ink-100 px-5 py-3">
          <Button variant="secondary" onClick={onCancel} disabled={saving}>Cancel</Button>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              disabled={saving}
              onClick={() => {
                const formEl = document.getElementById("add-site-form") as HTMLFormElement | null;
                if (formEl?.reportValidity()) {
                  onSave(form, false);
                }
              }}
            >
              <MapPin aria-hidden className="h-3.5 w-3.5" />
              Save Site Only
            </Button>
            <Button
              type="button"
              variant="primary"
              loading={saving}
              onClick={() => {
                const formEl = document.getElementById("add-site-form") as HTMLFormElement | null;
                if (formEl?.reportValidity()) {
                  onSave(form, true);
                }
              }}
            >
              <Play aria-hidden className="h-3.5 w-3.5" />
              Save & Run Investigation
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export function BeforeConstruction({
  detail,
  meta,
  onProjectChanged,
  onOpenAdvisor,
  onAdvisorSiteChange,
}: {
  detail: ProjectDetail;
  meta: Meta;
  onProjectChanged: () => void;
  /** Open the app-level advisor, optionally on a specific site. */
  onOpenAdvisor: (siteId: string | null) => void;
  /** Tell the app which candidate is selected, so the advisor follows. */
  onAdvisorSiteChange?: (siteId: string | null) => void;
}) {
  const projectId = detail.project.id;
  const [sites, setSites] = useState<CandidateSite[]>(detail.sites);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [ranking, setRanking] = useState<SiteRanking | null>(null);
  const [gaps, setGaps] = useState<InformationGap[]>([]);
  const [weights, setWeights] = useState<Record<string, number>>(
    detail.project.dimension_weights ?? meta.dimension_weights,
  );
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [investigationFailed, setInvestigationFailed] = useState(false);
  const [selectedSite, setSelectedSite] = useState<string | null>(null);

  // Keep the app-level advisor pointed at whichever candidate is selected here,
  // so opening it from another tab still knows which site is under discussion.
  useEffect(() => {
    onAdvisorSiteChange?.(selectedSite);
  }, [selectedSite, onAdvisorSiteChange]);
  const [whatIf, setWhatIf] = useState<string[]>([]);
  const [evidenceFor, setEvidenceFor] = useState<{ id: string; name: string } | null>(null);
  const [busyOverride, setBusyOverride] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showScoutModal, setShowScoutModal] = useState(false);
  const [savingSite, setSavingSite] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const weightSeq = useRef(0);

  // Separate real (user-added) from synthetic (seeded demo) sites
  const realSites = sites.filter((s) => !s.synthetic);
  const syntheticSites = sites.filter((s) => s.synthetic);
  // Show synthetic as fallback when: no real sites, or live investigation failed
  const showSyntheticFallback = realSites.length === 0 || investigationFailed;
  const visibleSites = showSyntheticFallback ? sites : realSites;

  const refresh = useCallback(async () => {
    const [siteList, gapList, investigations] = await Promise.all([
      api.project(projectId).then((d) => d.sites),
      api.gaps(projectId),
      api.investigations(projectId, "before_construction"),
    ]);
    setSites(siteList);
    setGaps(gapList.filter((g) => siteList.some((s) => s.id === g.subject_id) || !g.subject_id));
    const latest = investigations[0];
    if (latest) {
      setInvestigation(latest);
      if (latest.ranking) setRanking(latest.ranking);
      if (latest.status === "failed") setInvestigationFailed(true);
    }
  }, [projectId]);

  useEffect(() => { refresh().catch(setError); }, [refresh]);

  const scores = ranking?.scores ?? [];
  const leader = scores[0];
  const selected: SiteScore | undefined = scores.find((s) => s.site_id === selectedSite) ?? leader;

  const chartData = useMemo(
    () =>
      scores
        .filter((s) => s.overall_score !== null)
        .map((s) => ({ name: s.site_name, score: s.overall_score ?? 0, risk: s.risk_level })),
    [scores],
  );

  const radarData = useMemo(() => {
    if (!selected) return [];
    return selected.dimensions
      .filter((d) => d.score !== null)
      .map((d) => ({
        dimension: meta.dimension_labels[d.dimension] ?? d.dimension,
        score: Math.round(d.score ?? 0),
      }));
  }, [selected, meta.dimension_labels]);

  async function runInvestigation() {
    setRunning(true);
    setError(null);
    setInvestigationFailed(false);
    try {
      const result = await api.runSiteInvestigation(projectId, { weights });
      setInvestigation(result);
      if (result.ranking) setRanking(result.ranking);
      // If backend investigation failed (Mireye error etc.) show synthetic fallback
      if (result.status === "failed") setInvestigationFailed(true);
      await refresh();
    } catch (e) {
      setError(e);
      setInvestigationFailed(true); // Network/Mireye failure → show synthetic fallback
    } finally {
      setRunning(false);
    }
  }

  async function applyWeights(next: Record<string, number>) {
    setWeights(next);
    if (!ranking) return;
    const seq = ++weightSeq.current;
    try {
      const result = await api.ranking(projectId, { weights: next });
      if (seq !== weightSeq.current) return;
      setRanking(result.ranking);
      setWhatIf(result.explanation);
    } catch (e) {
      if (seq === weightSeq.current) setError(e);
    }
  }

  async function handleSaveSite(form: AddSiteForm, runInvestigationAfter = false) {
    setSavingSite(true);
    setSaveError(null);
    try {
      await api.createSite(projectId, {
        name: form.name,
        address: form.address || null,
        latitude: form.latitude ? Number(form.latitude) : null,
        longitude: form.longitude ? Number(form.longitude) : null,
        area_hectares: form.area_hectares ? Number(form.area_hectares) : null,
        notes: form.notes || null,
      });
      setShowAddModal(false);
      setInvestigationFailed(false); // Real site saved - exit fallback mode
      await refresh();
      onProjectChanged();

      if (runInvestigationAfter) {
        await runInvestigation();
      }
    } catch (e) {
      setSaveError(e);
    } finally {
      setSavingSite(false);
    }
  }

  async function overrideValue(fieldKey: string, value: string) {
    if (!selected) return;
    setBusyOverride(true);
    try {
      const result = await api.override(projectId, selected.site_id, {
        field_key: fieldKey,
        value: Number.isNaN(Number(value)) ? value : Number(value),
        note: "What-if override entered in the UI",
      });
      setRanking(result.ranking);
      setWhatIf(result.explanation);
      await refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusyOverride(false);
    }
  }

  const readyToInvestigate = realSites.length > 0 && !investigation && !running;

  return (
    <div className="flex flex-col gap-4">
      {showAddModal && (
        <AddSiteModal
          onSave={handleSaveSite}
          onCancel={() => { setShowAddModal(false); setSaveError(null); }}
          saving={savingSite}
          error={saveError}
        />
      )}

      {error ? <ErrorState error={error} onRetry={() => refresh().catch(setError)} /> : null}

      {/* Candidate Sites Card */}
      <Card
        title="Candidate sites"
        subtitle={`${realSites.length} real · ${syntheticSites.length} demo (fallback) · broad sweep → shortlist → deep pass`}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <Button
              variant="secondary"
              onClick={() => setShowScoutModal(true)}
              className="border-signal-300 bg-signal-50 text-signal-800 hover:bg-signal-100 font-semibold"
            >
              <Sparkles aria-hidden className="h-3.5 w-3.5 text-signal-600 mr-1" />
              AI Find Sites
            </Button>
            <Button variant="secondary" onClick={() => { setSaveError(null); setShowAddModal(true); }}>
              <Plus aria-hidden className="h-3.5 w-3.5" />
              Add Site
            </Button>
            <Button variant="primary" onClick={runInvestigation} loading={running}>
              <Play aria-hidden className="h-3.5 w-3.5" />
              {investigation ? "Re-run investigation" : "Run investigation"}
            </Button>
          </div>
        }
      >
        {/* Synthetic fallback banner */}
        {showSyntheticFallback && (
          <div className={cx(
            "mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs",
            investigationFailed
              ? "border-rose-200 bg-rose-50 text-rose-800"
              : "border-amber-200 bg-amber-50 text-amber-900",
          )}>
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              {investigationFailed
                ? "The live Mireye investigation failed or returned no data. Showing synthetic demo sites as a fallback - add real sites or resolve the API connection to use live data."
                : 'No real sites added yet. The 5 demo sites below are synthetic placeholders. Click \u201c+ Add Site\u201d to add your actual candidate location and run a live Mireye investigation.'}
            </span>
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
          <SiteMap
            sites={visibleSites}
            scores={scores}
            selectedId={selected?.site_id ?? null}
            onSelect={setSelectedSite}
          />
          <div>
            {/* Real sites */}
            {realSites.length > 0 && (
              <>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                  Your sites ({realSites.length})
                </p>
                <ul className="flex flex-col gap-1">
                  {realSites.map((site) => (
                    <SiteListItem
                      key={site.id}
                      site={site}
                      score={scores.find((sc) => sc.site_id === site.id)}
                      selected={selectedSite === site.id}
                      onSelect={() => setSelectedSite(site.id)}
                      onDelete={async () => { await api.deleteSite(projectId, site.id); await refresh(); }}
                    />
                  ))}
                </ul>
              </>
            )}

            {/* Synthetic fallback sites */}
            {showSyntheticFallback && syntheticSites.length > 0 && (
              <>
                <p className={cx(
                  "mt-3 mb-1 text-[11px] font-semibold uppercase tracking-wide",
                  investigationFailed ? "text-rose-400" : "text-amber-500",
                )}>
                  {investigationFailed ? "Fallback demo sites" : "Example sites (demo)"}
                </p>
                <ul className="flex max-h-44 flex-col gap-1 overflow-y-auto opacity-60">
                  {syntheticSites.map((site) => (
                    <li
                      key={site.id}
                      className="flex items-center justify-between gap-2 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs"
                    >
                      <button className="min-w-0 grow text-left" onClick={() => setSelectedSite(site.id)}>
                        <span className="font-medium text-ink-700">{site.name}</span>
                        <Badge className="ml-1 border-amber-300 bg-amber-100 text-amber-800">synthetic</Badge>
                        <span className="block text-[11px] text-ink-400">
                          {site.latitude?.toFixed(4)}, {site.longitude?.toFixed(4)} · {site.geocode_resolution ?? "unresolved"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {/* Prompt to add first site */}
            {realSites.length === 0 && !investigationFailed && (
              <div className="mt-4 flex flex-col items-start gap-2 rounded-lg border border-dashed border-ink-300 p-3">
                <p className="text-xs text-ink-600">
                  Add your first real candidate location to begin a live investigation.
                </p>
                <Button variant="primary" size="sm" onClick={() => { setSaveError(null); setShowAddModal(true); }}>
                  <Plus aria-hidden className="h-3.5 w-3.5" />
                  Add your first site
                </Button>
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* Ready-to-investigate CTA banner */}
      {readyToInvestigate && (
        <div className="flex items-center justify-between gap-4 rounded-xl border border-emerald-300 bg-gradient-to-r from-emerald-50 to-teal-50 px-4 py-3 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-white">
              <Play className="h-4 w-4" aria-hidden />
            </div>
            <div>
              <p className="text-sm font-semibold text-emerald-900">
                {realSites.length} {realSites.length === 1 ? "site" : "sites"} ready to investigate
              </p>
              <p className="text-xs text-emerald-700">
                Fetch real-world data from Mireye and score all candidates deterministically.
              </p>
            </div>
          </div>
          <Button variant="primary" onClick={runInvestigation} loading={running}>
            <Play aria-hidden className="h-3.5 w-3.5" />
            Run Investigation
          </Button>
        </div>
      )}

      {running && !investigation && <Spinner label="Investigating candidate sites\u2026" />}

      {!investigation && !running && !readyToInvestigate && (
        <Card>
          <EmptyState
            title="No investigation has run yet"
            detail="Run the investigation to fetch physical-world evidence for every candidate, score them and see why one ranks above another."
            action={
              <Button variant="primary" onClick={runInvestigation}>
                <Play aria-hidden className="h-3.5 w-3.5" /> Run investigation
              </Button>
            }
          />
        </Card>
      )}

      {ranking && (
        <>
          <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
            <Card title="Ranking" subtitle="Deterministic weighted score \u2014 the backend recomputes it on every weight change">
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} layout="vertical" margin={{ left: 24, right: 16 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e9ef" />
                    <XAxis type="number" domain={[0, 100]} fontSize={11} />
                    <YAxis type="category" dataKey="name" width={110} fontSize={11} />
                    <Tooltip formatter={(v: number) => [`${v.toFixed(1)} / 100`, "Score"]} />
                    <Bar dataKey="score" radius={[0, 4, 4, 0]}>
                      {chartData.map((entry) => (
                        <Cell key={entry.name} fill={RISK_COLOR[entry.risk] ?? "#475569"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <caption className="sr-only">Candidate site ranking</caption>
                  <thead className="text-ink-500">
                    <tr>
                      <th className="py-1 pr-2 font-medium">#</th>
                      <th className="py-1 pr-2 font-medium">Site</th>
                      <th className="py-1 pr-2 font-medium">Score</th>
                      <th className="py-1 pr-2 font-medium">Risk</th>
                      <th className="py-1 pr-2 font-medium">Coverage</th>
                      <th className="py-1 pr-2 font-medium">Confidence</th>
                      <th className="py-1 font-medium">Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scores.map((score) => (
                      <tr key={score.site_id} className={cx("border-t border-ink-100", selected?.site_id === score.site_id && "bg-ink-50")}>
                        <td className="py-1.5 pr-2 tabular">{score.rank ?? "—"}</td>
                        <td className="py-1.5 pr-2">
                          <button className="font-medium text-ink-900 underline-offset-2 hover:underline" onClick={() => setSelectedSite(score.site_id)}>
                            {score.site_name}
                          </button>
                        </td>
                        <td className="py-1.5 pr-2 tabular font-semibold">{score.overall_score?.toFixed(1) ?? "—"}</td>
                        <td className="py-1.5 pr-2"><Badge className={RISK_STYLE[score.risk_level]}>{score.risk_level}</Badge></td>
                        <td className="py-1.5 pr-2 tabular">{pct(score.evidence_coverage)}</td>
                        <td className="py-1.5 pr-2 tabular">{pct(score.confidence)}</td>
                        <td className="py-1.5">
                          <Button size="sm" variant="ghost" onClick={() => setEvidenceFor({ id: score.site_id, name: score.site_name })}>View</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {ranking.comparisons.length > 0 && (
                <div className="mt-3 rounded-lg border border-ink-200 bg-ink-50 p-2.5">
                  <h3 className="text-xs font-semibold text-ink-700">Why this order</h3>
                  <ul className="mt-1 flex list-disc flex-col gap-1 pl-4 text-xs text-ink-700">
                    {ranking.comparisons.map((c) => <li key={c}>{c}</li>)}
                  </ul>
                </div>
              )}
            </Card>

            <div className="flex flex-col gap-4">
              <Card
                title="Dimension weights (what-if)"
                subtitle="Changing a weight re-scores on the backend against the same evidence"
                actions={
                  <Button size="sm" variant="ghost" onClick={() => applyWeights({ ...meta.dimension_weights })}>
                    <RotateCcw aria-hidden className="h-3.5 w-3.5" /> Reset
                  </Button>
                }
              >
                <div className="flex flex-col gap-2">
                  {Object.entries(meta.dimension_labels).map(([key, label]) => (
                    <div key={key} className="grid grid-cols-[9rem_1fr_2.5rem] items-center gap-2">
                      <label htmlFor={`w-${key}`} className="text-xs text-ink-700">{label}</label>
                      <input
                        id={`w-${key}`}
                        type="range"
                        min={0}
                        max={3}
                        step={0.1}
                        value={weights[key] ?? 1}
                        onChange={(e) => applyWeights({ ...weights, [key]: Number(e.target.value) })}
                        className="accent-ink-900"
                      />
                      <span className="tabular text-xs text-ink-600">{(weights[key] ?? 1).toFixed(1)}</span>
                    </div>
                  ))}
                </div>
                {whatIf.length > 0 && (
                  <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 p-2.5 text-xs text-sky-900">
                    <p className="font-semibold">Effect of the change</p>
                    <ul className="mt-1 list-disc pl-4">{whatIf.map((line) => <li key={line}>{line}</li>)}</ul>
                  </div>
                )}
              </Card>

              {selected && (
                <Card title={`Dimension profile \u2014 ${selected.site_name}`} subtitle={selected.summary}>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <RadarChart data={radarData} outerRadius="75%">
                        <PolarGrid stroke="#e5e9ef" />
                        <PolarAngleAxis dataKey="dimension" fontSize={10} />
                        <Radar dataKey="score" stroke="#0b7565" fill="#0f8f7a" fillOpacity={0.35} />
                        <Tooltip formatter={(v: number) => [`${v}/100`, "Score"]} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
              )}
            </div>
          </div>

          {selected && (
            <Card
              title={`Evidence detail \u2014 ${selected.site_name}`}
              subtitle="Every metric shows its value, how it was normalised and the status of its evidence"
              actions={<Badge className={RISK_STYLE[selected.risk_level]}>{selected.risk_level} risk</Badge>}
            >
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {selected.dimensions
                  .map((dim) => ({
                    ...dim,
                    metrics: dim.metrics.filter(
                      (m) => m.status !== "missing" && m.raw_value !== null && m.raw_value !== undefined,
                    ),
                  }))
                  .filter((dim) => dim.metrics.length > 0 || (dim.score !== null && dim.score > 0))
                  .map((dimension) => (
                  <div key={dimension.dimension} className="rounded-lg border border-ink-200 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-xs font-semibold text-ink-800">{meta.dimension_labels[dimension.dimension] ?? dimension.dimension}</h3>
                      <span className="tabular text-sm font-semibold text-ink-900">{dimension.score?.toFixed(0) ?? "—"}</span>
                    </div>
                    <Meter value={dimension.score ?? 0} className="mt-2 bg-signal-600" />
                    <p className="mt-1 text-[11px] text-ink-500">weight {dimension.weight.toFixed(1)} · coverage {pct(dimension.coverage)}</p>
                    <ul className="mt-2 flex flex-col gap-1">
                      {dimension.metrics.map((metric) => (
                        <li key={metric.field_key} className="text-[11px]">
                          <div className="flex items-center justify-between gap-1">
                            <span className="truncate text-ink-700 font-medium" title={metric.explanation}>{metric.label}</span>
                            <Badge className={EVIDENCE_STATUS_STYLE[metric.status]}>
                              {metric.normalized?.toFixed(0) ?? "—"}
                            </Badge>
                          </div>
                          <p className="text-ink-500">
                            {`${metric.raw_value} ${metric.unit && metric.unit !== "dimensionless" ? metric.unit : ""} · ${EVIDENCE_STATUS_LABEL[metric.status]}`}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>

              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">Project target checks</h3>
                  <ul className="mt-2 flex flex-col gap-1 text-xs">
                    {selected.requirement_flags.map((flag) => (
                      <li
                        key={flag.requirement}
                        className={cx(
                          "rounded border p-2",
                          flag.passed === true && "border-emerald-200 bg-emerald-50",
                          flag.passed === false && "border-rose-200 bg-rose-50",
                          flag.passed === null && "border-amber-200 bg-amber-50",
                        )}
                      >
                        <span className="font-medium">{flag.requirement}</span> — {flag.explanation}
                      </li>
                    ))}
                    {selected.requirement_flags.length === 0 && <li className="text-ink-500">No hard targets set on this project.</li>}
                  </ul>
                </div>
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">What-if: correct one site assumption</h3>
                  <WhatIfOverride
                    busy={busyOverride}
                    fields={selected.dimensions.flatMap((d) =>
                      d.metrics.map((m) => ({
                        key: m.field_key,
                        label: `${meta.dimension_labels[d.dimension] ?? d.dimension}: ${m.label}`,
                      })),
                    )}
                    onApply={overrideValue}
                  />
                  <p className="mt-2 text-[11px] text-ink-500">
                    The override is stored as user-confirmed evidence (the previous value is kept and marked superseded), then the backend re-scores every candidate.
                  </p>
                  {whatIf.length > 0 && (
                    <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-900">
                      <p className="font-semibold">Latest re-scoring result:</p>
                      <ul className="mt-1 list-disc pl-4">
                        {whatIf.map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          )}

          <GapPanel projectId={projectId} gaps={gaps} onChanged={refresh} />
        </>
      )}

      {investigation && (
        <>
          <div className="grid gap-4 xl:grid-cols-2">
            <DecisionCard investigation={investigation} />
            <NextActionPreview actions={investigation.next_actions} />
          </div>
          <InvestigationTimeline investigation={investigation} />
        </>
      )}

      <EvidenceDrawer
        open={!!evidenceFor}
        onClose={() => setEvidenceFor(null)}
        projectId={projectId}
        subjectId={evidenceFor?.id}
        title={`Evidence - ${evidenceFor?.name ?? ""}`}
      />

      {/* AI Site Scout Modal */}
      {showScoutModal && (
        <SiteScoutModal
          detail={detail}
          onClose={() => setShowScoutModal(false)}
          onSiteAdded={async () => {
            await refresh();
            onProjectChanged();
          }}
          onOpenAdvisor={(siteId) => onOpenAdvisor(siteId ?? selectedSite ?? null)}
        />
      )}

    </div>
  );
}

// ─── Site List Item ──────────────────────────────────────────────────────────

function SiteListItem({
  site,
  score,
  selected,
  onSelect,
  onDelete,
}: {
  site: CandidateSite;
  score?: SiteScore;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const hasScore = score && score.overall_score !== null;
  return (
    <li className={cx(
      "flex items-center justify-between gap-2 rounded border px-2 py-1.5 text-xs transition-colors",
      selected ? "border-emerald-300 bg-emerald-50" : "border-ink-100 hover:bg-ink-50",
    )}>
      <button className="min-w-0 grow text-left" onClick={onSelect}>
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-medium text-ink-800">{site.name}</span>
          {site.shortlisted && <Badge className="border-ink-300 bg-ink-100 text-ink-700">shortlisted</Badge>}
          {hasScore ? (
            <Badge className="border-emerald-200 bg-emerald-100 text-emerald-800 font-semibold">
              Score: {score.overall_score?.toFixed(1)}
            </Badge>
          ) : (
            <Badge className="border-amber-200 bg-amber-50 text-amber-800">
              Pending investigation
            </Badge>
          )}
        </div>
        <span className="block text-[11px] text-ink-500 mt-0.5">
          {site.latitude?.toFixed(4)}, {site.longitude?.toFixed(4)} · {site.geocode_resolution ?? "unresolved"}
        </span>
      </button>
      <Button size="sm" variant="ghost" aria-label={`Remove ${site.name}`} onClick={onDelete}>
        <Trash2 aria-hidden className="h-3.5 w-3.5 text-rose-500" />
      </Button>
    </li>
  );
}

// ─── What-if Override ────────────────────────────────────────────────────────

function WhatIfOverride({
  fields,
  onApply,
  busy,
}: {
  fields: { key: string; label: string }[];
  onApply: (fieldKey: string, value: string) => void;
  busy: boolean;
}) {
  const [fieldKey, setFieldKey] = useState(fields[0]?.key ?? "");
  const [value, setValue] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    if (!fieldKey || !fields.some((f) => f.key === fieldKey)) {
      if (fields[0]?.key) {
        setFieldKey(fields[0].key);
      }
    }
  }, [fields, fieldKey]);

  const activeKey = fieldKey || fields[0]?.key || "";

  return (
    <form
      className="mt-2 flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (activeKey && value.trim()) {
          onApply(activeKey, value.trim());
          const targetLabel = fields.find((f) => f.key === activeKey)?.label || activeKey;
          setFeedback(`Applied ${targetLabel}: ${value.trim()}`);
          setValue("");
        }
      }}
    >
      <Field label="Field / Parameter" htmlFor="override-field">
        <select
          id="override-field"
          className={cx(inputClass, "max-w-[14rem]")}
          value={activeKey}
          onChange={(e) => {
            setFieldKey(e.target.value);
            setFeedback(null);
          }}
        >
          {fields.map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Confirmed value" htmlFor="override-value">
        <input
          id="override-value"
          className={inputClass}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setFeedback(null);
          }}
          placeholder="e.g. 450 or 0.15"
          required
        />
      </Field>
      <Button type="submit" loading={busy} variant="primary">
        <Sparkles aria-hidden className="h-3.5 w-3.5" /> Apply &amp; re-rank
      </Button>
      {feedback && (
        <span className="text-[11px] font-medium text-emerald-600 basis-full">
          ✓ {feedback}
        </span>
      )}
    </form>
  );
}
