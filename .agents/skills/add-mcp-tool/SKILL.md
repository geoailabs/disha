---
name: add-mcp-tool
description: Use when adding a new backend tool the AI agent can call (OSM query, GIS operation, weather lookup, demographic stat, polygon query, etc.). Encodes the procedure across the Domain Hubs and the in-app chat router.
---

# Add MCP / Domain Tool

A "tool" is a function the LLM can call during a chat. In Disha, backend tools are organized into **7+1 Domain Hubs** in `packages/backend/domains/` and communicate via the structured `ToolResult` protocol.

## Three categories of tools

| Category | Where it lives | Files to touch |
|---|---|---|
| **Domain Hub tool** (a domain operation: `osm_search`, `gis_buffer`, `get_weather`, `list_polygons`) | A Domain Hub in `packages/backend/domains/*.py` | One domain hub file. Auto-registered. |
| **Action tool** (a map operation the frontend executes: `fly_to`, `add_geojson`, `draw_line`) | The action contract crossing backend → WebSocket → `MapView.tsx` | **Use the [[add-map-action]] skill instead.** |
| **Cross-cutting utility tool** (`web_search`, `geocode`, `measure_distance`, `create_artifact`) | `UtilityHub` in `packages/backend/domains/utility_hub.py` | `utility_hub.py` / `tools/utility.py`. |

## The 8 Domain Hubs

| If the tool relates to… | Use Domain Hub | File |
|---|---|---|
| Spatial geometry, boundaries, GIS operations, polygon registry & land budgets | `SpatialHub` | `domains/spatial_hub.py` |
| Road networks, Dijkstra/freight routing, GTFS transit, ITS signals, OD flows | `MobilityHub` | `domains/mobility_hub.py` |
| GEE satellite LULC/NDVI, weather, air quality, solar/elevation, emissions | `EnvironmentHub` | `domains/environment_hub.py` |
| Zoning compliance, document georeferencing, image feature digitization | `PlanningHub` | `domains/planning_hub.py` |
| WorldPop population, cohort demographic forecasting, employment | `DemographicsHub` | `domains/demographics_hub.py` |
| Google Places search & Overture 3D buildings | `PlacesHub` | `domains/places_hub.py` |
| Planning scenario generation & MCDA alternative scoring | `ScenariosHub` | `domains/scenarios_hub.py` |
| Web search, geocoding, distance/area measurement, artifact persistence | `UtilityHub` | `domains/utility_hub.py` |

---

## Procedure: Adding a Tool to a Domain Hub

### 1. Add Tool Declaration & Implementation in the Target Hub

In the chosen Hub file (e.g. `packages/backend/domains/spatial_hub.py`):

1. Add the tool name to `self.tool_names` in `__init__()`.
2. Add a `ToolDeclaration` or include it in `get_declarations()`.
3. In `async def execute(self, tool_name: str, args: dict, context: dict | None = None) -> ToolResult:`, add the execution branch returning a `ToolResult`:

```python
from domains.protocol import ToolResult

if tool_name == "my_new_tool":
    res = await self._compute_something(args)
    
    # Declarative UI and Artifact side-effects
    map_action = None
    if "geojson" in res:
        map_action = {"action": "add_geojson", "payload": {"geojson": res["geojson"], "name": args.get("name", "Layer")}}
        
    return ToolResult(
        status="success",
        data={"count": len(res.get("items", [])), "summary": res.get("summary")},
        map_action=map_action,
        artifact=None, # Or {"title": "Report", "content": markdown_str, "artifact_type": "report"}
    )
```

### 2. Auto-Registration

All hubs in `packages/backend/domains/` are automatically instantiated in `packages/backend/routers/chat.py:_hubs` and their tools are flattened into the LLM function list by `_build_tools()`.

**No changes to `chat.py` are required.** The agent loop automatically receives the tool, calls the hub, sends `ToolResult.map_action` over WebSocket if present, and auto-saves `ToolResult.artifact` if present.

### 3. Tell the Model the Tool Exists

Add the tool name to the appropriate section in `SYSTEM_PROMPT` in `packages/backend/routers/chat.py` so the model knows when to choose it.

### 4. Verify

Run the backend test suite:
```bash
cd packages/backend
.buildenv/bin/pytest tests/
```
