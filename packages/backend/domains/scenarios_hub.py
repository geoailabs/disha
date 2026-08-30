"""
Scenarios Domain Hub for Disha.

Consolidates urban planning alternative scenario generation (Baseline, TOD, Green, Compact)
and multi-criteria scenario evaluation.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.protocol import BaseDomainHub, ToolResult
from mcp_servers.scenario_server import ScenarioServer

logger = logging.getLogger(__name__)


class ScenariosHub(BaseDomainHub):
    """Domain Hub for Policy Alternatives & Multi-Criteria Scenario Comparison."""

    name = "scenarios"
    description = "Scenario alternatives, development typologies, and multi-criteria comparison."

    def __init__(self) -> None:
        self.scenario_server = ScenarioServer()
        self.tool_names = self.scenario_server.tool_names

    def get_declarations(self) -> list[dict[str, Any]]:
        decls = self.scenario_server.get_declarations()
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
        res = await self.scenario_server.execute(tool_name, {**args, **context})

        map_action = None
        artifact = None

        if tool_name == "generate_planning_scenarios" and res.get("status") == "success":
            map_action = {"action": "add_scenarios", "payload": {"scenarios": res.get("scenarios_data", [])}}

        if tool_name == "compare_scenarios" and res.get("status") == "success":
            report_md = res.get("report") or res.get("summary", "")
            if report_md:
                artifact = {
                    "title": "Scenario Comparison Assessment",
                    "artifact_type": "report",
                    "format": "markdown",
                    "content": report_md,
                }

        return ToolResult(status=res.get("status", "success"), data=res, map_action=map_action, artifact=artifact)
