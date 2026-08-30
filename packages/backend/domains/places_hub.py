"""
Places Domain Hub for Disha.

Consolidates commercial Point of Interest (POI) intelligence (Google Places),
and open global building footprints & places (Overture Maps).
"""

from __future__ import annotations

import logging
from typing import Any

from domains.protocol import BaseDomainHub, ToolResult
from mcp_servers.google_places_server import GooglePlacesServer
from mcp_servers.overture_server import OvertureServer

logger = logging.getLogger(__name__)


class PlacesHub(BaseDomainHub):
    """Domain Hub for POIs, Commercial Places & Building Footprints."""

    name = "places"
    description = "Commercial POIs, business amenities, and Overture building footprints."

    def __init__(self) -> None:
        self.google_places_server = GooglePlacesServer()
        self.overture_server = OvertureServer()

        self.tool_names = (
            self.google_places_server.tool_names
            | self.overture_server.tool_names
        )

    def get_declarations(self) -> list[dict[str, Any]]:
        decls = []
        decls.extend(self.google_places_server.get_declarations())
        decls.extend(self.overture_server.get_declarations())

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

        # ── 1. Google Places ──
        if tool_name in self.google_places_server.tool_names:
            res = await self.google_places_server.execute(tool_name, {**args, **context})
            map_action = None

            if tool_name in ("nearby_places", "nearby_places_in_polygon") and "geojson" in res and res.get("count", 0) > 0:
                types_label = ",".join(args.get("included_types") or []) or "places"
                suffix = " (in polygon)" if tool_name == "nearby_places_in_polygon" else ""
                label = f"Google: {types_label}{suffix}"
                map_action = {"action": "add_geojson", "payload": {"geojson": res["geojson"], "name": label}}

                features_summary = []
                for f in res["geojson"].get("features", [])[:50]:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    entry = {
                        "name": props.get("name", "") or props.get("id", ""),
                        "primary_type": props.get("primary_type"),
                        "address": props.get("address"),
                    }
                    if geom.get("type") == "Point":
                        entry["lat"] = geom["coordinates"][1]
                        entry["lng"] = geom["coordinates"][0]
                    features_summary.append(entry)

                trimmed = {
                    "count": res["count"],
                    "displayed_on_map": True,
                    "features": features_summary,
                }
                for k in ("truncated_search", "upstream_count", "search_radius_meters", "centroid"):
                    if k in res:
                        trimmed[k] = res[k]
                return ToolResult(status="success", data=trimmed, map_action=map_action)

            return ToolResult(status=res.get("status", "success"), data=res, map_action=map_action)

        # ── 2. Overture Maps ──
        if tool_name in self.overture_server.tool_names:
            res = await self.overture_server.execute(tool_name, {**args, **context})
            map_action = None

            if "geojson" in res and res.get("count", 0) > 0:
                if tool_name == "overture_places_search":
                    label = f"Overture: {args.get('category') or args.get('query') or 'places'}"
                else:
                    label = "Overture: buildings"
                map_action = {"action": "add_geojson", "payload": {"geojson": res["geojson"], "name": label}}

                features_summary = []
                for f in res["geojson"].get("features", [])[:50]:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    entry = {"name": props.get("name", "") or props.get("id", "")}
                    if "category" in props:
                        entry["category"] = props["category"]
                    if "height" in props and props["height"] is not None:
                        entry["height_m"] = props["height"]
                    if geom.get("type") == "Point":
                        entry["lat"] = geom["coordinates"][1]
                        entry["lng"] = geom["coordinates"][0]
                    features_summary.append(entry)

                trimmed = {
                    "count": res["count"],
                    "displayed_on_map": True,
                    "features": features_summary,
                }
                return ToolResult(status="success", data=trimmed, map_action=map_action)

            return ToolResult(status=res.get("status", "success"), data=res, map_action=map_action)

        return ToolResult(status="error", error=f"Unknown tool '{tool_name}' in PlacesHub")
