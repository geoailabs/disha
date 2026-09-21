"""
Environment Domain Hub for Disha.

Consolidates Earth Observation (Google Earth Engine), climate & weather (Open-Meteo),
Google environmental intelligence (elevation & rooftop solar), and tailpipe emissions.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.protocol import BaseDomainHub, ToolResult
from mcp_servers.emissions_server import EmissionsServer
from mcp_servers.gee_server import GEEServer
from mcp_servers.google_environment_server import GoogleEnvironmentServer
from mcp_servers.weather_server import WeatherServer

logger = logging.getLogger(__name__)


class EnvironmentHub(BaseDomainHub):
    """Domain Hub for Climate, Remote Sensing, Air Quality, Solar & Emissions."""

    name = "environment"
    description = "Earth observation (GEE), climate/weather, solar potential, elevation, and emissions."

    def __init__(self) -> None:
        self.gee_server = GEEServer()
        self.weather_server = WeatherServer()
        self.google_env_server = GoogleEnvironmentServer()
        self.emissions_server = EmissionsServer()

        self.tool_names = (
            self.gee_server.tool_names
            | self.weather_server.tool_names
            | self.google_env_server.tool_names
            | self.emissions_server.tool_names
        )

    def get_declarations(self) -> list[dict[str, Any]]:
        decls = []
        decls.extend(self.gee_server.get_declarations())
        decls.extend(self.weather_server.get_declarations())
        decls.extend(self.google_env_server.get_declarations())
        decls.extend(self.emissions_server.get_declarations())

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

        # ── 1. Emissions Evaluation Report ──
        if tool_name == "estimate_scenario_emissions":
            res = await self.emissions_server.execute(tool_name, {**args, **context})
            report_md = res.get("report") or res.get("summary", "")
            artifact = None
            if res.get("status") == "success" and report_md:
                artifact = {
                    "title": "Scenario Emissions & Air Quality Assessment",
                    "artifact_type": "report",
                    "format": "markdown",
                    "content": report_md,
                }
            return ToolResult(status=res.get("status", "success"), data=res, artifact=artifact)

        # ── 2. GEE Land Cover & NDVI ──
        if tool_name in self.gee_server.tool_names:
            workspace = (
                context.get("_workspace")
                or (context.get("_map_context") or {}).get("workspace")
                or args.get("workspace")
            )
            merged_args = {**args, **context}
            if workspace:
                merged_args["_workspace"] = workspace

            res = await self.gee_server.execute(tool_name, merged_args)
            if "error" in res or res.get("status") == "error":
                return ToolResult(status="error", error=res.get("error", "GEE execution error"), data=res)

            map_action = None
            target_cls = res.get("target_class", "Land Cover")
            place_nm = res.get("place_name")
            display_title = res.get("layer_title") or res.get("layer_name") or (f"{target_cls} - {place_nm}" if place_nm else f"{target_cls} Polygons")
            color = res.get("color", "#C4281B")

            if res.get("geojson_file"):
                map_action = {
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(res["geojson_file"]),
                        "name": display_title,
                        "color": color,
                    },
                }
            elif res.get("geojson"):
                map_action = {
                    "action": "add_geojson",
                    "payload": {
                        "geojson": res["geojson"],
                        "name": display_title,
                        "color": color,
                    },
                }
            elif res.get("tile_url"):
                map_action = {
                    "action": "add_gee_layer",
                    "payload": {
                        "url": res["tile_url"],
                        "dataset": res.get("dataset_id") or res.get("dataset", ""),
                        "vis_params": res.get("vis") or res.get("vis_params", {}),
                        "title": display_title,
                    },
                }

            if "geojson" in res and res.get("polygons_extracted", 0) > 0:
                try:
                    from tools.spatial_registry import spatial_registry
                    spatial_registry.register_or_get(
                        name=display_title,
                        geometry=res["geojson"],
                        source="extract_land_use_polygons",
                        properties={"color": color},
                    )
                except Exception as _re:
                    logger.debug(f"Failed to register in spatial registry: {_re}")

            clean_data = {k: v for k, v in res.items() if k != "geojson"}
            if map_action:
                clean_data["displayed_on_map"] = True

            return ToolResult(
                status=res.get("status", "success"),
                data=clean_data,
                map_action=map_action,
            )

        # ── 3. Weather & Air Quality ──
        if tool_name in self.weather_server.tool_names:
            res = await self.weather_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        # ── 4. Google Environment (Elevation / Solar) ──
        if tool_name in self.google_env_server.tool_names:
            res = await self.google_env_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        return ToolResult(status="error", error=f"Unknown tool '{tool_name}' in EnvironmentHub")
