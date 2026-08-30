"""
Planning Domain Hub for Disha.

Consolidates zoning analysis, land use code assignment, setback calculations,
and scanned master plan georeferencing & digitization.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.protocol import BaseDomainHub, ToolResult
from mcp_servers.zoning_server import ZoningServer
from tools.spatial_registry import spatial_registry

logger = logging.getLogger(__name__)


class PlanningHub(BaseDomainHub):
    """Domain Hub for Zoning, Land Use & Master Plan Digitization."""

    name = "planning"
    description = "Zoning analysis, land use assignment, and scanned master plan digitization."

    def __init__(self, utility_server: Any = None) -> None:
        self.zoning_server = ZoningServer()
        self.utility_server = utility_server

        self._planning_tools = {
            "analyze_zones",
            "detect_zone_overlaps",
            "autogeoreference_image",
            "georeference_active_document",
            "digitize_image_features",
        }
        self.tool_names = self._planning_tools

    def get_declarations(self) -> list[dict[str, Any]]:
        decls = []
        decls.extend(self.zoning_server.get_declarations())

        if self.utility_server:
            for d in self.utility_server.get_declarations():
                if d.name in ("autogeoreference_image", "georeference_active_document", "digitize_image_features"):
                    decls.append(d)

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

        # ── 1. Zoning Operations ──
        if tool_name in self.zoning_server.tool_names:
            res = await self.zoning_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        # ── 2. Digitization & Georeferencing Operations ──
        if self.utility_server and tool_name in ("autogeoreference_image", "georeference_active_document", "digitize_image_features"):
            res = await self.utility_server.execute(tool_name, {**args, **context})
            map_action = None
            if tool_name == "digitize_image_features" and "features" in res:
                # Auto register digitized features in spatial registry
                name = args.get("layer_name") or "Digitized Plan"
                geojson = {"type": "FeatureCollection", "features": res["features"]}
                spatial_registry.register_or_get(name=name, geometry=geojson, source="digitize")
                map_action = {"action": "add_geojson", "payload": {"geojson": geojson, "name": name}}
            return ToolResult(status=res.get("status", "success"), data=res, map_action=map_action)

        return ToolResult(status="error", error=f"Unknown tool '{tool_name}' in PlanningHub")
