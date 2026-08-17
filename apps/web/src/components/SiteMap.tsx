import L from "leaflet";
import { useEffect } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";

import type { CandidateSite, SiteScore } from "../lib/types";

/** Div icons avoid Leaflet's bundled image assets entirely, so the map still
 *  renders markers when tile servers are unreachable (offline demo). */
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

function FitBounds({ sites }: { sites: CandidateSite[] }) {
  const map = useMap();
  useEffect(() => {
    const points = sites
      .filter((s) => s.latitude != null && s.longitude != null)
      .map((s) => [s.latitude as number, s.longitude as number] as [number, number]);
    if (points.length === 1) map.setView(points[0], 9);
    else if (points.length > 1) map.fitBounds(L.latLngBounds(points).pad(0.25));
  }, [map, sites]);
  return null;
}

export function SiteMap({
  sites,
  scores,
  selectedId,
  onSelect,
}: {
  sites: CandidateSite[];
  scores: SiteScore[];
  selectedId?: string | null;
  onSelect?: (siteId: string) => void;
}) {
  const located = sites.filter((s) => s.latitude != null && s.longitude != null);
  const scoreOf = (id: string) => scores.find((s) => s.site_id === id);

  if (located.length === 0) {
    return (
      <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-ink-300 bg-ink-50 text-sm text-ink-500">
        No candidate site has coordinates yet.
      </div>
    );
  }

  return (
    <div className="h-80 overflow-hidden rounded-lg border border-ink-200">
      <MapContainer
        center={[39.5, -98.35]}
        zoom={4}
        scrollWheelZoom={false}
        style={{ height: "100%", width: "100%" }}
        aria-label="Candidate site map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds sites={located} />
        {located.map((site) => {
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
                {site.address ?? "—"}
                <br />
                {score
                  ? `Score ${score.overall_score ?? "—"} · ${score.risk_level} risk · ${(
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
