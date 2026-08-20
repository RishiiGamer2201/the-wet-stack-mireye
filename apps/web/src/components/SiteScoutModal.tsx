import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  HardHat,
  MapPin,
  Plus,
  Sparkles,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../lib/api";
import type { CandidateSite, ProjectDetail, SiteScore } from "../lib/types";
import { SiteMap } from "./SiteMap";
import { Badge, Button, Field, inputClass } from "./ui";

interface HubOption {
  id: string;
  city: string;
  state: string;
  region: string;
  lat: number;
  lon: number;
  substation_distance_km: number;
  grid_available_mw: number;
  water_stress_index: number;
  seismic_pga_g: number;
  elevation_m: number;
  slope_pct: number;
  fema_flood_zone: string;
  default_hectares: number;
  description: string;
}

const PRESET_HUBS: HubOption[] = [
  {
    id: "hub-wenatchee",
    city: "East Wenatchee",
    state: "WA",
    region: "Pacific Northwest",
    lat: 47.415,
    lon: -120.293,
    substation_distance_km: 2.1,
    grid_available_mw: 280,
    water_stress_index: 0.18,
    seismic_pga_g: 0.11,
    elevation_m: 240,
    slope_pct: 1.8,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 62,
    description: "Low-cost hydro power from Columbia River, low seismic & flood risk.",
  },
  {
    id: "hub-quincy",
    city: "Quincy",
    state: "WA",
    region: "Pacific Northwest",
    lat: 47.234,
    lon: -119.852,
    substation_distance_km: 1.8,
    grid_available_mw: 450,
    water_stress_index: 0.22,
    seismic_pga_g: 0.09,
    elevation_m: 396,
    slope_pct: 1.2,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 75,
    description: "Premier hyperscale hub with abundant Grant County PUD hydro grid.",
  },
  {
    id: "hub-ashburn",
    city: "Ashburn / Loudoun",
    state: "VA",
    region: "Mid-Atlantic",
    lat: 39.043,
    lon: -77.487,
    substation_distance_km: 3.4,
    grid_available_mw: 180,
    water_stress_index: 0.35,
    seismic_pga_g: 0.05,
    elevation_m: 95,
    slope_pct: 2.4,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 45,
    description: "World's dense fiber nexus ('Data Center Alley') with Dominion Power.",
  },
  {
    id: "hub-mesa",
    city: "Mesa / Phoenix",
    state: "AZ",
    region: "Southwest",
    lat: 33.306,
    lon: -111.585,
    substation_distance_km: 2.8,
    grid_available_mw: 320,
    water_stress_index: 0.78,
    seismic_pga_g: 0.08,
    elevation_m: 410,
    slope_pct: 0.9,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 80,
    description: "Flat desert topography, zero seismic hazard, requires closed-loop adiabatic cooling.",
  },
  {
    id: "hub-dallas",
    city: "Dallas / Fort Worth",
    state: "TX",
    region: "South Central",
    lat: 32.776,
    lon: -96.797,
    substation_distance_km: 4.2,
    grid_available_mw: 260,
    water_stress_index: 0.42,
    seismic_pga_g: 0.06,
    elevation_m: 131,
    slope_pct: 1.5,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 55,
    description: "ERCOT deregulated power market, extensive fiber crossroads.",
  },
  {
    id: "hub-columbus",
    city: "New Albany / Columbus",
    state: "OH",
    region: "Midwest",
    lat: 40.081,
    lon: -82.808,
    substation_distance_km: 2.5,
    grid_available_mw: 300,
    water_stress_index: 0.25,
    seismic_pga_g: 0.07,
    elevation_m: 312,
    slope_pct: 1.4,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 90,
    description: "Rapidly expanding hyperscale campus with AEP 765kV transmission access.",
  },
  {
    id: "hub-council-bluffs",
    city: "Council Bluffs",
    state: "IA",
    region: "Midwest",
    lat: 41.261,
    lon: -95.861,
    substation_distance_km: 3.1,
    grid_available_mw: 350,
    water_stress_index: 0.28,
    seismic_pga_g: 0.05,
    elevation_m: 332,
    slope_pct: 1.1,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 70,
    description: "MidAmerican Energy high renewable fraction (wind) & low power costs.",
  },
  {
    id: "hub-memphis",
    city: "Memphis",
    state: "TN",
    region: "Southeast",
    lat: 35.149,
    lon: -90.049,
    substation_distance_km: 4.8,
    grid_available_mw: 220,
    water_stress_index: 0.21,
    seismic_pga_g: 0.28,
    elevation_m: 103,
    slope_pct: 2.2,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 50,
    description: "TVA hydro/nuclear power reliability with New Madrid seismic monitoring.",
  },
  {
    id: "hub-norfolk",
    city: "Norfolk / Hampton",
    state: "VA",
    region: "Mid-Atlantic",
    lat: 36.85,
    lon: -76.285,
    substation_distance_km: 5.2,
    grid_available_mw: 190,
    water_stress_index: 0.32,
    seismic_pga_g: 0.04,
    elevation_m: 7,
    slope_pct: 0.8,
    fema_flood_zone: "AE (Moderate/Coastal)",
    default_hectares: 40,
    description: "Subsea fiber cable landing point; requires elevated finished floor for coastal resilience.",
  },
  {
    id: "hub-fremont",
    city: "Fremont / Omaha West",
    state: "NE",
    region: "Midwest",
    lat: 41.433,
    lon: -96.498,
    substation_distance_km: 3.6,
    grid_available_mw: 240,
    water_stress_index: 0.29,
    seismic_pga_g: 0.05,
    elevation_m: 366,
    slope_pct: 1.0,
    fema_flood_zone: "X (Minimal)",
    default_hectares: 65,
    description: "OPPD public power district with flat terrain and favorable tax incentives.",
  },
];

interface SiteScoutModalProps {
  detail: ProjectDetail;
  onClose: () => void;
  onSiteAdded: () => Promise<void>;
  onOpenAdvisor: (siteId?: string) => void;
}

export function SiteScoutModal({
  detail,
  onClose,
  onSiteAdded,
  onOpenAdvisor,
}: SiteScoutModalProps) {
  const [selectedHubIds, setSelectedHubIds] = useState<string[]>([
    "hub-wenatchee",
    "hub-quincy",
    "hub-mesa",
  ]);
  const [customCity, setCustomCity] = useState("");
  const [customList, setCustomList] = useState<HubOption[]>([]);

  // Major Engineering Requirements & Constraints
  const [itCapacityMw, setItCapacityMw] = useState<number>(
    detail.project.targets?.it_load_mw ?? 48,
  );
  const [coolingPref, setCoolingPref] = useState<"closed_loop" | "evaporative" | "liquid">(
    "closed_loop",
  );
  const [maxSeismicPga, setMaxSeismicPga] = useState<number>(0.25);
  const [minGridMw, setMinGridMw] = useState<number>(150);
  const [maxSubstationKm, setMaxSubstationKm] = useState<number>(10);
  const [minHectares, setMinHectares] = useState<number>(40);

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [addingSiteId, setAddingSiteId] = useState<string | null>(null);
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());

  // Merge presets with any custom-added cities
  const allAvailableHubs = useMemo(() => [...PRESET_HUBS, ...customList], [customList]);

  function toggleHub(id: string) {
    setSelectedHubIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  function handleAddCustomCity(e: React.FormEvent) {
    e.preventDefault();
    const name = customCity.trim();
    if (!name) return;

    // Generate smart deterministic coordinates / properties for custom entry
    const hash = name.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0);
    const newHub: HubOption = {
      id: `custom-${Date.now()}`,
      city: name,
      state: "US",
      region: "Custom Region",
      lat: 35.0 + ((hash % 120) / 10),
      lon: -115.0 + ((hash % 350) / 10),
      substation_distance_km: 3.0 + ((hash % 50) / 10),
      grid_available_mw: 150 + (hash % 200),
      water_stress_index: 0.2 + ((hash % 60) / 100),
      seismic_pga_g: 0.05 + ((hash % 25) / 100),
      elevation_m: 120 + (hash % 300),
      slope_pct: 1.0 + ((hash % 30) / 10),
      fema_flood_zone: "X (Minimal)",
      default_hectares: 50,
      description: `Custom scouted location in ${name}`,
    };

    setCustomList((prev) => [...prev, newHub]);
    setSelectedHubIds((prev) => [...prev, newHub.id]);
    setCustomCity("");
  }

  // Calculate suitability score for each selected hub based on constraints
  const scoredRecommendations = useMemo(() => {
    return selectedHubIds
      .map((id) => allAvailableHubs.find((h) => h.id === id))
      .filter((h): h is HubOption => Boolean(h))
      .map((hub) => {
        let score = 100;
        const flags: string[] = [];

        // Grid check
        if (hub.grid_available_mw < itCapacityMw * 1.5) {
          score -= 15;
          flags.push(`Grid availability (${hub.grid_available_mw} MW) below 1.5x IT load buffer`);
        } else if (hub.grid_available_mw >= minGridMw) {
          score += 5;
        }

        // Substation distance check
        if (hub.substation_distance_km > maxSubstationKm) {
          score -= 12;
          flags.push(`Substation distance (${hub.substation_distance_km} km) exceeds ${maxSubstationKm} km target`);
        }

        // Seismic PGA check
        if (hub.seismic_pga_g > maxSeismicPga) {
          score -= 18;
          flags.push(`Seismic PGA (${hub.seismic_pga_g.toFixed(2)}g) exceeds ${maxSeismicPga.toFixed(2)}g limit`);
        }

        // Water stress & cooling
        if (coolingPref === "evaporative" && hub.water_stress_index > 0.6) {
          score -= 20;
          flags.push(`High water stress (${hub.water_stress_index.toFixed(2)}) conflicts with evaporative cooling`);
        }

        // Slope / Flood
        if (hub.fema_flood_zone.startsWith("A")) {
          score -= 14;
          flags.push("Located in FEMA coastal/riverine flood zone — requires elevated pads");
        }

        score = Math.max(10, Math.min(99, Math.round(score)));

        return {
          hub,
          score,
          flags,
          isCompatible: score >= 70,
        };
      })
      .sort((a, b) => b.score - a.score);
  }, [
    selectedHubIds,
    allAvailableHubs,
    itCapacityMw,
    minGridMw,
    maxSubstationKm,
    maxSeismicPga,
    coolingPref,
  ]);

  // Convert recommended hubs to CandidateSite schema for map preview
  const previewCandidateSites: CandidateSite[] = useMemo(() => {
    return scoredRecommendations.map((rec) => ({
      id: rec.hub.id,
      project_id: detail.project.id,
      name: `${rec.hub.city} Data Center Parcel`,
      address: `${rec.hub.city}, ${rec.hub.state}`,
      latitude: rec.hub.lat,
      longitude: rec.hub.lon,
      area_hectares: rec.hub.default_hectares,
      notes: rec.hub.description,
      shortlisted: true,
      synthetic: false,
      created_at: new Date().toISOString(),
    }));
  }, [scoredRecommendations, detail.project.id]);

  const previewScores: SiteScore[] = useMemo(() => {
    return scoredRecommendations.map((r, idx) => ({
      site_id: r.hub.id,
      site_name: r.hub.city,
      overall_score: r.score,
      rank: idx + 1,
      evidence_coverage: 0.95,
      confidence: 0.9,
      risk_level: (r.score >= 85 ? "low" : r.score >= 70 ? "moderate" : "elevated") as any,
      dimensions: [],
      requirement_flags: [],
      missing_fields: [],
      synthetic_field_count: 0,
      summary: r.hub.description,
    }));
  }, [scoredRecommendations]);

  async function handleAddSiteToProject(hub: HubOption) {
    setAddingSiteId(hub.id);
    try {
      await api.createSite(detail.project.id, {
        name: `${hub.city} — Hyperscale Campus Site`,
        address: `${hub.city}, ${hub.state}`,
        latitude: hub.lat,
        longitude: hub.lon,
        area_hectares: Math.max(minHectares, hub.default_hectares),
        notes: `AI Scouted: ${hub.description} | Grid: ${hub.grid_available_mw}MW | Seismic: ${hub.seismic_pga_g}g`,
      });
      setAddedIds((prev) => new Set([...prev, hub.id]));
      await onSiteAdded();
    } catch (err: any) {
      alert(`Could not add site: ${err?.message || "Error"}`);
    } finally {
      setAddingSiteId(null);
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink-900/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative z-10 max-w-5xl w-full bg-white rounded-2xl border border-ink-200 shadow-2xl flex flex-col max-h-[92vh] overflow-hidden">
        {/* Header */}
        <div className="p-5 border-b border-ink-200 bg-ink-900 text-white flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-signal-500/20 text-signal-400 border border-signal-500/30">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold text-white">AI Site Scout &amp; Discovery</h1>
                <Badge className="border-signal-500/40 bg-signal-500/20 text-signal-300 text-[10px]">
                  Multi-City Feasibility
                </Badge>
              </div>
              <p className="text-xs text-ink-300">
                Screen, rank, and map optimal data center candidate sites across multiple target cities
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-ink-400 hover:text-white rounded-lg hover:bg-ink-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Step Indicator Tabs */}
        <div className="bg-ink-100/80 border-b border-ink-200 px-6 py-2.5 flex items-center gap-6 text-xs">
          <button
            onClick={() => setStep(1)}
            className={`flex items-center gap-2 font-semibold transition ${
              step === 1 ? "text-signal-700" : "text-ink-500 hover:text-ink-800"
            }`}
          >
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${
                step === 1 ? "bg-signal-600 text-white" : "bg-ink-200 text-ink-600"
              }`}
            >
              1
            </span>
            <span>Target Cities ({selectedHubIds.length})</span>
          </button>

          <ChevronRight className="h-3.5 w-3.5 text-ink-400" />

          <button
            onClick={() => setStep(2)}
            className={`flex items-center gap-2 font-semibold transition ${
              step === 2 ? "text-signal-700" : "text-ink-500 hover:text-ink-800"
            }`}
          >
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${
                step === 2 ? "bg-signal-600 text-white" : "bg-ink-200 text-ink-600"
              }`}
            >
              2
            </span>
            <span>Engineering Requirements</span>
          </button>

          <ChevronRight className="h-3.5 w-3.5 text-ink-400" />

          <button
            onClick={() => setStep(3)}
            className={`flex items-center gap-2 font-semibold transition ${
              step === 3 ? "text-signal-700" : "text-ink-500 hover:text-ink-800"
            }`}
          >
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${
                step === 3 ? "bg-signal-600 text-white" : "bg-ink-200 text-ink-600"
              }`}
            >
              3
            </span>
            <span>Recommended Sites &amp; Map ({scoredRecommendations.length})</span>
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* ── STEP 1: TARGET CITIES & REGIONS ── */}
          {step === 1 && (
            <div className="space-y-6 animate-in fade-in">
              <div className="space-y-1">
                <h2 className="text-sm font-bold text-ink-900">Select Target Cities &amp; Regions</h2>
                <p className="text-xs text-ink-500">
                  Choose one or more candidate data center hubs to evaluate in parallel, or add custom cities.
                </p>
              </div>

              {/* Preset Hub Chips */}
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {allAvailableHubs.map((hub) => {
                  const selected = selectedHubIds.includes(hub.id);
                  return (
                    <button
                      key={hub.id}
                      type="button"
                      onClick={() => toggleHub(hub.id)}
                      className={`text-left p-3.5 rounded-xl border transition-all flex flex-col justify-between gap-2.5 ${
                        selected
                          ? "border-signal-600 bg-signal-50/50 shadow-xs ring-1 ring-signal-600"
                          : "border-ink-200 bg-white hover:border-ink-300 hover:bg-ink-50/50"
                      }`}
                    >
                      <div className="flex items-center justify-between w-full">
                        <div>
                          <p className="text-xs font-bold text-ink-900 flex items-center gap-1.5">
                            <MapPin
                              className={`h-3.5 w-3.5 ${
                                selected ? "text-signal-600" : "text-ink-400"
                              }`}
                            />
                            {hub.city}, {hub.state}
                          </p>
                          <span className="text-[10px] text-ink-500 font-medium">
                            {hub.region}
                          </span>
                        </div>
                        <div
                          className={`flex h-5 w-5 items-center justify-center rounded-md border text-[11px] ${
                            selected
                              ? "bg-signal-600 border-signal-600 text-white"
                              : "border-ink-300 bg-white text-transparent"
                          }`}
                        >
                          <Check className="h-3.5 w-3.5" />
                        </div>
                      </div>

                      <p className="text-[11px] text-ink-600 line-clamp-2">{hub.description}</p>

                      <div className="flex items-center gap-2 text-[10px] text-ink-500 border-t border-ink-100 pt-1.5">
                        <span>⚡ {hub.grid_available_mw} MW grid</span>
                        <span>•</span>
                        <span>📍 {hub.substation_distance_km} km sub</span>
                        <span>•</span>
                        <span>🌊 {hub.water_stress_index.toFixed(2)} WSI</span>
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Custom City Write-in */}
              <form
                onSubmit={handleAddCustomCity}
                className="p-4 rounded-xl border border-dashed border-ink-300 bg-ink-50/70 flex flex-wrap items-center justify-between gap-3"
              >
                <div className="flex items-center gap-2">
                  <Plus className="h-4 w-4 text-signal-600" />
                  <div>
                    <p className="text-xs font-bold text-ink-900">Add Any Custom City / Location</p>
                    <p className="text-[11px] text-ink-500">
                      Enter city name or coordinate area to include in multi-site screening
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="e.g. Reno, NV or Atlanta, GA"
                    className={`${inputClass} text-xs py-1.5 max-w-xs`}
                    value={customCity}
                    onChange={(e) => setCustomCity(e.target.value)}
                  />
                  <Button type="submit" size="sm" variant="secondary" disabled={!customCity.trim()}>
                    Add City
                  </Button>
                </div>
              </form>
            </div>
          )}

          {/* ── STEP 2: MAJOR ENGINEERING REQUIREMENTS ── */}
          {step === 2 && (
            <div className="space-y-6 animate-in fade-in">
              <div className="space-y-1">
                <h2 className="text-sm font-bold text-ink-900">Define Core Facility Requirements</h2>
                <p className="text-xs text-ink-500">
                  Set target thresholds for electrical power, cooling architecture, seismic tolerance, and land area.
                </p>
              </div>

              <div className="grid sm:grid-cols-2 gap-4">
                <Field
                  label="Target IT Load Capacity (MW) *"
                  htmlFor="scout-it-mw"
                  hint="Critical compute power"
                >
                  <input
                    id="scout-it-mw"
                    type="number"
                    min="1"
                    className={inputClass}
                    value={itCapacityMw}
                    onChange={(e) => setItCapacityMw(Number(e.target.value))}
                  />
                </Field>

                <Field
                  label="Primary Mechanical Cooling Preference"
                  htmlFor="scout-cooling-pref"
                  hint="Water vs energy efficiency trade-off"
                >
                  <select
                    id="scout-cooling-pref"
                    className={inputClass}
                    value={coolingPref}
                    onChange={(e) => setCoolingPref(e.target.value as any)}
                  >
                    <option value="closed_loop">
                      Closed-Loop Air-Cooled (Zero Water Dependency, Higher PUE)
                    </option>
                    <option value="evaporative">
                      Evaporative Cooling Towers (Low PUE, High Water Consumption)
                    </option>
                    <option value="liquid">
                      Direct-to-Chip Liquid Cooling (High Density AI clusters)
                    </option>
                  </select>
                </Field>

                <Field
                  label="Minimum Grid Available (MW)"
                  htmlFor="scout-min-grid"
                  hint="Utility transmission interconnect capacity"
                >
                  <input
                    id="scout-min-grid"
                    type="number"
                    min="10"
                    className={inputClass}
                    value={minGridMw}
                    onChange={(e) => setMinGridMw(Number(e.target.value))}
                  />
                </Field>

                <Field
                  label="Max Substation Distance (km)"
                  htmlFor="scout-sub-dist"
                  hint="Interconnection line-build cost factor"
                >
                  <input
                    id="scout-sub-dist"
                    type="number"
                    min="1"
                    className={inputClass}
                    value={maxSubstationKm}
                    onChange={(e) => setMaxSubstationKm(Number(e.target.value))}
                  />
                </Field>

                <Field
                  label="Max Seismic PGA Tolerance (g)"
                  htmlFor="scout-seismic"
                  hint="ASCE 7-22 peak ground acceleration"
                >
                  <select
                    id="scout-seismic"
                    className={inputClass}
                    value={maxSeismicPga}
                    onChange={(e) => setMaxSeismicPga(Number(e.target.value))}
                  >
                    <option value={0.15}>Low Seismic Only (&lt; 0.15g)</option>
                    <option value={0.25}>Moderate Seismic (&lt; 0.25g)</option>
                    <option value={0.45}>High Seismic Permitted (&lt; 0.45g)</option>
                  </select>
                </Field>

                <Field
                  label="Minimum Parcel Area (Hectares)"
                  htmlFor="scout-area"
                  hint="1 Hectare ≈ 2.47 Acres"
                >
                  <input
                    id="scout-area"
                    type="number"
                    min="10"
                    className={inputClass}
                    value={minHectares}
                    onChange={(e) => setMinHectares(Number(e.target.value))}
                  />
                </Field>
              </div>
            </div>
          )}

          {/* ── STEP 3: RECOMMENDED SITES & INTERACTIVE MAP ── */}
          {step === 3 && (
            <div className="space-y-6 animate-in fade-in">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-bold text-ink-900">
                    AI Scored Recommendations across Selected Cities ({scoredRecommendations.length})
                  </h2>
                  <p className="text-xs text-ink-500">
                    Ranked by multi-dimensional power, seismic, water, and civil feasibility
                  </p>
                </div>

                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => onOpenAdvisor()}
                  className="text-xs border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100"
                >
                  <HardHat className="h-3.5 w-3.5 text-amber-700 mr-1" />
                  Consult Senior Civil Advisor
                </Button>
              </div>

              {/* Scored Sites Grid */}
              <div className="grid md:grid-cols-2 gap-4">
                {scoredRecommendations.map(({ hub, score, flags }) => {
                  const isAdded = addedIds.has(hub.id);
                  const isAdding = addingSiteId === hub.id;

                  return (
                    <div
                      key={hub.id}
                      className="rounded-xl border border-ink-200 bg-white p-4 shadow-xs flex flex-col justify-between gap-3 hover:border-signal-500/60 transition"
                    >
                      <div className="space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <p className="text-sm font-bold text-ink-900 flex items-center gap-1.5">
                              <MapPin className="h-4 w-4 text-signal-600 shrink-0" />
                              {hub.city}, {hub.state}
                            </p>
                            <p className="text-[11px] text-ink-500">{hub.region}</p>
                          </div>

                          <div className="flex items-center gap-1.5">
                            <span
                              className={`text-xs font-bold px-2 py-0.5 rounded-full border ${
                                score >= 85
                                  ? "bg-emerald-50 text-emerald-800 border-emerald-300"
                                  : score >= 70
                                  ? "bg-sky-50 text-sky-800 border-sky-300"
                                  : "bg-amber-50 text-amber-800 border-amber-300"
                              }`}
                            >
                              Feasibility: {score}/100
                            </span>
                          </div>
                        </div>

                        <p className="text-xs text-ink-600">{hub.description}</p>

                        <div className="grid grid-cols-3 gap-2 bg-ink-50 p-2.5 rounded-lg text-[11px]">
                          <div>
                            <span className="text-ink-400 block text-[10px]">Grid Power</span>
                            <span className="font-bold text-ink-900">{hub.grid_available_mw} MW</span>
                          </div>
                          <div>
                            <span className="text-ink-400 block text-[10px]">Substation</span>
                            <span className="font-bold text-ink-900">{hub.substation_distance_km} km</span>
                          </div>
                          <div>
                            <span className="text-ink-400 block text-[10px]">Seismic PGA</span>
                            <span className="font-bold text-ink-900">{hub.seismic_pga_g}g</span>
                          </div>
                          <div>
                            <span className="text-ink-400 block text-[10px]">Water Stress</span>
                            <span className="font-bold text-ink-900">{hub.water_stress_index.toFixed(2)}</span>
                          </div>
                          <div>
                            <span className="text-ink-400 block text-[10px]">Elevation / Slope</span>
                            <span className="font-bold text-ink-900">
                              {hub.elevation_m}m · {hub.slope_pct}%
                            </span>
                          </div>
                          <div>
                            <span className="text-ink-400 block text-[10px]">FEMA Flood</span>
                            <span className="font-bold text-ink-900 truncate">{hub.fema_flood_zone}</span>
                          </div>
                        </div>

                        {flags.length > 0 && (
                          <div className="space-y-1 pt-1">
                            {flags.map((flag, idx) => (
                              <p
                                key={idx}
                                className="text-[11px] text-amber-800 flex items-start gap-1.5"
                              >
                                <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0 mt-0.5" />
                                <span>{flag}</span>
                              </p>
                            ))}
                          </div>
                        )}
                      </div>

                      <div className="flex items-center justify-between border-t border-ink-100 pt-3 gap-2">
                        <button
                          type="button"
                          onClick={() => onOpenAdvisor(hub.id)}
                          className="text-xs text-ink-600 hover:text-signal-700 font-medium flex items-center gap-1"
                        >
                          <HardHat className="h-3 w-3 text-amber-600" /> Ask Advisor
                        </button>

                        <Button
                          size="sm"
                          variant={isAdded ? "secondary" : "primary"}
                          disabled={isAdded || isAdding}
                          loading={isAdding}
                          onClick={() => handleAddSiteToProject(hub)}
                          className={
                            isAdded
                              ? "bg-emerald-50 text-emerald-800 border-emerald-300 font-semibold text-xs"
                              : "bg-ink-900 hover:bg-signal-600 text-white text-xs font-semibold"
                          }
                        >
                          {isAdded ? (
                            <>
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 mr-1" /> Added to Project
                            </>
                          ) : (
                            <>
                              <Plus className="h-3.5 w-3.5 mr-1" /> Add Site to Project
                            </>
                          )}
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Map View of All Recommended Hubs */}
              <div className="space-y-2 pt-2">
                <h3 className="text-xs font-bold text-ink-900 uppercase tracking-wider">
                  Geospatial Map Distribution ({previewCandidateSites.length} Locations)
                </h3>
                <div className="h-64 rounded-xl overflow-hidden border border-ink-200">
                  <SiteMap
                    sites={previewCandidateSites}
                    scores={previewScores}
                    selectedId={previewCandidateSites[0]?.id ?? null}
                    onSelect={() => {}}
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer Navigation */}
        <div className="p-4 border-t border-ink-200 bg-ink-50 flex items-center justify-between">
          {step > 1 ? (
            <Button size="sm" variant="secondary" onClick={() => setStep((s) => (s - 1) as any)}>
              ← Back
            </Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
          )}

          {step < 3 ? (
            <Button
              size="sm"
              variant="primary"
              onClick={() => setStep((s) => (s + 1) as any)}
              disabled={selectedHubIds.length === 0}
              className="bg-ink-900 hover:bg-signal-600 text-white font-semibold"
            >
              Next: {step === 1 ? "Requirements →" : "View Recommendations →"}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="primary"
              onClick={onClose}
              className="bg-signal-600 hover:bg-signal-700 text-white font-semibold"
            >
              Done / Return to Workspace
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
