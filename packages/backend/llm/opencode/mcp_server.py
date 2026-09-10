"""
MCP (Model Context Protocol) Server for Disha Tools.

Exposes all Disha capabilities to OpenCode via standard JSON-RPC 2.0 stdio protocol:
1. 24 Map Action Tools (fly_to, fit_bounds, add_marker, draw_polygon, style_layer, export_map_jpeg, etc.)
2. 7+1 Domain Hubs (Spatial, Mobility, Environment, Planning, Demographics, Places, Scenarios, Utility)
3. Interactive Tools (ask_question, create_plot, create_artifact, edit_artifact)
4. Google Earth Engine (GEE) Analytics
5. Central Spatial & Polygon Registry integration with IoU deduplication and geodesic math
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx

# Ensure packages/backend is on PYTHONPATH
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from domains import (
    SpatialHub,
    MobilityHub,
    EnvironmentHub,
    PlanningHub,
    DemographicsHub,
    PlacesHub,
    ScenariosHub,
    UtilityHub,
    ToolResult,
)
from tools.spatial_registry import spatial_registry
from tools.artifact_store import save_artifact
from database import DB_PATH

logger = logging.getLogger("disha.mcp_server")

# Backend internal bridge port
_BACKEND_PORT = int(os.environ.get("DISHA_BACKEND_PORT", "8765"))
_BACKEND_URL = f"http://127.0.0.1:{_BACKEND_PORT}"

# Instantiate all 8 Domain Hubs
_hubs = {
    "spatial": SpatialHub(),
    "mobility": MobilityHub(),
    "environment": EnvironmentHub(),
    "planning": PlanningHub(),
    "demographics": DemographicsHub(),
    "places": PlacesHub(),
    "scenarios": ScenariosHub(),
    "utility": UtilityHub(db_path=str(DB_PATH)),
}

# The 24 Map Action tools
_ACTION_TOOLS = {
    "fly_to", "fit_bounds", "add_marker", "add_markers", "clear_markers",
    "draw_line", "draw_polygon", "draw_circle", "add_geojson", "add_geojson_file",
    "highlight_features", "set_layer_style", "style_layer", "toggle_layer", "remove_layer",
    "save_bookmark", "go_to_bookmark", "export_region_clip", "export_map_png", "export_map_jpeg", "export_map_pdf",
    "switch_basemap", "add_gee_layer", "add_raster_overlay",
}


async def _notify_backend_action(action: str, payload: dict[str, Any]) -> None:
    """Send MapAction to backend WebSocket router over internal loopback endpoint."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                f"{_BACKEND_URL}/api/chat/internal_action",
                json={"action": action, "payload": payload},
            )
    except Exception as e:
        logger.debug(f"Action dispatch to backend internal endpoint skipped/failed: {e}")


async def _ask_backend_question(question: str, options: list[str], is_multi_select: bool = False) -> Any:
    """Send interactive question to backend and await user's answer from WebSocket."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{_BACKEND_URL}/api/chat/internal_question",
                json={"question": question, "options": options, "is_multi_select": is_multi_select},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response")
    except Exception as e:
        logger.warning(f"Failed to ask question via backend bridge: {e}")
    return None


def get_all_tool_definitions() -> list[dict[str, Any]]:
    """Return all tool declarations formatted as standard MCP tool objects."""
    tools: list[dict[str, Any]] = []

    # 1. Action tools
    action_defs = [
        ("fly_to", "Fly map viewport to coordinates (lat, lng, zoom, optional pitch/bearing)", {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude in decimal degrees (EPSG:4326)"},
                "lng": {"type": "number", "description": "Longitude in decimal degrees (EPSG:4326)"},
                "zoom": {"type": "number", "description": "Map zoom level (0-22)"},
                "pitch": {"type": "number", "description": "Camera pitch angle in degrees (0-60)"},
                "bearing": {"type": "number", "description": "Camera bearing angle in degrees (0-360)"},
            },
            "required": ["lat", "lng"],
        }),
        ("fit_bounds", "Fit map camera to a geographic bounding box [west, south, east, north]", {
            "type": "object",
            "properties": {
                "bounds": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[west, south, east, north] bounding box in EPSG:4326 lng/lat coordinates",
                },
                "padding": {"type": "number", "description": "Screen pixel padding around bounds"},
            },
            "required": ["bounds"],
        }),
        ("add_marker", "Place a single pin marker on the map at the given location", {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lng": {"type": "number", "description": "Longitude"},
                "label": {"type": "string", "description": "Marker label or title"},
                "color": {"type": "string", "description": "Marker hex color (e.g. '#2563eb')"},
                "description": {"type": "string", "description": "Optional description for marker popup"},
            },
            "required": ["lat", "lng"],
        }),
        ("add_markers", "Place multiple pin markers on the map at once", {
            "type": "object",
            "properties": {
                "markers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lng": {"type": "number"},
                            "label": {"type": "string"},
                            "color": {"type": "string"},
                        },
                        "required": ["lat", "lng"],
                    },
                    "description": "List of marker objects with lat, lng, and optional label/color",
                }
            },
            "required": ["markers"],
        }),
        ("clear_markers", "Remove all AI pin markers from the map canvas", {
            "type": "object",
            "properties": {},
        }),
        ("draw_line", "Draw a polyline path on the map canvas", {
            "type": "object",
            "properties": {
                "coordinates": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "List of [lng, lat] coordinate pairs",
                },
                "label": {"type": "string", "description": "Label for the drawn line layer"},
                "color": {"type": "string", "description": "Line stroke color hex"},
                "width": {"type": "number", "description": "Line width in pixels"},
            },
            "required": ["coordinates"],
        }),
        ("draw_polygon", "Draw a polygon study area on the map canvas", {
            "type": "object",
            "properties": {
                "coordinates": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "List of [lng, lat] vertex pairs forming the closed boundary ring",
                },
                "label": {"type": "string", "description": "Label for the drawn polygon layer"},
                "color": {"type": "string", "description": "Fill color hex"},
            },
            "required": ["coordinates"],
        }),
        ("draw_circle", "Draw a circular buffer area on the map canvas", {
            "type": "object",
            "properties": {
                "center": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[lng, lat] center coordinates",
                },
                "radius_meters": {"type": "number", "description": "Circle radius in meters"},
                "label": {"type": "string", "description": "Layer label"},
                "color": {"type": "string", "description": "Fill color hex"},
            },
            "required": ["center", "radius_meters"],
        }),
        ("add_geojson", "Render a GeoJSON Feature or FeatureCollection as a styled layer on the map", {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Layer name"},
                "data": {"type": "object", "description": "GeoJSON Feature or FeatureCollection"},
                "color": {"type": "string", "description": "Optional default hex color"},
            },
            "required": ["name", "data"],
        }),
        ("add_geojson_file", "Load a local GeoJSON file as a map layer from workspace disk path", {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute or workspace-relative path to GeoJSON file"},
                "layer_name": {"type": "string", "description": "Name for the loaded layer"},
            },
            "required": ["file_path"],
        }),
        ("highlight_features", "Visually highlight specific features or an entire layer on the map", {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string", "description": "Target layer name"},
                "feature_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of feature IDs"},
            },
            "required": ["layer_name"],
        }),
        ("style_layer", "Apply data-driven symbology styling (categorized, graduated, or labels) to a map layer", {
            "type": "object",
            "properties": {
                "layer_id": {"type": "string", "description": "Layer ID or name"},
                "mode": {"type": "string", "enum": ["categorized", "graduated", "single"], "description": "Symbology mode"},
                "property": {"type": "string", "description": "Feature property name to style by"},
                "color_ramp": {"type": "string", "description": "Color ramp name (e.g. 'Viridis', 'Blues', 'YlOrRd')"},
                "classes": {"type": "integer", "description": "Number of class breaks for graduated mode (2-9)"},
                "label_property": {"type": "string", "description": "Optional property to display as on-map text labels"},
            },
            "required": ["layer_id"],
        }),
        ("toggle_layer", "Toggle visibility of a map layer on or off", {
            "type": "object",
            "properties": {
                "layer_id": {"type": "string", "description": "Layer ID or name"},
                "visible": {"type": "boolean", "description": "True to show, false to hide"},
            },
            "required": ["layer_id"],
        }),
        ("remove_layer", "Remove a layer completely from the map canvas", {
            "type": "object",
            "properties": {
                "layer_id": {"type": "string", "description": "Layer ID or name to remove"},
            },
            "required": ["layer_id"],
        }),
        ("save_bookmark", "Save current or specified map extent as a named bookmark", {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the bookmark"},
            },
            "required": ["name"],
        }),
        ("go_to_bookmark", "Fly camera viewport to a previously saved named bookmark", {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the bookmark"},
            },
            "required": ["name"],
        }),
        ("export_map_png", "Capture a publication-ready PNG map snapshot", {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title block for the figure"},
                "save_to_artifacts": {"type": "boolean", "description": "Save to artifact catalog"},
                "layers_to_show": {"type": "array", "items": {"type": "string"}, "description": "Layer names to display exclusively in this figure"},
                "layer_name": {"type": "string", "description": "Single layer name to isolate"},
                "bbox": {"type": "array", "items": {"type": "number"}, "description": "[west, south, east, north] bounding box to frame"},
            },
        }),
        ("export_map_jpeg", "Capture a publication-ready JPEG map snapshot", {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title block for the figure"},
                "save_to_artifacts": {"type": "boolean", "description": "Save to artifact catalog"},
                "layers_to_show": {"type": "array", "items": {"type": "string"}, "description": "Layer names to display exclusively in this figure"},
                "layer_name": {"type": "string", "description": "Single layer name to isolate"},
                "bbox": {"type": "array", "items": {"type": "number"}, "description": "[west, south, east, north] bounding box to frame"},
            },
        }),
        ("export_map_pdf", "Capture a publication-ready landscape PDF map snapshot", {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title block for the figure"},
                "save_to_artifacts": {"type": "boolean", "description": "Save to artifact catalog"},
                "layers_to_show": {"type": "array", "items": {"type": "string"}, "description": "Layer names to display exclusively in this figure"},
                "layer_name": {"type": "string", "description": "Single layer name to isolate"},
                "bbox": {"type": "array", "items": {"type": "number"}, "description": "[west, south, east, north] bounding box to frame"},
            },
        }),
        ("switch_basemap", "Switch the background raster basemap", {
            "type": "object",
            "properties": {
                "basemap": {
                    "type": "string",
                    "enum": ["street", "satellite", "dark", "light", "terrain", "topo", "humanitarian"],
                    "description": "Basemap name",
                }
            },
            "required": ["basemap"],
        }),
        ("ask_question", "Ask the user an interactive question to clarify intent or select from options", {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question prompt to display to user"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "List of selectable options"},
                "is_multi_select": {"type": "boolean", "description": "Allow multiple options"},
            },
            "required": ["question", "options"],
        }),
    ]

    for name, desc, params in action_defs:
        tools.append({
            "name": name,
            "description": desc,
            "inputSchema": params,
        })

    # 2. Domain Hub tools
    for hub in _hubs.values():
        for decl in hub.get_declarations():
            tools.append({
                "name": decl["function"]["name"],
                "description": decl["function"]["description"],
                "inputSchema": decl["function"]["parameters"],
            })

    return tools


async def execute_disha_tool(
    name: str,
    args: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute a Disha tool and return an MCP-compliant result dictionary.
    Handles side effects (MapActions, artifact storage, question cards, spatial registry sync).
    """
    context = context or {}
    map_context = context.get("_map_context")
    action_cb = context.get("_action_callback")

    # Helper to send actions either directly or via HTTP bridge
    async def _emit_action(act_name: str, act_payload: dict[str, Any]) -> None:
        if action_cb:
            await action_cb(act_name, act_payload)
        else:
            await _notify_backend_action(act_name, act_payload)

    # 1. Real-time Spatial Registry sync
    if map_context and "layers" in map_context:
        spatial_registry.sync_from_map_layers(map_context.get("layers"))

    # 2. Interactive ask_question
    if name == "ask_question":
        question = args.get("question", "")
        options = args.get("options", [])
        is_multi_select = bool(args.get("is_multi_select", False))
        ans = await _ask_backend_question(question, options, is_multi_select)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"status": "success", "selected_response": ans or "Skipped"}),
            }],
            "isError": False,
        }

    # 3. Action Tools dispatch
    if name in _ACTION_TOOLS:
        if name == "draw_polygon":
            coords = args.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 3:
                ring = list(coords)
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                geom = {"type": "Polygon", "coordinates": [ring]}
                label = args.get("label") or "Drawn Polygon"
                reg_res = spatial_registry.register_or_get(
                    name=label,
                    geometry=geom,
                    source="ai_draw",
                    properties={"color": args.get("color")},
                )
                poly_data = reg_res.get("polygon", {})
                if reg_res.get("is_duplicate"):
                    await _emit_action("highlight_features", {"layer_name": reg_res["layer_name"]})
                    return {
                        "content": [{
                            "type": "text",
                            "text": json.dumps({
                                "status": "success",
                                "reused_existing": True,
                                "layer_name": reg_res["layer_name"],
                                "message": f"Polygon '{label}' matches existing layer '{reg_res['layer_name']}' ({reg_res['match_reason']}). Focused existing layer.",
                                "area_km2": poly_data.get("area_km2"),
                                "area_hectares": poly_data.get("area_hectares"),
                                "centroid": poly_data.get("centroid"),
                                "bbox": poly_data.get("bbox"),
                            })
                        }],
                        "isError": False,
                    }
                else:
                    await _emit_action(name, args)
                    return {
                        "content": [{
                            "type": "text",
                            "text": json.dumps({
                                "status": "success",
                                "message": f"Drawn polygon '{label}' on map canvas.",
                                "area_km2": poly_data.get("area_km2"),
                                "area_hectares": poly_data.get("area_hectares"),
                                "centroid": poly_data.get("centroid"),
                                "bbox": poly_data.get("bbox"),
                            })
                        }],
                        "isError": False,
                    }

        if name in ("export_map_png", "export_map_jpeg", "export_map_pdf"):
            save_to_art = args.get("save_to_artifacts", True)
            title = args.get("title") or "Map Export"
            fmt = "jpg" if name == "export_map_jpeg" else ("png" if name == "export_map_png" else "pdf")
            workspace = map_context.get("workspace") if map_context else None

            if save_to_art:
                art_row = save_artifact(
                    title=title,
                    artifact_type="sketch",
                    format=fmt,
                    content="",
                    workspace=workspace,
                )
                art_id = art_row["id"]
                file_path_rel = art_row.get("file_path") or f"artifacts_store/{art_id}.{fmt}"
                args_with_id = {**args, "title": title, "artifact_id": art_id, "save_to_artifacts": True}

                await _emit_action(name, args_with_id)
                await _emit_action("refresh_artifacts", {"id": art_id})

                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "status": "success",
                            "artifact_id": art_id,
                            "file_path": file_path_rel,
                            "title": title,
                            "format": fmt,
                            "message": f"Exported map figure '{title}' (Artifact ID: {art_id}, Path: {file_path_rel}). Reference in markdown documents using: ![{title}]({file_path_rel})",
                        })
                    }],
                    "isError": False,
                }
            else:
                await _emit_action(name, args)
                return {
                    "content": [{"type": "text", "text": json.dumps({"status": "success", "message": f"'{name}' triggered on map."})}],
                    "isError": False,
                }

        await _emit_action(name, args)
        return {
            "content": [{"type": "text", "text": json.dumps({"status": "success", "message": f"'{name}' executed on map."})}],
            "isError": False,
        }

    # 4. Domain Hub tools execution
    target_hub = next((h for h in _hubs.values() if name in h.tool_names), None)
    if target_hub:
        try:
            result: ToolResult = await target_hub.execute(name, args, context)
        except Exception as exc:
            logger.exception(f"Tool '{name}' failed in hub '{target_hub.name}'")
            return {
                "content": [{"type": "text", "text": json.dumps({"status": "error", "error": str(exc)})}],
                "isError": True,
            }

        if result.map_action:
            await _emit_action(result.map_action["action"], result.map_action.get("payload", {}))

        if result.artifact:
            try:
                save_artifact(
                    title=result.artifact.get("title", "Report"),
                    artifact_type=result.artifact.get("artifact_type", "report"),
                    format=result.artifact.get("format", "markdown"),
                    content=result.artifact.get("content", ""),
                    workspace=map_context.get("workspace") if map_context else None,
                )
                await _emit_action("refresh_artifacts", {})
            except Exception as _ae:
                logger.warning(f"Failed to auto-save artifact for tool '{name}': {_ae}")

        if name in ("create_artifact", "edit_artifact", "create_plot", "save_artifact"):
            try:
                res_dict = json.loads(result.to_json())
                created_id = res_dict.get("id") or (res_dict.get("artifact", {}).get("id") if isinstance(res_dict.get("artifact"), dict) else None)
                await _emit_action("refresh_artifacts", {"id": created_id} if created_id else {})
            except Exception:
                await _emit_action("refresh_artifacts", {})

        return {
            "content": [{"type": "text", "text": result.to_json()}],
            "isError": result.status == "error",
        }

    return {
        "content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {name}"})}],
        "isError": True,
    }


def run_stdio_mcp_server() -> None:
    """Run line-delimited JSON-RPC 2.0 stdio loop for OpenCode."""
    tools = get_all_tool_definitions()

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception:
            continue

        msg_id = req.get("id")
        method = req.get("method")

        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "disha-tools", "version": "1.0.0"},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": tools},
            }
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            exec_res = loop.run_until_complete(execute_disha_tool(name, args))
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": exec_res,
            }
        else:
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_mcp_server()
