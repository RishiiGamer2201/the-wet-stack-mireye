import {
  AlertTriangle,
  CheckCircle2,
  Compass,
  Layers,
  MapPin,
  RotateCcw,
  Search,
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

const CITY_COORDINATES: Record<string, { lat: number; lon: number; label: string }> = {
  "east wenatchee": { lat: 47.415, lon: -120.293, label: "Pacific Northwest Hydro" },
  "quincy": { lat: 47.234, lon: -119.852, label: "Hyperscale Hub" },
  "dallas": { lat: 32.7767, lon: -96.797, label: "ERCOT Grid Crossroads" },
  "santa clara": { lat: 37.3541, lon: -121.9552, label: "Silicon Valley Alley" },
  "ashburn": { lat: 39.043, lon: -77.487, label: "Data Center Alley" },
  "frankfurt": { lat: 50.1109, lon: 8.6821, label: "FLAP Europe Hub" },
  "london": { lat: 51.5074, lon: -0.1278, label: "Europe Core" },
  "chicago": { lat: 41.8781, lon: -87.6298, label: "Midwest Hub" },
  "atlanta": { lat: 33.749, lon: -84.388, label: "Southeast Hub" },
  "phoenix": { lat: 33.4484, lon: -112.074, label: "Southwest Hub" },
  "seattle": { lat: 47.6062, lon: -122.3321, label: "Pacific Northwest" },
  "austin": { lat: 30.2672, lon: -97.7431, label: "Texas Tech Belt" },
};

const CITY_PRESETS = [
  { name: "East Wenatchee, WA", key: "east wenatchee", label: "Pacific Northwest Hydro" },
  { name: "Quincy, WA", key: "quincy", label: "Hyperscale Hub" },
  { name: "Dallas, TX", key: "dallas", label: "ERCOT Grid Crossroads" },
  { name: "Santa Clara, CA", key: "santa clara", label: "Silicon Valley Alley" },
  { name: "Ashburn, VA", key: "ashburn", label: "Data Center Alley" },
  { name: "Frankfurt, Germany", key: "frankfurt", label: "FLAP Europe Hub" },
];

export function MapBoundaryDrawerModal({
  projectId,
  onClose,
  onSiteCreated,
}: MapBoundaryDrawerModalProps) {
  const [siteName, setSiteName] = useState("Custom Parcel Alpha");
  const [cityName, setCityName] = useState("East Wenatchee, WA");
  const [cityInput, setCityInput] = useState("East Wenatchee, WA");
  // NO pre-defined pins: user starts with clean empty map!
  const [points, setPoints] = useState<Array<{ lat: number; lon: number }>>([]);
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

  const [searchingLocation, setSearchingLocation] = useState(false);

  async function handleCitySearch(query: string) {
    const term = query.trim().toLowerCase();
    if (!term) return;

    setError(null);
    setSearchingLocation(true);

    try {
      // 1. Check local presets for instant offline match
      const matchedKey = Object.keys(CITY_COORDINATES).find(
        (k) => term.includes(k) || k.includes(term),
      );

      if (matchedKey) {
        const coord = CITY_COORDINATES[matchedKey];
        setMapCenter([coord.lat, coord.lon]);
        setMapZoom(13);
        setCityName(query.trim());
        setSearchingLocation(false);
        return;
      }

      // 2. Query OpenStreetMap Nominatim for real-time worldwide geocoding
      const response = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query.trim())}&limit=1`,
        {
          headers: {
            "Accept-Language": "en",
          },
        },
      );

      if (response.ok) {
        const results = await response.json();
        if (Array.isArray(results) && results.length > 0) {
          const lat = parseFloat(results[0].lat);
          const lon = parseFloat(results[0].lon);
          if (!Number.isNaN(lat) && !Number.isNaN(lon)) {
            setMapCenter([lat, lon]);
            setMapZoom(13);
            const displayName = results[0].display_name || query.trim();
            const shortName = displayName.split(",")[0] || query.trim();
            setCityName(shortName);
            setSearchingLocation(false);
            return;
          }
        }
      }

      // 3. Fallback warning if not found
      setError(`Could not locate "${query}". Please verify spelling or try adding state/country (e.g. "Boston, MA" or "Tokyo, Japan").`);
    } catch (err) {
      setError(`Failed to geocode location "${query}". Please check your internet connection or click directly on the map.`);
    } finally {
      setSearchingLocation(false);
    }
  }

  function handleSelectPreset(preset: typeof CITY_PRESETS[number]) {
    setCityInput(preset.name);
    handleCitySearch(preset.name);
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
                Search a city to pan the map, then click on the location to place 3-5 pins to form a site boundary
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

          {/* City Search & Map Panning Control */}
          <div className="space-y-2.5">
            <label className="block text-xs font-semibold text-ink-800">
              Search City Location (Pans Map Instantly)
            </label>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleCitySearch(cityInput);
              }}
              className="flex items-center gap-2"
            >
              <div className="relative flex-1">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-ink-400" />
                <input
                  type="text"
                  value={cityInput}
                  onChange={(e) => setCityInput(e.target.value)}
                  placeholder="Type a city name (e.g., Dallas TX, Frankfurt, Santa Clara CA, Seattle)..."
                  className={`${inputClass} pl-9`}
                />
              </div>
              <Button
                type="submit"
                variant="secondary"
                disabled={searchingLocation}
                className="border-ink-300 bg-ink-100 text-ink-800 hover:bg-ink-200 shrink-0"
              >
                {searchingLocation ? "Searching..." : "Pan Map to City"}
              </Button>
            </form>

            <div className="flex flex-wrap gap-2 pt-1">
              <span className="text-[11px] font-medium text-ink-400 self-center">Quick Presets:</span>
              {CITY_PRESETS.map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  onClick={() => handleSelectPreset(preset)}
                  className={`text-xs px-2.5 py-1 rounded-lg border font-medium transition flex items-center gap-1 ${
                    cityName.toLowerCase().includes(preset.key)
                      ? "bg-signal-50 border-signal-500 text-signal-700 shadow-sm font-semibold"
                      : "bg-white border-ink-200 text-ink-600 hover:bg-ink-50"
                  }`}
                >
                  <MapPin className="h-3 w-3 text-signal-600" />
                  <span>{preset.name}</span>
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
                  Interactive Map Canvas
                </span>
                <Badge className="bg-emerald-50 border-emerald-200 text-emerald-700 text-[10px]">
                  {points.length === 0
                    ? "Click Map to Add First Pin (P1)"
                    : points.length === 1
                      ? "Click 2nd Point for Straight Line"
                      : points.length === 2
                        ? "2 Pins Connected (Straight Line)"
                        : `${points.length} Pins Connected (Polygon)`}
                </Badge>
              </div>
              {points.length > 0 && (
                <button
                  type="button"
                  onClick={handleResetPoints}
                  className="text-xs text-rose-600 hover:text-rose-800 font-medium flex items-center gap-1 transition"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Clear All Pins
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
              onRemovePoint={handleRemovePoint}
              centerOverride={mapCenter}
              zoomOverride={mapZoom}
              heightClass="h-96"
            />
            <p className="text-[11px] text-ink-500 italic">
              💡 Instructions: Click anywhere on the map to drop pins (P1, P2...). <strong>2 pins draw a straight line.</strong> Adding 3+ pins forms a closed parcel polygon. Click any pin to delete it.
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
                            Remove Pin
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-ink-400 italic py-1">No pins placed yet. Click anywhere on the map above to drop pins.</p>
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
            ) : points.length === 2 ? (
              <span className="text-signal-700 font-medium">
                Straight line P1-P2 drawn. Add a 3rd pin to form a closed plot boundary polygon.
              </span>
            ) : points.length === 1 ? (
              <span className="text-ink-600">
                1 pin placed. Click a 2nd point on the map to draw a straight line.
              </span>
            ) : (
              <span>Click on the map above to drop your first coordinate pin (P1).</span>
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

