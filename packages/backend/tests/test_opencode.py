"""
Unit and integration test suite for OpenCode Integration in Disha backend.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket

from llm.opencode.client import OpenCodeClient
from llm.opencode.mcp_server import (
    get_all_tool_definitions,
    execute_disha_tool,
    _ACTION_TOOLS,
)
from llm.opencode.session_manager import OpenCodeSessionManager
from llm.opencode.server_manager import OpenCodeServerManager
from llm.opencode.orchestrator import _consume_opencode_stream, run_opencode_agent


# ── 1. MCP Tool Declarations and Execution Tests ──────────────────────────────

def test_mcp_tool_definitions():
    """Verify that MCP server exports standard tool declarations for all Disha tools."""
    tools = get_all_tool_definitions()
    assert isinstance(tools, list)
    assert len(tools) >= 50  # 24 Map Actions + ~45 Domain Hub tools + interactive tools

    tool_names = {t["name"] for t in tools}
    # Check Action tools
    assert "fly_to" in tool_names
    assert "draw_polygon" in tool_names
    assert "export_map_jpeg" in tool_names
    assert "add_marker" in tool_names
    assert "style_layer" in tool_names

    # Check Domain Hub tools
    assert "osm_search" in tool_names
    assert "gis_buffer" in tool_names
    assert "get_land_cover" in tool_names
    assert "generate_planning_scenarios" in tool_names

    # Check Interactive tools
    assert "ask_question" in tool_names
    assert "create_plot" in tool_names
    assert "create_artifact" in tool_names

    # Verify MCP schema structure
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_mcp_execute_action_tool():
    """Verify executing an action tool returns success and dispatches loopback notification."""
    with patch("llm.opencode.mcp_server._notify_backend_action", new_callable=AsyncMock) as mock_notify:
        res = await execute_disha_tool("fly_to", {"lat": 30.7333, "lng": 76.7794, "zoom": 13})
        assert res["isError"] is False
        assert len(res["content"]) > 0
        content = json.loads(res["content"][0]["text"])
        assert content["status"] == "success"
        mock_notify.assert_called_once_with("fly_to", {"lat": 30.7333, "lng": 76.7794, "zoom": 13})


@pytest.mark.asyncio
async def test_mcp_execute_polygon_with_spatial_metrics():
    """Verify draw_polygon computes spatial metrics and checks spatial registry."""
    coords = [
        [76.77, 30.73],
        [76.78, 30.73],
        [76.78, 30.74],
        [76.77, 30.74],
        [76.77, 30.73],
    ]
    with patch("llm.opencode.mcp_server._notify_backend_action", new_callable=AsyncMock):
        res = await execute_disha_tool("draw_polygon", {
            "coordinates": coords,
            "label": "Sector 17 Boundary",
            "color": "#3b82f6",
        })
        assert res["isError"] is False
        content = json.loads(res["content"][0]["text"])
        assert content["status"] == "success"
        assert "area_km2" in content
        assert "area_hectares" in content
        assert "centroid" in content
        assert "bbox" in content
        assert content["area_km2"] > 0


@pytest.mark.asyncio
async def test_mcp_execute_domain_hub_tool():
    """Verify executing a Domain Hub tool executes via the hub and returns ToolResult JSON."""
    with patch("domains.spatial_hub.SpatialHub.execute", new_callable=AsyncMock) as mock_exec:
        from domains import ToolResult
        mock_exec.return_value = ToolResult(
            status="success",
            data={"buffer_radius": 500, "feature_count": 1},
            map_action={"action": "add_geojson", "payload": {"layer_name": "Buffer Layer"}},
        )

        with patch("llm.opencode.mcp_server._notify_backend_action", new_callable=AsyncMock) as mock_notify:
            res = await execute_disha_tool("gis_buffer", {"layer_name": "Points", "distance_meters": 500})
            assert res["isError"] is False
            content = json.loads(res["content"][0]["text"])
            assert content["buffer_radius"] == 500
            assert content["feature_count"] == 1
            mock_notify.assert_called_once_with("add_geojson", {"layer_name": "Buffer Layer"})


# ── 2. Session Manager Tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_manager_lifecycle():
    """Verify OpenCode session creation, persistence, retrieval, and clearing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = OpenCodeSessionManager()

        with patch.object(OpenCodeClient, "create_session", new_callable=AsyncMock) as mock_create, \
             patch.object(OpenCodeClient, "get_session", new_callable=AsyncMock) as mock_get:

            mock_create.return_value = "session-1234"
            mock_get.return_value = {"id": "session-1234", "title": "Urban Study"}

            # 1. Create session
            sid = await sm.get_or_create_session(conversation_id="conv-1", title="Urban Study", workspace=tmpdir)
            assert sid == "session-1234"
            assert sm.get_active_session_id("conv-1") == "session-1234"

            # 2. Check persistence to .disha/opencode_sessions.json
            cache_file = Path(tmpdir) / ".disha" / "opencode_sessions.json"
            assert cache_file.exists()
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert data.get("conv-1") == "session-1234"

            # 3. Retrieve existing session
            sid2 = await sm.get_or_create_session(conversation_id="conv-1", workspace=tmpdir)
            assert sid2 == "session-1234"
            mock_create.assert_called_once()  # Should not create duplicate

            # 4. Clear session
            sm.clear_session("conv-1", workspace=tmpdir)
            assert sm.get_active_session_id("conv-1") is None
            data_cleared = json.loads(cache_file.read_text(encoding="utf-8"))
            assert "conv-1" not in data_cleared


# ── 3. Server Manager Tests ───────────────────────────────────────────────────

def test_server_manager_config_generation():
    """Verify server manager creates opencode.json with valid MCP configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = OpenCodeServerManager(port=4096, host="127.0.0.1")
        sm.ensure_opencode_config(workspace_path=tmpdir)

        cfg_path = Path(tmpdir) / "opencode.json"
        assert cfg_path.exists()
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

        assert "mcp" in cfg
        assert "disha_tools" in cfg["mcp"]
        assert cfg["mcp"]["disha_tools"]["type"] == "local"
        assert len(cfg["mcp"]["disha_tools"]["command"]) == 2
        assert "mcp_server.py" in cfg["mcp"]["disha_tools"]["command"][1]
        assert cfg["permission"]["bash"] == "allow"


# ── 4. SSE Stream Translation & Orchestrator Tests ────────────────────────────

@pytest.mark.asyncio
async def test_consume_opencode_stream_translation():
    """Verify SSE events are properly translated to Disha WebSocket frame format."""
    mock_ws = AsyncMock(spec=WebSocket)
    client = OpenCodeClient()

    fake_events = [
        {"type": "message.part.delta", "properties": {"sessionID": "s1", "delta": "Analyzing "}},
        {"type": "message.part.delta", "properties": {"sessionID": "s1", "delta": "land use..."}},
        {
            "type": "message.part.updated",
            "properties": {
                "sessionID": "s1",
                "part": {
                    "type": "tool-invocation",
                    "tool": "get_land_cover",
                    "input": {"year": 2024},
                }
            }
        },
        {"type": "session.idle", "properties": {"sessionID": "s1"}},
    ]

    async def fake_stream():
        for ev in fake_events:
            yield ev

    with patch.object(client, "stream_events", side_effect=fake_stream):
        await _consume_opencode_stream(client, session_id="s1", ws=mock_ws)

    sent_frames = [json.loads(call.args[0]) for call in mock_ws.send_text.call_args_list]

    assert len(sent_frames) == 4
    assert sent_frames[0] == {"type": "stream", "content": "Analyzing "}
    assert sent_frames[1] == {"type": "stream", "content": "land use..."}
    assert sent_frames[2] == {"type": "tool_use", "tool": "get_land_cover", "args": {"year": 2024}}
    assert sent_frames[3] == {"type": "end"}


# ── 5. Internal Bridge Endpoints Tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_internal_action_endpoint():
    """Verify /api/chat/internal_action broadcasts MapActions to active websockets."""
    from routers.chat import internal_action, InternalActionRequest, _active_websockets

    mock_ws = AsyncMock(spec=WebSocket)
    _active_websockets.add(mock_ws)

    try:
        req = InternalActionRequest(action="fly_to", payload={"lat": 30.7, "lng": 76.7, "zoom": 14})
        res = await internal_action(req)
        assert res == {"status": "ok"}

        # Verify action was sent to websocket
        assert mock_ws.send_text.called
        sent = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent["type"] == "action"
        assert sent["action"] == "fly_to"
        assert sent["payload"]["lat"] == 30.7
    finally:
        _active_websockets.discard(mock_ws)


@pytest.mark.asyncio
async def test_internal_question_endpoint():
    """Verify /api/chat/internal_question dispatches question and awaits response."""
    from routers.chat import internal_question, InternalQuestionRequest, _active_websockets
    from tools.utility import register_question_response

    mock_ws = AsyncMock(spec=WebSocket)
    _active_websockets.add(mock_ws)

    try:
        async def respond_later():
            await asyncio.sleep(0.05)
            register_question_response(mock_ws, "Option B")

        asyncio.create_task(respond_later())

        req = InternalQuestionRequest(
            question="Which study area?",
            options=["Option A", "Option B"],
            is_multi_select=False,
        )
        res = await internal_question(req)

        assert res["status"] == "success"
        assert res["response"] == "Option B"
    finally:
        _active_websockets.discard(mock_ws)
