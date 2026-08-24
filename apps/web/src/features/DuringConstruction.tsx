import { ArrowRight, CheckCheck, CloudSun, Database, Droplet, FileText, Play, Sparkles, Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EvidenceDrawer } from "../components/EvidencePanel";
import { GapPanel } from "../components/GapPanel";
import { DecisionCard, InvestigationTimeline, NextActionPreview } from "../components/Investigation";
import { ImpactGraphView, ImpactList } from "../components/ImpactGraphView";
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
  ChangeDetail,
  ClimateStationInfo,
  EquipmentChange,
  EquipmentConfiguration,
  ImpactGraph,
  InformationGap,
  Investigation,
  ProjectDetail,
  ReferenceSpec,
  Requirement,
} from "../lib/types";

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

export function DuringConstruction({ detail }: { detail: ProjectDetail }) {
  const projectId = detail.project.id;
  const [changes, setChanges] = useState<EquipmentChange[]>(detail.changes);
  const [selectedId, setSelectedId] = useState<string | null>(detail.changes[0]?.id ?? null);
  const [change, setChange] = useState<ChangeDetail | null>(null);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [graph, setGraph] = useState<ImpactGraph | null>(null);
  const [gaps, setGaps] = useState<InformationGap[]>([]);
  const [climateStation, setClimateStation] = useState<ClimateStationInfo | null>(null);
  const [refSpec, setRefSpec] = useState<ReferenceSpec | null>(null);
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
      try {
        const [changeDetail, allGaps] = await Promise.all([
          api.change(projectId, changeId),
          api.gaps(projectId),
        ]);
        setChange(changeDetail);
        setGaps(allGaps.filter((g) => g.subject_id === changeId));
        
        // Load climate station if site is linked
        if (changeDetail.site?.latitude && changeDetail.site?.longitude) {
          api.climateStation(projectId, changeId).then(setClimateStation).catch(() => setClimateStation(null));
        }

        // Load reference specs from RacksDB / LBNL
        api.referenceSpecs(changeDetail.change.equipment_tag).then(setRefSpec).catch(() => setRefSpec(null));

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

  useEffect(() => {
    api.changes(projectId).then(setChanges).catch(setError);
  }, [projectId]);

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
      const [impactGraph, allGaps, changeDetail] = await Promise.all([
        api.impact(selectedId).catch(() => null),
        api.gaps(projectId),
        api.change(projectId, selectedId),
      ]);
      setGraph(impactGraph);
      setChange(changeDetail);
      setGaps(allGaps.filter((g) => g.subject_id === selectedId));
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
      const [impactGraph, allGaps, changeDetail] = await Promise.all([
        api.impact(selectedId).catch(() => null),
        api.gaps(projectId),
        api.change(projectId, selectedId),
      ]);
      setGraph(impactGraph);
      setChange(changeDetail);
      setGaps(allGaps.filter((g) => g.subject_id === selectedId));
    } catch (e) {
      setError(e);
    } finally {
      setAutofilling(false);
    }
  }

  if (changes.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No equipment change cases"
          detail="Seed the demo data to load three synthetic change cases."
        />
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {error ? <ErrorState error={error} onRetry={() => selectedId && load(selectedId)} /> : null}

      <Card title="Equipment change cases" subtitle="Select a case to analyse">
        <div className="grid gap-2 md:grid-cols-3">
          {changes.map((item) => (
            <button
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              aria-pressed={selectedId === item.id}
              className={cx(
                "rounded-lg border p-3 text-left transition-colors",
                selectedId === item.id
                  ? "border-ink-900 bg-ink-50"
                  : "border-ink-200 hover:border-ink-400",
              )}
            >
              <div className="flex items-center gap-2">
                <Badge className="border-ink-300 bg-white text-ink-800">{item.equipment_tag}</Badge>
                {item.synthetic && (
                  <Badge className="border-amber-300 bg-amber-100 text-amber-900">synthetic</Badge>
                )}
                <Badge className="border-ink-200 bg-ink-100 text-ink-600">{item.status}</Badge>
              </div>
              <p className="mt-1.5 text-sm font-medium text-ink-900">{item.title}</p>
              <p className="mt-0.5 text-xs text-ink-500">{item.reason}</p>
            </button>
          ))}
        </div>
      </Card>

      {!change && <Spinner label="Loading change case…" />}

      {change && (
        <>
          <Card
            title={`Old vs proposed - ${change.change.equipment_tag}`}
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
                  <FileText aria-hidden className="h-3.5 w-3.5" /> Evidence
                </Button>
                <Button variant="primary" onClick={analyze} loading={running}>
                  <Play aria-hidden className="h-3.5 w-3.5" />
                  {investigation ? "Re-run analysis" : "Run analysis"}
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
                  <tr className="border-t border-ink-100">
                    <td className="py-1.5 pr-3 text-ink-600">Rating conditions</td>
                    <td className="py-1.5 pr-3">{ratingText(change.existing.configuration)}</td>
                    <td className="py-1.5 pr-3">{ratingText(change.proposed.configuration)}</td>
                    <td />
                  </tr>
                  <tr className="border-t border-ink-100">
                    <td className="py-1.5 pr-3 text-ink-600">Support points</td>
                    <td className="py-1.5 pr-3">
                      {supportText(change.existing.configuration)}
                    </td>
                    <td className="py-1.5 pr-3">
                      {supportText(change.proposed.configuration)}
                    </td>
                    <td />
                  </tr>
                </tbody>
              </table>
            </div>
            {/* Open-Source Dataset Auto-Fill (RacksDB / LBNL) */}
            {refSpec && (
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-sky-200 bg-sky-50/70 p-3 text-xs">
                <div className="flex items-start gap-2.5">
                  <Database className="h-4 w-4 text-sky-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold text-sky-900">
                      RacksDB &amp; LBNL Open Catalog Benchmark: {refSpec.reference_model}
                    </span>
                    <p className="text-sky-700 text-[11px] mt-0.5">
                      {refSpec.description}
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
                  Auto-fill Missing Data from RacksDB
                </Button>
              </div>
            )}

            <p className="mt-2 text-[11px] text-amber-800">
              All equipment values in this demo are synthetic. Manufacturers and model numbers are
              invented for demonstration.
            </p>
          </Card>

          {/* Site Climate Design Conditions (StationFinder & ASHRAE 2021) */}
          {climateStation && (
            <Card
              title="Site Climate Design Conditions (StationFinder / ASHRAE)"
              subtitle={`Nearest Weather Station: ${climateStation.name} (${climateStation.distance_km} km away, elevation ${climateStation.elevation_m}m)`}
              actions={
                <Badge className="border-sky-300 bg-sky-50 text-sky-800">
                  <CloudSun className="h-3.5 w-3.5 mr-1 inline" /> StationFinder WMO #{climateStation.station_id}
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
                  <span className="text-[10px] text-ink-400">Evaporative cooling limit</span>
                </div>
                <div className="rounded-lg border border-ink-200 bg-white p-2.5">
                  <span className="text-ink-500 block text-[11px]">Standard Summer Cooling (1.0%)</span>
                  <span className="text-base font-bold text-ink-800 mt-1 block">
                    {climateStation.cooling_db_1_0_pct_degc}°C DB
                  </span>
                  <span className="text-[10px] text-ink-400">Annual 99.0% exceedance</span>
                </div>
                <div className="rounded-lg border border-ink-200 bg-white p-2.5">
                  <span className="text-ink-500 block text-[11px]">Extreme Winter Heating (99.6%)</span>
                  <span className="text-base font-bold text-rose-700 mt-1 block">
                    {climateStation.heating_db_99_6_pct_degc}°C DB
                  </span>
                  <span className="text-[10px] text-ink-400">Lowest design temp</span>
                </div>
              </div>
            </Card>
          )}

          {/* Water & Energy Benchmarks (LBNL / AI-WaterStress) */}
          {change.change.equipment_tag.startsWith("CH-") && (
            <Card
              title="Water & Energy Efficiency Benchmarks (LBNL / AI-WaterStress)"
              subtitle="Derived from LBNL Data Center Energy Efficiency Center & Water Usage Effectiveness (WUE) models"
              actions={
                <Badge className="border-teal-300 bg-teal-50 text-teal-800">
                  <Droplet className="h-3.5 w-3.5 mr-1 inline" /> LBNL Chilled-Water Baseline
                </Badge>
              }
            >
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-2.5">
                  <span className="text-teal-800 font-semibold block text-[11px]">Target Chiller COP</span>
                  <span className="text-base font-bold text-teal-900 mt-1 block">5.8 – 6.2 COP</span>
                  <span className="text-[10px] text-teal-700">AHRI 550/590 efficiency tier</span>
                </div>
                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-2.5">
                  <span className="text-teal-800 font-semibold block text-[11px]">Cooling Tower WUE Rate</span>
                  <span className="text-base font-bold text-teal-900 mt-1 block">1.45 L/kWh</span>
                  <span className="text-[10px] text-teal-700">Evaporative water demand</span>
                </div>
                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-2.5">
                  <span className="text-teal-800 font-semibold block text-[11px]">Power Demand Intensity</span>
                  <span className="text-base font-bold text-teal-900 mt-1 block">0.606 kW / ton</span>
                  <span className="text-[10px] text-teal-700">Hyperscale standard baseline</span>
                </div>
              </div>
            </Card>
          )}

          <RequirementsPanel
            projectId={projectId}
            requirements={change.requirements}
            onChanged={() => selectedId && load(selectedId)}
          />

          {running && <Spinner label="Running verification gates, deltas and impact tracing…" />}

          {!investigation && !running && (
            <Card>
              <EmptyState
                title="This change has not been analysed yet"
                detail="Run the analysis to verify comparability, calculate deltas and trace downstream impacts."
                action={
                  <Button variant="primary" onClick={analyze}>
                    <Play aria-hidden className="h-3.5 w-3.5" /> Run analysis
                  </Button>
                }
              />
            </Card>
          )}

          {investigation && (
            <>
              <div className="grid gap-4 xl:grid-cols-2">
                <Card
                  title="Verification gate"
                  subtitle="Checks that must pass before any comparison is accepted"
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
                        {(check.expected || check.observed) && (
                          <p className="mt-1 text-[11px] text-ink-500">
                            expected: {check.expected ?? "-"} · observed: {check.observed ?? "-"}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </Card>

                <Card
                  title="Deterministic deltas"
                  subtitle="Computed in Pint-checked units - never by the language model"
                >
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <caption className="sr-only">Calculated deltas</caption>
                      <thead className="text-ink-500">
                        <tr>
                          <th className="py-1 pr-2 font-medium">Property</th>
                          <th className="py-1 pr-2 font-medium">Existing</th>
                          <th className="py-1 pr-2 font-medium">Proposed</th>
                          <th className="py-1 pr-2 font-medium">Δ</th>
                          <th className="py-1 pr-2 font-medium">Δ%</th>
                          <th className="py-1 font-medium">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {investigation.deltas.map((delta) => (
                          <tr key={delta.field} className="border-t border-ink-100">
                            <td className="py-1.5 pr-2 text-ink-700" title={delta.explanation}>
                              {delta.label}
                            </td>
                            <td className="py-1.5 pr-2 tabular">{fmtQuantity(delta.old_value)}</td>
                            <td className="py-1.5 pr-2 tabular">{fmtQuantity(delta.new_value)}</td>
                            <td className="py-1.5 pr-2 tabular">
                              {fmtQuantity(delta.absolute_delta ?? null)}
                            </td>
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
              <GapPanel
                projectId={projectId}
                gaps={gaps}
                onChanged={() => selectedId && load(selectedId)}
                title="Missing information for this change"
              />
              <InvestigationTimeline investigation={investigation} />
            </>
          )}
        </>
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

function ratingText(config: EquipmentConfiguration) {
  const r = config.rating_conditions;
  if (!r) return <span className="italic text-rose-700">not stated</span>;
  return (
    <span className="tabular">
      {[
        r.entering_water_temp && `EWT ${fmtQuantity(r.entering_water_temp)}`,
        r.leaving_water_temp && `LWT ${fmtQuantity(r.leaving_water_temp)}`,
        r.ambient_temp && `ambient ${fmtQuantity(r.ambient_temp)}`,
        r.standard,
      ]
        .filter(Boolean)
        .join(" · ")}
    </span>
  );
}

function supportText(config: EquipmentConfiguration) {
  if (!config.support_points?.length)
    return <span className="italic text-rose-700">not supplied</span>;
  return (
    <span className="tabular">
      {config.support_points.length} × {fmtQuantity(config.support_points[0].load)}
    </span>
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
      title="Project assumptions"
      subtitle="Assumptions go stale when the evidence they depend on changes"
      actions={
        <Badge className={staleIds.length ? SEVERITY_STYLE.high : SEVERITY_STYLE.info}>
          {staleIds.length} stale
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
                      ? "border-orange-400 bg-orange-100 text-orange-900"
                      : "border-emerald-300 bg-emerald-50 text-emerald-900"
                  }
                >
                  {stale ? "STALE" : "active"}
                </Badge>
              </div>
              <p className="mt-1 text-[11px] text-ink-500">
                {titleize(assumption.discipline)} · depends on{" "}
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
      title="Extracted project requirements"
      subtitle="Confirm or correct each value before it is used in a check"
      actions={
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-ink-300 px-2.5 py-1 text-xs font-medium hover:bg-ink-50">
          <Upload aria-hidden className="h-3.5 w-3.5" />
          {uploading ? "Uploading…" : "Upload PDF"}
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
            <caption className="sr-only">Extracted requirements</caption>
            <thead className="text-ink-500">
              <tr>
                <th className="py-1 pr-2 font-medium">Requirement</th>
                <th className="py-1 pr-2 font-medium">Value</th>
                <th className="py-1 pr-2 font-medium">Source</th>
                <th className="py-1 pr-2 font-medium">Status</th>
                <th className="py-1 font-medium">Confirm / correct</th>
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
                        <CheckCheck aria-hidden className="h-3 w-3" /> confirmed
                      </Badge>
                    ) : (
                      <Badge className="border-amber-300 bg-amber-100 text-amber-900">
                        extracted ({(requirement.confidence * 100).toFixed(0)}%)
                      </Badge>
                    )}
                    {requirement.from_ocr && (
                      <Badge
                        className="ml-1 border-rose-300 bg-rose-100 text-rose-900"
                        title="Transcribed by OCR from a scanned page. Read the page before confirming - a misread digit is a wrong number with a citation on it."
                      >
                        OCR - read the page
                      </Badge>
                    )}
                    {requirement.corrected_from && (
                      <span className="mt-0.5 block text-[11px] text-ink-500">
                        was {requirement.corrected_from}
                      </span>
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
