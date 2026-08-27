import {
  AlertTriangle,
  CheckCircle2,
  Compass,
  Layers,
  MapPin,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../lib/api";
import { SiteMap } from "./SiteMap";
import { Badge, Button, Field, inputClass } from "./ui";

interface MapBoundaryDrawerModalProps {
  projectId: string;
  onClose: () => void;
  onSiteCreated: () => Promise<void>;
}

const CITY_PRESETS: Array<{ name: string; lat: number; lon: number; label: string }> = [
  { name: "East Wenatchee, WA", lat: 47.415, lon: -120.293, label: "Pacific Northwest Hydro" },
  { name: "Quincy, WA", lat: 47.234, lon: -119.852, label: "Hyperscale Hub" },
  { name: "Dallas, TX", lat: 32.7767, lon: -96.797, label: "ERCOT Grid Crossroads" },
  { name: "Santa Clara, CA", lat: 37.3541, lon: -121.9552, label: "Silicon Valley Alley" },
  { name: "Ashburn, VA", lat: 39.043, lon: -77.487, label: "Data Center Alley" },
  { name: "Frankfurt, Germany", lat: 50.1109, lon: 8.6821, label: "FLAP Europe Hub" },
];

export function MapBoundaryDrawerModal({
  projectId,
  onClose,
  onSiteCreated,
}: MapBoundaryDrawerModalProps) {
  const [siteName, setSiteName] = useState("Custom Parcel Alpha");
  const [cityName, setCityName] = useState("East Wenatchee, WA");
  const [points, setPoints] = useState<Array<{ lat: number; lon: number }>>([
    { lat: 47.418, lon: -120.298 },
    { lat: 47.419, lon: -120.288 },
    { lat: 47.412, lon: -120.286 },
    { lat: 47.411, lon: -120.296 },
  ]);
  const notes = "Drawn custom boundary plot for due-diligence site evaluation";
  const [mapCenter, setMapCenter] = useState<[number, number]>([47.415, -120.293]);
  const [mapZoom, setMapZoom] = useState<number>(13);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Compute centroid
  const centroid = useMemo(() => {
    if (points.length === 0) return { lat: mapCenter[0], lon: mapCenter[1] };
    const sumLat = points.reduce((acc, p) => acc + p.lat, 0);
    const sumLon = points.reduce((acc, p) => acc + p.lon, 0);
    return {
      lat: sumLat / points.length,
      lon: sumLon / points.length,
    };
  }, [points, mapCenter]);

  // Compute polygon area in hectares and acres
  const calculatedArea = useMemo(() => {
    if (points.length < 3) return { hectares: 0, acres: 0 };
    const avgLat = centroid.lat;
    const avgLon = centroid.lon;
    const scaleY = 111320.0;
    const scaleX = scaleY * Math.cos((avgLat * Math.PI) / 180);
    const pts = points.map((p) => [
      (p.lon - avgLon) * scaleX,
      (p.lat - avgLat) * scaleY,
    ]);
    let areaM2 = 0;
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const p1 = pts[i];
      const p2 = pts[(i + 1) % n];
      areaM2 += p1[0] * p2[1] - p2[0] * p1[1];
    }
    areaM2 = Math.abs(areaM2) / 2.0;
    const ha = areaM2 / 10000.0;
    const ac = ha * 2.47105;
    return {
      hectares: Number(ha.toFixed(2)),
      acres: Number(ac.toFixed(1)),
    };
  }, [points, centroid]);

  function handleMapClick(coords: { lat: number; lon: number }) {
    setPoints((prev) => [...prev, coords]);
    setError(null);
  }

  function handleRemovePoint(index: number) {
    setPoints((prev) => prev.filter((_, i) => i !== index));
  }

  function handleResetPoints() {
    setPoints([]);
  }

  function handleSelectPreset(preset: typeof CITY_PRESETS[number]) {
    setCityName(preset.name);
    setMapCenter([preset.lat, preset.lon]);
    setMapZoom(13);
    const dLat = 0.005;
    const dLon = 0.007;
    setPoints([
      { lat: preset.lat + dLat, lon: preset.lon - dLon },
      { lat: preset.lat + dLat, lon: preset.lon + dLon },
      { lat: preset.lat - dLat, lon: preset.lon + dLon },
      { lat: preset.lat - dLat, lon: preset.lon - dLon },
    ]);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (points.length < 3) {
      setError("Please click at least 3 to 5 coordinates on the map to define a closed plot boundary.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const site = await api.createSiteFromBoundary(projectId, {
        name: siteName.trim() || "Custom Polygon Site",
        coordinates: points.map((p) => ({ latitude: p.lat, longitude: p.lon })),
        city: cityName.trim() || undefined,
        area_hectares: calculatedArea.hectares > 0 ? calculatedArea.hectares : undefined,
        notes: notes.trim(),
      });

      await api.runSiteInvestigation(projectId, { site_ids: [site.id] }).catch(() => null);

      await onSiteCreated();
      onClose();
    } catch (err: any) {
      setError(err?.message || "Failed to save and evaluate site boundary.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink-900/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative z-10 max-w-5xl w-full bg-white rounded-2xl border border-ink-200 shadow-2xl flex flex-col max-h-[94vh] overflow-hidden">
        {/* Header */}
        <div className="p-5 border-b border-ink-200 bg-ink-900 text-white flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-signal-500/20 text-signal-400 border border-signal-500/30">
              <Compass className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold text-white">Draw Boundary &amp; Map Coordinates</h1>
                <Badge className="border-signal-500/40 bg-signal-500/20 text-signal-300 text-[10px]">
                  Mireye Telemetry Fetch
                </Badge>
              </div>
              <p className="text-xs text-ink-300">
                Mark 4-5 coordinate pins or draw a polygon on the map to evaluate physical site details via Mireye API
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

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto flex-1 space-y-6">
          {error && (
            <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-700 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-rose-600 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Quick City Presets */}
          <div>
            <label className="block text-xs font-semibold text-ink-700 mb-2">
              Quick City Presets (Centers Map &amp; Initializes Plot Pins)
            </label>
            <div className="flex flex-wrap gap-2">
              {CITY_PRESETS.map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  onClick={() => handleSelectPreset(preset)}
                  className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition flex items-center gap-1.5 ${
                    cityName === preset.name
                      ? "bg-signal-50 border-signal-500 text-signal-700 shadow-sm"
                      : "bg-white border-ink-200 text-ink-700 hover:bg-ink-50"
                  }`}
                >
                  <MapPin className="h-3.5 w-3.5 text-signal-600" />
                  <span>{preset.name}</span>
                  <span className="text-[10px] text-ink-400 font-normal">({preset.label})</span>
                </button>
              ))}
            </div>
          </div>

          {/* Map Section */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-ink-800 flex items-center gap-1.5">
                  <Layers className="h-4 w-4 text-signal-600" />
                  Interactive Map Drawing Mode
                </span>
                <Badge className="bg-emerald-50 border-emerald-200 text-emerald-700 text-[10px]">
                  Click Map to Drop Pins ({points.length} Vertices)
                </Badge>
              </div>
              {points.length > 0 && (
                <button
                  type="button"
                  onClick={handleResetPoints}
                  className="text-xs text-rose-600 hover:text-rose-800 font-medium flex items-center gap-1 transition"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset Pins
                </button>
              )}
            </div>

            {/* Render Leaflet Map */}
            <SiteMap
              sites={[]}
              scores={[]}
              drawingMode={true}
              drawingPoints={points}
              onMapClick={handleMapClick}
              centerOverride={mapCenter}
              zoomOverride={mapZoom}
              heightClass="h-96"
            />
            <p className="text-[11px] text-ink-500 italic">
              💡 Tip: Click anywhere on the map to add coordinate vertices (P1, P2, P3...). Connecting 3+ points creates a closed polygon boundary.
            </p>
          </div>

          {/* Site Metadata & Geometry Calculation */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field label="Site Name">
              <input
                type="text"
                value={siteName}
                onChange={(e) => setSiteName(e.target.value)}
                placeholder="e.g. East Wenatchee West Campus"
                className={inputClass}
                required
              />
            </Field>

            <Field label="City / Region Name">
              <input
                type="text"
                value={cityName}
                onChange={(e) => setCityName(e.target.value)}
                placeholder="e.g. East Wenatchee, WA"
                className={inputClass}
              />
            </Field>

            <Field label="Calculated Plot Area">
              <div className="h-10 px-3.5 rounded-lg border border-ink-200 bg-ink-50/80 flex items-center justify-between text-xs">
                <span className="font-semibold text-ink-800">
                  {calculatedArea.hectares > 0 ? `${calculatedArea.hectares} ha` : "0 ha"}
                </span>
                <span className="text-ink-500">
                  ({calculatedArea.acres > 0 ? `${calculatedArea.acres} acres` : "0 acres"})
                </span>
              </div>
            </Field>
          </div>

          {/* Centroid & Vertex Details Card */}
          <div className="bg-ink-50/70 rounded-xl border border-ink-200 p-4 space-y-3">
            <div className="flex items-center justify-between border-b border-ink-200/80 pb-2">
              <div className="text-xs font-semibold text-ink-800 flex items-center gap-1.5">
                <Compass className="h-4 w-4 text-signal-600" />
                <span>Calculated Boundary Centroid (Mireye Telemetry Point)</span>
              </div>
              <span className="text-xs font-mono font-semibold text-signal-700">
                Lat: {centroid.lat.toFixed(6)}, Lon: {centroid.lon.toFixed(6)}
              </span>
            </div>

            {points.length > 0 ? (
              <div className="max-h-36 overflow-y-auto space-y-1.5 pr-1">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="text-[11px] text-ink-500 border-b border-ink-200">
                      <th className="pb-1 font-semibold">Vertex</th>
                      <th className="pb-1 font-semibold">Latitude</th>
                      <th className="pb-1 font-semibold">Longitude</th>
                      <th className="pb-1 font-semibold text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {points.map((pt, idx) => (
                      <tr key={`v-${idx}`} className="text-ink-700 hover:bg-white/60">
                        <td className="py-1 font-bold text-signal-700">P{idx + 1}</td>
                        <td className="py-1 font-mono text-[11px]">{pt.lat.toFixed(6)}</td>
                        <td className="py-1 font-mono text-[11px]">{pt.lon.toFixed(6)}</td>
                        <td className="py-1 text-right">
                          <button
                            type="button"
                            onClick={() => handleRemovePoint(idx)}
                            className="text-rose-600 hover:text-rose-800 text-[11px] font-medium transition"
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-ink-400 italic py-1">No vertices placed yet. Click on the map to drop pins.</p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-ink-200 bg-ink-50 flex items-center justify-between">
          <div className="text-xs text-ink-500">
            {points.length >= 3 ? (
              <span className="text-emerald-700 font-medium flex items-center gap-1">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                Valid polygon boundary defined ({points.length} vertices, {calculatedArea.hectares} ha)
              </span>
            ) : (
              <span>Add at least 3 vertices to form a closed site boundary.</span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleSubmit}
              disabled={submitting || points.length < 3}
              className="bg-signal-600 hover:bg-signal-700 text-white"
            >
              {submitting ? (
                <>
                  <span className="animate-spin text-sm mr-2">⚙️</span>
                  Fetching Mireye Telemetry...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4 mr-1.5 text-signal-200" />
                  Evaluate Site Details via Mireye
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
