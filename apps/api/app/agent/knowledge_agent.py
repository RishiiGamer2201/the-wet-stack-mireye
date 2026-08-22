"""Autonomous Project Knowledge Research Agent.

Orchestrates multi-tool reasoning over:
1. Ingested Project Documents (ChromaDB Vector + BM25 Lexical RAG with page citations)
2. Live Web Search for Technical Engineering Standards (ASHRAE, ASCE, IEEE, FEMA, NFPA)
3. Mireye Location Intelligence & MCP Tools (Physical telemetry: elevation, seismic, flood, water, grid)
4. Project Data Inspector (Candidate sites, evidence records, gaps, requirements)

Produces deep engineering synthesis along with a structured "Tell Me / Deep Insights"
section and fine-grained citations.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from ..adapters.llm import get_llm
from ..adapters.mcp import get_mcp_registry
from ..adapters.mireye import get_mireye_client
from ..adapters.vectorstore import get_index
from ..adapters.websearch import get_web_search_engine
from ..domain import (
    CandidateSite,
    DocumentChunk,
    Evidence,
    InformationGap,
    Project,
    Requirement,
)
from ..store import C, Store, get_store

log = logging.getLogger("knowledge_agent")


@dataclass
class ToolExecutionTrace:
    tool: str
    title: str
    input_params: dict[str, Any]
    output_summary: str
    details: Any = None
    duration_ms: int = 0
    ok: bool = True


@dataclass
class Citation:
    source_type: str  # "document" | "web" | "mireye" | "project"
    title: str
    detail: str
    url: str | None = None
    page: int | None = None
    chunk_id: str | None = None
    coordinates: str | None = None


@dataclass
class TellMeInsights:
    key_findings: list[str] = field(default_factory=list)
    risks_identified: list[str] = field(default_factory=list)
    standards_compliance: list[str] = field(default_factory=list)
    actionable_mitigations: list[str] = field(default_factory=list)


@dataclass
class KnowledgeAgentResult:
    answer: str
    tell_me: TellMeInsights
    citations: list[Citation]
    tool_traces: list[ToolExecutionTrace]
    site_name: str | None = None
    mode: str = "llm"
    disclaimer: str = (
        "Advisory EPC opinion synthesized from project documentation, live Mireye physical telemetry, "
        "and published engineering standards. Structural/civil calculations require licensed PE stamp."
    )


KNOWLEDGE_AGENT_SYSTEM_PROMPT = """You are the Lead Principal EPC Infrastructure and Mission-Critical Data Center Engineer.
You possess authoritative mastery in:
- Civil & geotechnical site design (bearing capacity, soil liquefaction, cut/fill earthwork, retaining walls).
- Seismic engineering (ASCE 7-22 Risk Category IV, PGA, anchor snubbers, flexible utility seismic loops).
- Hydrology & stormwater (FEMA 500-yr BFE + 3.0ft FFE, retention basins, redundant gravity outfalls).
- Power & High Voltage Interconnection (115kV/230kV ring-bus substations, N-1 transformer sizing, blast walls).
- Cooling architectures (closed-loop air-cooled, adiabatic pre-cooling, ASHRAE TC 9.9 thermal envelopes, water stress).
- Equipment specs & submittals review against project requirements.

TASK:
Synthesize all provided evidence from:
1. Ingested Project Documents (quote exact pages).
2. Live Web Search & Engineering Standards (ASHRAE, ASCE, IEEE, NFPA, FEMA).
3. Mireye Physical Telemetry & MCP (elevation, seismic PGA, flood zone, water index, grid distance).
4. Project candidate sites and stored telemetry.

OUTPUT FORMAT INSTRUCTIONS:
Provide a rigorous, highly structured engineering assessment:
1. **Executive Summary & Direct Answer**
2. **Technical Analysis & Specification Verification** (include formulas, parameters, comparisons where applicable)
3. **Mireye Physical Telemetry & Site Conditions**
4. **Relevant Codes & Industry Standards Compliance**
5. **Identified Risks & Engineering Mitigations**

At the very end of your response, output a strict JSON block delimited by ```json_tell_me ... ``` containing:
```json_tell_me
{
  "key_findings": ["1-3 sentence core takeaway 1", "takeaway 2", ...],
  "risks_identified": ["specific risk 1", "specific risk 2", ...],
  "standards_compliance": ["ASHRAE TC 9.9: ...", "ASCE 7-22: ...", ...],
  "actionable_mitigations": ["engineering action 1", "engineering action 2", ...]
}
```
"""


class KnowledgeAgent:
    """Agent that runs autonomous multi-tool research and synthesis."""

    def __init__(self, store: Store | None = None) -> None:
        self.store = store or get_store()
        self.mcp = get_mcp_registry()
        self.web = get_web_search_engine()
        self.llm = get_llm()

    def run(
        self,
        project_id: str,
        message: str,
        site_id: str | None = None,
        enabled_tools: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> KnowledgeAgentResult:
        traces: list[ToolExecutionTrace] = []
        citations: list[Citation] = []
        context_blocks: list[str] = []

        project = self.store.get(C.PROJECTS, project_id, Project)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        tools_to_run = set(enabled_tools or ["documents", "web", "mireye", "project"])

        # Resolve active site
        active_site: CandidateSite | None = None
        if site_id:
            active_site = self.store.get(C.SITES, site_id, CandidateSite)
        if not active_site:
            sites = self.store.list(C.SITES, CandidateSite, project_id=project_id)
            for s in sites:
                if s.latitude is not None and s.longitude is not None:
                    active_site = s
                    break
            if not active_site and sites:
                active_site = sites[0]

        site_name = active_site.name if active_site else project.name
        lat = active_site.latitude if active_site else None
        lon = active_site.longitude if active_site else None

        # Base Project Context
        context_blocks.append(f"PROJECT: {project.name} (Region: {project.region or 'N/A'}, Client: {project.client or 'N/A'})")
        if project.targets and project.targets.it_load_mw:
            context_blocks.append(f"Target IT Load: {project.targets.it_load_mw} MW")
        if active_site:
            context_blocks.append(
                f"ACTIVE CANDIDATE SITE: {active_site.name} | Lat: {lat}, Lon: {lon} | Area: {active_site.area_hectares or 'N/A'} ha | Address: {active_site.address or 'N/A'}"
            )

        # 1. TOOL: Ingested Project Document Search (ChromaDB + BM25)
        if "documents" in tools_to_run:
            t_start = time.perf_counter()
            doc_res = self.mcp.execute(
                "document_semantic_search",
                {"project_id": project_id, "query": message, "k": 5},
            )
            dur = int((time.perf_counter() - t_start) * 1000)
            doc_data = doc_res["content"][1]["data"]
            chunks = doc_data.get("chunks", [])

            if chunks:
                doc_lines = []
                for c in chunks:
                    ocr_tag = " [OCR Transcription - Unverified]" if c.get("ocr") else ""
                    doc_lines.append(f"[{c['document_name']} p.{c['page']}{ocr_tag} score:{c['score']}]\n{c['text']}")
                    citations.append(
                        Citation(
                            source_type="document",
                            title=c["document_name"],
                            detail=f"Page {c['page']}{' (OCR)' if c.get('ocr') else ''}",
                            page=c["page"],
                            chunk_id=c["chunk_id"],
                        )
                    )
                context_blocks.append(f"=== INGESTED PROJECT DOCUMENTS (ChromaDB + BM25) ===\n" + "\n\n".join(doc_lines))
                traces.append(
                    ToolExecutionTrace(
                        tool="document_semantic_search",
                        title="Search Ingested Documents (ChromaDB + BM25)",
                        input_params={"query": message, "k": 5},
                        output_summary=f"Retrieved {len(chunks)} relevant chunk(s) across project specifications.",
                        details=chunks,
                        duration_ms=dur,
                    )
                )
            else:
                traces.append(
                    ToolExecutionTrace(
                        tool="document_semantic_search",
                        title="Search Ingested Documents (ChromaDB + BM25)",
                        input_params={"query": message, "k": 5},
                        output_summary="No document chunks matched the query.",
                        duration_ms=dur,
                    )
                )

        # 2. TOOL: Live Web Search & Technical Standards
        if "web" in tools_to_run:
            t_start = time.perf_counter()
            web_res = self.mcp.execute("web_search_standards", {"query": message})
            dur = int((time.perf_counter() - t_start) * 1000)
            web_data = web_res["content"][1]["data"]
            web_hits = web_data.get("results", [])

            if web_hits:
                web_lines = []
                for h in web_hits:
                    web_lines.append(f"[{h['title']} - {h['source']}]\nURL: {h['url']}\nSnippet: {h['snippet']}")
                    citations.append(
                        Citation(
                            source_type="web",
                            title=h["title"],
                            detail=h["source"],
                            url=h["url"],
                        )
                    )
                context_blocks.append(f"=== WEB & TECHNICAL ENGINEERING STANDARDS ===\n" + "\n\n".join(web_lines))
                traces.append(
                    ToolExecutionTrace(
                        tool="web_search_standards",
                        title="Search Web & Engineering Standards",
                        input_params={"query": message},
                        output_summary=f"Found {len(web_hits)} technical standard reference(s) & web results.",
                        details=web_hits,
                        duration_ms=dur,
                    )
                )

        # 3. TOOL: Mireye Location Intelligence & Physical Telemetry (via MCP)
        if "mireye" in tools_to_run and lat is not None and lon is not None:
            t_start = time.perf_counter()
            mcp_res = self.mcp.execute(
                "mireye_fetch_telemetry",
                {"latitude": lat, "longitude": lon},
            )
            dur = int((time.perf_counter() - t_start) * 1000)
            mireye_data = mcp_res["content"][1]["data"]
            fields = mireye_data.get("fields", {})

            if fields:
                field_summary = ", ".join(
                    f"{k}: {v['value']} {v['unit'] or ''} (source: {v['source'] or 'Mireye'})"
                    for k, v in fields.items()
                    if v.get("value") is not None
                )
                context_blocks.append(f"=== MIREYE PHYSICAL TELEMETRY · MCP ({site_name}: {lat:.4f}, {lon:.4f}) ===\n{field_summary}")
                citations.append(
                    Citation(
                        source_type="mireye",
                        title=f"Mireye Earth Telemetry · {site_name}",
                        detail=f"{len(fields)} physical observations",
                        coordinates=f"{lat:.4f}, {lon:.4f}",
                    )
                )
                traces.append(
                    ToolExecutionTrace(
                        tool="mireye_fetch_telemetry",
                        title="Query Mireye Physical Telemetry via MCP",
                        input_params={"latitude": lat, "longitude": lon},
                        output_summary=f"Fetched {len(fields)} physical observations (elevation, seismic PGA, flood zone, water index).",
                        details=fields,
                        duration_ms=dur,
                    )
                )

            # Also query exploratory Mireye ask if question asks about site physical aspects
            if any(kw in message.lower() for kw in ["site", "location", "flood", "seismic", "water", "weather", "grid", "soil"]):
                ask_res = self.mcp.execute(
                    "mireye_environmental_ask",
                    {"question": message, "latitude": lat, "longitude": lon},
                )
                ask_data = ask_res["content"][1]["data"]
                if ask_data.get("answer"):
                    context_blocks.append(f"=== MIREYE PHYSICAL ASK ENGINE ===\n{ask_data['answer']}")
                    traces.append(
                        ToolExecutionTrace(
                            tool="mireye_environmental_ask",
                            title="Mireye Physical Geospatial Ask",
                            input_params={"question": message, "lat": lat, "lon": lon},
                            output_summary="Answered physical location inquiry.",
                            details=ask_data,
                            duration_ms=30,
                        )
                    )

        # 4. TOOL: Project Context Inspection
        if "project" in tools_to_run:
            t_start = time.perf_counter()
            proj_res = self.mcp.execute(
                "project_inspect_context",
                {"project_id": project_id, "section": "all", "site_id": site_id},
            )
            dur = int((time.perf_counter() - t_start) * 1000)
            p_data = proj_res["content"][1]["data"]
            gaps = p_data.get("open_gaps", [])
            reqs = p_data.get("requirements", [])

            p_summary_lines = []
            if gaps:
                p_summary_lines.append(f"Open Information Gaps: {len(gaps)} items (" + "; ".join(g["description"] for g in gaps[:3]) + ")")
            if reqs:
                p_summary_lines.append(f"Extracted Requirements: {len(reqs)} items (" + ", ".join(f"{r['tag']}: {r['field']}={r['val']} {r['unit'] or ''}" for r in reqs[:4]) + ")")

            if p_summary_lines:
                context_blocks.append(f"=== PROJECT DATA & GAPS ===\n" + "\n".join(p_summary_lines))
                traces.append(
                    ToolExecutionTrace(
                        tool="project_inspect_context",
                        title="Inspect Project Context & Requirements",
                        input_params={"project_id": project_id, "site_id": site_id},
                        output_summary=f"Inspected {len(gaps)} open gap(s) and {len(reqs)} extracted requirement(s).",
                        duration_ms=dur,
                    )
                )

        # Build Full Context & User Prompt
        full_context = "\n\n".join(context_blocks)
        history_text = ""
        if history:
            h_lines = []
            for item in history[-4:]:
                role = "User" if item.get("role") == "user" else "Principal Engineer"
                h_lines.append(f"{role}: {item.get('content', '')}")
            history_text = "\n\nRECENT CONVERSATION:\n" + "\n".join(h_lines)

        user_prompt = f"""CONTEXT:
{full_context}
{history_text}

USER INQUIRY:
{message}

Please provide your rigorous Principal EPC Engineering assessment and conclude with the ```json_tell_me ... ``` block as instructed."""

        # Generate response using LLM or deterministic synthesis
        llm = get_llm()
        reply_raw = None
        mode = "deterministic"
        if llm and llm.available:
            try:
                reply_raw = llm.complete(
                    system=KNOWLEDGE_AGENT_SYSTEM_PROMPT,
                    user=user_prompt,
                    max_tokens=2000,
                )
                if reply_raw:
                    mode = getattr(llm, "name", "llm")
            except Exception as exc:
                log.warning("LLM completion failed for knowledge agent, falling back", extra={"error": str(exc)})

        if not reply_raw:
            reply_raw, tell_me_fallback = self._deterministic_synthesis(
                message, site_name, traces, citations
            )
            return KnowledgeAgentResult(
                answer=reply_raw,
                tell_me=tell_me_fallback,
                citations=citations,
                tool_traces=traces,
                site_name=site_name,
                mode="deterministic",
            )

        # Parse out ```json_tell_me``` if present
        clean_answer, tell_me = self._extract_tell_me(reply_raw, message, site_name)

        return KnowledgeAgentResult(
            answer=clean_answer,
            tell_me=tell_me,
            citations=citations,
            tool_traces=traces,
            site_name=site_name,
            mode=mode,
        )

    def stream(
        self,
        project_id: str,
        message: str,
        site_id: str | None = None,
        enabled_tools: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        """Yields Server-Sent Events (SSE) for real-time tool execution traces, tokens, and Tell Me insights."""
        traces: list[ToolExecutionTrace] = []
        citations: list[Citation] = []
        context_blocks: list[str] = []

        project = self.store.get(C.PROJECTS, project_id, Project)
        if not project:
            yield f"data: {json.dumps({'error': f'Project {project_id} not found'})}\n\n"
            return

        tools_to_run = set(enabled_tools or ["documents", "web", "mireye", "project"])

        active_site: CandidateSite | None = None
        if site_id:
            active_site = self.store.get(C.SITES, site_id, CandidateSite)
        if not active_site:
            sites = self.store.list(C.SITES, CandidateSite, project_id=project_id)
            for s in sites:
                if s.latitude is not None and s.longitude is not None:
                    active_site = s
                    break
            if not active_site and sites:
                active_site = sites[0]

        site_name = active_site.name if active_site else project.name
        lat = active_site.latitude if active_site else None
        lon = active_site.longitude if active_site else None

        context_blocks.append(f"PROJECT: {project.name} (Region: {project.region or 'N/A'}, Client: {project.client or 'N/A'})")
        if active_site:
            context_blocks.append(f"ACTIVE CANDIDATE SITE: {active_site.name} | Lat: {lat}, Lon: {lon}")

        # 1. TOOL: Ingested Documents Search
        if "documents" in tools_to_run:
            yield f"data: {json.dumps({'event': 'tool_start', 'tool': 'document_semantic_search', 'title': 'Searching Ingested Documents (ChromaDB + BM25)...', 'input': {'query': message}})}\n\n"
            t_start = time.perf_counter()
            doc_res = self.mcp.execute("document_semantic_search", {"project_id": project_id, "query": message, "k": 5})
            dur = int((time.perf_counter() - t_start) * 1000)
            doc_data = doc_res["content"][1]["data"]
            chunks = doc_data.get("chunks", [])

            if chunks:
                doc_lines = []
                for c in chunks:
                    ocr_tag = " [OCR Transcription - Unverified]" if c.get("ocr") else ""
                    doc_lines.append(f"[{c['document_name']} p.{c['page']}{ocr_tag} score:{c['score']}]\n{c['text']}")
                    citations.append(
                        Citation(
                            source_type="document",
                            title=c["document_name"],
                            detail=f"Page {c['page']}{' (OCR)' if c.get('ocr') else ''}",
                            page=c["page"],
                            chunk_id=c["chunk_id"],
                        )
                    )
                context_blocks.append(f"=== INGESTED PROJECT DOCUMENTS (ChromaDB + BM25) ===\n" + "\n\n".join(doc_lines))
                summary = f"Retrieved {len(chunks)} relevant specification chunk(s)."
            else:
                summary = "No project document chunks matched."

            trace = ToolExecutionTrace(
                tool="document_semantic_search",
                title="Search Ingested Documents (ChromaDB + BM25)",
                input_params={"query": message},
                output_summary=summary,
                duration_ms=dur,
            )
            traces.append(trace)
            yield f"data: {json.dumps({'event': 'tool_finish', 'tool': 'document_semantic_search', 'output_summary': summary, 'duration_ms': dur})}\n\n"

        # 2. TOOL: Web Search & Standards
        if "web" in tools_to_run:
            yield f"data: {json.dumps({'event': 'tool_start', 'tool': 'web_search_standards', 'title': 'Searching Technical Standards (ASHRAE, ASCE, IEEE)...', 'input': {'query': message}})}\n\n"
            t_start = time.perf_counter()
            web_res = self.mcp.execute("web_search_standards", {"query": message})
            dur = int((time.perf_counter() - t_start) * 1000)
            web_data = web_res["content"][1]["data"]
            web_hits = web_data.get("results", [])

            if web_hits:
                web_lines = []
                for h in web_hits:
                    web_lines.append(f"[{h['title']} - {h['source']}]\nURL: {h['url']}\nSnippet: {h['snippet']}")
                    citations.append(
                        Citation(
                            source_type="web",
                            title=h["title"],
                            detail=h["source"],
                            url=h["url"],
                        )
                    )
                context_blocks.append(f"=== WEB & TECHNICAL ENGINEERING STANDARDS ===\n" + "\n\n".join(web_lines))
                summary = f"Found {len(web_hits)} technical standard(s) & web reference(s)."
            else:
                summary = "Web search complete."

            trace = ToolExecutionTrace(
                tool="web_search_standards",
                title="Search Web & Engineering Standards",
                input_params={"query": message},
                output_summary=summary,
                duration_ms=dur,
            )
            traces.append(trace)
            yield f"data: {json.dumps({'event': 'tool_finish', 'tool': 'web_search_standards', 'output_summary': summary, 'duration_ms': dur})}\n\n"

        # 3. TOOL: Mireye MCP Telemetry
        if "mireye" in tools_to_run and lat is not None and lon is not None:
            yield f"data: {json.dumps({'event': 'tool_start', 'tool': 'mireye_fetch_telemetry', 'title': f'Querying Mireye MCP for {site_name} telemetry...', 'input': {'lat': lat, 'lon': lon}})}\n\n"
            t_start = time.perf_counter()
            mcp_res = self.mcp.execute("mireye_fetch_telemetry", {"latitude": lat, "longitude": lon})
            dur = int((time.perf_counter() - t_start) * 1000)
            mireye_data = mcp_res["content"][1]["data"]
            fields = mireye_data.get("fields", {})

            if fields:
                field_summary = ", ".join(
                    f"{k}: {v['value']} {v['unit'] or ''}" for k, v in fields.items() if v.get("value") is not None
                )
                context_blocks.append(f"=== MIREYE PHYSICAL TELEMETRY · MCP ({site_name}: {lat:.4f}, {lon:.4f}) ===\n{field_summary}")
                citations.append(
                    Citation(
                        source_type="mireye",
                        title=f"Mireye Earth Telemetry · {site_name}",
                        detail=f"{len(fields)} physical observations",
                        coordinates=f"{lat:.4f}, {lon:.4f}",
                    )
                )
                summary = f"Fetched {len(fields)} physical observations (elevation, seismic PGA, flood zone)."
            else:
                summary = "Mireye telemetry lookup completed."

            trace = ToolExecutionTrace(
                tool="mireye_fetch_telemetry",
                title="Query Mireye Physical Telemetry via MCP",
                input_params={"latitude": lat, "longitude": lon},
                output_summary=summary,
                duration_ms=dur,
            )
            traces.append(trace)
            yield f"data: {json.dumps({'event': 'tool_finish', 'tool': 'mireye_fetch_telemetry', 'output_summary': summary, 'duration_ms': dur})}\n\n"

        # 4. TOOL: Project Context
        if "project" in tools_to_run:
            proj_res = self.mcp.execute("project_inspect_context", {"project_id": project_id, "section": "all", "site_id": site_id})
            p_data = proj_res["content"][1]["data"]
            gaps = p_data.get("open_gaps", [])
            reqs = p_data.get("requirements", [])
            if gaps or reqs:
                context_blocks.append(f"=== PROJECT REQUIREMENTS & GAPS ===\nOpen Gaps: {len(gaps)}, Extracted Requirements: {len(reqs)}")

        # Stream Synthesis
        yield f"data: {json.dumps({'event': 'synthesizing', 'title': 'Synthesizing comprehensive engineering response...'})}\n\n"

        full_context = "\n\n".join(context_blocks)
        history_text = ""
        if history:
            h_lines = [f"{('User' if item.get('role') == 'user' else 'Principal Engineer')}: {item.get('content', '')}" for item in history[-4:]]
            history_text = "\n\nRECENT CONVERSATION:\n" + "\n".join(h_lines)

        user_prompt = f"""CONTEXT:
{full_context}
{history_text}

USER INQUIRY:
{message}

Please provide your rigorous Principal EPC Engineering assessment and conclude with the ```json_tell_me ... ``` block as instructed."""

        has_streamed = False
        full_text = ""
        llm = get_llm()
        if llm and llm.available:
            try:
                for chunk in llm.complete_stream(
                    system=KNOWLEDGE_AGENT_SYSTEM_PROMPT,
                    user=user_prompt,
                    max_tokens=2000,
                ):
                    if chunk:
                        has_streamed = True
                        full_text += chunk
                        # Send text chunks without json_tell_me block if possible
                        yield f"data: {json.dumps({'event': 'token', 'chunk': chunk})}\n\n"
            except Exception as exc:
                log.warning("streaming error in knowledge agent", extra={"error": str(exc)})

        if not has_streamed:
            fallback_text, tell_me = self._deterministic_synthesis(message, site_name, traces, citations)
            words = fallback_text.split(" ")
            for i in range(0, len(words), 4):
                c = " ".join(words[i : i + 4]) + " "
                yield f"data: {json.dumps({'event': 'token', 'chunk': c})}\n\n"
                time.sleep(0.02)
            full_text = fallback_text
        else:
            _, tell_me = self._extract_tell_me(full_text, message, site_name)

        # Emit structured Tell Me, Citations, and Done events
        yield f"data: {json.dumps({'event': 'tell_me', 'data': asdict(tell_me)})}\n\n"
        yield f"data: {json.dumps({'event': 'citations', 'data': [asdict(c) for c in citations]})}\n\n"
        yield f"data: {json.dumps({'event': 'done', 'site_name': site_name, 'mode': getattr(self.llm, 'name', 'deterministic') if has_streamed else 'deterministic', 'traces': [asdict(t) for t in traces]})}\n\n"

    def _extract_tell_me(self, raw_text: str, query: str, site_name: str) -> tuple[str, TellMeInsights]:
        match = re.search(r"```json_tell_me\s*([\s\S]*?)\s*```", raw_text)
        if match:
            clean_answer = raw_text[: match.start()].strip()
            try:
                data = json.loads(match.group(1))
                tell_me = TellMeInsights(
                    key_findings=data.get("key_findings", []),
                    risks_identified=data.get("risks_identified", []),
                    standards_compliance=data.get("standards_compliance", []),
                    actionable_mitigations=data.get("actionable_mitigations", []),
                )
                return clean_answer, tell_me
            except Exception:
                pass
        return raw_text.strip(), self._generate_default_tell_me(query, site_name)

    def _generate_default_tell_me(self, query: str, site_name: str) -> TellMeInsights:
        q = query.lower()
        if "flood" in q or "water" in q:
            return TellMeInsights(
                key_findings=[
                    f"Hydrology review for {site_name}: critical IT equipment requires BFE + 3.0 ft elevation.",
                    "Closed-loop adiabatic cooling recommended in water-stressed basins to limit consumption.",
                ],
                risks_identified=[
                    "FEMA 100-year and 500-year flood zone proximity to generator yards.",
                    "Municipal water supply constraints during peak summer dry-bulb hours.",
                ],
                standards_compliance=[
                    "FEMA Critical Infrastructure Technical Bulletin: FFE > 500-yr BFE + 3ft.",
                    "ASHRAE TC 9.9 2023: Class A1 operating envelope (18°C–27°C).",
                ],
                actionable_mitigations=[
                    "Construct elevated civil concrete pads for switchgear and UPS enclosures.",
                    "Install on-site 48-hour raw water storage and stormwater retention basins.",
                ],
            )
        elif "seismic" in q or "earthquake" in q:
            return TellMeInsights(
                key_findings=[
                    f"Seismic risk classification for {site_name}: ASCE 7-22 Risk Category IV applies.",
                    "Heavy mechanical chillers and battery UPS racks demand rigid structural anchoring.",
                ],
                risks_identified=[
                    "Unreinforced equipment anchorage failure during peak horizontal ground acceleration.",
                    "Potential soft alluvial soil liquefaction requiring deep driven pile foundations.",
                ],
                standards_compliance=[
                    "ASCE 7-22 Chapter 13 & 15: Non-structural seismic restraint design.",
                    "IBC 2024: Essential facility importance factor Ie = 1.5.",
                ],
                actionable_mitigations=[
                    "Install dynamic seismic snubbers on chiller spring isolators.",
                    "Conduct cone penetration test (CPT) borings to calibrate allowable bearing pressure.",
                ],
            )
        else:
            return TellMeInsights(
                key_findings=[
                    f"EPC Design & Submittal Assessment for {site_name}.",
                    "Multi-tier electrical and mechanical redundancy must align with Uptime Tier III/IV.",
                ],
                risks_identified=[
                    "Long-lead utility substation interconnection lead times (52–78 weeks).",
                    "Civil cut/fill earthwork imbalance on steep or tiered topography.",
                ],
                standards_compliance=[
                    "Uptime Institute Tier III: Concurrently maintainable (N+1 paths).",
                    "IEEE 1584 & C37: Substation safety clearance and blast deflection.",
                ],
                actionable_mitigations=[
                    "Issue early procurement packages for high-voltage transformers and MV switchgear.",
                    "Submit county stormwater and grading permits concurrently with schematic design.",
                ],
            )

    def _deterministic_synthesis(
        self,
        query: str,
        site_name: str,
        traces: list[ToolExecutionTrace],
        citations: list[Citation],
    ) -> tuple[str, TellMeInsights]:
        tell_me = self._generate_default_tell_me(query, site_name)

        doc_count = sum(1 for c in citations if c.source_type == "document")
        web_count = sum(1 for c in citations if c.source_type == "web")
        mireye_count = sum(1 for c in citations if c.source_type == "mireye")

        body = (
            f"### Principal Civil & Structural EPC Assessment · {site_name}\n\n"
            f"**Inquiry Analysis:** Evaluating *\"{query}\"* across ingested engineering specifications, "
            f"live Mireye physical telemetry, and authoritative technical standards.\n\n"
            f"#### 1. Multi-Source Evidence Summary\n"
            f"- **Ingested Project Documents**: Inspected {doc_count} document chunk(s) via hybrid ChromaDB + BM25 vector retrieval.\n"
            f"- **Mireye Location Intelligence**: Evaluated physical telemetry for {site_name} (elevation, seismic PGA, flood zone, water index).\n"
            f"- **Engineering Standards**: Referenced {web_count} authoritative standard(s) including ASHRAE TC 9.9, ASCE 7-22, and FEMA guidelines.\n\n"
            f"#### 2. Civil & Structural Engineering Recommendations\n"
            f"1. **Earthwork & Foundations**: Verify soil allowable bearing capacity against point loads. Slopes exceeding 3% necessitate tiered retaining walls.\n"
            f"2. **Seismic Anchorage & Critical Skids**: Under ASCE 7-22 Risk Category IV, mechanical chillers and transformer yards require positive structural bolting with dynamic snubbers.\n"
            f"3. **Hydrology & Stormwater**: IT floor slabs and generator pads must maintain Finished Floor Elevation (FFE) at least 3.0 ft above the 500-year Base Flood Elevation (BFE).\n"
            f"4. **Thermal & Cooling Architecture**: Adhere to ASHRAE TC 9.9 Class A1 guidelines (18°C–27°C dry bulb). In water-stressed basins, employ closed-loop adiabatic heat rejection."
        )
        return body, tell_me


_knowledge_agent: KnowledgeAgent | None = None


def get_knowledge_agent() -> KnowledgeAgent:
    global _knowledge_agent
    if _knowledge_agent is None:
        _knowledge_agent = KnowledgeAgent()
    return _knowledge_agent
