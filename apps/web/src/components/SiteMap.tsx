import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";

import type { CandidateSite, SiteScore } from "../lib/types";

/** Div icons avoid Leaflet's bundled image assets, so markers render offline. */
function pin(rank: number | null, risk: string | undefined, selected: boolean) {
  const color =
    risk === "low"
      ? "#059669"
      : risk === "moderate"
        ? "#0284c7"
        : risk === "elevated"
          ? "#d97706"
          : risk === "high"
            ? "#e11d48"
            : "#475569";
  return L.divIcon({
    className: "",
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    html: `<div style="width:28px;height:28px;border-radius:9999px;background:${color};
      border:${selected ? "3px solid #151b26" : "2px solid white"};color:white;display:flex;
      align-items:center;justify-content:center;font:600 12px system-ui;
      box-shadow:0 1px 4px rgba(0,0,0,.35)">${rank ?? "?"}</div>`,
  });
}

function vertexPin(index: number) {
  return L.divIcon({
    className: "",
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    html: `<div style="width:24px;height:24px;border-radius:9999px;background:#0b7565;
      border:2px solid white;color:white;display:flex;align-items:center;justify-content:center;
      font:700 11px system-ui;box-shadow:0 2px 6px rgba(0,0,0,0.4)">P${index + 1}</div>`,
  });
}

/** Component that catches map click events in drawing mode. */
function MapClickHandler({ onClick }: { onClick?: (coords: { lat: number; lon: number }) => void }) {
  useMapEvents({
    click(e) {
      if (onClick) {
        onClick({ lat: e.latlng.lat, lon: e.latlng.lng });
      }
    },
  });
  return null;
}

/** Handles invalidating map size when container dimensions change or modal opens. */
function MapResizer() {
  const map = useMap();
  useEffect(() => {
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 150);
    return () => clearTimeout(timer);
  }, [map]);
  return null;
}

/** Only re-fits when the positioned site IDs/coords actually change. */
function FitBounds({ sites }: { sites: CandidateSite[] }) {
  const map = useMap();
  const prevKey = useRef<string>("");

  const key = useMemo(
    () =>
      sites
        .filter((s) => s.latitude != null && s.longitude != null)
        .map((s) => `${s.id}:${s.latitude},${s.longitude}`)
        .join("|"),
    [sites],
  );

  useEffect(() => {
    if (key === prevKey.current) return;
    prevKey.current = key;
    const points = sites
      .filter((s) => s.latitude != null && s.longitude != null)
      .map((s) => [s.latitude as number, s.longitude as number] as [number, number]);
    if (points.length === 1) map.setView(points[0], 9);
    else if (points.length > 1) map.fitBounds(L.latLngBounds(points).pad(0.25));
  }, [map, sites, key]);
  return null;
}

export function SiteMap({
  sites,
  scores,
  selectedId,
  onSelect,
  drawingMode = false,
  drawingPoints = [],
  onMapClick,
  centerOverride,
  zoomOverride,
  heightClass = "h-80",
}: {
  sites: CandidateSite[];
  scores: SiteScore[];
  selectedId?: string | null;
  onSelect?: (siteId: string) => void;
  drawingMode?: boolean;
  drawingPoints?: Array<{ lat: number; lon: number }>;
  onMapClick?: (coords: { lat: number; lon: number }) => void;
  centerOverride?: [number, number];
  zoomOverride?: number;
  heightClass?: string;
}) {
  const located = sites.filter((s) => s.latitude != null && s.longitude != null);
  const scoreOf = (id: string) => scores.find((s) => s.site_id === id);

  const polygonCoords: [number, number][] = useMemo(
    () => drawingPoints.map((p) => [p.lat, p.lon]),
    [drawingPoints],
  );

  if (located.length === 0 && drawingPoints.length === 0 && !centerOverride && !drawingMode) {
    return (
      <div className={`flex ${heightClass} items-center justify-center rounded-lg border border-dashed border-ink-300 bg-ink-50 text-sm text-ink-500`}>
        No candidate site has coordinates yet.
      </div>
    );
  }

  const initialCenter: [number, number] = centerOverride
    ? centerOverride
    : located.length > 0 && located[0].latitude != null && located[0].longitude != null
      ? [located[0].latitude as number, located[0].longitude as number]
      : [39.5, -98.35];

  return (
    <div className={`leaflet-map-wrapper ${heightClass} overflow-hidden rounded-lg border border-ink-200 relative`}>
      <MapContainer
        center={initialCenter}
        zoom={zoomOverride ?? (located.length === 1 ? 10 : 4)}
        scrollWheelZoom={true}
        style={{ height: "100%", width: "100%", cursor: drawingMode ? "crosshair" : "grab" }}
        aria-label="Candidate site map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapResizer />
        {drawingMode && <MapClickHandler onClick={onMapClick} />}
        {!drawingMode && located.length > 0 && <FitBounds sites={located} />}

        {/* Vertex markers when drawing boundary */}
        {drawingPoints.map((pt, idx) => (
          <Marker key={`draw-pt-${idx}`} position={[pt.lat, pt.lon]} icon={vertexPin(idx)}>
            <Popup>
              <strong>Vertex P{idx + 1}</strong>
              <br />
              Lat: {pt.lat.toFixed(5)}, Lon: {pt.lon.toFixed(5)}
            </Popup>
          </Marker>
        ))}

        {/* Boundary Polygon or Polyline */}
        {polygonCoords.length >= 3 ? (
          <Polygon
            positions={polygonCoords}
            pathOptions={{ color: "#0b7565", weight: 3, fillColor: "#0f8f7a", fillOpacity: 0.35 }}
          />
        ) : polygonCoords.length === 2 ? (
          <Polyline
            positions={polygonCoords}
            pathOptions={{ color: "#0b7565", weight: 3, dashArray: "6,6" }}
          />
        ) : null}

        {/* Existing site markers */}
        {!drawingMode &&
          located.map((site) => {
            const score = scoreOf(site.id);
            return (
              <Marker
                key={site.id}
                position={[site.latitude as number, site.longitude as number]}
                icon={pin(score?.rank ?? null, score?.risk_level, selectedId === site.id)}
                eventHandlers={{ click: () => onSelect?.(site.id) }}
              >
                <Popup>
                  <strong>{site.name}</strong>
                  <br />
                  {site.address ?? "-"}
                  <br />
                  {score
                    ? `Score ${score.overall_score ?? "-"} · ${score.risk_level} risk · ${(
                        score.evidence_coverage * 100
                      ).toFixed(0)}% coverage`
                    : "Not yet investigated"}
                </Popup>
              </Marker>
            );
          })}
      </MapContainer>
    </div>
  );
}

