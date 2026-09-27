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
            map_action = None
            if res.get("status") == "success" or "output_layer" in res or "output_file" in res or "geojson" in res:
                out_path = res.get("output_layer") or res.get("output_file")
                title = args.get("title") or tool_name.replace("_", " ").title()
                if out_path:
                    map_action = {
                        "action": "add_geojson_file",
                        "payload": {
                            "path": out_path,
                            "name": title,
                            "color": args.get("color") or "#8a3324",
                        },
                    }
                elif "geojson" in res:
                    map_action = {
                        "action": "add_geojson",
                        "payload": {
                            "geojson": res["geojson"],
                            "name": title,
                            "color": args.get("color") or "#8a3324",
                        },
                    }
            clean_data = {k: v for k, v in res.items() if k != "geojson"}
            return ToolResult(status=res.get("status", "success"), data=clean_data, map_action=map_action)

        if tool_name in self.gtfs_server.tool_names:
            pass_args = dict(args)
            if not pass_args.get("workspace") and context.get("_workspace"):
                pass_args["workspace"] = context["_workspace"]
            res = await self.gtfs_server.execute(tool_name, {**pass_args, **context})
            map_action = None
            send_act_fn = context.get("send_action")
            ws = context.get("_ws")

            async def _dispatch_act(act: str, payload: dict):
                if send_act_fn:
                    await send_act_fn(act, payload)
                elif ws:
                    from tools.action_utils import send_action
                    await send_action(ws, act, payload)

            if tool_name == "import_gtfs_feed" and res.get("status") == "success":
                # 1. Add routes layer (line strings)
                if res.get("routes_file"):
                    await _dispatch_act("add_geojson_file", {
                        "path": res["routes_file"],
                        "name": res.get("routes_layer_name", "Transit Routes"),
                        "color": "#e11d48",
                    })
                # 2. Add stops layer (points)
                if res.get("stops_file"):
                    await _dispatch_act("add_geojson_file", {
                        "path": res["stops_file"],
                        "name": res.get("stops_layer_name", "Transit Stops"),
                        "color": "#2563eb",
                    })
                # 3. Fit bounds to transit network extent
                if res.get("bbox"):
                    b = res["bbox"]
                    await _dispatch_act("fit_bounds", {
                        "west": b[0], "south": b[1], "east": b[2], "north": b[3],
                    })

                primary_path = res.get("routes_file") or res.get("stops_file")
                primary_name = res.get("routes_layer_name") if res.get("routes_file") else res.get("stops_layer_name")
                if primary_path:
                    map_action = {
                        "action": "add_geojson_file",
                        "payload": {
                            "path": primary_path,
                            "name": primary_name or "Transit Network",
                            "color": "#e11d48" if res.get("routes_file") else "#2563eb",
                        },
                    }

            elif tool_name == "analyze_transit_catchment" or "output_file" in res or "file_path" in res:
                out_path = res.get("output_file") or res.get("file_path")
                if out_path:
                    map_action = {
                        "action": "add_geojson_file",
                        "payload": {
                            "path": out_path,
                            "name": res.get("output_layer") or res.get("layer_name") or args.get("layer_name") or "Transit Catchment",
                            "color": args.get("color") or "#3b82f6",
                        },
                    }

            elif "geojson" in res:
                map_action = {
                    "action": "add_geojson",
                    "payload": {
                        "geojson": res["geojson"],
                        "name": args.get("title") or "Transit Catchment",
                        "color": args.get("color") or "#3b82f6",
                    },
                }

            clean_data = {k: v for k, v in res.items() if k != "geojson"}
            return ToolResult(status=res.get("status", "success"), data=clean_data, map_action=map_action)

        if tool_name in self.its_server.tool_names:
            res = await self.its_server.execute(tool_name, {**args, **context})
            return ToolResult(status=res.get("status", "success"), data=res)

        if tool_name in self.od_server.tool_names:
            res = await self.od_server.execute(tool_name, {**args, **context})
            map_action = None
            if "geojson" in res:
                map_action = {
                    "action": "add_geojson",
                    "payload": {
                        "geojson": res["geojson"],
                        "name": args.get("title") or "OD Desire Lines",
                        "color": args.get("color") or "#10b981",
                    },
                }
            clean_data = {k: v for k, v in res.items() if k != "geojson"}
            return ToolResult(status=res.get("status", "success"), data=clean_data, map_action=map_action)

        return ToolResult(status="error", error=f"Unknown tool '{tool_name}' in MobilityHub")
