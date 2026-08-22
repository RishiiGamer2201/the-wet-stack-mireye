"""Tests for Project Knowledge Agent, MCP Tools, and Web Search."""

from __future__ import annotations

from app.adapters.mcp import get_mcp_registry
from app.adapters.websearch import get_web_search_engine


def test_mcp_tools_registration_and_list():
    registry = get_mcp_registry()
    tools = registry.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "mireye_geocode" in tool_names
    assert "mireye_fetch_telemetry" in tool_names
    assert "mireye_environmental_ask" in tool_names
    assert "document_semantic_search" in tool_names
    assert "web_search_standards" in tool_names
    assert "project_inspect_context" in tool_names


def test_mcp_mireye_telemetry_execution():
    registry = get_mcp_registry()
    res = registry.execute(
        "mireye_fetch_telemetry",
        {"latitude": 45.5898, "longitude": -122.5951},
    )
    assert res["isError"] is False
    data = res["content"][1]["data"]
    assert "fields" in data
    assert "elevation_m" in data["fields"]


def test_web_search_standards_kb_and_live():
    engine = get_web_search_engine()
    results = engine.search("ASHRAE TC 9.9 thermal temperature envelope")
    assert len(results) > 0
    assert any("ASHRAE" in r["title"] or "ASHRAE" in r["snippet"] for r in results)


def test_knowledge_agent_execution(api):
    from app.adapters.llm import DeterministicNarrator, set_llm
    set_llm(DeterministicNarrator())

    project_id = api.get("/api/projects").json()[0]["id"]

    # Test sync agent endpoint
    payload = {
        "message": "Analyze chiller net cooling capacity and check seismic PGA requirements.",
        "enabled_tools": ["documents", "web", "mireye", "project"],
    }
    res = api.post(f"/api/projects/{project_id}/knowledge/agent/chat", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    assert "tell_me" in data
    assert "key_findings" in data["tell_me"]
    assert "risks_identified" in data["tell_me"]
    assert "standards_compliance" in data["tell_me"]
    assert "actionable_mitigations" in data["tell_me"]
    assert len(data["tool_traces"]) > 0


def test_knowledge_suggestions_endpoint(api):
    project_id = api.get("/api/projects").json()[0]["id"]
    res = api.get(f"/api/projects/{project_id}/knowledge/suggestions")
    assert res.status_code == 200
    suggestions = res.json()["suggestions"]
    assert len(suggestions) >= 4


def test_mcp_api_endpoints(api):
    # GET /api/mcp/tools
    tools_res = api.get("/api/mcp/tools")
    assert tools_res.status_code == 200
    tools = tools_res.json()
    assert len(tools) >= 6

    # POST /api/mcp/rpc tools/list
    rpc_res = api.post(
        "/api/mcp/rpc",
        json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}},
    )
    assert rpc_res.status_code == 200
    assert "tools" in rpc_res.json()["result"]

    # POST /api/mcp/rpc tools/call
    call_res = api.post(
        "/api/mcp/rpc",
        json={
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {
                "name": "web_search_standards",
                "arguments": {"query": "ASCE 7-22 seismic PGA"},
            },
        },
    )
    assert call_res.status_code == 200
    assert call_res.json()["result"]["isError"] is False
