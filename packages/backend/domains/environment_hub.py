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
            res = await self.gee_server.execute(tool_name, {**args, **context})
            clean_data = {k: v for k, v in res.items() if k != "geojson"}
            return ToolResult(status=res.get("status", "success"), data=clean_data)

        # ── 3. Weather & Air Quality ──
        if tool_name in self.weather_server.tool_names:
            res = await self.weather_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        # ── 4. Google Environment (Elevation / Solar) ──
        if tool_name in self.google_env_server.tool_names:
            res = await self.google_env_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        return ToolResult(status="error", error=f"Unknown tool '{tool_name}' in EnvironmentHub")
