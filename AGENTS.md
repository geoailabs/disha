# AGENTS.md

Orientation for AI coding assistants (Claude Code, Codex, Antigravity, Cursor) working in this repo. Read this first; then jump to the file you need.

## What this is

A geospatial-first, AI-native desktop IDE for urban and regional planners. Disha unifies an interactive spatial map canvas with a multi-domain AI reasoning engine structured across 7 core urban planning domains and 1 cross-cutting utility engine.

**Quality bar:** solid prototype. Golden paths must work and not crash. Automated backend unit tests exist in `packages/backend/tests/`; do not introduce regressions in the chat → tool-call → map-action flow.

## Architecture in 10 lines

```
Electron main (apps/desktop/src/main/index.ts)
  ├─ spawns FastAPI backend on :8765 (PyInstaller-frozen in prod, uvicorn in dev)
  └─ creates BrowserWindow → loads renderer (React)

Renderer (apps/desktop/src/renderer/) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws   ← streaming chat + tool calls
  ├─ Backend over HTTP       /api/files /api/artifacts /api/reports
  └─ Electron main over IPC  (file dialogs, read directory, switch model)

Backend (packages/backend/) talks to:
  └─ OpenAI HTTPS  (key from OPENAI_API_KEY env)
     + Overpass, Nominatim, OSRM, Open-Meteo, GEE, WorldPop (free/keyless + Google)
```

## The three communication channels

| Channel | Used for |
|---|---|
| **WebSocket** (renderer ↔ backend) | Streaming chat, tool calls, map actions. Lives in `ChatPanel.tsx` ↔ `routers/chat.py:chat_websocket`. |
| **HTTP** (renderer ↔ backend) | List workspace files, CRUD on artifacts, generate Markdown reports. Routers in `packages/backend/routers/`. |
| **Electron IPC** (renderer ↔ main) | Local OS only — open file picker, read a directory, persist last-workspace, switch model. Surface defined in `apps/desktop/src/preload/index.ts`. |

## The 7+1 Domain Hub Architecture & ToolResult Protocol

Tools are organized into **7+1 Domain Hubs** in `packages/backend/domains/`, inheriting from `BaseDomainHub` in `domains/protocol.py`:

```python
class BaseDomainHub(ABC):
    name: str
    description: str
    tool_names: set[str]
    def get_declarations(self) -> list[dict[str, Any]]: ...
    async def execute(self, tool_name: str, args: dict, context: dict | None = None) -> ToolResult: ...
```

Each tool execution returns a typed `ToolResult`:
- `data`: Clean summary dictionary returned to the LLM.
- `map_action`: Optional map action `{"action": "<name>", "payload": {...}}` automatically sent over the WebSocket.
- `artifact`: Optional markdown report `{"title": "...", "content": "...", "artifact_type": "report"}` automatically persisted.
- `error`: Error message if status is `"error"`.

### The 8 Domain Hubs:

1. **`SpatialHub`** (`domains/spatial_hub.py`): GIS operations, OSM/DataMeet boundaries, WMS, and polygon registry tools (`list_polygons`, `get_polygon`, `check_polygon_overlap`, `calculate_land_budget`).
2. **`MobilityHub`** (`domains/mobility_hub.py`): Road networks, Dijkstra/freight routing, GTFS transit, ITS, and OD flows.
3. **`EnvironmentHub`** (`domains/environment_hub.py`): GEE satellite LULC/NDVI, weather, air quality, solar/elevation, and fleet emissions.
4. **`PlanningHub`** (`domains/planning_hub.py`): Zoning classification, document georeferencing, image digitization.
5. **`DemographicsHub`** (`domains/demographics_hub.py`): WorldPop population metrics, cohort-component demographic forecasts, employment.
6. **`PlacesHub`** (`domains/places_hub.py`): Google Places search and Overture 3D buildings.
7. **`ScenariosHub`** (`domains/scenarios_hub.py`): Planning scenarios and MCDA scoring.
8. **`UtilityHub`** (`domains/utility_hub.py`): Geocoding, web search, distance/area measurement, artifacts.

## Centralized Spatial & Polygon Registry

All polygon lifecycles (user drawing, AI drawing, OSM administrative boundaries, DataMeet boundaries, zoning parcels) are tracked centrally in `packages/backend/tools/spatial_registry.py`:
- **IoU Deduplication ($\ge 90\%$):** Prevents duplicate polygons and overdrawing by matching spatial overlap and normalized place names.
- **Reuse & Focus:** Reuses existing layers, highlights them on the map, and returns computed metrics without spawning redundant layers.
- **Geodesic Calculations:** Accurate WGS84 geodesic area ($\text{m}^2$, ha, $\text{km}^2$), centroid, and bounding box metrics.
- **Real-Time Layer Sync:** Automatically synchronized with `map_context["layers"]` on every turn.

## The action contract

When the model calls a function whose name is in `_ACTION_TOOLS` (`routers/chat.py:121`) or when a Domain Hub returns a `map_action`, the backend forwards it to the renderer over the WebSocket as:

```json
{ "type": "action", "action": "<name>", "payload": { ...args } }
```

`MapView.tsx` consumes these via the `mapActions` queue from `App.tsx` and turns them into MapLibre operations (fly, fit_bounds, add_marker, add_geojson, draw_line, etc.). To add a new action you must touch **both ends** — backend tool def + frontend handler. See the `add-map-action` skill (in `.agents/skills/`) for the procedure.

## Tool dispatch

All tool logic flows through `packages/backend/routers/chat.py`:

- Hubs are instantiated in `_hubs`, their `get_declarations()` is flattened into the OpenAI tool list by `_build_tools()`, and dispatch happens in `_execute_tool()`.
- Adding a domain tool means editing a Domain Hub class in `packages/backend/domains/` returning a `ToolResult` — the flatten step picks it up automatically.
- Action tools (the names in `_ACTION_TOOLS`) need the OpenAI schema in `_build_tools()` plus a frontend handler in `MapView.tsx`. Use the `add-map-action` skill.

There is no external MCP stdio bridge — the in-app chat is the only surface.

## Geospatial conventions

- **Coordinates everywhere are EPSG:4326 lat/lng.** No reprojection is performed anywhere in the codebase.
- **Area and perimeter math are geodesic.** `tools/geo.py` and `tools/spatial_registry.py` compute true ellipsoidal metrics using pyproj WGS84 (`Geod`). Quantitative metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`) must NEVER be stripped from model responses (Workspace Rule 9).
- **Tile sources are free raster XYZ** (OSM, CartoDB, Esri, OpenTopoMap). No Mapbox token, no PMTiles, no MBTiles. Defined in `apps/desktop/src/renderer/types.ts:BASEMAPS`.
- **OSM data path** is Overpass API → `_merge_ways()` ring-merge → GeoJSON Feature. Boundary fetches additionally fall through to Nominatim with `polygon_geojson=1`.
- **Frontend geometry ops use Turf.js** (`@turf/turf`).

## Frontend state

Pure React `useState`/`useRef`. **No** Zustand/Redux/Context. All state lives in `App.tsx` and flows down as props. `MapView` exposes a ref (`MapViewHandle`) for canvas access. `mapActions` is a queue array; `MapView` processes and clears via `onActionsProcessed`. Don't add a state library — match the existing pattern.

## Critical Invariants & Guardrails

1. **Workspace Auto-Save Guard (`isClosingRef`):** In `App.tsx`, whenever resetting workspace state (`handleCloseWorkspace`, `handleSelectWorkspace`), ALWAYS set `isClosingRef.current = true` before resetting state and await all saves (`saveProjectRef.current(true)`). Never remove or bypass `isClosingRef` in `useEffect` dependency arrays or `ArtifactsPanel.tsx`—doing so corrupts `project.json` and `documents.json`.
2. **Model Metric Preservation:** Never strip calculated spatial metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`) from tool result dictionaries returned to the LLM loop in `packages/backend/routers/chat.py`. The LLM requires these to verify tool execution success.
3. **Prompt Location Neutrality:** Prompts in `chat.py` (`SYSTEM_PROMPT`, `_RESEARCH_SYSTEM`, tool descriptions) must remain 100% location-neutral and globally applicable. Never hardcode specific city names or test-case entities.
4. **State Management Constraint:** Maintain pure React `useState`/`useRef` in `App.tsx`. Do NOT introduce external state stores (Zustand, Redux, Context).

## Run instructions

```bash
pnpm install                # once
cd packages/backend && python -m venv .buildenv && \
  source .buildenv/bin/activate && pip install -r requirements.txt   # once
export OPENAI_API_KEY=...

pnpm dev                    # starts backend (uvicorn :8765) + renderer (electron-vite)
```

In dev, `apps/desktop/src/main/index.ts:startBackend` is a no-op — uvicorn runs separately via `pnpm dev:backend`. In prod (`pnpm package`), the PyInstaller binary is spawned by Electron from `Resources/backend/backend`.

## Testing

```bash
# Backend pytest suite (all hubs, registry, websocket)
cd packages/backend
.buildenv/bin/pytest tests/

# Frontend typecheck & full Vite bundler build verification
pnpm --filter @disha/desktop exec tsc --noEmit
pnpm --filter @disha/desktop build
```

## Key files to read first (in order)

1. `packages/backend/routers/chat.py` — agentic loop, action contract, tool registry. **The heart of the AI behavior.**
2. `packages/backend/tools/spatial_registry.py` — centralized polygon registry, geodesic metrics, and IoU deduplication.
3. `packages/backend/domains/` — the 7+1 Domain Hubs and `ToolResult` protocol.
4. `apps/desktop/src/renderer/App.tsx` — single state container, component wiring, conversation persistence.
5. `apps/desktop/src/renderer/components/MapView.tsx` — MapLibre setup + action handlers.
6. `apps/desktop/src/renderer/components/ChatPanel.tsx` — WebSocket client, streaming render.
7. `apps/desktop/src/renderer/types.ts` — shared interfaces, basemap defs, zone presets, layer colors.
8. `apps/desktop/src/preload/index.ts` — full IPC surface between renderer and Electron main.

## How to work in this repo

- **Adding a tool?** Add the method to the corresponding Domain Hub in `packages/backend/domains/` returning a `ToolResult`.
- **Adding a map action?** Use the `add-map-action` skill — touches the backend action contract in `chat.py` and the frontend handler in `MapView.tsx` together.
- **Designing a new feature?** Formulate a step-by-step implementation plan before modifying code.
- **Debugging the agent loop?** Inspect `packages/backend/routers/chat.py:_run_agent()` — streaming tool-call deltas accumulate in `tool_calls_acc`, execute via domain hubs, and loop until `finish_reason == "stop"`.
- **Before claiming a change works:** Run backend unit tests (`.buildenv/bin/pytest tests/`), frontend typecheck (`pnpm --filter @disha/desktop exec tsc --noEmit`), and full bundler build (`pnpm --filter @disha/desktop build`). Type-check passing alone is not the same as runtime correctness.

