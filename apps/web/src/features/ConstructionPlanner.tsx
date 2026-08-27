import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Database,
  DollarSign,
  Droplets,
  HardHat,
  MapPin,
  Play,
  Zap,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { Badge, Button, Card, ErrorState, Field, cx, inputClass } from "../components/ui";
import { api } from "../lib/api";
import type { CandidateSite, ConstructionPlanResponse } from "../lib/types";

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const measurement = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });

function metric(value: number, unit: string) {
  return `${number.format(value)} ${unit}`;
}

export function ConstructionPlanner({
  projectId,
  sites,
  defaultItLoadMw,
}: {
  projectId: string;
  sites: CandidateSite[];
  defaultItLoadMw?: number | null;
}) {
  const initialSite = useMemo(
    () => sites.find((site) => site.shortlisted) ?? sites[0] ?? null,
    [sites],
  );
  const [siteId, setSiteId] = useState(initialSite?.id ?? "");
  const [itLoadMw, setItLoadMw] = useState(defaultItLoadMw ?? 10);
  const [redundancy, setRedundancy] = useState<"N" | "N+1" | "2N">("N+1");
  const [targetPue, setTargetPue] = useState(1.35);
  const [utilizationPct, setUtilizationPct] = useState(70);
  const [electricityRate, setElectricityRate] = useState(0.085);
  const [budget, setBudget] = useState("");
  const [coolingStrategy, setCoolingStrategy] = useState<"water_cooled" | "hybrid_economizer">(
    "water_cooled",
  );
  const [requirementsNote, setRequirementsNote] = useState("");
  const [plan, setPlan] = useState<ConstructionPlanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function generatePlan() {
    if (!siteId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.constructionPlan(projectId, {
        site_id: siteId,
        it_load_mw: itLoadMw,
        redundancy,
        target_pue: targetPue,
        utilization_pct: utilizationPct,
        annual_operating_hours: 8760,
        electricity_rate_usd_kwh: electricityRate,
        cooling_strategy: coolingStrategy,
        voltage_v: 480,
        budget_usd: budget ? Number(budget) : null,
        contingency_pct: 15,
        requirements_note: requirementsNote || null,
      });
      setPlan(result);
    } catch (caught) {
      setError(caught);
    } finally {
      setLoading(false);
    }
  }

  if (sites.length === 0) {
    return (
      <Card title="Build the construction plan">
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <MapPin className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
          <div>
            <p className="text-sm font-semibold text-amber-950">Add a candidate site first</p>
            <p className="mt-1 text-xs text-amber-800">
              The plan needs a site so climate, water and physical constraints can be attached to the equipment schedule.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const selectedSite = sites.find((site) => site.id === siteId);

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-2xl bg-gradient-to-br from-ink-900 via-ink-800 to-signal-600 p-5 text-white shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <Badge className="border-white/20 bg-white/10 text-white">During construction</Badge>
            <h2 className="mt-3 text-xl font-bold">Turn the selected site into an equipment plan</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-100">
              Choose the site, enter the facility requirements, and get a sized equipment schedule with power, water, cost and delivery estimates.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            {["1 · Site", "2 · Requirements", "3 · Plan"].map((step) => (
              <span key={step} className="rounded-lg border border-white/15 bg-white/10 px-3 py-2 font-semibold">
                {step}
              </span>
            ))}
          </div>
        </div>
      </div>

      {error ? <ErrorState error={error} onRetry={generatePlan} /> : null}

      <Card
        title="1. Select the construction site"
        subtitle="Site evidence and the nearest climate station will constrain the plan"
      >
        <div className="grid max-h-64 gap-2 overflow-y-auto pr-1 md:grid-cols-3">
          {sites.map((site) => (
            <button
              type="button"
              key={site.id}
              onClick={() => {
                setSiteId(site.id);
                setPlan(null);
              }}
              aria-pressed={siteId === site.id}
              className={cx(
                "rounded-xl border p-3 text-left transition-all",
                siteId === site.id
                  ? "border-signal-600 bg-emerald-50 shadow-sm"
                  : "border-ink-200 bg-white hover:border-ink-400",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="flex items-center gap-2 text-sm font-semibold text-ink-900">
                  <MapPin className="h-4 w-4 text-signal-600" /> {site.name}
                </span>
                {site.shortlisted ? (
                  <Badge className="border-emerald-200 bg-emerald-100 text-emerald-800">shortlisted</Badge>
                ) : null}
              </div>
              <p className="mt-1 text-xs text-ink-500">{site.address ?? site.jurisdiction ?? "Coordinates supplied"}</p>
              <p className="mt-2 text-[11px] text-ink-500">
                {site.area_hectares ? `${site.area_hectares} ha` : "Area not supplied"}
                {site.latitude != null && site.longitude != null
                  ? ` · ${site.latitude.toFixed(3)}, ${site.longitude.toFixed(3)}`
                  : " · unresolved location"}
              </p>
            </button>
          ))}
        </div>
      </Card>

      <Card
        title="2. Enter project requirements"
        subtitle={selectedSite ? `Sizing basis for ${selectedSite.name}` : "Select a site above"}
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Target IT load" hint="Critical IT capacity in MW" htmlFor="plan-it-load">
            <input
              id="plan-it-load"
              className={inputClass}
              type="number"
              min="0.1"
              max="500"
              step="0.1"
              value={itLoadMw}
              onChange={(event) => setItLoadMw(Number(event.target.value))}
            />
          </Field>
          <Field label="Redundancy" hint="Applied to each equipment train" htmlFor="plan-redundancy">
            <select
              id="plan-redundancy"
              className={inputClass}
              value={redundancy}
              onChange={(event) => setRedundancy(event.target.value as "N" | "N+1" | "2N")}
            >
              <option value="N">N · capacity only</option>
              <option value="N+1">N+1 · one spare</option>
              <option value="2N">2N · fully duplicated</option>
            </select>
          </Field>
          <Field label="Target PUE" hint="Peak facility power ÷ IT power" htmlFor="plan-pue">
            <input
              id="plan-pue"
              className={inputClass}
              type="number"
              min="1"
              max="3"
              step="0.01"
              value={targetPue}
              onChange={(event) => setTargetPue(Number(event.target.value))}
            />
          </Field>
          <Field label="Average utilization" hint="Used for annual energy" htmlFor="plan-utilization">
            <div className="relative">
              <input
                id="plan-utilization"
                className={cx(inputClass, "pr-8")}
                type="number"
                min="1"
                max="100"
                value={utilizationPct}
                onChange={(event) => setUtilizationPct(Number(event.target.value))}
              />
              <span className="absolute right-3 top-1.5 text-sm text-ink-500">%</span>
            </div>
          </Field>
          <Field label="Cooling strategy" hint="Adds economizer equipment when selected" htmlFor="plan-cooling">
            <select
              id="plan-cooling"
              className={inputClass}
              value={coolingStrategy}
              onChange={(event) =>
                setCoolingStrategy(event.target.value as "water_cooled" | "hybrid_economizer")
              }
            >
              <option value="water_cooled">Water-cooled plant</option>
              <option value="hybrid_economizer">Water-cooled + economizer</option>
            </select>
          </Field>
          <Field label="Electricity tariff" hint="USD per kWh; replace the benchmark" htmlFor="plan-rate">
            <input
              id="plan-rate"
              className={inputClass}
              type="number"
              min="0"
              max="5"
              step="0.001"
              value={electricityRate}
              onChange={(event) => setElectricityRate(Number(event.target.value))}
            />
          </Field>
          <Field label="Equipment budget (optional)" hint="Compared with the planning range" htmlFor="plan-budget">
            <input
              id="plan-budget"
              className={inputClass}
              type="number"
              min="1"
              step="100000"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              placeholder="e.g. 30000000"
            />
          </Field>
          <Field label="Other requirements" hint="Recorded for engineering review" htmlFor="plan-note">
            <input
              id="plan-note"
              className={inputClass}
              value={requirementsNote}
              onChange={(event) => setRequirementsNote(event.target.value)}
              placeholder="Phasing, fuel, noise, schedule…"
            />
          </Field>
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-ink-100 pt-4">
          <p className="max-w-2xl text-[11px] text-ink-500">
            Quantities and energy are calculated from these fields. Free-text notes never silently change a numeric engineering check.
          </p>
          <Button
            variant="primary"
            loading={loading}
            disabled={!siteId || itLoadMw <= 0 || targetPue < 1 || utilizationPct <= 0}
            onClick={generatePlan}
          >
            <Play className="h-3.5 w-3.5" /> Generate construction plan
          </Button>
        </div>
      </Card>

      {plan ? <PlanResults plan={plan} /> : null}
    </div>
  );
}

function PlanResults({ plan }: { plan: ConstructionPlanResponse }) {
  const totals = plan.totals;
  const budgetClass =
    totals.budget_status === "BELOW_RANGE"
      ? "border-rose-200 bg-rose-50 text-rose-800"
      : "border-emerald-200 bg-emerald-50 text-emerald-800";

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="3. Construction plan summary"
        subtitle={`${plan.site.name} · ${plan.design_basis.redundancy} redundancy · ${plan.design_basis.target_pue} target PUE`}
        actions={<Badge className="border-emerald-200 bg-emerald-100 text-emerald-800">plan ready</Badge>}
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <SummaryMetric
            icon={<Zap className="h-4 w-4" />}
            label="Peak facility power"
            value={metric(totals.peak_facility_power_kw / 1000, "MW")}
            detail={`${number.format(totals.facility_overhead_kw)} kW facility overhead`}
          />
          <SummaryMetric
            icon={<ClipboardList className="h-4 w-4" />}
            label="Annual energy"
            value={metric(totals.annual_energy_kwh / 1_000_000, "GWh")}
            detail={`${plan.design_basis.utilization_pct}% utilization`}
          />
          <SummaryMetric
            icon={<DollarSign className="h-4 w-4" />}
            label="Annual electricity"
            value={money.format(totals.annual_energy_cost_usd)}
            detail={`$${Number(plan.design_basis.electricity_rate_usd_kwh).toFixed(3)}/kWh tariff`}
          />
          <SummaryMetric
            icon={<Droplets className="h-4 w-4" />}
            label="Annual cooling water"
            value={totals.annual_water_m3 != null ? metric(totals.annual_water_m3, "m³") : "Needs data"}
            detail="LBNL first-pass benchmark"
          />
          <SummaryMetric
            icon={<HardHat className="h-4 w-4" />}
            label="Equipment plan range"
            value={`${money.format(totals.plan_cost_low_usd)}–${money.format(totals.plan_cost_high_usd)}`}
            detail={`Includes ${totals.contingency_pct}% contingency`}
          />
        </div>
        {totals.budget_usd != null ? (
          <div className={cx("mt-3 rounded-lg border px-3 py-2 text-xs", budgetClass)}>
            <span className="font-semibold">Budget check: </span>
            {totals.budget_status === "BELOW_RANGE"
              ? `${money.format(totals.budget_usd)} is below the low planning estimate by ${money.format(totals.plan_cost_low_usd - totals.budget_usd)}.`
              : `${money.format(totals.budget_usd)} covers the low end of the current planning range.`}
          </div>
        ) : null}
      </Card>

      {plan.site_constraints.length > 0 ? (
        <Card title="Site-specific design inputs" subtitle="Measured or dataset-backed values attached to this plan">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {plan.site_constraints.map((constraint) => (
              <div key={constraint.field_key} className="rounded-lg border border-ink-200 bg-ink-50 p-3">
                <p className="text-[11px] font-medium uppercase tracking-wide text-ink-500">{constraint.label}</p>
                <p className="mt-1 text-base font-bold text-ink-900">
                  {typeof constraint.value === "number" ? measurement.format(constraint.value) : constraint.value} {constraint.unit ?? ""}
                </p>
                <p className="mt-1 text-[10px] leading-relaxed text-ink-500">{constraint.source}</p>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <Card
        title="Equipment schedule"
        subtitle="Open reference models sized to the selected capacity and redundancy basis"
        actions={<Badge className="border-amber-200 bg-amber-100 text-amber-900">synthetic cost ranges</Badge>}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[68rem] text-left text-xs">
            <thead className="text-ink-500">
              <tr>
                <th className="pb-2 pr-3 font-medium">Equipment</th>
                <th className="pb-2 pr-3 font-medium">Reference model</th>
                <th className="pb-2 pr-3 text-right font-medium">Qty</th>
                <th className="pb-2 pr-3 text-right font-medium">Rated duty / unit</th>
                <th className="pb-2 pr-3 text-right font-medium">Connected kW</th>
                <th className="pb-2 pr-3 text-right font-medium">Lead time</th>
                <th className="pb-2 text-right font-medium">Installed planning range</th>
              </tr>
            </thead>
            <tbody>
              {plan.equipment_schedule.map((item) => (
                <tr key={item.category} className="border-t border-ink-100 align-top">
                  <td className="py-2.5 pr-3">
                    <p className="font-semibold text-ink-900">{item.label}</p>
                    <p className="mt-0.5 text-[10px] text-ink-500">{item.category.replaceAll("_", " ")}</p>
                  </td>
                  <td className="max-w-xs py-2.5 pr-3">
                    <p className="font-medium text-ink-800">{item.model_number}</p>
                    <p className="mt-0.5 text-[10px] text-ink-500">{item.manufacturer}</p>
                  </td>
                  <td className="py-2.5 pr-3 text-right text-base font-bold tabular text-ink-900">{item.quantity}</td>
                  <td className="py-2.5 pr-3 text-right tabular">
                    {item.duty_per_unit != null ? `${number.format(item.duty_per_unit)} ${item.duty_unit ?? ""}` : "—"}
                  </td>
                  <td className="py-2.5 pr-3 text-right tabular">
                    {item.connected_power_kw > 0 ? number.format(item.connected_power_kw) : "—"}
                  </td>
                  <td className="py-2.5 pr-3 text-right tabular">{item.lead_time_weeks} weeks</td>
                  <td className="py-2.5 text-right font-semibold tabular text-ink-900">
                    {money.format(item.estimated_cost_low_usd)}–{money.format(item.estimated_cost_high_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card title="Construction sequence" subtitle="A simple dependency order for the concept plan">
          <ol className="flex flex-col gap-3">
            {plan.work_packages.map((workPackage) => (
              <li key={workPackage.sequence} className="flex gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink-900 text-xs font-bold text-white">
                  {workPackage.sequence}
                </span>
                <div>
                  <p className="text-sm font-semibold text-ink-900">{workPackage.name}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-ink-600">{workPackage.scope}</p>
                  {workPackage.depends_on.length > 0 ? (
                    <p className="mt-1 text-[10px] text-ink-400">After: {workPackage.depends_on.join(", ")}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Data quality and next checks" subtitle="What can be pitched now, and what must be replaced later">
          <div className="flex flex-col gap-3">
            {plan.warnings.map((warning, index) => (
              <div key={warning} className="flex gap-2.5 text-xs leading-relaxed text-ink-700">
                {index === 0 ? (
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                ) : (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-signal-600" />
                )}
                <span>{warning}</span>
              </div>
            ))}
            <div className="border-t border-ink-100 pt-3">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                <Database className="h-3.5 w-3.5" /> Sources
              </p>
              <ul className="mt-2 flex flex-col gap-1 text-[11px] text-ink-500">
                {plan.data_sources.map((source) => (
                  <li key={source}>• {source}</li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function SummaryMetric({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-ink-200 bg-ink-50 p-3">
      <p className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500">
        {icon} {label}
      </p>
      <p className="mt-1.5 text-base font-bold tabular text-ink-900">{value}</p>
      <p className="mt-0.5 text-[10px] text-ink-500">{detail}</p>
    </div>
  );
}
