"""
Utility Domain Hub for Disha.

Consolidates platform cross-cutting services: web search, geocoding, distance/area measurement,
and artifact CRUD management.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.protocol import BaseDomainHub, ToolResult
from mcp_servers.plot_server import PlotServer
from tools.utility import UtilityServer

logger = logging.getLogger(__name__)


class UtilityHub(BaseDomainHub):
    """Domain Hub for Platform Utilities, Search, Geocoding, Plotting & Artifacts."""

    name = "utility"
    description = "Web search, geocoding, distance/area measurement, plots/charts, and artifact storage."

    def __init__(self, db_path: str | None = None) -> None:
        self.utility_server = UtilityServer(db_path=db_path)
        self.plot_server = PlotServer()
        # Exclude planning digitization tools which live in PlanningHub
        self.tool_names = {
            name for name in self.utility_server.tool_names
            if name not in ("autogeoreference_image", "georeference_active_document", "digitize_image_features")
        } | self.plot_server.tool_names

    def get_declarations(self) -> list[dict[str, Any]]:
        decls = [
            d for d in self.utility_server.get_declarations()
            if d.name in self.tool_names
        ]
        decls.extend(self.plot_server.get_declarations())
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
        if tool_name in self.plot_server.tool_names:
            res = await self.plot_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        res = await self.utility_server.execute(tool_name, {**args, **context})

        map_action = None
        artifact = None

        # ── 1. Distance Measurement Auto-Draw ──
        if tool_name == "measure_distance" and "direct" in res and "points" in res:
            route = res.get("route", {})
            payload: dict[str, Any] = {
                "points": res["points"],
                "direct_km": res["direct"]["distance_km"],
            }
            if route:
                payload["route_coordinates"] = route.get("coordinates", [])
                payload["route_km"] = route.get("distance_km")
                payload["duration_minutes"] = route.get("duration_minutes")
            if res.get("route_error"):
                payload["route_error"] = res["route_error"]

            map_action = {"action": "draw_distance_measurement", "payload": payload}

            summary: dict[str, Any] = {
                "direct_distance_km": res["direct"]["distance_km"],
                "direct_distance_m": res["direct"]["distance_meters"],
            }
            if route:
                summary["route_distance_km"] = route.get("distance_km")
                summary["route_distance_m"] = route.get("distance_meters")
                summary["route_duration_minutes"] = route.get("duration_minutes")
            if res.get("route_error"):
                summary["route_error"] = res["route_error"]
            summary["map_layers_drawn"] = True

            return ToolResult(status="success", data=summary, map_action=map_action)

        # ── 2. Artifact Creation side effects ──
        if tool_name in ("create_artifact", "extract_attribute_table"):
            map_action = {"action": "refresh_artifacts", "payload": {}}

        return ToolResult(status=res.get("status", "success"), data=res, map_action=map_action, artifact=artifact)
