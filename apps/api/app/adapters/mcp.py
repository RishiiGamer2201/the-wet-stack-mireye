"""Model Context Protocol (MCP) Server and Tool Adapter.

Implements standard MCP tool definitions and JSON-RPC 2.0 tool execution protocol
for Mireye location intelligence, ChromaDB + BM25 document retrieval, web standards search,
and EPC project context inspection.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..adapters.mireye import get_mireye_client
from ..adapters.vectorstore import get_index
from ..domain import (
    CandidateSite,
    Evidence,
    InformationGap,
    Project,
    Requirement,
)
from ..fields import FIELD_INDEX
from ..store import C, get_store

log = logging.getLogger("mcp")


MCP_TOOLS_SPEC = [
    {
        "name": "mireye_geocode",
        "description": "Geocodes a physical parcel or candidate site address into verified latitude/longitude coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Full street address, parcel ID, or city/state/region"},
            },
            "required": ["address"],
        },
    },
    {
        "name": "mireye_fetch_telemetry",
        "description": "Fetches physical, environmental, and geological telemetry from Mireye for given coordinates (elevation, slope, flood zone BFE, seismic PGA, water risk, grid distance).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Site latitude (-90 to 90)"},
                "longitude": {"type": "number", "description": "Site longitude (-180 to 180)"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of specific Mireye telemetry field names to request (e.g. elevation, design_wind_speed_mph, seismic_pga_100yr, flood_zone).",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "mireye_environmental_ask",
        "description": "Exploratory geospatial question answering at specific coordinates (e.g. historical flooding, utility constraints, climate risks).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Engineering question regarding the physical location"},
                "latitude": {"type": "number", "description": "Site latitude"},
                "longitude": {"type": "number", "description": "Site longitude"},
            },
            "required": ["question", "latitude", "longitude"],
        },
    },
    {
        "name": "document_semantic_search",
        "description": "Searches ingested project documents (PDF submittals, specifications, engineering reports, drawings) using hybrid ChromaDB vector + BM25 lexical search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Active project ID"},
                "query": {"type": "string", "description": "Engineering query or specification term to search"},
                "k": {"type": "integer", "default": 5, "description": "Number of relevant chunks to return"},
            },
            "required": ["project_id", "query"],
        },
    },
    {
        "name": "web_search_standards",
        "description": "Performs live web search for technical engineering standards (ASHRAE, ASCE 7-22, IEEE, NFPA, IBC, Uptime Institute) and equipment cut sheets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Technical search query for standards, codes, or datasheets"},
                "domain_filter": {"type": "string", "description": "Optional focus (e.g. 'ashrae', 'asce', 'ieee', 'fema')"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "project_inspect_context",
        "description": "Inspects project data: candidate sites, stored physical evidence, open information gaps, and extracted equipment requirements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Active project ID"},
                "section": {
                    "type": "string",
                    "enum": ["all", "sites", "evidence", "gaps", "requirements"],
                    "default": "all",
                    "description": "Section of project state to inspect",
                },
                "site_id": {"type": "string", "description": "Optional specific candidate site ID"},
            },
            "required": ["project_id"],
        },
    },
]


class MCPToolRegistry:
    """Registry and executor for Model Context Protocol tools."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = {}
        self._register_defaults()

    def register(self, name: str, handler: Callable[..., dict[str, Any]]) -> None:
        self._handlers[name] = handler

    def list_tools(self) -> list[dict[str, Any]]:
        return MCP_TOOLS_SPEC

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(name)
        if not handler:
            return {"isError": True, "content": [{"type": "text", "text": f"Tool '{name}' not found."}]}
        try:
            res = handler(**arguments)
            return {"isError": False, "content": [{"type": "text", "text": str(res.get("text", "") or res)}, {"type": "json", "data": res}]}
        except Exception as exc:
            log.warning(f"MCP tool '{name}' execution failed", extra={"error": str(exc)})
            return {"isError": True, "content": [{"type": "text", "text": f"Tool execution failed: {exc}"}]}

    def _register_defaults(self) -> None:
        self.register("mireye_geocode", self._handle_geocode)
        self.register("mireye_fetch_telemetry", self._handle_fetch_telemetry)
        self.register("mireye_environmental_ask", self._handle_environmental_ask)
        self.register("document_semantic_search", self._handle_doc_search)
        self.register("web_search_standards", self._handle_web_search)
        self.register("project_inspect_context", self._handle_project_inspect)

    def _handle_geocode(self, address: str) -> dict[str, Any]:
        client = get_mireye_client()
        geo = client.geocode(address)
        return {
            "address": address,
            "normalized_address": getattr(geo, "formatted_address", getattr(geo, "normalized_address", address)),
            "latitude": geo.latitude,
            "longitude": geo.longitude,
            "accuracy": getattr(geo, "confidence", getattr(geo, "accuracy", 0.9)),
            "provider": getattr(geo, "resolution", "mireye"),
            "mode": getattr(client, "mode", "mock"),
        }

    def _handle_fetch_telemetry(
        self, latitude: float, longitude: float, fields: list[str] | None = None
    ) -> dict[str, Any]:
        client = get_mireye_client()
        # One credit per field, except anything in Mireye's parcel_record group,
        # which is 300 per location. `wetland_fraction` sat in this default list,
        # so a deployment with MIREYE_INCLUDE_PARCEL_FIELDS=true paid 307 credits
        # for every telemetry call instead of 7 - on the default path, not when
        # anyone asked about a parcel. A default must never carry a billed field;
        # a caller can still request one explicitly.
        default_fields = [
            "elevation_m",
            "mean_slope_pct",
            "seismic_pga_g",
            "flood_zone",
            "distance_to_substation_km",
            "water_stress_index",
            "ambient_design_db_c",
            "design_wind_speed_mph",
            "soil_bearing_capacity_kpa",
            "grid_capacity_mw",
        ]
        target_fields = fields or default_fields
        valid_fields = [f for f in target_fields if f in FIELD_INDEX] or default_fields
        res = client.fetch(latitude, longitude, valid_fields)
        values_dict = getattr(res, "values", getattr(res, "fields", {}))
        return {
            "latitude": latitude,
            "longitude": longitude,
            "fetched_count": len(values_dict),
            "mode": getattr(client, "mode", getattr(res, "mode", "mock")),
            "fields": {
                k: {
                    "value": getattr(f, "value", f),
                    "unit": getattr(f, "unit", None),
                    "source": getattr(f, "source", "Mireye"),
                    "confidence": getattr(f, "confidence", 1.0),
                }
                for k, f in values_dict.items()
            },
        }

    def _handle_environmental_ask(
        self, question: str, latitude: float, longitude: float
    ) -> dict[str, Any]:
        client = get_mireye_client()
        res = client.ask(question, latitude, longitude)
        return {
            "question": question,
            "latitude": latitude,
            "longitude": longitude,
            "answer": res.answer,
            "confidence": res.confidence,
            "mode": res.mode,
            "citations": list(res.citations),
        }

    def _handle_doc_search(
        self, project_id: str, query: str, k: int = 5
    ) -> dict[str, Any]:
        index = get_index()
        hits = index.search(project_id, query, k=k)
        return {
            "project_id": project_id,
            "query": query,
            "backend": getattr(index, "backend", "hybrid"),
            "hit_count": len(hits),
            "chunks": [
                {
                    "chunk_id": h.chunk_id,
                    "document_id": h.document_id,
                    "document_name": h.document_name,
                    "page": h.page,
                    "text": h.text,
                    "score": h.score,
                    "ocr": h.ocr,
                }
                for h in hits
            ],
        }

    def _handle_web_search(
        self, query: str, domain_filter: str | None = None
    ) -> dict[str, Any]:
        from .websearch import get_web_search_engine
        engine = get_web_search_engine()
        results = engine.search(query, domain_filter=domain_filter, max_results=5)
        return {
            "query": query,
            "count": len(results),
            "results": results,
        }

    def _handle_project_inspect(
        self, project_id: str, section: str = "all", site_id: str | None = None
    ) -> dict[str, Any]:
        store = get_store()
        project = store.get(C.PROJECTS, project_id, Project)
        if not project:
            return {"error": f"Project {project_id} not found"}

        data: dict[str, Any] = {"project": {"id": project.id, "name": project.name, "region": project.region}}

        if section in ("all", "sites"):
            sites = store.list(C.SITES, CandidateSite, project_id=project_id)
            if site_id:
                sites = [s for s in sites if s.id == site_id]
            data["sites"] = [
                {
                    "id": s.id,
                    "name": s.name,
                    "lat": s.latitude,
                    "lon": s.longitude,
                    "area_ha": s.area_hectares,
                    "address": s.address,
                }
                for s in sites
            ]

        if section in ("all", "evidence"):
            evidence = store.list(C.EVIDENCE, Evidence, project_id=project_id)
            if site_id:
                evidence = [e for e in evidence if e.subject_id == site_id]
            data["evidence"] = [
                {"field": e.field_key, "value": e.value, "unit": e.unit, "subject": e.subject_id}
                for e in evidence[:25]
            ]

        if section in ("all", "gaps"):
            gaps = store.list(C.GAPS, InformationGap, project_id=project_id)
            data["open_gaps"] = [
                {"description": g.description, "field": g.field_key, "blocking": g.blocking}
                for g in gaps if g.status != "resolved"
            ]

        if section in ("all", "requirements"):
            reqs = store.list(C.REQUIREMENTS, Requirement, project_id=project_id)
            data["requirements"] = [
                {"tag": r.equipment_tag, "kind": r.kind.value if hasattr(r.kind, "value") else str(r.kind), "field": r.field_key, "val": r.value, "unit": r.unit}
                for r in reqs[:25]
            ]

        return data


_mcp_registry: MCPToolRegistry | None = None


def get_mcp_registry() -> MCPToolRegistry:
    global _mcp_registry
    if _mcp_registry is None:
        _mcp_registry = MCPToolRegistry()
    return _mcp_registry
