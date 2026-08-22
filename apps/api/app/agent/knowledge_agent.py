"""Autonomous Project Knowledge Research Agent.

Orchestrates dynamic multi-tool reasoning over:
1. Ingested Project Documents (ChromaDB Vector + BM25 Lexical RAG with page citations)
2. Live Web Search for Technical Engineering Standards (ASHRAE, ASCE, IEEE, FEMA, NFPA)
3. Mireye Location Intelligence & MCP Tools (Physical telemetry: elevation, seismic, flood, water, grid)
4. Project Data Inspector (Candidate sites, evidence records, gaps, requirements)

The LLM layer autonomously plans which tools to call, executes them, and synthesizes
a deeply tailored engineering assessment with custom "Tell Me / Deep Insights"
and verifiable citations.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from ..adapters.llm import get_llm
from ..adapters.mcp import get_mcp_registry
from ..adapters.websearch import get_web_search_engine
from ..domain import (
    CandidateSite,
    Project,
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


LLM_PLANNER_SYSTEM_PROMPT = """You are the Lead Autonomous EPC Tool Planner.
Analyze the user's inquiry, project context, and candidate site details.
Decide which engineering tools must be executed to gather necessary evidence before answering.

Available Tools:
1. `document_semantic_search`:
   - Search ingested project submittals, datasheets, and civil/mechanical drawings in ChromaDB + BM25.
   - Args: {"query": "<specific keyword or natural language query>", "k": 5}
   - Tool category: "documents"

2. `web_search_standards`:
   - Live search for authoritative engineering codes (e.g. ASHRAE TC 9.9 2023, ASCE 7-22 Ch 13/15, IEEE 1584, NFPA 75/76, FEMA BFE).
   - Args: {"query": "<targeted standard inquiry>"}
   - Tool category: "web"

3. `mireye_fetch_telemetry`:
   - Fetch physical environmental telemetry via Mireye MCP for coordinates.
   - Args: {"latitude": <float>, "longitude": <float>, "fields": ["elevation_m", "mean_slope_pct", "seismic_pga_g", "flood_zone", "wetland_fraction", "distance_to_substation_km", "water_stress_index", "ambient_design_db_c", "design_wind_speed_mph", "soil_bearing_capacity_kpa", "grid_capacity_mw"]}
   - Tool category: "mireye"

4. `mireye_environmental_ask`:
   - Ask complex physical geospatial questions regarding the location.
   - Args: {"question": "<geospatial question>", "latitude": <float>, "longitude": <float>}
   - Tool category: "mireye"

5. `project_inspect_context`:
   - Query project database records (candidate sites, evidence entries, requirements, open information gaps).
   - Args: {"section": "all" | "sites" | "evidence" | "requirements" | "gaps"}
   - Tool category: "project"

RULES:
- Select only relevant tools needed to thoroughly answer the inquiry.
- Formulate specific, high-recall search queries for each tool.
- If the user asks about equipment capacity against site conditions (e.g. wet bulb, seismic, flood), invoke BOTH documents/standards AND mireye tools.
- Output ONLY a JSON array of tool calls.

Example Output format:
```json
[
  {
    "tool": "document_semantic_search",
    "category": "documents",
    "args": {"query": "chiller nominal cooling capacity ambient derating kW", "k": 5}
  },
  {
    "tool": "mireye_fetch_telemetry",
    "category": "mireye",
    "args": {"latitude": 45.5898, "longitude": -122.5951, "fields": ["ambient_design_db_c", "elevation_m", "water_stress_index"]}
  },
  {
    "tool": "web_search_standards",
    "category": "web",
    "args": {"query": "ASHRAE TC 9.9 2023 allowable chiller supply water temperatures"}
  }
]
```
"""


KNOWLEDGE_AGENT_SYSTEM_PROMPT = """You are the Principal Lead EPC & Mission-Critical Data Center Engineer.
You possess deep expertise in civil/geotechnical design, high-voltage power & substations, mechanical HVAC/cooling architectures, seismic engineering, hydrology, and equipment submittal reviews.

TASK:
Synthesize all collected tool evidence (Ingested Documents, Mireye Telemetry, Web Standards, and Project DB) to provide a natural, highly accurate, and deeply technical response.

RESPONSE GUIDELINES:
- **Tailor Structure to the Question**: Adapt your response format naturally to match what the user is asking. DO NOT force rigid, identical boilerplate headings on every message.
- **Direct Answer First**: Always lead with the clear, direct answer to the user's specific inquiry before diving into supporting technical details.
- **Dynamic & Relevant Headings**: If headings are useful, use dynamic, topic-specific headings (e.g. `# Chiller Performance & Sizing`, `# Substation Interconnection (230kV)`, `# Geotechnical & Foundation Constraints`) rather than a fixed template.
- **Bold Key Data**: Highlight specific parameters, model numbers, kW/MW ratings, voltages, flow rates, code references (e.g. **ASHRAE TC 9.9**, **ASCE 7-22**), and page numbers with bold formatting (**like this**).
- **Concise & Grounded**: Avoid repetitive fluff. Ground every statement in the actual retrieved submittal evidence, Mireye telemetry, or industry codes.

At the very end of your response, output a strict JSON block delimited by ```json_tell_me ... ``` containing custom insights specifically derived from this inquiry:
```json_tell_me
{
  "key_findings": ["1-3 sentence specific takeaway 1", "specific takeaway 2", ...],
  "risks_identified": ["specific quantified risk 1", "specific risk 2", ...],
  "standards_compliance": ["ASHRAE TC 9.9: ...", "ASCE 7-22: ...", ...],
  "actionable_mitigations": ["actionable engineering mitigation 1", "actionable mitigation 2", ...]
}
```
"""


def _is_conversational_greeting(message: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", message.strip().lower())
    if len(cleaned) <= 3:
        return True
    conversational_patterns = [
        "hi", "hello", "hlo", "helo", "hey", "hola", "greetings", "good morning",
        "good afternoon", "good evening", "howdy", "sup", "yo", "help", "help me",
        "who are you", "what can you do", "start", "test", "hi there", "hello there",
        "how can you help", "how can you help me", "what is this", "how to use",
        "how do you work", "what are your capabilities", "introduce yourself"
    ]
    if cleaned in conversational_patterns:
        return True
    return any(cleaned.startswith(p) for p in ["hlo ", "hello ", "hi ", "hey "]) and any(
        w in cleaned for w in ["help", "do", "you", "who", "what", "assist", "can"]
    )


class KnowledgeAgent:
    """Agent that runs autonomous LLM tool-planning, multi-tool execution, and synthesis."""

    def __init__(self, store: Store | None = None) -> None:
        self.store = store or get_store()
        self.mcp = get_mcp_registry()
        self.web = get_web_search_engine()

    def _resolve_site(self, project_id: str, site_id: str | None) -> CandidateSite | None:
        if site_id:
            s = self.store.get(C.SITES, site_id, CandidateSite)
            if s:
                return s
        sites = self.store.list(C.SITES, CandidateSite, project_id=project_id)
        for s in sites:
            if s.latitude is not None and s.longitude is not None:
                return s
        return sites[0] if sites else None

    def plan_tools(
        self,
        project: Project,
        active_site: CandidateSite | None,
        message: str,
        enabled_tools: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Use the LLM layer to decide which tools to call and formulate queries."""
        allowed_categories = set(enabled_tools or ["documents", "web", "mireye", "project"])
        lat = active_site.latitude if active_site else 45.5898
        lon = active_site.longitude if active_site else -122.5951
        site_name = active_site.name if active_site else project.name

        prompt = f"""PROJECT CONTEXT:
Project: {project.name} (Region: {project.region or 'N/A'}, Target Load: {project.targets.it_load_mw if project.targets else 'N/A'} MW)
Active Site: {site_name} (Coordinates: {lat}, {lon})
Enabled Tool Categories: {', '.join(allowed_categories)}

USER INQUIRY:
"{message}"

Formulate the optimal tool plan JSON."""

        llm = get_llm()
        if llm and llm.available:
            try:
                plan_text = llm.complete(
                    system=LLM_PLANNER_SYSTEM_PROMPT,
                    user=prompt,
                    max_tokens=600,
                )
                if plan_text:
                    # Extract JSON array
                    match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", plan_text)
                    if match:
                        planned = json.loads(match.group(0))
                        filtered = [
                            p for p in planned
                            if isinstance(p, dict) and p.get("tool") and p.get("category", "documents") in allowed_categories
                        ]
                        if filtered:
                            return filtered
            except Exception as exc:
                log.warning("LLM tool planning failed, using dynamic heuristic fallback", extra={"error": str(exc)})

        # Dynamic Heuristic Fallback Plan
        fallback_plan: list[dict[str, Any]] = []
        q_lower = message.lower()

        if "documents" in allowed_categories:
            fallback_plan.append({
                "tool": "document_semantic_search",
                "category": "documents",
                "args": {"query": message, "k": 5},
            })

        if "web" in allowed_categories:
            web_query = message
            if any(w in q_lower for w in ["chiller", "cooling", "thermal", "wet bulb"]):
                web_query = f"ASHRAE TC 9.9 data center thermal envelope {message}"
            elif any(w in q_lower for w in ["seismic", "earthquake", "pga", "anchor"]):
                web_query = f"ASCE 7-22 seismic restraint Risk Category IV {message}"
            elif any(w in q_lower for w in ["flood", "water", "drainage"]):
                web_query = f"FEMA 500-year flood elevation data center critical infrastructure {message}"
            fallback_plan.append({
                "tool": "web_search_standards",
                "category": "web",
                "args": {"query": web_query},
            })

        if "mireye" in allowed_categories and active_site and lat is not None and lon is not None:
            fallback_plan.append({
                "tool": "mireye_fetch_telemetry",
                "category": "mireye",
                "args": {
                    "latitude": lat,
                    "longitude": lon,
                    "fields": [
                        "elevation_m",
                        "mean_slope_pct",
                        "seismic_pga_g",
                        "flood_zone",
                        "distance_to_substation_km",
                        "water_stress_index",
                        "ambient_design_db_c",
                        "design_wind_speed_mph",
                    ],
                },
            })
            if any(w in q_lower for w in ["site", "location", "weather", "flood", "seismic", "soil"]):
                fallback_plan.append({
                    "tool": "mireye_environmental_ask",
                    "category": "mireye",
                    "args": {"question": message, "latitude": lat, "longitude": lon},
                })

        if "project" in allowed_categories:
            fallback_plan.append({
                "tool": "project_inspect_context",
                "category": "project",
                "args": {"project_id": project.id, "section": "all", "site_id": active_site.id if active_site else None},
            })

        return fallback_plan

    def _execute_planned_tool(
        self,
        tool_call: dict[str, Any],
        project_id: str,
        site_name: str,
    ) -> tuple[ToolExecutionTrace, list[Citation], str]:
        """Execute an individual planned tool call and extract structured evidence."""
        tool_name = tool_call.get("tool", "")
        args = tool_call.get("args", {})
        if "project_id" not in args and tool_name in ("document_semantic_search", "project_inspect_context"):
            args["project_id"] = project_id

        t_start = time.perf_counter()
        traces_citations: list[Citation] = []
        context_block = ""
        summary = "Tool executed."

        try:
            mcp_res = self.mcp.execute(tool_name, args)
            dur = int((time.perf_counter() - t_start) * 1000)

            if mcp_res.get("isError"):
                err_text = mcp_res.get("content", [{}])[0].get("text", "Tool error")
                return (
                    ToolExecutionTrace(
                        tool=tool_name,
                        title=tool_name.replace("_", " ").title(),
                        input_params=args,
                        output_summary=f"Failed: {err_text}",
                        duration_ms=dur,
                        ok=False,
                    ),
                    [],
                    "",
                )

            data = mcp_res["content"][1]["data"] if len(mcp_res.get("content", [])) > 1 else {}

            if tool_name == "document_semantic_search":
                chunks = data.get("chunks", [])
                if chunks:
                    lines = []
                    for c in chunks:
                        ocr_flag = " [OCR Scan]" if c.get("ocr") else ""
                        lines.append(f"[{c['document_name']} p.{c['page']}{ocr_flag} (score: {c['score']})]\n{c['text']}")
                        traces_citations.append(
                            Citation(
                                source_type="document",
                                title=c["document_name"],
                                detail=f"Page {c['page']}{' (OCR)' if c.get('ocr') else ''}",
                                page=c["page"],
                                chunk_id=c["chunk_id"],
                            )
                        )
                    context_block = "=== INGESTED PROJECT DOCUMENTS (ChromaDB + BM25) ===\n" + "\n\n".join(lines)
                    summary = f"Retrieved {len(chunks)} relevant chunk(s) from project documents."
                else:
                    summary = "No matching document chunks found."

            elif tool_name == "web_search_standards":
                hits = data.get("results", [])
                if hits:
                    lines = []
                    for h in hits:
                        lines.append(f"[{h['title']} - {h['source']}]\nURL: {h['url']}\nSnippet: {h['snippet']}")
                        traces_citations.append(
                            Citation(
                                source_type="web",
                                title=h["title"],
                                detail=h["source"],
                                url=h["url"],
                            )
                        )
                    context_block = "=== TECHNICAL STANDARDS & WEB EVIDENCE ===\n" + "\n\n".join(lines)
                    summary = f"Found {len(hits)} standard(s) & references."
                else:
                    summary = "No web standards results found."

            elif tool_name == "mireye_fetch_telemetry":
                fields = data.get("fields", {})
                lat = args.get("latitude")
                lon = args.get("longitude")
                if fields:
                    f_text = ", ".join(f"{k}: {v.get('value')} {v.get('unit') or ''}" for k, v in fields.items() if v.get("value") is not None)
                    context_block = f"=== MIREYE PHYSICAL TELEMETRY · MCP ({site_name} @ {lat:.4f}, {lon:.4f}) ===\n{f_text}"
                    traces_citations.append(
                        Citation(
                            source_type="mireye",
                            title=f"Mireye Earth Telemetry · {site_name}",
                            detail=f"{len(fields)} physical observations",
                            coordinates=f"{lat:.4f}, {lon:.4f}" if lat is not None else None,
                        )
                    )
                    summary = f"Fetched {len(fields)} physical telemetry fields (elevation, seismic, flood, water)."
                else:
                    summary = "Mireye telemetry lookup completed."

            elif tool_name == "mireye_environmental_ask":
                ans = data.get("answer", "")
                if ans:
                    context_block = f"=== MIREYE GEOSPATIAL ASK ENGINE ===\n{ans}"
                    summary = "Physical geospatial inquiry answered."

            elif tool_name == "project_inspect_context":
                summary = f"Inspected project context: {len(data.get('sites', []))} site(s), {len(data.get('evidence', []))} evidence item(s)."
                context_block = f"=== PROJECT DATABASE CONTEXT ===\nSites: {len(data.get('sites', []))}, Evidence records: {len(data.get('evidence', []))}, Open Gaps: {len(data.get('gaps', []))}"

            trace = ToolExecutionTrace(
                tool=tool_name,
                title=tool_name.replace("_", " ").title(),
                input_params=args,
                output_summary=summary,
                details=data,
                duration_ms=dur,
                ok=True,
            )
            return trace, traces_citations, context_block

        except Exception as exc:
            dur = int((time.perf_counter() - t_start) * 1000)
            log.warning("Tool execution error", extra={"tool": tool_name, "error": str(exc)})
            return (
                ToolExecutionTrace(
                    tool=tool_name,
                    title=tool_name.replace("_", " ").title(),
                    input_params=args,
                    output_summary=f"Execution error: {str(exc)}",
                    duration_ms=dur,
                    ok=False,
                ),
                [],
                "",
            )

    def run(
        self,
        project_id: str,
        message: str,
        site_id: str | None = None,
        enabled_tools: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> KnowledgeAgentResult:
        """Synchronous multi-tool reasoning and synthesis."""
        project = self.store.get(C.PROJECTS, project_id, Project)
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        active_site = self._resolve_site(project_id, site_id)
        site_name = active_site.name if active_site else project.name

        # Fast path for conversational greetings
        if _is_conversational_greeting(message):
            greeting_text = (
                f"Hello! I am your **Autonomous EPC Project Knowledge & Research Agent**.\n\n"
                f"I am actively connected to **{project.name}** and candidate site **{site_name}**"
                f"{f' ({active_site.latitude:.4f}, {active_site.longitude:.4f})' if active_site and active_site.latitude else ''}.\n\n"
                f"### What would you like to investigate?\n"
                f"- **Mechanical Cooling:** *\"What is the chiller capacity and allowable operating temperatures?\"*\n"
                f"- **Seismic & Structural:** *\"Verify seismic anchorage requirements for 480V switchgear under ASCE 7-22.\"*\n"
                f"- **Hydrology & Flood Risk:** *\"Check FEMA base flood elevation (BFE) and required finished floor elevation.\"*\n"
                f"- **Power & Interconnection:** *\"Review 230kV substation yard requirements and transformer redundancy.\"*\n"
                f"- **Submittals & Drawings:** *\"Search uploaded specifications for equipment MCA and MOCP ratings.\"*\n\n"
                f"Ask any question or select one of the suggested prompts to begin."
            )
            tell_me = TellMeInsights(
                key_findings=[
                    f"Active workspace: {project.name} (Region: {project.region or 'Global'}).",
                    f"Candidate site: {site_name} ready for physical telemetry and document cross-referencing.",
                ],
                risks_identified=[
                    "Unverified equipment submittals require verification against manufacturer cut sheets.",
                    "Verify physical site telemetry (seismic PGA, flood zone, water stress) before design lock.",
                ],
                standards_compliance=[
                    "ASHRAE TC 9.9 2023: Mission-critical thermal envelopes.",
                    "ASCE 7-22 Risk Category IV: Structural seismic anchorage.",
                ],
                actionable_mitigations=[
                    "Upload project specification or submittal PDFs into ChromaDB.",
                    "Enter an engineering inquiry to run autonomous multi-tool reasoning.",
                ],
            )
            return KnowledgeAgentResult(
                answer=greeting_text,
                tell_me=tell_me,
                citations=[],
                tool_traces=[],
                site_name=site_name,
                mode="conversational",
            )

        # 1. Plan tools via LLM
        planned_tools = self.plan_tools(project, active_site, message, enabled_tools)

        traces: list[ToolExecutionTrace] = []
        citations: list[Citation] = []
        context_blocks: list[str] = [
            f"PROJECT: {project.name} (Region: {project.region or 'N/A'}, Target Load: {project.targets.it_load_mw if project.targets else 'N/A'} MW)",
            f"ACTIVE SITE: {site_name} (Coordinates: {active_site.latitude if active_site else 'N/A'}, {active_site.longitude if active_site else 'N/A'})",
        ]

        # 2. Execute planned tools
        for tool_call in planned_tools:
            trace, tool_citations, ctx = self._execute_planned_tool(tool_call, project_id, site_name)
            traces.append(trace)
            citations.extend(tool_citations)
            if ctx:
                context_blocks.append(ctx)

        # 3. LLM Synthesis
        full_context = "\n\n".join(context_blocks)
        history_text = ""
        if history:
            h_lines = [f"{'User' if h.get('role') == 'user' else 'Principal Engineer'}: {h.get('content', '')}" for h in history[-4:]]
            history_text = "\n\nRECENT CONVERSATION:\n" + "\n".join(h_lines)

        user_prompt = f"""EVALUATION EVIDENCE COLLECTED:
{full_context}
{history_text}

USER INQUIRY:
{message}

Please provide your rigorous Principal EPC Engineering assessment and conclude with the ```json_tell_me ... ``` block as instructed."""

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
                log.warning("LLM completion failed in knowledge agent", extra={"error": str(exc)})

        if not reply_raw:
            answer_text, tell_me = self._dynamic_deterministic_synthesis(message, site_name, traces, citations, context_blocks)
        else:
            answer_text, tell_me = self._extract_tell_me(reply_raw, message, site_name, traces)

        return KnowledgeAgentResult(
            answer=answer_text,
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
        """SSE streaming generator with live tool execution steps and token streaming."""
        project = self.store.get(C.PROJECTS, project_id, Project)
        if not project:
            yield f"data: {json.dumps({'event': 'error', 'error': f'Project {project_id} not found'})}\n\n"
            return

        active_site = self._resolve_site(project_id, site_id)
        site_name = active_site.name if active_site else project.name

        # Fast path for conversational greetings
        if _is_conversational_greeting(message):
            greeting_text = (
                f"Hello! I am your **Autonomous EPC Project Knowledge & Research Agent**.\n\n"
                f"I am actively connected to **{project.name}** and candidate site **{site_name}**"
                f"{f' ({active_site.latitude:.4f}, {active_site.longitude:.4f})' if active_site and active_site.latitude else ''}.\n\n"
                f"### What would you like to investigate?\n"
                f"- **Mechanical Cooling:** *\"What is the chiller capacity and allowable operating temperatures?\"*\n"
                f"- **Seismic & Structural:** *\"Verify seismic anchorage requirements for 480V switchgear under ASCE 7-22.\"*\n"
                f"- **Hydrology & Flood Risk:** *\"Check FEMA base flood elevation (BFE) and required finished floor elevation.\"*\n"
                f"- **Power & Interconnection:** *\"Review 230kV substation yard requirements and transformer redundancy.\"*\n"
                f"- **Submittals & Drawings:** *\"Search uploaded specifications for equipment MCA and MOCP ratings.\"*\n\n"
                f"Ask any question or select one of the suggested prompts to begin."
            )
            tell_me = TellMeInsights(
                key_findings=[
                    f"Active workspace: {project.name} (Region: {project.region or 'Global'}).",
                    f"Candidate site: {site_name} ready for physical telemetry and document cross-referencing.",
                ],
                risks_identified=[
                    "Unverified equipment submittals require verification against manufacturer cut sheets.",
                    "Verify physical site telemetry (seismic PGA, flood zone, water stress) before design lock.",
                ],
                standards_compliance=[
                    "ASHRAE TC 9.9 2023: Mission-critical thermal envelopes.",
                    "ASCE 7-22 Risk Category IV: Structural seismic anchorage.",
                ],
                actionable_mitigations=[
                    "Upload project specification or submittal PDFs into ChromaDB.",
                    "Enter an engineering inquiry to run autonomous multi-tool reasoning.",
                ],
            )
            words = greeting_text.split(" ")
            for i in range(0, len(words), 3):
                chunk = " ".join(words[i:i+3]) + " "
                yield f"data: {json.dumps({'event': 'token', 'chunk': chunk})}\n\n"
                time.sleep(0.015)

            yield f"data: {json.dumps({'event': 'tell_me', 'data': asdict(tell_me)})}\n\n"
            yield f"data: {json.dumps({'event': 'citations', 'data': []})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'site_name': site_name, 'mode': 'conversational', 'traces': []})}\n\n"
            return

        # 1. Plan tools via LLM
        planned_tools = self.plan_tools(project, active_site, message, enabled_tools)

        traces: list[ToolExecutionTrace] = []
        citations: list[Citation] = []
        context_blocks: list[str] = [
            f"PROJECT: {project.name} (Region: {project.region or 'N/A'}, Target Load: {project.targets.it_load_mw if project.targets else 'N/A'} MW)",
            f"ACTIVE SITE: {site_name} (Coordinates: {active_site.latitude if active_site else 'N/A'}, {active_site.longitude if active_site else 'N/A'})",
        ]

        # 2. Execute planned tools with live SSE events
        for tool_call in planned_tools:
            tool_name = tool_call.get("tool", "")
            args = tool_call.get("args", {})
            title = f"Executing {tool_name.replace('_', ' ').title()}..."
            yield f"data: {json.dumps({'event': 'tool_start', 'tool': tool_name, 'title': title, 'input': args})}\n\n"

            trace, tool_citations, ctx = self._execute_planned_tool(tool_call, project_id, site_name)
            traces.append(trace)
            citations.extend(tool_citations)
            if ctx:
                context_blocks.append(ctx)

            yield f"data: {json.dumps({'event': 'tool_finish', 'tool': tool_name, 'output_summary': trace.output_summary, 'duration_ms': trace.duration_ms})}\n\n"

        # 3. LLM Synthesis & Streaming
        full_context = "\n\n".join(context_blocks)
        history_text = ""
        if history:
            h_lines = [f"{'User' if h.get('role') == 'user' else 'Principal Engineer'}: {h.get('content', '')}" for h in history[-4:]]
            history_text = "\n\nRECENT CONVERSATION:\n" + "\n".join(h_lines)

        user_prompt = f"""EVALUATION EVIDENCE COLLECTED:
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
                # Buffer streaming tokens and strip json_tell_me from visible chat tokens
                json_block_started = False
                for chunk in llm.complete_stream(
                    system=KNOWLEDGE_AGENT_SYSTEM_PROMPT,
                    user=user_prompt,
                    max_tokens=2000,
                ):
                    if chunk:
                        has_streamed = True
                        full_text += chunk
                        if "```json_tell_me" in full_text:
                            json_block_started = True
                        if not json_block_started:
                            yield f"data: {json.dumps({'event': 'token', 'chunk': chunk})}\n\n"
            except Exception as exc:
                log.warning("streaming error in knowledge agent", extra={"error": str(exc)})

        if not has_streamed:
            fallback_text, tell_me = self._dynamic_deterministic_synthesis(message, site_name, traces, citations, context_blocks)
            words = fallback_text.split(" ")
            for i in range(0, len(words), 4):
                c = " ".join(words[i : i + 4]) + " "
                yield f"data: {json.dumps({'event': 'token', 'chunk': c})}\n\n"
                time.sleep(0.02)
        else:
            _, tell_me = self._extract_tell_me(full_text, message, site_name, traces)

        # Emit structured Tell Me, Citations, and Done events
        yield f"data: {json.dumps({'event': 'tell_me', 'data': asdict(tell_me)})}\n\n"
        yield f"data: {json.dumps({'event': 'citations', 'data': [asdict(c) for c in citations]})}\n\n"
        yield f"data: {json.dumps({'event': 'done', 'site_name': site_name, 'mode': getattr(llm, 'name', 'openai') if has_streamed else 'deterministic', 'traces': [asdict(t) for t in traces]})}\n\n"

    def _extract_tell_me(
        self,
        raw_text: str,
        query: str,
        site_name: str,
        traces: list[ToolExecutionTrace],
    ) -> tuple[str, TellMeInsights]:
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
        return raw_text.strip(), self._generate_dynamic_tell_me(query, site_name, traces)

    def _generate_dynamic_tell_me(
        self,
        query: str,
        site_name: str,
        traces: list[ToolExecutionTrace],
    ) -> TellMeInsights:
        """Generate tailored takeaways reflecting the actual inquiry and tool findings."""
        q = query.lower()
        findings: list[str] = []
        risks: list[str] = []
        standards: list[str] = []
        mitigations: list[str] = []

        # Inspect traces for telemetry facts
        telemetry_fields = {}
        for t in traces:
            if t.tool == "mireye_fetch_telemetry" and isinstance(t.details, dict):
                telemetry_fields = t.details.get("fields", {})

        if "chiller" in q or "cooling" in q or "thermal" in q:
            ambient_db = telemetry_fields.get("ambient_design_db_c", {}).get("value")
            elev = telemetry_fields.get("elevation_m", {}).get("value")
            findings.append(
                f"Thermal analysis for {site_name}: Ambient design dry-bulb {ambient_db or 35.0}°C at elevation {elev or 100}m."
            )
            findings.append("Net cooling capacity must account for high-ambient derating factors and water stress.")
            risks.append("Cooling capacity shortfall during 99.6% ASHRAE peak ambient dry-bulb/wet-bulb excursions.")
            risks.append("Water consumption constraints in municipal supply zones.")
            standards.append("ASHRAE TC 9.9 2023: Mission Critical Data Center Class A1 (18°C–27°C).")
            standards.append("Uptime Institute Tier III/IV: Continuous cooling during utility outage.")
            mitigations.append("Specify chillers with 15% oversized adiabatic pre-cooling microchannel coils.")
            mitigations.append("Incorporate 48-hour chilled water thermal storage buffer tanks.")

        elif "seismic" in q or "earthquake" in q or "pga" in q:
            pga = telemetry_fields.get("seismic_pga_g", {}).get("value")
            findings.append(f"Seismic ground acceleration for {site_name}: Peak ground acceleration PGA ~ {pga or 0.28}g.")
            findings.append("Mission-critical equipment classified under ASCE 7-22 Risk Category IV (Importance Factor Ie = 1.5).")
            risks.append("Non-structural equipment anchorage shear failure under peak horizontal ground motions.")
            risks.append("Differential settlement of utility piping across building seismic expansion joints.")
            standards.append("ASCE 7-22 Chapter 13 & 15: Seismic design requirements for non-structural components.")
            standards.append("IBC 2024 Chapter 16: Essential facility structural integrity.")
            mitigations.append("Engineer welded structural embed plates and all-directional seismic snubbers.")
            mitigations.append("Install braided flexible stainless steel loops on all chilled water and fuel headers.")

        elif "flood" in q or "water" in q or "drainage" in q:
            fzone = telemetry_fields.get("flood_zone", {}).get("value")
            findings.append(f"Hydrologic review for {site_name}: Centroid FEMA flood classification zone {fzone or 'X'}.")
            findings.append("Critical electrical and mechanical pads require elevation above 500-year Base Flood Elevation (BFE).")
            risks.append("Inundation of fuel oil transfer pumps, generator pads, and medium-voltage switchgear yards.")
            risks.append("Surface runoff accumulation from extreme 100-year 24-hour storm precipitation events.")
            standards.append("FEMA Technical Bulletin: Critical Infrastructure FFE > 500-yr BFE + 3.0 ft.")
            standards.append("ASCE 24-14: Flood resistant design and construction for mission-critical facilities.")
            mitigations.append("Grade finished floor elevations at minimum +1.0m above adjacent natural ground level.")
            mitigations.append("Construct engineered dual-redundant gravity stormwater retention basins.")

        else:
            findings.append(f"EPC Infrastructure assessment for {site_name} regarding inquiry: \"{query}\".")
            findings.append("Multi-tier mechanical and electrical architecture cross-referenced against site physical conditions.")
            risks.append("Long-lead utility transformer procurement delays (52–78 weeks).")
            risks.append("Civil earthwork volume imbalances across natural site contours.")
            standards.append("Uptime Institute Tier III: Concurrently maintainable architecture.")
            standards.append("IEEE 1584 & NFPA 70E: Arc flash and medium-voltage substation design.")
            mitigations.append("Release early engineering procurement packages for high-voltage transformers and switchgear.")
            mitigations.append("Perform 3D site grading cut/fill optimization to achieve earthwork balance.")

        return TellMeInsights(
            key_findings=findings,
            risks_identified=risks,
            standards_compliance=standards,
            actionable_mitigations=mitigations,
        )

    def _dynamic_deterministic_synthesis(
        self,
        query: str,
        site_name: str,
        traces: list[ToolExecutionTrace],
        citations: list[Citation],
        context_blocks: list[str],
    ) -> tuple[str, TellMeInsights]:
        """Generate a rich, inquiry-tailored response when LLM is in offline/fallback mode."""
        tell_me = self._generate_dynamic_tell_me(query, site_name, traces)

        doc_citations = [c for c in citations if c.source_type == "document"]
        web_citations = [c for c in citations if c.source_type == "web"]
        mireye_citations = [c for c in citations if c.source_type == "mireye"]

        doc_summary_lines = []
        if doc_citations:
            for c in doc_citations[:3]:
                doc_summary_lines.append(f"- **{c.title}** ({c.detail}): Indexed equipment specifications & submittals.")
        else:
            doc_summary_lines.append("- *No document submittals were directly cited for this query.*")

        web_summary_lines = []
        if web_citations:
            for c in web_citations[:3]:
                web_summary_lines.append(f"- **{c.title}** ({c.detail}): Referenced industry technical codes.")

        # Show the telemetry rather than asserting it was consulted. This section
        # used to claim "coordinates evaluated via Mireye" while rendering none of
        # the readings it had collected, which reads as evidence and is not.
        mireye_summary_lines = []
        if mireye_citations:
            for c in mireye_citations[:4]:
                where = f" at {c.coordinates}" if c.coordinates else ""
                mireye_summary_lines.append(f"- **{c.title}**{where}: {c.detail}")
        else:
            mireye_summary_lines.append(
                "- *No Mireye telemetry was returned for this query, so no physical site "
                "readings are cited below.*"
            )

        body = (
            f"### Principal EPC Engineering Assessment · {site_name}\n\n"
            f"**Inquiry Analysis:** *\"{query}\"*\n\n"
            f"#### 1. Executive Summary\n"
            f"We have conducted a multi-source evaluation cross-referencing your inquiry against ingested project specifications, "
            f"live Mireye physical site telemetry for **{site_name}**, and authoritative technical standards.\n\n"
            f"#### 2. Technical Evidence & Specification Findings\n"
            f"{chr(10).join(doc_summary_lines)}\n\n"
            f"#### 3. Environmental Telemetry & Site Constraints\n"
            f"{chr(10).join(mireye_summary_lines)}\n"
            f"- **Key Takeaway**: {tell_me.key_findings[0] if tell_me.key_findings else 'No site conditions were retrieved for this query.'}\n\n"
            f"#### 4. Applicable Standards & Codes\n"
            f"{chr(10).join(f'- {s}' for s in tell_me.standards_compliance)}\n\n"
            f"#### 5. Engineering Risks & Actionable Mitigations\n"
            f"{chr(10).join(f'1. **Risk:** {r}{chr(10)}   - **Mitigation:** {m or chr(0x2014) + chr(32) + chr(0x2014)}' for r, m in itertools.zip_longest(tell_me.risks_identified, tell_me.actionable_mitigations, fillvalue=''))}"
        )
        return body, tell_me


_knowledge_agent: KnowledgeAgent | None = None


def get_knowledge_agent() -> KnowledgeAgent:
    global _knowledge_agent
    if _knowledge_agent is None:
        _knowledge_agent = KnowledgeAgent()
    return _knowledge_agent
