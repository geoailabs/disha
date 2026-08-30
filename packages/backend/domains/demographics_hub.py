"""
Demographics Domain Hub for Disha.

Consolidates population estimation (WorldPop 100m grid), cohort population forecasting,
baseline employment density, and commercial land demand calculations.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.protocol import BaseDomainHub, ToolResult
from mcp_servers.demographics_server import DemographicsServer

logger = logging.getLogger(__name__)


class DemographicsHub(BaseDomainHub):
    """Domain Hub for Socio-Economic Demographics, Population & Jobs."""

    name = "demographics"
    description = "Population estimation, cohort population forecasting, and employment density."

    def __init__(self) -> None:
        self.demographics_server = DemographicsServer()
        self.tool_names = self.demographics_server.tool_names

    def get_declarations(self) -> list[dict[str, Any]]:
        decls = self.demographics_server.get_declarations()
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
        res = await self.demographics_server.execute(tool_name, {**args, **context})

        artifact = None
        # Auto-package population projection report as an Artifact
        if tool_name == "project_population" and res.get("status") == "success":
            report_md = res.get("report", "")
            if report_md:
                place_name = (res.get("place_name") or "").strip()
                title = f"Population Projection – {place_name}" if place_name else "Population Projection"
                artifact = {
                    "title": title,
                    "artifact_type": "report",
                    "format": "markdown",
                    "content": report_md,
                }
                # Return clean summary to LLM so it narrates rather than duplicating the full markdown
                clean_data = {
                    "status": "success",
                    "artifact_saved": True,
                    "artifact_title": title,
                    "baseline_year": res.get("baseline", {}).get("year"),
                    "baseline_population": res.get("baseline", {}).get("population"),
                    "model_type": res.get("model_type"),
                    "growth_rate_pct": round(res.get("growth_rate", 0) * 100, 2),
                    "projections": res.get("projections", []),
                    "land_demand_hectares": res.get("land_demand_hectares"),
                }
                return ToolResult(status="success", data=clean_data, artifact=artifact)

        # Auto-package employment projection report as an Artifact
        if tool_name == "project_employment" and res.get("status") == "success":
            report_md = res.get("report", "")
            if report_md:
                place_name = (res.get("place_name") or "").strip()
                title = f"Employment Projection – {place_name}" if place_name else "Employment Projection"
                artifact = {
                    "title": title,
                    "artifact_type": "report",
                    "format": "markdown",
                    "content": report_md,
                }

        return ToolResult(status=res.get("status", "success"), data=res, artifact=artifact)
