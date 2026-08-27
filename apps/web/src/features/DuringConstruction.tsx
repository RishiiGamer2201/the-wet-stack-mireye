import {
  ArrowRight,
  BookOpen,
  Check,
  CheckCheck,
  Clock,
  CloudSun,
  Copy,
  Database,
  FileText,
  Layers,
  ListChecks,
  Play,
  Send,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EvidenceDrawer } from "../components/EvidencePanel";
import { GapPanel } from "../components/GapPanel";
import { DecisionCard, InvestigationTimeline, NextActionPreview } from "../components/Investigation";
import { ImpactGraphView, ImpactList } from "../components/ImpactGraphView";
import { ProjectKnowledgeAgent } from "./ProjectKnowledgeAgent";
import { ConstructionPlanner } from "./ConstructionPlanner";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Spinner,
  cx,
  inputClass,
} from "../components/ui";
import { api } from "../lib/api";
import {
  CHECK_STATUS_STYLE,
  SEVERITY_STYLE,
  fmtQuantity,
  signedPct,
  titleize,
} from "../lib/format";
import type {
  ActionPackageResponse,
  CandidateSite,
  CandidateProduct,
  CascadeImpactSummary,
  ChangeDetail,
  ClimateStationInfo,
  CostScheduleImpact,
  DecisionLineageRecord,
  DesignMargin,
  EquipmentChange,
  EquipmentConfiguration,
  ImpactGraph,
  InformationGap,
  Investigation,
  ProductRecommendationResult,
  ProjectDetail,
  ReferenceSpec,
  Requirement,
  StructuredRequirementSet,
} from "../lib/types";

export type DuringTab = "planner" | "verification" | "recommendations" | "cascade" | "actions" | "knowledge";

const COMPARE_ROWS: {
  key: keyof EquipmentConfiguration;
  label: string;
  kind: "quantity" | "text";
}[] = [
  { key: "manufacturer", label: "Manufacturer", kind: "text" },
  { key: "model_number", label: "Model number", kind: "text" },
  { key: "equipment_type", label: "Equipment type", kind: "text" },
  { key: "configuration_code", label: "Configuration", kind: "text" },
  { key: "circuits", label: "Refrigerant circuits", kind: "text" },
  { key: "weight", label: "Weight", kind: "quantity" },
  { key: "weight_basis", label: "Weight basis", kind: "text" },
  { key: "length", label: "Length", kind: "quantity" },
  { key: "width", label: "Width", kind: "quantity" },
  { key: "height", label: "Height", kind: "quantity" },
  { key: "voltage", label: "Voltage", kind: "quantity" },
  { key: "phases", label: "Phases", kind: "text" },
  { key: "full_load_amps", label: "Full load amps", kind: "quantity" },
  { key: "mca", label: "MCA", kind: "quantity" },
  { key: "mocp", label: "MOCP", kind: "quantity" },
  { key: "power_input", label: "Power input", kind: "quantity" },
  { key: "refrigerant_type", label: "Refrigerant", kind: "text" },
  { key: "refrigerant_charge", label: "Refrigerant charge", kind: "quantity" },
  { key: "cooling_capacity", label: "Cooling capacity", kind: "quantity" },
];

function cell(config: EquipmentConfiguration, key: keyof EquipmentConfiguration, kind: string) {
  const raw = config[key];
  if (raw === null || raw === undefined || raw === "")
    return <span className="italic text-rose-700">not supplied</span>;
  if (kind === "quantity") return <span className="tabular">{fmtQuantity(raw as never)}</span>;
  return <span>{String(raw)}</span>;
}

export function DuringConstruction({
  detail,
  onProjectChanged,
}: {
  detail: ProjectDetail;
  onProjectChanged?: () => void;
}) {
  const projectId = detail.project.id;
  const [tab, setTab] = useState<DuringTab>("planner");
  const [changes, setChanges] = useState<EquipmentChange[]>(detail.changes);
  const [selectedId, setSelectedId] = useState<string | null>(detail.changes[0]?.id ?? null);
  const [change, setChange] = useState<ChangeDetail | null>(null);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [graph, setGraph] = useState<ImpactGraph | null>(null);
  const [gaps, setGaps] = useState<InformationGap[]>([]);
  const [climateStation, setClimateStation] = useState<ClimateStationInfo | null>(null);
  const [refSpec, setRefSpec] = useState<ReferenceSpec | null>(null);
  const [marginsList, setMarginsList] = useState<DesignMargin[]>([]);
  const [lineage, setLineage] = useState<DecisionLineageRecord[]>([]);
  const [costSchedule, setCostSchedule] = useState<CostScheduleImpact | null>(null);
  const [cascade, setCascade] = useState<CascadeImpactSummary | null>(null);
  const [autofilling, setAutofilling] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [evidenceFor, setEvidenceFor] = useState<{ id: string; name: string } | null>(null);

  const load = useCallback(
    async (changeId: string) => {
      setError(null);
      setGraph(null);
      setInvestigation(null);
      setClimateStation(null);
      setRefSpec(null);
      setMarginsList([]);
      setLineage([]);
      setCostSchedule(null);
      try {
        const [changeDetail, allGaps] = await Promise.all([
          api.change(projectId, changeId),
          api.gaps(projectId),
        ]);
        setChange(changeDetail);
        setGaps(allGaps.filter((g) => g.subject_id === changeId));

        if (changeDetail.site?.latitude && changeDetail.site?.longitude) {
          api.climateStation(projectId, changeId).then(setClimateStation).catch(() => setClimateStation(null));
        }

        api.referenceSpecs(changeDetail.change.equipment_tag).then(setRefSpec).catch(() => setRefSpec(null));

        api.changeMargins(projectId, changeId).then(setMarginsList).catch(() => setMarginsList([]));
        api.changeLineage(projectId, changeId).then(setLineage).catch(() => setLineage([]));
        api.changeCostSchedule(projectId, changeId).then(setCostSchedule).catch(() => setCostSchedule(null));

        if (changeDetail.latest_investigation_id) {
          const found = await api.investigation(projectId, changeDetail.latest_investigation_id);
          setInvestigation(found);
          await api.impact(changeId).then(setGraph).catch(() => setGraph(null));
        }
      } catch (e) {
        setError(e);
      }
    },
    [projectId],
  );

  const refreshCascade = useCallback(async () => {
    try {
      const summary = await api.cascadeAnalysis(projectId);
      setCascade(summary);
    } catch {
      setCascade(null);
    }
  }, [projectId]);

  useEffect(() => {
    api.changes(projectId).then(setChanges).catch(setError);
    refreshCascade();
  }, [projectId, refreshCascade]);

  useEffect(() => {
    if (selectedId) load(selectedId);
  }, [selectedId, load]);

  async function analyze() {
    if (!selectedId) return;
    setRunning(true);
    setError(null);
    try {
      const result = await api.analyzeChange(projectId, selectedId);
      setInvestigation(result);
      const [impactGraph, allGaps, changeDetail, marginsRes, lineageRes, costRes] = await Promise.all([
        api.impact(selectedId).catch(() => null),
        api.gaps(projectId),
        api.change(projectId, selectedId),
        api.changeMargins(projectId, selectedId).catch(() => []),
        api.changeLineage(projectId, selectedId).catch(() => []),
        api.changeCostSchedule(projectId, selectedId).catch(() => null),
      ]);
      setGraph(impactGraph);
      setChange(changeDetail);
      setGaps(allGaps.filter((g) => g.subject_id === selectedId));
      setMarginsList(marginsRes);
      setLineage(lineageRes);
      setCostSchedule(costRes);
      refreshCascade();
    } catch (e) {
      setError(e);
    } finally {
      setRunning(false);
    }
  }

  async function handleAutofill() {
    if (!selectedId) return;
    setAutofilling(true);
    setError(null);
    try {
      const updatedInv = await api.autofillFromReference(projectId, selectedId);
      setInvestigation(updatedInv);
      const [impactGraph, allGaps, changeDetail, marginsRes, lineageRes, costRes] = await Promise.all([
        api.impact(selectedId).catch(() => null),
        api.gaps(projectId),
        api.change(projectId, selectedId),
        api.changeMargins(projectId, selectedId).catch(() => []),
        api.changeLineage(projectId, selectedId).catch(() => []),
        api.changeCostSchedule(projectId, selectedId).catch(() => null),
      ]);
      setGraph(impactGraph);
      setChange(changeDetail);
      setGaps(allGaps.filter((g) => g.subject_id === selectedId));
      setMarginsList(marginsRes);
      setLineage(lineageRes);
      setCostSchedule(costRes);
      refreshCascade();
    } catch (e) {
      setError(e);
    } finally {
      setAutofilling(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ─── WORKFLOW TAB NAVIGATION ─── */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-200 bg-white p-3 rounded-xl shadow-xs">
        <div className="flex items-center gap-1.5 overflow-x-auto">
          <button
            onClick={() => setTab("planner")}
            className={cx(
              "flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg transition-all",
              tab === "planner"
                ? "bg-signal-600 text-white shadow-xs"
                : "text-ink-600 hover:text-ink-900 hover:bg-ink-100",
            )}
          >
            <ListChecks className="h-4 w-4" /> Site Equipment Plan
          </button>
          <button
            onClick={() => setTab("verification")}
            className={cx(
              "flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg transition-all",
              tab === "verification"
                ? "bg-ink-900 text-white shadow-xs"
                : "text-ink-600 hover:text-ink-900 hover:bg-ink-100",
            )}
          >
            <ShieldCheck className="h-4 w-4" /> Verify Existing Changes
          </button>
          <button
            onClick={() => setTab("recommendations")}
            className={cx(
              "flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg transition-all",
              tab === "recommendations"
                ? "bg-sky-600 text-white shadow-xs"
                : "text-ink-600 hover:text-ink-900 hover:bg-ink-100",
            )}
          >
            <Sparkles className="h-4 w-4 text-amber-300" /> Replace Equipment
          </button>
          <button
            onClick={() => setTab("cascade")}
            className={cx(
              "flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg transition-all",
              tab === "cascade"
                ? "bg-indigo-600 text-white shadow-xs"
                : "text-ink-600 hover:text-ink-900 hover:bg-ink-100",
            )}
          >
            <Layers className="h-4 w-4" /> Combined Load Check
          </button>
          <button
            onClick={() => setTab("actions")}
            className={cx(
              "flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg transition-all",
              tab === "actions"
                ? "bg-teal-700 text-white shadow-xs"
                : "text-ink-600 hover:text-ink-900 hover:bg-ink-100",
            )}
          >
            <FileText className="h-4 w-4" /> RFIs &amp; Actions
          </button>
          <button
            onClick={() => setTab("knowledge")}
            className={cx(
              "flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg transition-all",
              tab === "knowledge"
                ? "bg-purple-700 text-white shadow-xs"
                : "text-ink-600 hover:text-ink-900 hover:bg-ink-100",
            )}
          >
            <BookOpen className="h-4 w-4" /> Project Data
          </button>
        </div>

        <div className="flex items-center gap-2 text-xs text-ink-500">
          <Badge className="border-ink-200 bg-ink-50 text-ink-700">
            {changes.length} Active Substitution(s)
          </Badge>
        </div>
      </div>

      {error ? <ErrorState error={error} onRetry={() => selectedId && load(selectedId)} /> : null}

      {tab === "planner" && (
        <ConstructionPlanner
          projectId={projectId}
          sites={detail.sites}
          defaultItLoadMw={detail.project.targets.it_load_mw}
          onSiteCreated={onProjectChanged}
        />
      )}

      {/* ────────────────────────────────────────────────────────────────────────── */}
      {/* TAB 1: CHANGE INTELLIGENCE & VERIFICATION                                  */}
      {/* ────────────────────────────────────────────────────────────────────────── */}
      {tab === "verification" && (
        <>
          <Card title="Equipment change cases" subtitle="Select a substitution case to analyze">
            <div className="grid gap-2 md:grid-cols-3">
              {changes.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  aria-pressed={selectedId === item.id}
                  className={cx(
                    "rounded-lg border p-3 text-left transition-all",
                    selectedId === item.id
                      ? "border-sky-600 bg-sky-50/50 shadow-xs"
                      : "border-ink-200 hover:border-ink-400 bg-white",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Badge className="border-ink-300 bg-white text-ink-800 font-mono">{item.equipment_tag}</Badge>
                    {item.synthetic && (
                      <Badge className="border-amber-300 bg-amber-100 text-amber-900">synthetic</Badge>
                    )}
                    <Badge className="border-ink-200 bg-ink-100 text-ink-600">{item.status}</Badge>
                  </div>
                  <p className="mt-1.5 text-sm font-medium text-ink-900 line-clamp-1">{item.title}</p>
                  <p className="mt-0.5 text-xs text-ink-500 line-clamp-1">{item.reason}</p>
                </button>
              ))}
            </div>
          </Card>

          {!change && <Spinner label="Loading change case…" />}

          {change && (
            <>
              {/* SIDE BY SIDE SPEC COMPARISON */}
              <Card
                title={`Old vs Proposed - ${change.change.equipment_tag}`}
                subtitle={
                  change.site
                    ? `Linked site: ${change.site.name} (${change.site.geocode_resolution ?? "unresolved"})`
                    : "No site linked - site-dependent checks will be skipped"
                }
                actions={
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setEvidenceFor({ id: change.change.equipment_tag, name: change.change.equipment_tag })
                      }
                    >
                      <FileText aria-hidden className="h-3.5 w-3.5 mr-1" /> Evidence
                    </Button>
                    <Button variant="primary" onClick={analyze} loading={running}>
                      <Play aria-hidden className="h-3.5 w-3.5 mr-1" />
                      {investigation ? "Re-run Analysis" : "Run Analysis"}
                    </Button>
                  </div>
                }
              >
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[40rem] text-left text-xs">
                    <caption className="sr-only">Existing versus proposed equipment</caption>
                    <thead className="text-ink-500">
                      <tr>
                        <th className="py-1 pr-3 font-medium">Property</th>
                        <th className="py-1 pr-3 font-medium">
                          Existing - {change.existing.configuration.model_number ?? "-"}
                        </th>
                        <th className="py-1 pr-3 font-medium">
                          Proposed - {change.proposed.configuration.model_number ?? "-"}
                        </th>
                        <th className="py-1 font-medium">Delta</th>
                      </tr>
                    </thead>
                    <tbody>
                      {COMPARE_ROWS.map((row) => {
                        const delta = investigation?.deltas.find(
                          (d) => d.field === row.key || (row.key === "weight" && d.field === "weight"),
                        );
                        return (
                          <tr key={row.key} className="border-t border-ink-100">
                            <td className="py-1.5 pr-3 text-ink-600">{row.label}</td>
                            <td className="py-1.5 pr-3">
                              {cell(change.existing.configuration, row.key, row.kind)}
                            </td>
                            <td className="py-1.5 pr-3">
                              {cell(change.proposed.configuration, row.key, row.kind)}
                            </td>
                            <td className="py-1.5">
                              {delta ? (
                                <span className="inline-flex items-center gap-1">
                                  <Badge className={CHECK_STATUS_STYLE[delta.status]}>{delta.status}</Badge>
                                  {delta.percent_delta != null && (
                                    <span className="tabular text-ink-700">
                                      {signedPct(delta.percent_delta)}
                                    </span>
                                  )}
                                </span>
                              ) : (
                                <span className="text-ink-300">-</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Open Catalog Auto-fill prompt if gaps exist */}
                {refSpec && (
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-sky-200 bg-sky-50/70 p-3 text-xs">
                    <div className="flex items-start gap-2.5">
                      <Database className="h-4 w-4 text-sky-600 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-semibold text-sky-900">
                          Synthetic Prototype Benchmark: {refSpec.model_number ?? refSpec.reference_model ?? refSpec.id}
                        </span>
                        <p className="text-sky-700 text-[11px] mt-0.5">
                          {refSpec.description} Replace every auto-filled value with a certified manufacturer submittal before review.
                        </p>
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="primary"
                      loading={autofilling}
                      onClick={handleAutofill}
                      className="bg-sky-600 hover:bg-sky-700 text-white shrink-0 font-medium"
                    >
                      <Sparkles aria-hidden className="h-3.5 w-3.5 mr-1" />
                      Auto-fill Synthetic Demo Gaps
                    </Button>
                  </div>
                )}
              </Card>

              {/* SITE CLIMATE CARD */}
              {climateStation && (
                <Card
                  title="Prototype Climate Design Context"
                  subtitle={`Nearest bundled station: ${climateStation.name} (${climateStation.distance_km} km away, elevation ${climateStation.elevation_m}m)`}
                  actions={
                    <Badge className="border-sky-300 bg-sky-50 text-sky-800">
                      <CloudSun className="h-3.5 w-3.5 mr-1 inline" /> verify source #{climateStation.station_id}
                    </Badge>
                  }
                >
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                    <div className="rounded-lg border border-ink-200 bg-white p-2.5">
                      <span className="text-ink-500 block text-[11px]">Extreme Summer Cooling (0.4%)</span>
                      <span className="text-base font-bold text-ink-900 mt-1 block">
                        {climateStation.cooling_db_0_4_pct_degc}°C DB
                      </span>
                      <span className="text-[10px] text-ink-400">Peak dry-bulb design</span>
                    </div>
                    <div className="rounded-lg border border-ink-200 bg-white p-2.5">
                      <span className="text-ink-500 block text-[11px]">Coincident Wet-Bulb (0.4%)</span>
                      <span className="text-base font-bold text-sky-700 mt-1 block">
                        {climateStation.cooling_wb_0_4_pct_degc}°C WB
                      </span>
                      <span className="text-[10px] text-ink-400">Evaporative limit</span>
                    </div>
                    <div className="rounded-lg border border-ink-200 bg-white p-2.5">
                      <span className="text-ink-500 block text-[11px]">Standard Cooling (1.0%)</span>
                      <span className="text-base font-bold text-ink-800 mt-1 block">
                        {climateStation.cooling_db_1_0_pct_degc}°C DB
                      </span>
                      <span className="text-[10px] text-ink-400">Annual 99.0% exceedance</span>
                    </div>
                    <div className="rounded-lg border border-ink-200 bg-white p-2.5">
                      <span className="text-ink-500 block text-[11px]">Extreme Winter (99.6%)</span>
                      <span className="text-base font-bold text-rose-700 mt-1 block">
                        {climateStation.heating_db_99_6_pct_degc}°C DB
                      </span>
                      <span className="text-[10px] text-ink-400">Lowest design temp</span>
                    </div>
                  </div>
                </Card>
              )}

              {/* DETERMINISTIC DESIGN MARGINS PANEL */}
              <DesignMarginsPanel margins={marginsList} />

              {/* COST & SCHEDULE IMPACT */}
              {costSchedule && <CostScheduleCard impact={costSchedule} />}

              {/* EXTRACTED REQUIREMENTS PANEL */}
              <RequirementsPanel
                projectId={projectId}
                requirements={change.requirements}
                onChanged={() => selectedId && load(selectedId)}
              />

              {running && <Spinner label="Running verification gates, Pint deltas, design margins and impact graph…" />}

              {investigation && (
                <>
                  <div className="grid gap-4 xl:grid-cols-2">
                    <Card
                      title="9 Deterministic Verification Gates"
                      subtitle="Pre-comparison gates that must pass before delta verification"
                    >
                      <ul className="flex flex-col gap-2">
                        {investigation.checks.map((check) => (
                          <li key={check.id} className="rounded-lg border border-ink-200 p-2.5">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-sm font-medium text-ink-900">{check.name}</p>
                              <div className="flex items-center gap-1">
                                <Badge className={SEVERITY_STYLE[check.severity]}>{check.severity}</Badge>
                                <Badge className={CHECK_STATUS_STYLE[check.status]}>{check.status}</Badge>
                              </div>
                            </div>
                            <p className="mt-1 text-xs text-ink-600">{check.detail}</p>
                          </li>
                        ))}
                      </ul>
                    </Card>

                    <Card
                      title="15 Pint-Checked Deterministic Deltas"
                      subtitle="Unit-safe physical & electrical differences"
                    >
                      <div className="overflow-x-auto">
                        <table className="w-full text-left text-xs">
                          <thead className="text-ink-500">
                            <tr>
                              <th className="py-1 pr-2 font-medium">Property</th>
                              <th className="py-1 pr-2 font-medium">Existing</th>
                              <th className="py-1 pr-2 font-medium">Proposed</th>
                              <th className="py-1 pr-2 font-medium">Δ%</th>
                              <th className="py-1 font-medium">Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {investigation.deltas.map((delta) => (
                              <tr key={delta.field} className="border-t border-ink-100">
                                <td className="py-1.5 pr-2 text-ink-700">{delta.label}</td>
                                <td className="py-1.5 pr-2 tabular">{fmtQuantity(delta.old_value)}</td>
                                <td className="py-1.5 pr-2 tabular">{fmtQuantity(delta.new_value)}</td>
                                <td className="py-1.5 pr-2 tabular">{signedPct(delta.percent_delta)}</td>
                                <td className="py-1.5">
                                  <Badge className={CHECK_STATUS_STYLE[delta.status]}>{delta.status}</Badge>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </Card>
                  </div>

                  <div className="grid gap-4 xl:grid-cols-2">
                    <DecisionCard investigation={investigation} />
                    <NextActionPreview actions={investigation.next_actions} />
                  </div>

                  <StaleAssumptions
                    assumptions={change.assumptions}
                    staleIds={investigation.stale_assumption_ids}
                  />

                  <ImpactList impacts={investigation.impacts} />
                  <ImpactGraphView
                    graph={graph}
                    changeLabel={change ? `${change.change.equipment_tag}: ${change.change.title}` : undefined}
                    impacts={investigation.impacts}
                    assumptions={change.assumptions}
                  />

                  {/* DECISION LINEAGE & AUDIT LOG */}
                  {lineage.length > 0 && <DecisionLineageCard lineage={lineage} />}

                  <GapPanel
                    projectId={projectId}
                    gaps={gaps}
                    onChanged={() => selectedId && load(selectedId)}
                    title="Missing Information Gaps for this Change"
                  />
                  <InvestigationTimeline investigation={investigation} />
                </>
              )}
            </>
          )}
        </>
      )}

      {/* ────────────────────────────────────────────────────────────────────────── */}
      {/* TAB 2: RECOMMENDATION & REQUIREMENT STUDIO                                  */}
      {/* ────────────────────────────────────────────────────────────────────────── */}
      {tab === "recommendations" && (
        <RecommendationStudio
          projectId={projectId}
          sites={detail.sites}
          initialSiteId={change?.site?.id ?? detail.sites[0]?.id ?? null}
          onApplyProduct={async (product, replacementSiteId, equipmentTag) => {
            try {
              setRunning(true);
              setError(null);
              const inv = await api.applyRecommendation(projectId, {
                equipment_tag: equipmentTag,
                candidate_product_id: product.id,
                title: `Substitution: ${product.model_number}`,
                reason: `Recommended selection (${product.score}/100 score) from ${product.manufacturer}`,
                site_id: replacementSiteId,
                existing_change_id: selectedId || null,
              });
              setInvestigation(inv);
              const appliedChangeId = inv.subject_id;
              if (!appliedChangeId) throw new Error("The recommendation was applied without a change identifier.");
              setSelectedId(appliedChangeId);
              setChanges(await api.changes(projectId));
              await load(appliedChangeId);
              onProjectChanged?.();
              setTab("verification");
            } catch (caught) {
              setError(caught);
              throw caught;
            } finally {
              setRunning(false);
            }
          }}
        />
      )}

      {/* ────────────────────────────────────────────────────────────────────────── */}
      {/* TAB 3: CUMULATIVE CASCADE LOADING OVERVIEW                                 */}
      {/* ────────────────────────────────────────────────────────────────────────── */}
      {tab === "cascade" && (
        <CascadeOverview
          cascade={cascade}
          onRefresh={refreshCascade}
        />
      )}

      {/* ────────────────────────────────────────────────────────────────────────── */}
      {/* TAB 4: ACTION PACKAGE GENERATOR & RFIS                                     */}
      {/* ────────────────────────────────────────────────────────────────────────── */}
      {tab === "actions" && change && (
        <ActionPackageGenerator
          projectId={projectId}
          changeId={change.change.id}
          equipmentTag={change.change.equipment_tag}
          changeTitle={change.change.title}
        />
      )}

      {/* ────────────────────────────────────────────────────────────────────────── */}
      {/* TAB 5: PROJECT KNOWLEDGE & DOCUMENT AGENT                                  */}
      {/* ────────────────────────────────────────────────────────────────────────── */}
      {tab === "knowledge" && (
        <ProjectKnowledgeAgent
          detail={detail}
          onProjectChanged={() => {
            onProjectChanged?.();
            refreshCascade();
          }}
        />
      )}

      <EvidenceDrawer
        open={!!evidenceFor}
        onClose={() => setEvidenceFor(null)}
        projectId={projectId}
        subjectId={evidenceFor?.id}
        title={`Evidence - ${evidenceFor?.name ?? ""}`}
      />
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* SUB-COMPONENTS                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

function DesignMarginsPanel({ margins }: { margins: DesignMargin[] }) {
  if (!margins || margins.length === 0) return null;

  return (
    <Card
      title="Deterministic Design Margins & Remaining Facility Headroom"
      subtitle="Evaluated against design capacities - unbacked capacities are flagged as NEEDS INFORMATION"
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {margins.map((m) => {
          const isOk = m.status === "WITHIN_MARGIN";
          const isCrit = m.status === "CRITICAL_MARGIN";
          const isExceeded = m.status === "EXCEEDED";

          return (
            <div
              key={m.id || m.name}
              className={cx(
                "rounded-xl border p-3 flex flex-col justify-between transition-all",
                isOk && "border-emerald-200 bg-emerald-50/40",
                isCrit && "border-amber-200 bg-amber-50/40",
                isExceeded && "border-rose-300 bg-rose-50/40",
                m.status === "NEEDS_INFORMATION" && "border-ink-200 bg-ink-50/40",
              )}
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-ink-900">{m.name}</span>
                  <Badge
                    className={cx(
                      "text-[10px] uppercase font-bold",
                      isOk && "bg-emerald-100 text-emerald-800 border-emerald-300",
                      isCrit && "bg-amber-100 text-amber-800 border-amber-300",
                      isExceeded && "bg-rose-100 text-rose-800 border-rose-300",
                      m.status === "NEEDS_INFORMATION" && "bg-ink-100 text-ink-700 border-ink-300",
                    )}
                  >
                    {m.status.replace("_", " ")}
                  </Badge>
                </div>
                <p className="mt-1 text-[11px] text-ink-600 leading-relaxed">{m.detail}</p>
              </div>

              {m.remaining_margin && (
                <div className="mt-2.5 pt-2 border-t border-ink-100/60 flex items-center justify-between text-xs">
                  <span className="text-ink-500 text-[11px]">Remaining Margin:</span>
                  <span className="font-bold tabular text-ink-900">
                    {fmtQuantity(m.remaining_margin)}
                    {m.margin_pct != null && ` (${m.margin_pct > 0 ? "+" : ""}${m.margin_pct}%)`}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function CostScheduleCard({ impact }: { impact: CostScheduleImpact }) {
  return (
    <Card
      title="Cost, Energy & Schedule Impact Assessment"
      subtitle="Deterministic OPEX estimation and critical-path construction delay analysis"
      actions={
        <Badge className="border-indigo-200 bg-indigo-50 text-indigo-800">
          <Clock className="h-3.5 w-3.5 mr-1 inline" /> {impact.lead_time_weeks} Weeks Lead Time
        </Badge>
      }
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="rounded-lg border border-ink-200 bg-white p-3">
          <span className="text-[11px] text-ink-500 block">Annual OPEX Delta (Energy + Water)</span>
          <span className="text-lg font-bold text-ink-900 mt-1 block">
            {impact.total_annual_opex_delta_usd != null
              ? `$${impact.total_annual_opex_delta_usd.toLocaleString()}/yr`
              : "Quotation Required"}
          </span>
          <span className="text-[10px] text-ink-400">
            {impact.annual_energy_delta_usd != null ? `Power: $${impact.annual_energy_delta_usd}/yr` : "Baseline dependent"}
          </span>
        </div>

        <div className="rounded-lg border border-ink-200 bg-white p-3">
          <span className="text-[11px] text-ink-500 block">Critical Path Delay</span>
          <span className={cx("text-lg font-bold mt-1 block", impact.schedule_delay_days > 0 ? "text-amber-700" : "text-emerald-700")}>
            {impact.schedule_delay_days > 0 ? `+${impact.schedule_delay_days} Days Delay` : "0 Days (On Track)"}
          </span>
          <span className="text-[10px] text-ink-400">
            {impact.on_critical_path ? "Long-lead equipment item" : "Non-critical path"}
          </span>
        </div>

        <div className="rounded-lg border border-ink-200 bg-white p-3">
          <span className="text-[11px] text-ink-500 block">Engineering Rationale</span>
          <p className="text-xs text-ink-700 mt-1 line-clamp-2" title={impact.explanation}>
            {impact.explanation || "No adverse cost/schedule impact recorded."}
          </p>
        </div>
      </div>
    </Card>
  );
}

function DecisionLineageCard({ lineage }: { lineage: DecisionLineageRecord[] }) {
  return (
    <Card
      title="Decision Lineage & Verification Audit Log"
      subtitle="Complete traceability of why engineering reviews or gates were triggered"
    >
      <div className="flex flex-col gap-2">
        {lineage.map((l) => (
          <div key={l.id} className="rounded-lg border border-ink-200 bg-white p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-ink-900">Verdict: {l.decision_state}</span>
              <span className="text-[11px] text-ink-400 font-mono">{new Date(l.timestamp).toLocaleTimeString()}</span>
            </div>
            <div className="mt-2 text-ink-600">
              <span className="font-medium text-ink-800">Triggers:</span>
              <ul className="list-disc list-inside mt-0.5 space-y-0.5 text-[11px]">
                {l.triggered_reasons.map((r, idx) => (
                  <li key={idx}>{r}</li>
                ))}
              </ul>
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-ink-500 border-t border-ink-100 pt-1.5">
              <span>Sources: {l.source_documents.join(", ")}</span>
              <span className="font-mono text-ink-400">{l.engine_version}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function RecommendationStudio({
  projectId,
  sites,
  initialSiteId,
  onApplyProduct,
}: {
  projectId: string;
  sites: CandidateSite[];
  initialSiteId?: string | null;
  onApplyProduct: (product: CandidateProduct, siteId: string | null, equipmentTag: string) => Promise<void>;
}) {
  const [prompt, setPrompt] = useState(
    "I need a water-cooled chiller with at least 1200 kW cooling capacity, COP above 5.8, 480V, footprint under 20 m2, and max ambient 45°C.",
  );
  const [equipmentType, setEquipmentType] = useState("chiller");
  const [equipmentTag, setEquipmentTag] = useState("CH-NEW");
  const [siteId, setSiteId] = useState(initialSiteId ?? "");
  const [searching, setSearching] = useState(false);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [reqSet, setReqSet] = useState<StructuredRequirementSet | null>(null);
  const [result, setResult] = useState<ProductRecommendationResult | null>(null);
  const [studioError, setStudioError] = useState<unknown>(null);

  async function handleSearch() {
    setSearching(true);
    setStudioError(null);
    setResult(null);
    try {
      // 1. Parse prompt
      const parsed = await api.parseRequirements(projectId, prompt, equipmentType);
      setReqSet(parsed);

      // 2. Search & rank candidates
      const res = await api.searchRecommendations(projectId, {
        equipment_type: equipmentType,
        constraints: parsed.constraints,
        site_id: siteId || null,
        limit: 20,
      });
      setResult(res);
    } catch (e) {
      setStudioError(e);
    } finally {
      setSearching(false);
    }
  }

  async function applyProduct(product: CandidateProduct) {
    setApplyingId(product.id);
    setStudioError(null);
    try {
      await onApplyProduct(product, siteId || null, equipmentTag.trim());
    } catch (caught) {
      setStudioError(caught);
    } finally {
      setApplyingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Equipment Replacement Finder"
        subtitle="Coordinate stated requirements and rank benchmark models across 11 equipment categories"
      >
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <Field label="Construction Site" htmlFor="replacement-site">
              <select
                id="replacement-site"
                value={siteId}
                onChange={(e) => setSiteId(e.target.value)}
                className={cx(inputClass, "w-56 text-xs")}
              >
                <option value="">No site selected</option>
                {sites.map((site) => (
                  <option key={site.id} value={site.id}>{site.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Equipment Category" htmlFor="eq-category">
              <select
                id="eq-category"
                value={equipmentType}
                onChange={(e) => {
                  const category = e.target.value;
                  setEquipmentType(category);
                  setEquipmentTag(`${category.toUpperCase().replaceAll("_", "-")}-NEW`);
                  setResult(null);
                  setReqSet(null);
                }}
                className={cx(inputClass, "w-48 text-xs")}
              >
                <option value="chiller">Chiller</option>
                <option value="crah">CRAH (Fan Wall / In-Row)</option>
                <option value="ahu">AHU (Air Handler)</option>
                <option value="cooling_tower">Cooling Tower</option>
                <option value="pump">Pump (Primary CHW / CW)</option>
                <option value="transformer">Transformer (Substation)</option>
                <option value="ups">UPS (Modular Double-Conversion)</option>
                <option value="generator">Standby Generator</option>
                <option value="switchgear">Main Switchgear</option>
                <option value="pdu">Power Distribution Unit (PDU)</option>
                <option value="heat_exchanger">Heat Exchanger (Economizer)</option>
              </select>
            </Field>
            <Field label="Equipment Tag" hint="Creates a new change if none is selected" htmlFor="eq-tag">
              <input
                id="eq-tag"
                value={equipmentTag}
                onChange={(e) => setEquipmentTag(e.target.value)}
                className={cx(inputClass, "w-48 text-xs")}
                placeholder="CH-NEW"
              />
            </Field>
          </div>

          <Field label="Natural Language Specification Prompt" htmlFor="nl-prompt">
            <textarea
              id="nl-prompt"
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className={cx(inputClass, "w-full text-xs font-mono")}
              placeholder="e.g. Need a 2.5 MVA substation transformer 13.8kV/480V with copper windings and impedance < 6%..."
            />
          </Field>

          <div className="flex items-center justify-between">
            <span className="text-[11px] text-ink-500">
              Deterministic ranking: Capacity (25%) · Efficiency (20%) · Electrical (15%) · Climate (10%) · Footprint (10%)
            </span>
            <Button variant="primary" loading={searching} disabled={!prompt.trim()} onClick={handleSearch}>
              <Sparkles aria-hidden className="h-3.5 w-3.5 mr-1 text-amber-300" />
              Read Requirements &amp; Find Candidates
            </Button>
          </div>
        </div>
      </Card>

      {studioError ? <ErrorState error={studioError} onRetry={handleSearch} /> : null}

      {/* STRUCTURED CONSTRAINTS PREVIEW */}
      {reqSet && (
        <Card
          title="Extracted Structured Engineering Constraints"
          subtitle="Physics and electrical rules extracted deterministically from your inquiry"
        >
          {reqSet.constraints.length === 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              No numeric engineering constraints were detected. Add capacity, efficiency, voltage, ambient, flow, footprint or cost requirements before treating the ranking as a design decision.
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {reqSet.constraints.map((c, i) => (
              <Badge key={i} className="border-sky-300 bg-sky-50 text-sky-900 text-xs py-1 px-2.5">
                <span className="font-semibold text-sky-800">{c.parameter}</span>
                <span className="font-mono mx-1 text-sky-600">{c.operator}</span>
                <span className="font-bold">{c.value} {c.unit ?? ""}</span>
                <span className="text-[10px] text-sky-500 ml-1.5">({c.priority})</span>
              </Badge>
            ))}
          </div>
        </Card>
      )}

      {/* CANDIDATE PRODUCTS LIST */}
      {result && (
        <Card
          title={`Top Catalog Recommendations (${result.candidates.length} Found)`}
          subtitle={result.explanation_narrative.split("\n")[0]}
        >
          {result.candidates.length === 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              No catalog models match this equipment category. Check the category or add models to the catalog.
            </div>
          ) : null}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {result.candidates.map((prod) => {
              const isTop = result.top_recommendation?.id === prod.id;
              return (
                <div
                  key={prod.id}
                  className={cx(
                    "rounded-xl border p-4 flex flex-col justify-between transition-all",
                    isTop ? "border-sky-500 bg-sky-50/30 shadow-sm" : "border-ink-200 bg-white",
                  )}
                >
                  <div>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-sm text-ink-900">{prod.model_number}</span>
                          {isTop && (
                            <Badge className="border-amber-400 bg-amber-100 text-amber-900 text-[10px] font-bold">
                              #1 TOP PICK
                            </Badge>
                          )}
                          {prod.specs.synthetic === true ? (
                            <Badge className="border-violet-200 bg-violet-50 text-violet-800 text-[10px]">synthetic prototype</Badge>
                          ) : null}
                          <Badge
                            className={cx(
                              "text-[10px]",
                              prod.compatibility_status === "COMPATIBLE" && "border-emerald-200 bg-emerald-50 text-emerald-800",
                              prod.compatibility_status === "CONDITIONALLY_COMPATIBLE" && "border-amber-200 bg-amber-50 text-amber-800",
                              prod.compatibility_status === "INCOMPATIBLE" && "border-rose-200 bg-rose-50 text-rose-800",
                            )}
                          >
                            {prod.compatibility_status.replaceAll("_", " ").toLowerCase()}
                          </Badge>
                        </div>
                        <p className="text-xs text-ink-500 mt-0.5">{prod.manufacturer}</p>
                      </div>

                      <div className="text-right">
                        <span className="text-xl font-extrabold text-sky-700">{prod.score}</span>
                        <span className="text-[10px] text-ink-400 block">/ 100 PTS</span>
                      </div>
                    </div>

                    <p className="mt-2 text-xs text-ink-700 leading-relaxed">{prod.explanation}</p>

                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {prod.passed_constraints.slice(0, 3).map((p, idx) => (
                        <span key={idx} className="inline-flex items-center text-[10px] rounded bg-emerald-50 text-emerald-800 border border-emerald-200 px-1.5 py-0.5">
                          ✓ {p}
                        </span>
                      ))}
                    </div>
                    {prod.failed_constraints.length > 0 ? (
                      <div className="mt-2 rounded-lg border border-rose-100 bg-rose-50/60 p-2 text-[10px] leading-relaxed text-rose-800">
                        {prod.failed_constraints.slice(0, 2).map((failure) => <p key={failure}>× {failure}</p>)}
                      </div>
                    ) : null}
                  </div>

                  <div className="mt-4 pt-3 border-t border-ink-100 flex items-center justify-between">
                    <span className="text-[11px] text-ink-400 font-mono">{prod.reference_source}</span>
                    <Button
                      size="sm"
                      variant="primary"
                      loading={applyingId === prod.id}
                      disabled={!equipmentTag.trim() || applyingId !== null || prod.compatibility_status === "INCOMPATIBLE"}
                      onClick={() => applyProduct(prod)}
                      className="bg-sky-600 hover:bg-sky-700 text-white font-medium"
                    >
                      <Play className="h-3 w-3 mr-1" />
                      {prod.compatibility_status === "INCOMPATIBLE" ? "Mandatory Criteria Failed" : "Run Change Impact Analysis"}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}

function CascadeOverview({
  cascade,
  onRefresh,
}: {
  cascade: CascadeImpactSummary | null;
  onRefresh: () => void;
}) {
  if (!cascade) return <Spinner label="Loading cascade impact..." />;

  const isSafe = cascade.collective_status === "WITHIN_FACILITY_LIMITS";

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="System-Level Multi-Change Cascade Loading Analysis"
        subtitle="Cumulative facility-wide impact of all concurrent equipment substitutions on substation transformers, emergency generators, and structural steel"
        actions={
          <Button size="sm" variant="ghost" onClick={onRefresh}>
            Refresh Summary
          </Button>
        }
      >
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          <div className="rounded-xl border border-ink-200 bg-white p-3.5">
            <span className="text-xs text-ink-500 font-medium">Cumulative Electrical Power</span>
            <span className="text-xl font-bold text-ink-900 mt-1 block">
              {cascade.cumulative_electrical_delta_kw > 0 ? "+" : ""}
              {cascade.cumulative_electrical_delta_kw.toLocaleString()} kW
            </span>
            <span className="text-[11px] text-ink-400 mt-0.5 block">
              Transformer Headroom: {cascade.transformer_headroom_pct}%
            </span>
          </div>

          <div className="rounded-xl border border-ink-200 bg-white p-3.5">
            <span className="text-xs text-ink-500 font-medium">Cumulative Equipment Weight</span>
            <span className="text-xl font-bold text-ink-900 mt-1 block">
              {cascade.cumulative_weight_delta_kg > 0 ? "+" : ""}
              {cascade.cumulative_weight_delta_kg.toLocaleString()} kg
            </span>
            <span className="text-[11px] text-ink-400 mt-0.5 block">
              Structural Headroom: {cascade.structural_headroom_pct}%
            </span>
          </div>

          <div className="rounded-xl border border-ink-200 bg-white p-3.5">
            <span className="text-xs text-ink-500 font-medium">Cooling Duty Delta</span>
            <span className="text-xl font-bold text-ink-900 mt-1 block">
              {cascade.cumulative_cooling_delta_kw > 0 ? "+" : ""}
              {cascade.cumulative_cooling_delta_kw.toLocaleString()} kW
            </span>
            <span className="text-[11px] text-ink-400 mt-0.5 block">Central chilled water plant</span>
          </div>

          <div className="rounded-xl border border-ink-200 bg-white p-3.5">
            <span className="text-xs text-ink-500 font-medium">Collective Facility Status</span>
            <Badge
              className={cx(
                "mt-2 text-xs py-1 px-2 font-bold uppercase",
                isSafe ? "bg-emerald-100 text-emerald-900 border-emerald-300" : "bg-rose-100 text-rose-900 border-rose-300",
              )}
            >
              {cascade.collective_status.replace(/_/g, " ")}
            </Badge>
          </div>
        </div>

        <div className="mt-4 rounded-lg bg-ink-50 p-3 border border-ink-200">
          <span className="text-xs font-semibold text-ink-900">Engineering Rationale &amp; Boundary Check:</span>
          <ul className="mt-1.5 space-y-1 text-xs text-ink-700 list-disc list-inside">
            {cascade.rationale.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      </Card>
    </div>
  );
}

function ActionPackageGenerator({
  projectId,
  changeId,
  equipmentTag,
  changeTitle,
}: {
  projectId: string;
  changeId: string;
  equipmentTag: string;
  changeTitle: string;
}) {
  const [actionType, setActionType] = useState("rfi");
  const [recipient, setRecipient] = useState("");
  const [generating, setGenerating] = useState(false);
  const [packageRes, setPackageRes] = useState<ActionPackageResponse | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleGenerate() {
    setGenerating(true);
    try {
      const res = await api.generateActionPackage(projectId, {
        change_id: changeId,
        action_type: actionType,
        recipient: recipient || undefined,
      });
      setPackageRes(res);
    } catch (e) {
      console.error(e);
    } finally {
      setGenerating(false);
    }
  }

  function copyMarkdown() {
    if (!packageRes) return;
    navigator.clipboard.writeText(packageRes.body_markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="flex flex-col gap-4">
      <Card
        title={`Action Package & RFI Generator - ${equipmentTag}`}
        subtitle={`Generate structured, evidence-backed engineering documentation for ${changeTitle}`}
      >
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Action Package Type" htmlFor="action-type">
              <select
                id="action-type"
                value={actionType}
                onChange={(e) => setActionType(e.target.value)}
                className={cx(inputClass, "w-full text-xs")}
              >
                <option value="rfi">Request for Information (RFI to EOR / Structural / Electrical)</option>
                <option value="vendor_request">Vendor Evidence &amp; Clarification Request</option>
                <option value="review_package">Engineering Change Review &amp; Sign-off Package</option>
              </select>
            </Field>

            <Field label="Recipient / Addressee" htmlFor="recipient-input">
              <input
                id="recipient-input"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                placeholder="e.g. Lead Structural Engineer of Record"
                className={cx(inputClass, "w-full text-xs")}
              />
            </Field>
          </div>

          <div className="flex justify-end">
            <Button variant="primary" loading={generating} onClick={handleGenerate}>
              <Send className="h-3.5 w-3.5 mr-1" /> Generate Formal Package Draft
            </Button>
          </div>
        </div>
      </Card>

      {packageRes && (
        <Card
          title={packageRes.title}
          subtitle={`Addressed to: ${packageRes.recipient} · Due in ${packageRes.due_in_days} business days`}
          actions={
            <Button size="sm" variant="ghost" onClick={copyMarkdown}>
              {copied ? <Check className="h-3.5 w-3.5 mr-1 text-emerald-600" /> : <Copy className="h-3.5 w-3.5 mr-1" />}
              {copied ? "Copied!" : "Copy Markdown"}
            </Button>
          }
        >
          <div className="rounded-lg border border-ink-200 bg-ink-50/50 p-4 font-mono text-xs text-ink-900 whitespace-pre-wrap leading-relaxed">
            {packageRes.body_markdown}
          </div>
        </Card>
      )}
    </div>
  );
}

function StaleAssumptions({
  assumptions,
  staleIds,
}: {
  assumptions: ChangeDetail["assumptions"];
  staleIds: string[];
}) {
  if (assumptions.length === 0) return null;
  return (
    <Card
      title="Project Assumptions"
      subtitle="Assumptions go stale when the evidence they depend on changes"
      actions={
        <Badge className={staleIds.length ? SEVERITY_STYLE.high : SEVERITY_STYLE.info}>
          {staleIds.length} Stale
        </Badge>
      }
    >
      <ul className="flex flex-col gap-2">
        {assumptions.map((assumption) => {
          const stale = assumption.status === "stale" || staleIds.includes(assumption.id);
          return (
            <li
              key={assumption.id}
              className={cx(
                "rounded-lg border p-2.5",
                stale ? "border-orange-300 bg-orange-50" : "border-ink-200",
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-ink-900">{assumption.statement}</p>
                <Badge
                  className={
                    stale
                      ? "border-orange-400 bg-orange-100 text-orange-900 font-bold"
                      : "border-emerald-300 bg-emerald-50 text-emerald-900"
                  }
                >
                  {stale ? "STALE" : "active"}
                </Badge>
              </div>
              <p className="mt-1 text-[11px] text-ink-500">
                {titleize(assumption.discipline)} · Depends on{" "}
                <span className="font-mono">{assumption.depends_on_fields.join(", ")}</span>
              </p>
              {assumption.stale_reason && (
                <p className="mt-1 text-xs text-orange-900">{assumption.stale_reason}</p>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function RequirementsPanel({
  projectId,
  requirements,
  onChanged,
}: {
  projectId: string;
  requirements: Requirement[];
  onChanged: () => void;
}) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadNote, setUploadNote] = useState<string | null>(null);

  async function confirm(requirement: Requirement) {
    setBusy(requirement.id);
    try {
      const raw = edits[requirement.id];
      const value =
        raw === undefined || raw === ""
          ? requirement.value
          : Number.isNaN(Number(raw))
            ? raw
            : Number(raw);
      await api.confirmRequirement(projectId, requirement.id, { value, confirmed: true });
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  async function upload(file: File) {
    setUploading(true);
    setUploadNote(null);
    try {
      const result = await api.uploadDocument(projectId, file, "specification");
      setUploadNote(
        `${result.document.filename}: ${result.document.page_count} page(s), ${result.chunk_count} chunk(s), ${result.requirements.length} candidate requirement(s).` +
          (result.warning ? ` Warning: ${result.warning}` : ""),
      );
      onChanged();
    } catch (e) {
      setUploadNote(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  const relevant = requirements.filter((r) => r.value !== null);

  return (
    <Card
      title="Extracted Project Requirements"
      subtitle="Confirm or correct each value before it is used in a verification check"
      actions={
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-ink-300 px-2.5 py-1 text-xs font-medium hover:bg-ink-50">
          <Upload aria-hidden className="h-3.5 w-3.5" />
          {uploading ? "Uploading…" : "Upload PDF Spec"}
          <input
            type="file"
            accept="application/pdf"
            className="sr-only"
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
        </label>
      }
    >
      {uploadNote && (
        <p className="mb-2 rounded border border-sky-200 bg-sky-50 p-2 text-xs text-sky-900">
          {uploadNote}
        </p>
      )}
      {relevant.length === 0 ? (
        <EmptyState
          title="No requirements extracted"
          detail="Upload a specification PDF to extract candidate requirements."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-ink-500">
              <tr>
                <th className="py-1 pr-2 font-medium">Requirement</th>
                <th className="py-1 pr-2 font-medium">Value</th>
                <th className="py-1 pr-2 font-medium">Source</th>
                <th className="py-1 pr-2 font-medium">Status</th>
                <th className="py-1 font-medium">Confirm / Correct</th>
              </tr>
            </thead>
            <tbody>
              {relevant.slice(0, 14).map((requirement) => (
                <tr key={requirement.id} className="border-t border-ink-100 align-top">
                  <td className="py-1.5 pr-2">
                    <span className="font-medium text-ink-800">{requirement.label}</span>
                    <span className="block text-[11px] text-ink-500">
                      {requirement.equipment_tag ?? "unassigned"} ·{" "}
                      <span className="font-mono">{requirement.field_key}</span>
                    </span>
                  </td>
                  <td className="py-1.5 pr-2 tabular">
                    {requirement.value} {requirement.unit ?? ""}
                  </td>
                  <td className="py-1.5 pr-2 text-[11px] text-ink-500">
                    page {requirement.page ?? "-"}
                    {requirement.raw_text && (
                      <span className="mt-0.5 block max-w-[18rem] truncate" title={requirement.raw_text}>
                        “{requirement.raw_text}”
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 pr-2">
                    {requirement.confirmed ? (
                      <Badge className="border-violet-300 bg-violet-100 text-violet-900">
                        <CheckCheck aria-hidden className="h-3 w-3 inline mr-1" /> confirmed
                      </Badge>
                    ) : (
                      <Badge className="border-amber-300 bg-amber-100 text-amber-900">
                        extracted ({(requirement.confidence * 100).toFixed(0)}%)
                      </Badge>
                    )}
                  </td>
                  <td className="py-1.5">
                    <div className="flex items-end gap-1">
                      <Field label="" htmlFor={`req-${requirement.id}`}>
                        <input
                          id={`req-${requirement.id}`}
                          aria-label={`Corrected value for ${requirement.label}`}
                          className={cx(inputClass, "w-24")}
                          placeholder={String(requirement.value)}
                          value={edits[requirement.id] ?? ""}
                          onChange={(e) =>
                            setEdits({ ...edits, [requirement.id]: e.target.value })
                          }
                        />
                      </Field>
                      <Button
                        size="sm"
                        loading={busy === requirement.id}
                        onClick={() => confirm(requirement)}
                      >
                        <ArrowRight aria-hidden className="h-3 w-3" /> Confirm
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
