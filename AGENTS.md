# AGENTS.md

Orientation for AI coding assistants (Claude Code, Codex, Antigravity, Cursor, OpenCode) working in this repository. Read this first; then jump to the specific subsystem or domain hub file you need.

## What this is

A geospatial-first, AI-native desktop IDE for urban and regional planners. Disha unifies an interactive spatial map canvas (MapLibre GL) with a multi-domain AI reasoning engine structured across **7 core urban planning domains and 1 cross-cutting utility engine**.

**Quality bar:** Solid production-grade prototype. Golden paths must work and not crash. Automated backend unit tests exist in `packages/backend/tests/`; do not introduce regressions in the chat → tool-call → map-action flow or workspace persistence.

## Architecture in 16 lines

```
Electron main (apps/desktop/src/main/index.ts)
  ├─ spawns FastAPI backend on :8765 (PyInstaller-frozen in prod, uvicorn in dev)
  └─ creates BrowserWindow → loads renderer (React 19 + TypeScript)

Renderer (apps/desktop/src/renderer/) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws   ← streaming chat, tool calls, map actions
  ├─ Backend over HTTP       /api/files, /api/artifacts, /api/geocode, /api/streetview,
  │                          /api/wms, /api/gee, /api/scenarios, /api/rag, /api/diagnostics
  └─ Electron main over IPC  (file dialogs, read/write workspace, switch model, last-workspace)

Backend (packages/backend/) talks to:
  ├─ OpenCode Agent Runtime (:4096)  ← Autonomous multi-step orchestration (when USE_OPENCODE=true)
  │    └─ stdio JSON-RPC 2.0 MCP Server (packages/backend/llm/opencode/mcp_server.py)
  └─ Direct LLM & Spatial APIs (legacy fallback, RAG embeddings, deep research)
     + Overpass, Nominatim, OSRM, Open-Meteo, Overture, WorldPop, Photon, Google Earth Engine, Google Maps Platform
```

## The Four Communication Channels

| Channel | Endpoint / Bridge | Used for |
|---|---|---|
| **WebSocket** (renderer ↔ backend) | `ws://localhost:8765/api/chat/ws` | Streaming chat tokens, tool execution status, map action dispatch, interactive questions (`ask_question`), deep-research progress. |
| **HTTP** (renderer ↔ backend) | `http://localhost:8765/api/*` | 10 mounted routers: Workspace file management & vector ingest (`/api/files`), Artifact CRUD & 8-format exports (`/api/artifacts`), Forward/Reverse geocoding (`/api/geocode`), Keyless Street View (`/api/streetview`), WMS proxy (`/api/wms`), GEE tile proxy & auth (`/api/gee`), Direct scenario generation (`/api/scenarios`), Document RAG indexing & search (`/api/rag`), Startup diagnostics (`/api/diagnostics`), and loopback bridges (`/api/chat/internal_action`, `/api/chat/internal_question`). |
| **OpenCode MCP & SSE** (backend ↔ runtime) | `http://127.0.0.1:4096/session` + stdio MCP | Multi-step agent loops, conversation context compaction, and tool invocation via `packages/backend/llm/opencode/`. |
| **Electron IPC** (renderer ↔ main) | `window.electronAPI.*` (`src/preload/index.ts`) | Local OS only — folder picker, file read/write, base64 file read for vision, workspace persistence, model selection switching. |

## The 7+1 Domain Hub Architecture & ToolResult Protocol

Tools are organized into **7+1 Domain Hubs** in `packages/backend/domains/`, inheriting from `BaseDomainHub` in `domains/protocol.py`:

```python
class BaseDomainHub(ABC):
    name: str
    description: str
    tool_names: set[str]
    @abstractmethod
    def get_declarations(self) -> list[dict[str, Any]]: ...
    @abstractmethod
    async def execute(self, tool_name: str, args: dict, context: dict | None = None) -> ToolResult: ...
```

Each tool execution returns a typed `ToolResult`:
- `data`: Clean summary dictionary returned directly to the LLM agent loop.
- `map_action`: Optional map action `{"action": "<name>", "payload": {...}}` automatically forwarded to the frontend over WebSocket.
- `artifact`: Optional markdown report `{"title": "...", "content": "...", "artifact_type": "report"}` automatically persisted to the workspace/SQLite store.
- `status`: Status string (`"success"` | `"error"` | `"cancelled"`).
- `error`: Error message if status is `"error"`.

### The 8 Domain Hubs:

1. **`SpatialHub`** (`domains/spatial_hub.py`): GIS operations (buffer, centroid, area, convex hull, intersection, difference, clip, dissolve, spatial join, nearest), OSM/DataMeet boundaries, WMS raster services, and Central Spatial Registry queries (`list_polygons`, `get_polygon`, `check_polygon_overlap`, `calculate_land_budget`).
2. **`MobilityHub`** (`domains/mobility_hub.py`): Road networks, Dijkstra/freight routing with Z-level modeling, GTFS transit feeds & 400m/800m catchment sheds, ITS signal timing optimization, parking demand, and OD flow gravity modeling.
3. **`EnvironmentHub`** (`domains/environment_hub.py`): Google Earth Engine satellite LULC & NDVI indices, Open-Meteo weather & air quality, Google Solar/Elevation, and fleet emissions modeling.
4. **`PlanningHub`** (`domains/planning_hub.py`): Zoning code compliance, zone density & overlap detection, master plan georeferencing (`georeference_active_document`), and raster digitization (`digitize_image_features`).
5. **`DemographicsHub`** (`domains/demographics_hub.py`): WorldPop 100m grid population extraction, cohort-component demographic forecasts, and employment density projections.
6. **`PlacesHub`** (`domains/places_hub.py`): Google Places search/details/nearby/density and Overture 3D buildings & POIs.
7. **`ScenariosHub`** (`domains/scenarios_hub.py`): Planning scenario generation and Multi-Criteria Decision Analysis (MCDA) matrix evaluation.
8. **`UtilityHub`** (`domains/utility_hub.py`): Forward/reverse geocoding, live web research, geodesic distance/area measurement, Matplotlib plotting (`create_plot`), interactive questions (`ask_question`), and artifact CRUD.

## Centralized Spatial & Polygon Registry

All polygon lifecycles (user drawing, AI drawing, OSM administrative boundaries, DataMeet boundaries, zoning parcels) are tracked centrally in `packages/backend/tools/spatial_registry.py`:
- **IoU Deduplication ($\ge 90\%$):** Prevents duplicate polygons and layer clutter by matching spatial overlap and normalized place names.
- **Reuse & Focus:** Automatically reuses existing layers, highlights them on the map, and returns computed metrics without spawning redundant layers.
- **Geodesic Calculations:** Accurate WGS84 geodesic area ($\text{m}^2$, ha, $\text{km}^2$), centroid, and bounding box metrics via `pyproj.Geod`.
- **Real-Time Layer Sync:** Synchronized with active map layers (`map_context["layers"]`) on every chat turn.

## The Action Contract

When the model calls a tool listed in `_ACTION_TOOLS` (`routers/chat.py`) or when a Domain Hub returns a `map_action`, the backend forwards it to the renderer over WebSocket as:

```json
{ "type": "action", "action": "<name>", "payload": { ...args } }
```

The supported action tools are:
```
fly_to · fit_bounds · add_marker · add_markers · clear_markers
draw_line · draw_polygon · draw_circle · add_geojson · add_geojson_file
highlight_features · set_layer_style · style_layer · toggle_layer · remove_layer
save_bookmark · go_to_bookmark · export_region_clip · export_map_png · export_map_jpeg · export_map_pdf
switch_basemap · add_gee_layer · add_raster_overlay
```

`MapView.tsx` consumes these via the `mapActions` queue from `App.tsx` and translates them into MapLibre operations. Adding a new action requires touching:
1. Backend tool definition & action schema (`routers/chat.py`).
2. Frontend `MapAction` union type (`apps/desktop/src/renderer/types.ts`).
3. Frontend action handler (`App.tsx` and/or `MapView.tsx`).

## Task Pipeline & Multi-Format Export Engine

1. **Task Pipeline Orchestrator (`tools/task_pipeline.py`):** When the AI requests document compilation (`create_artifact`) alongside map exports (`export_map_jpeg`) or charts (`create_plot`), the pipeline enforces a two-phase execution:
   - **Queue Phase (Assets):** Executes map exports and chart tools first, collecting real file paths (`artifacts_store/<id>.jpg`).
   - **Heap Phase (Document):** Injects real asset paths into document markdown before compiling Word/PDF documents, preventing placeholder hallucinations.
2. **Multi-Format Export Engine (`tools/export_engine.py`):** Compiles markdown reports, map snapshots, and tables into **8 export formats**: `PDF` (`ReportLab` native `%PDF-1.4`), `Word (.docx)`, `HTML`, `PNG Image`, `JPEG Image`, `Excel (.xlsx)`, `JSON`, and `TXT`.

## Geospatial Conventions

- **Coordinates everywhere are EPSG:4326 lng/lat.** No reprojection is performed in flight; all vector data in the frontend is WGS84 GeoJSON.
- **Vector ingestion auto-reprojects to 4326:** `tools/vector_convert.py` uses DuckDB `spatial` (`ST_Read` + `ST_Transform(..., always_xy := true)`) to ingest Shapefiles, GeoPackages, KML/KMZ, GPX, and CSVs.
- **Area and perimeter math are strictly geodesic:** `tools/geo.py` and `tools/spatial_registry.py` compute ellipsoidal metrics using `pyproj.Geod(ellps="WGS84")`. Quantitative spatial metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`) must NEVER be stripped from model responses.
- **Tile sources are free raster XYZ:** OSM, CartoDB, Esri, OpenTopoMap, OSM-HOT (defined in `types.ts:BASEMAPS`). GEE raster tiles are proxied with Bearer authentication via `/api/gee/tiles`.

## Frontend State Architecture

Pure React `useState`/`useRef`. **No** external state library (no Zustand, Redux, or React Context). All state lives in `App.tsx` and flows down as props:
- `layers`: Canonical GeoJSON layer list (data + `LayerStyleSpec`).
- `mapActions`: Queue array processed and drained by `MapView.tsx` via `onActionsProcessed`.
- `conversations`: Persisted in `project.json`.
- `isClosingRef`: Workspace auto-save concurrency guard.

## Critical Invariants & Guardrails

1. **Workspace Auto-Save Guard (`isClosingRef`):** In `App.tsx`, whenever resetting workspace state (`handleCloseWorkspace`, `handleSelectWorkspace`), ALWAYS assert `isClosingRef.current = true` before resetting state and await all saves (`saveProjectRef.current(true)`). Never remove or bypass `isClosingRef`—doing so corrupts `project.json` and `documents.json`.
2. **Model Metric Preservation:** Never strip calculated spatial metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`) from tool result dictionaries returned to the LLM loop in `packages/backend/routers/chat.py`. The LLM requires these to verify tool execution success.
3. **Prompt Location Neutrality:** Prompts in `chat.py` (`SYSTEM_PROMPT`, `DOCUMENT_SYSTEM_PROMPT`, tool descriptions) must remain 100% location-neutral and globally applicable. Never hardcode specific city names or test-case entities.
4. **Token-Optimized Spatial Context:** When passing map features or selected layers into chat context, pass compact spatial metadata summaries (~100 tokens) rather than raw coordinate geometry arrays (~274,000 tokens) to prevent context window overflow.
5. **State Management Constraint:** Maintain pure React `useState`/`useRef` in `App.tsx`. Do NOT introduce external state stores.
6. **Autonomous Execution & Implicit Authorization:** When the user requests a document, report, map, plot, analysis, or other artifact that requires data to be retrieved or generated first, execute the necessary intermediate operations automatically before producing the requested artifact. Do not stop to ask the user to confirm that you should proceed ("proceed", "yes") when the requested outputs and geographic scope are already clear. Do not ask the user to select administrative levels, datasets, data providers, or GIS operations unless the request is genuinely ambiguous and materially affects the result. If required data or maps are not yet available, retrieve or generate them using available tools (never invent figures, statistics, or maps). The user's request implicitly authorizes all intermediate data retrieval, spatial analysis, visualization, and artifact-generation steps.
7. **Geographic Interpretation & Boundary Containment:** When a user asks for features "in" a named geographic place, resolve the place boundary and spatially filter the requested features to that boundary. The geographic constraint implied by the user's wording must be preserved during tool selection, data retrieval, spatial processing, and visualization without substituting broad search extents, bounding boxes, viewports, or proximity searches. Internally infer and perform any necessary boundary resolution, clipping, intersection, containment, or filtering operations without requiring explicit GIS phrasing or hardcoding places.
8. **Document Visualization & Output Preservation:** When the user requests separate visuals under separate headings, generate a separate distinct visual for each heading; do not combine them unless explicitly requested. Each visual must contain only layers and information relevant to its corresponding request, with only necessary geographic context (no cross-section layer contamination). Preserve the user's requested structure and intent without simplifying, omitting, or merging outputs. When compiling a document, infer the structure from requested headings and generate all required underlying maps, plots, statistics, and artifacts before assembling the document.

## Run Instructions

```bash
pnpm install                # install frontend dependencies
cd packages/backend && python -m venv .buildenv && \
  source .buildenv/bin/activate && pip install -r requirements.txt   # backend setup
export OPENAI_API_KEY=...

pnpm dev                    # starts backend (uvicorn :8765) + renderer (electron-vite)
```

In development, `apps/desktop/src/main/index.ts:startBackend` is a no-op — uvicorn runs separately via `pnpm dev:backend`. In production (`pnpm package`), the PyInstaller binary is spawned by Electron from `Resources/backend/backend`.

## Testing

```bash
# Backend pytest suite (all 8 hubs, registry, websocket, exports)
cd packages/backend
.buildenv/bin/pytest tests/

# Frontend typecheck & full Vite bundler build verification
pnpm --filter @disha/desktop exec tsc --noEmit
pnpm --filter @disha/desktop build
```

## Key Files to Read First (in order)

1. `packages/backend/routers/chat.py` — Agentic loop, action contract, tool registry, deep research, pipeline orchestrator.
2. `packages/backend/tools/spatial_registry.py` — Centralized polygon registry, geodesic math, and IoU deduplication.
3. `packages/backend/domains/` — The 7+1 Domain Hubs and `ToolResult` protocol.
4. `packages/backend/tools/task_pipeline.py` & `tools/export_engine.py` — Document pipeline and multi-format exporter.
5. `apps/desktop/src/renderer/App.tsx` — Single state container, action routing, workspace auto-save guards.
6. `apps/desktop/src/renderer/components/MapView.tsx` — MapLibre setup, symbology paint expressions, drawing tools, map snapshot composer.
7. `apps/desktop/src/renderer/components/ChatPanel.tsx` — WebSocket client, streaming markdown, question interactions, deep research UI.
8. `apps/desktop/src/renderer/types.ts` — Shared interfaces, `LayerStyleSpec`, basemaps, zone presets, `MapAction` union.
9. `apps/desktop/src/preload/index.ts` — IPC bridge between renderer and Electron main.
