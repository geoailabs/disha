"""
Spatial Domain Hub for Disha.

Consolidates all spatial analysis, geometric calculations, administrative boundaries
(OSM, DataMeet), raster WMS services, and the Central Spatial & Polygon Registry.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.protocol import BaseDomainHub, ToolResult
from llm.base import ToolDeclaration
from mcp_servers.datameet_server import DatameetServer
from mcp_servers.gis_server import GISServer
from mcp_servers.osm_server import OSMServer
from mcp_servers.wms_server import WMSServer
from tools.spatial_registry import spatial_registry

logger = logging.getLogger(__name__)


class SpatialHub(BaseDomainHub):
    """Domain Hub for Spatial, Geometry, Boundaries & Polygon Management."""

    name = "spatial"
    description = "Spatial geometry, boundaries, GIS operations, and polygon lifecycle management."

    def __init__(self, db_path: str | None = None) -> None:
        self.gis_server = GISServer()
        self.osm_server = OSMServer()
        self.datameet_server = DatameetServer()
        self.wms_server = WMSServer()

        # Dedicated polygon management tool declarations
        self._polygon_declarations = [
            ToolDeclaration(
                name="list_polygons",
                description="List all active study areas, boundaries, and drawn polygons currently registered in the workspace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["user_draw", "ai_draw", "osm_boundary", "datameet", "zoning"],
                            "description": "Optional filter by creation source.",
                        }
                    },
                },
            ),
            ToolDeclaration(
                name="get_polygon",
                description="Retrieve the geometry, centroid, and area metrics of a specific registered polygon by name or ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name or ID of the polygon."}
                    },
                    "required": ["name"],
                },
            ),
            ToolDeclaration(
                name="check_polygon_overlap",
                description="Check if a polygon intersects or overlaps with any existing boundaries or zones in the workspace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of an existing polygon to check overlaps for."},
                        "coordinates": {
                            "type": "array",
                            "description": "Optional raw polygon coordinate ring [[lng, lat], ...] to test.",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                },
            ),
            ToolDeclaration(
                name="calculate_land_budget",
                description="Calculate the total land budget and percentage breakdown across all active zoning parcels and study areas.",
                parameters={"type": "object", "properties": {}},
            ),
        ]

        # Combine all tool names
        self.tool_names = (
            self.gis_server.tool_names
            | {
                "osm_search",
                "osm_boundary",
                "osm_boundary_union",
                "osm_reverse_geocode",
                "osm_fetch_bus_routes",
                "osm_route_overview",
            }
            | self.datameet_server.tool_names
            | self.wms_server.tool_names
            | {decl.name for decl in self._polygon_declarations}
        )

    def get_declarations(self) -> list[dict[str, Any]]:
        decls: list[ToolDeclaration] = []
        decls.extend(self.gis_server.get_declarations())
        for d in self.osm_server.get_declarations():
            if d.name in self.tool_names:
                decls.append(d)
        decls.extend(self.datameet_server.get_declarations())
        decls.extend(self.wms_server.get_declarations())
        decls.extend(self._polygon_declarations)

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

        # ── 1. Dedicated Polygon Tools ──
        if tool_name == "list_polygons":
            polys = spatial_registry.list_polygons(source=args.get("source"))
            return ToolResult(status="success", data={"count": len(polys), "polygons": polys})

        if tool_name == "get_polygon":
            poly = spatial_registry.get_polygon(args.get("name", ""))
            if poly:
                return ToolResult(status="success", data={"status": "found", "polygon": poly.to_dict()})
            return ToolResult(status="error", error=f"Polygon '{args.get('name')}' not found.", data={"status": "not_found"})

        if tool_name == "check_polygon_overlap":
            geom = None
            if "name" in args:
                poly = spatial_registry.get_polygon(args["name"])
                if poly:
                    geom = poly.geometry
            elif "coordinates" in args:
                coords = args["coordinates"]
                if len(coords) >= 3:
                    ring = list(coords)
                    if ring[0] != ring[-1]:
                        ring.append(ring[0])
                    geom = {"type": "Polygon", "coordinates": [ring]}

            if not geom:
                return ToolResult(status="error", error="Provide a valid polygon name or coordinate ring to check overlaps.")

            overlaps = spatial_registry.check_overlap(geom)
            return ToolResult(status="success", data={"overlap_count": len(overlaps), "overlaps": overlaps})

        if tool_name == "calculate_land_budget":
            budget = spatial_registry.calculate_land_budget()
            return ToolResult(status="success", data=budget)

        # ── 2. OSM Boundary with Deduplication & Spatial Registry ──
        if tool_name == "osm_boundary":
            res = await self.osm_server.execute(tool_name, {**args, **context})
            if res.get("status") == "error":
                return ToolResult(status="error", error=res.get("error", "Boundary lookup failed"), data=res)

            geojson = res.get("geojson")
            name = args.get("name") or res.get("name") or "Boundary"
            label = f"{name} boundary"

            feats = geojson.get("features", []) if geojson else []
            geom = feats[0].get("geometry") if feats else None

            if geom:
                reg_res = spatial_registry.register_or_get(
                    name=label,
                    geometry=geom,
                    source="osm_boundary",
                    properties={"admin_level": args.get("admin_level"), "country_code": args.get("country_code")},
                )
                entry = reg_res["polygon"]

                summary = {
                    "name": entry["name"],
                    "displayed_on_map": True,
                    "layer_name": label,
                    "area_km2": entry["area_km2"],
                    "area_hectares": entry["area_hectares"],
                    "centroid": entry["centroid"],
                    "bbox": entry["bbox"],
                }
                return ToolResult(
                    status="success",
                    data=summary,
                    map_action={"action": "add_geojson", "payload": {"geojson": geojson, "name": label}},
                )

            return ToolResult(status="success", data=res)

        # ── 3. OSM Boundary Union ──
        if tool_name == "osm_boundary_union":
            res = await self.osm_server.execute(tool_name, {**args, **context})
            if "geojson" in res:
                name = args.get("label") or "Merged boundary"
                spatial_registry.register_or_get(name=name, geometry=res["geojson"], source="osm_boundary")
                summary = {k: v for k, v in res.items() if k != "geojson"}
                summary["displayed_on_map"] = True
                return ToolResult(
                    status="success",
                    data=summary,
                    map_action={"action": "add_geojson", "payload": {"geojson": res["geojson"], "name": name}},
                )
            return ToolResult(status="success", data=res)

        # ── 4. OSM Search ──
        if tool_name == "osm_search":
            res = await self.osm_server.execute(tool_name, {**args, **context})
            map_action = None
            if "geojson" in res and res.get("count", 0) > 0:
                label = f"{args.get('feature_value', 'features')} ({args.get('feature_type', '')})"
                map_action = {"action": "add_geojson", "payload": {"geojson": res["geojson"], "name": label}}
                features_summary = []
                for f in res["geojson"].get("features", [])[:50]:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    entry = {"name": props.get("name", "")}
                    if geom.get("type") == "Point":
                        entry["lat"] = geom["coordinates"][1]
                        entry["lng"] = geom["coordinates"][0]
                    features_summary.append(entry)
                summary = {
                    "count": res["count"],
                    "displayed_on_map": True,
                    "features": features_summary,
                }
                return ToolResult(status="success", data=summary, map_action=map_action)
            return ToolResult(status="success", data=res)

        # ── 5. OSM Transit / Bus Routes ──
        if tool_name == "osm_fetch_bus_routes":
            res = await self.osm_server.execute(tool_name, {**args, **context})
            map_action = None
            if "geojson" in res:
                label = res.get("name") or "Transit Routes"
                map_action = {"action": "add_geojson", "payload": {"geojson": res["geojson"], "name": label}}
                summary = {
                    "name": label,
                    "count": res.get("count", 0),
                    "displayed_on_map": True,
                    "layer_name": label,
                }
                return ToolResult(status="success", data=summary, map_action=map_action)
            return ToolResult(status="success", data=res)

        # ── 6. OSM Route Overview ──
        if tool_name == "osm_route_overview":
            res = await self.osm_server.execute(tool_name, {**args, **context})
            map_action = None
            if "geometry" in res:
                label = args.get("title") or f"Route ({res.get('distance_km', '?')} km)"
                fc = {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": res["geometry"],
                            "properties": {
                                "name": label,
                                "distance_km": res.get("distance_km"),
                                "duration_minutes": res.get("duration_minutes"),
                                "mode": args.get("mode", "driving"),
                            },
                        }
                    ],
                }
                map_action = {
                    "action": "add_geojson",
                    "payload": {
                        "geojson": fc,
                        "name": label,
                        "color": args.get("color") or "#2563eb",
                    },
                }
                summary = {
                    "distance_km": res.get("distance_km"),
                    "duration_minutes": res.get("duration_minutes"),
                    "displayed_on_map": True,
                    "layer_name": label,
                }
                return ToolResult(status="success", data=summary, map_action=map_action)
            return ToolResult(status="success", data=res)

        # ── 7. DataMeet Boundaries ──
        if tool_name == "import_datameet_boundary":
            res = await self.datameet_server.execute(tool_name, {**args, **context})
            if "geojson" in res:
                name = args.get("name") or "DataMeet boundary"
                spatial_registry.register_or_get(name=name, geometry=res["geojson"], source="datameet")
                summary = {k: v for k, v in res.items() if k != "geojson"}
                summary["displayed_on_map"] = True
                return ToolResult(
                    status="success",
                    data=summary,
                    map_action={"action": "add_geojson", "payload": {"geojson": res["geojson"], "name": name}},
                )
            return ToolResult(status="success", data=res)

        # ── 8. GIS Server Operations ──
        if tool_name in self.gis_server.tool_names:
            res = await self.gis_server.execute(tool_name, {**args, **context})
            map_action = None

            if "geojson" in res:
                if tool_name in ("gis_buffer", "gis_convex_hull", "gis_union"):
                    label = {
                        "gis_buffer": f"Buffer ({args.get('radius_meters', '?')}m)",
                        "gis_convex_hull": "Convex Hull",
                        "gis_union": "Union",
                    }[tool_name]
                    map_action = {
                        "action": "add_geojson",
                        "payload": {
                            "geojson": {"type": "FeatureCollection", "features": [res["geojson"]]},
                            "name": label,
                        },
                    }
                elif tool_name in ("gis_intersection", "gis_difference", "gis_clip", "gis_dissolve", "gis_spatial_join"):
                    gj = res["geojson"]
                    fc = gj if gj.get("type") == "FeatureCollection" else {"type": "FeatureCollection", "features": [gj]}
                    label = {
                        "gis_intersection": "Intersection",
                        "gis_difference": "Difference",
                        "gis_clip": "Clipped",
                        "gis_dissolve": "Dissolved",
                        "gis_spatial_join": "Spatial join",
                    }[tool_name]
                    map_action = {"action": "add_geojson", "payload": {"geojson": fc, "name": label}}
                    collapsed = {"displayed_on_map": True, "layer_name": label}
                    for k in ("area", "kept", "group_count", "points", "joined", "intersects", "empty", "message"):
                        if k in res:
                            collapsed[k] = res[k]
                    return ToolResult(status="success", data=collapsed, map_action=map_action)
                else:
                    layer_name = args.get("output_layer_name") or f"GIS {tool_name.replace('gis_', '').title()}"
                    map_action = {"action": "add_geojson", "payload": {"geojson": res["geojson"], "name": layer_name}}

            return ToolResult(status="success" if res.get("status") != "error" else "error", data=res, map_action=map_action)

        # ── 9. Fallback ──
        if tool_name in self.datameet_server.tool_names:
            res = await self.datameet_server.execute(tool_name, {**args, **context})
            return ToolResult(status="success", data=res)

        if tool_name in self.wms_server.tool_names:
            res = await self.wms_server.execute(tool_name, {**args, **context})
            return ToolResult(status="success", data=res)

        return ToolResult(status="error", error=f"Unknown tool '{tool_name}' in SpatialHub")
