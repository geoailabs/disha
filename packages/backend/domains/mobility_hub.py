"""
Mobility Domain Hub for Disha.

Consolidates all transportation network analysis, Dijkstra and freight routing,
GTFS public transit feeds, traffic signal timing, and Origin-Destination travel demand models.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.protocol import BaseDomainHub, ToolResult
from mcp_servers.gtfs_server import GTFSServer
from mcp_servers.its_server import ITSServer
from mcp_servers.network_server import NetworkServer
from mcp_servers.od_server import ODServer

logger = logging.getLogger(__name__)


class MobilityHub(BaseDomainHub):
    """Domain Hub for Transportation, Transit, Networks & Travel Demand."""

    name = "mobility"
    description = "Street networks, routing, GTFS transit, signal optimization, and travel demand."

    def __init__(self) -> None:
        self.network_server = NetworkServer()
        self.gtfs_server = GTFSServer()
        self.its_server = ITSServer()
        self.od_server = ODServer()

        self.tool_names = (
            self.network_server.tool_names
            | self.gtfs_server.tool_names
            | self.its_server.tool_names
            | self.od_server.tool_names
        )

    def get_declarations(self) -> list[dict[str, Any]]:
        decls = []
        decls.extend(self.network_server.get_declarations())
        decls.extend(self.gtfs_server.get_declarations())
        decls.extend(self.its_server.get_declarations())
        decls.extend(self.od_server.get_declarations())

        return [
            {
                "type": "function",
                "function": {
                    "name": d.name,
                    "description": d.description,
                    "parameters": d.parameters,
                },
            }
            for d in decls
        ]

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        context = context or {}

        # ── 1. GTFS Transit Analysis Report ──
        if tool_name == "analyze_gtfs_service":
            res = await self.gtfs_server.execute(tool_name, {**args, **context})
            report_md = res.get("report") or res.get("summary", "")
            artifact = None
            if res.get("status") == "success" and report_md:
                artifact = {
                    "title": f"GTFS Transit Service Analysis – {res.get('feed_name', 'Report')}",
                    "artifact_type": "report",
                    "format": "markdown",
                    "content": report_md,
                }
            return ToolResult(status=res.get("status", "success"), data=res, artifact=artifact)

        # ── 2. Street Network Analysis Report ──
        if tool_name == "analyze_street_network":
            res = await self.network_server.execute(tool_name, {**args, **context})
            report_md = res.get("report") or res.get("summary", "")
            artifact = None
            if res.get("status") == "success" and report_md:
                artifact = {
                    "title": "Street Network & Bottleneck Analysis",
                    "artifact_type": "analysis",
                    "format": "markdown",
                    "content": report_md,
                }
            return ToolResult(status=res.get("status", "success"), data=res, artifact=artifact)

        # ── 3. Routing & Flow Visualizations ──
        if tool_name in self.network_server.tool_names:
            res = await self.network_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        if tool_name in self.gtfs_server.tool_names:
            res = await self.gtfs_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        if tool_name in self.its_server.tool_names:
            res = await self.its_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        if tool_name in self.od_server.tool_names:
            res = await self.od_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        return ToolResult(status="error", error=f"Unknown tool '{tool_name}' in MobilityHub")
