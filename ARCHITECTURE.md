# Disha — Architecture & Features

**A geospatial-first, AI-native desktop IDE for urban and regional planners.**

Disha unifies an interactive spatial map canvas with a multi-domain AI reasoning engine. Planners can explore, analyze, model, and document complex urban environments through natural conversation and direct spatial interaction — bridging computational GIS, domain-specific planning analytics, and cartography into a unified desktop workspace.

This document is split into two halves:

- **Part 1 — For Users.** What the app does and how to use it.
- **Part 2 — For Developers.** How the system is wired together.

If you only want the orientation needed to make code changes, jump to Part 2.

---

# Part 1 — For Users

## What it is

A desktop application (macOS / Windows / Linux) that unifies multiple analytical surfaces:

| Pane / Mode | Purpose |
|---|---|
| **Map** (center, Map mode) | Interactive MapLibre GL canvas with switchable raster basemaps, vector layer rendering, data-driven symbology (categorized, graduated) + text labels, drawing tools, marker pins, measurement, and a live legend. |
| **Document view** (center, Document mode) | Drop in a planning PDF or map image; the AI analyzes land use, zoning, networks, and spatial patterns via multimodal vision, with automatic/manual georeferencing and digitizing tools. |
| **Left panel** | Tabs for **Files** (workspace tree & vector import), **Layers** (+ Symbology & Attribute editors), **Bookmarks**, **Export** (publication figures & clipped layers), **Zoning legend**, **Scenario Builder** (MCDA evaluation), and **Diagnostics** (system self-checks). |
| **Right panel** | Tabs for **Chat** (streaming AI assistant, inline tool calls, interactive option cards, model switcher) and **Artifacts** (markdown reports, tables, plots, and figures with 8-format exports). |

Toggle between **Map** and **Document** modes from the title bar.

## Workspace & Persistence

Open any folder via the title-bar button. The application:

- Lists files in the **Files** tab. Click a `.geojson` to load it directly; click a `.shp`, `.gpkg`, `.kml`, `.kmz`, `.gpx`, or `.csv` to import it (automatically converted to WGS84 GeoJSON in the workspace and loaded as a layer).
- Auto-saves a `project.json` in the workspace folder containing layer configurations, symbology styling specs, camera viewports, conversations, bookmarks, and basemap settings (debounced 800ms).
- Materializes chat-generated layers into `<workspace>/.disha/layers/<id>.geojson` so they survive application restarts.
- Auto-indexes workspace documents (`.pdf`, `.docx`, `.txt`, `.md`) for semantic vector search (RAG) in `<workspace>/.disha/rag_index.json`.
- Remembers the last-opened workspace across launches.

## Map Mode Features

### Layers & Vector Ingestion
- Click `.geojson` files to load vector layers.
- Click Shapefiles, GeoPackages, KML, KMZ, GPX, or CSV files to auto-convert them to EPSG:4326 GeoJSON via backend DuckDB `spatial` (`ST_Read` + `ST_Transform`). CSV files automatically detect latitude and longitude columns.
- The **Layers** panel provides layer visibility toggles, zoom-to extent, remove layer, and triggers for the **Symbology** panel and **Attribute Table**.

### Data-Driven Symbology & Text Labels
Style any vector layer based on its feature properties:
- **Categorized:** Assign distinct colors per string value (e.g. `land_use`, `zone_code`). Pre-seeded with urban planning zone palettes.
- **Graduated:** Choropleth styling for numeric properties (e.g. `population`, `density`), using equal-interval or quantile class breaks (2–9 classes) and curated color ramps.
- **Labels:** On-map dynamic text labels from any feature attribute, with zoom gating, collision avoidance, and font size/color controls.
- **Live Legend:** Floating legend overlay automatically syncs with all visible styled layers.

### Drawing Tools & Attribute Editor
- Toolbar draw tools for **points**, **lines**, and **polygons**. Click to place vertices, double-click/Enter to complete, Escape to cancel, Backspace to undo vertices.
- Drawn shapes become real layers and open the **Attribute Table** to edit feature properties, add/delete columns, and modify values.

### Basemaps & Street View
- Seven free raster basemaps: Street (OSM), Satellite (Esri World Imagery), Dark / Light (CartoDB), Terrain (OpenTopoMap), Topo (Esri), Humanitarian (OSM-HOT).
- **Keyless 360° Street View:** Right-click anywhere on the map to inspect coordinates, drop reverse-geocoded pins, query the AI, or open an embedded 360° street-level panorama (powered by the `streetlevel` library and pannellum).

### Bookmarks & Publication Export
- Save named map extents as bookmarks. The assistant can also save and navigate to bookmarks.
- **Publication Map Export:** Export publication-ready figures with Web-Mercator scale bars, bearing-aware north arrows, title blocks, legends, and attributions in PNG or PDF.
- **Zero-Crop Geographic Padding:** When exporting study areas, the exporter calculates bounding boxes and applies an **18% geographic padding** on all four cardinal directions, repainting the WebGL buffer for uncropped figures.

## Document Mode & Master Plan Digitization
Drop in or open external planning documents:
- **Raster Images & PDFs:** Rasterized client-side via `pdfjs-dist` (capped at 2200px long axis) and passed to AI vision.
- **Georeferencing & Digitization:** Identify visual landmarks, georeference the document (`georeference_active_document`), and digitize visual boundaries and POIs (`digitize_image_features`) into real GeoJSON layers.

## AI Chat Assistant & 7+1 Planning Domains

The chat panel provides streaming conversational intelligence with full tool visibility:
- Multiple conversation threads persisted to `project.json`.
- Token-by-token streaming over WebSocket.
- Interactive question-and-answer cards (`ask_question`) with selectable single-choice or multi-select options.
- **Deep Research Reports:** Multi-search research passes using OpenAI's Responses API (`o4-mini-deep-research`), streaming research queries, live reasoning, and cited markdown reports.

### The 7+1 Domain Hub Capabilities:

| Domain Hub | Planning Discipline | Core Capabilities |
|---|---|---|
| **1. SpatialHub** | Spatial Geometry & Land Management | Central polygon registry (deduplication & reuse), geodesic buffering/areas, spatial overlays (intersection, difference, clip, dissolve, spatial join, nearest), OSM/DataMeet administrative boundaries, WMS raster services. |
| **2. MobilityHub** | Multimodal Transportation & Transit | Street network graphs, Dijkstra/freight routing with Z-level bridges/tunnels, GTFS transit feeds & 400m/800m walking sheds, ITS traffic signal timing optimization, Origin-Destination (OD) gravity matrices & flow assignment. |
| **3. EnvironmentHub** | Climate, Remote Sensing & Emissions | Google Earth Engine (GEE) satellite land cover (Dynamic World) & NDVI indices, Open-Meteo weather & air quality, Google Solar/Elevation APIs, fleet emissions modeling. |
| **4. PlanningHub** | Zoning & Plan Digitization | Zoning code compliance, zone density & overlap detection, master plan georeferencing, raster feature digitization. |
| **5. DemographicsHub** | Population & Economic Forecasting | WorldPop 100m grid population estimates, cohort-component demographic forecasts, employment density projections. |
| **6. PlacesHub** | Built Form & Urban POIs | Google Places search/details/nearby/density, Overture Maps 3D building footprints & heights. |
| **7. ScenariosHub** | Scenario Planning & Evaluation | Alternative planning scenario generation, Multi-Criteria Decision Analysis (MCDA) scoring matrices. |
| **+1. UtilityHub** | Shared System Infrastructure | Forward/reverse geocoding, live web research, geodesic distance/area measurement, Matplotlib plotting (`create_plot`), interactive questions (`ask_question`), and artifact CRUD. |

## Artifacts & Multi-Format Export

Generated reports, analytical tables, charts, and figures are cataloged in the **Artifacts** panel and stored in a local SQLite database (`disha.db`). Artifacts can be edited, reordered, and exported in **8 formats**:
1. **PDF (`.pdf`)** — Formatted publication document via `ReportLab` (`%PDF-1.4`).
2. **Word (`.docx`)** — Microsoft Word document via `python-docx` with embedded figures and tables.
3. **HTML (`.html`)** — Standalone responsive HTML report with modern CSS styling.
4. **PNG Image (`.png`)** — High-resolution map or chart snapshot.
5. **JPEG Image (`.jpg`)** — Compressed image figure.
6. **Excel (`.xlsx`)** — Multi-column spreadsheet via `openpyxl`.
7. **JSON (`.json`)** — Raw structured data and GeoJSON feature collections.
8. **TXT (`.txt`)** — Plain text document.

---

# Part 2 — For Developers

## Tech Stack

| Layer | Technologies |
|---|---|
| **Desktop Shell** | Electron 34+ |
| **Frontend Renderer** | React 19, TypeScript, Vite (`electron-vite`), CSS3 |
| **Map & Cartography** | MapLibre GL 4+, Turf.js, pannellum (Street View) |
| **Backend Framework** | Python 3.11+, FastAPI, uvicorn, Pydantic |
| **LLM & Reasoning** | OpenAI API (Chat Completions streaming, tool calling), OpenAI Responses API (`o4-mini-deep-research`), OpenAI Embeddings (`text-embedding-3-small`) |
| **Geospatial & Analysis** | Shapely, pyproj (WGS84 ellipsoidal geodesic math), DuckDB `spatial`, GeoPandas, Fiona, NetworkX |
| **External Geospatial APIs** | Overpass API (OSM), Nominatim, OSRM, Open-Meteo, Overture Maps (S3 Parquet), WorldPop, Google Earth Engine, Google Maps Platform |
| **Document & Chart Engines** | ReportLab, python-docx, openpyxl, Matplotlib, markdown, pdfjs-dist, pypdf |
| **Storage & Cache** | SQLite (WAL mode for artifacts & HTTP cache), JSON files for workspace state |
| **Packaging & Freezing** | electron-builder, PyInstaller (frozen backend binary) |

## Top-Level Directory Layout

```
.
├── apps/desktop/                  Electron + React frontend
│   ├── src/main/index.ts          Electron main: window management, IPC handlers, backend lifecycle
│   ├── src/preload/index.ts       Preload script exposing window.electronAPI via contextBridge
│   └── src/renderer/              React application
│       ├── App.tsx                Single state container; map ↔ chat ↔ panels wiring, auto-save guards
│       ├── types.ts               MapAction union, LayerStyleSpec, basemaps, zone presets, interfaces
│       ├── lib/
│       │   ├── classify.ts        Color ramps, class breaks, category palettes
│       │   ├── compose-figure.ts  Publication figure compositor (title/legend/scale/arrow)
│       │   ├── legend-data.ts     Shared legend builder for live legend and export compositor
│       │   └── pdf-raster.ts      PDF page rasterization via pdfjs-dist
│       └── components/            MapView, ChatPanel, ArtifactsPanel, LayerPanel, SymbologyPanel,
│                                  AttributeTable, ScenarioBuilderPanel, DiagnosticsPanel, DocumentView,
│                                  ExportPanel, StreetViewWorkspace, BookmarkPanel, FileTree, Legend...
├── packages/backend/              Python FastAPI backend
│   ├── main.py                    FastAPI app, lifespan, CORS, and router registration
│   ├── cli.py                     PyInstaller entrypoint for uvicorn server
│   ├── database.py                SQLite connection manager & schema migrations
│   ├── models.py                  Pydantic data models for artifacts and API requests
│   ├── routers/                   10 Mounted API Routers:
│   │   ├── chat.py                ★ Agentic loop, tool registry, action contract, deep research
│   │   ├── files.py               Workspace file listing and vector file conversion/probing
│   │   ├── artifacts.py           Artifact CRUD, file uploads, and 8-format download/export endpoints
│   │   ├── geocode.py             Forward and reverse geocoding proxy
│   │   ├── streetview.py          Keyless Street View metadata and equirectangular panoramas
│   │   ├── wms.py                 WMS GetCapabilities and GetFeatureInfo CORS proxy
│   │   ├── gee.py                 Google Earth Engine tile proxy and OAuth2 credential manager
│   │   ├── scenarios.py           Direct HTTP endpoints for planning scenario analysis & MCDA
│   │   ├── rag.py                 Document parsing, OpenAI embeddings, and semantic vector search
│   │   └── diagnostics.py         Startup self-check diagnostics for keys, APIs, and libraries
│   ├── domains/                   ★ 7+1 Domain Hubs & BaseDomainHub protocol
│   │   ├── protocol.py            BaseDomainHub abstract base class & typed ToolResult
│   │   ├── spatial_hub.py         Spatial geometry, overlays, boundary queries, polygon registry
│   │   ├── mobility_hub.py        Road networks, Dijkstra/freight routing, GTFS transit, ITS, OD flows
│   │   ├── environment_hub.py     GEE satellite LULC/NDVI, weather, air quality, solar/elevation, emissions
│   │   ├── planning_hub.py        Zoning compliance, master plan georeferencing, digitization
│   │   ├── demographics_hub.py    WorldPop demographics, cohort-component forecasts, employment
│   │   ├── places_hub.py          Google Places Platform and Overture 3D buildings & POIs
│   │   ├── scenarios_hub.py       Planning scenario generation and MCDA matrix comparisons
│   │   └── utility_hub.py         Geocoding, web search, measurements, PlotServer, artifacts
│   ├── mcp_servers/               Underlying MCP server implementations (OSM, GIS, weather, zoning, etc.)
│   ├── tools/                     Authoritative backend engines:
│   │   ├── spatial_registry.py    ★ Central spatial registry with IoU >= 90% deduplication & geodesic math
│   │   ├── task_pipeline.py       ★ Queue & Heap orchestrator for document asset-pipeline ordering
│   │   ├── export_engine.py       ★ Multi-format export compiler (PDF, Word, HTML, XLSX, PNG, JPEG)
│   │   ├── geo.py                 Geodesic area/perimeter/buffer calculations via pyproj WGS84
│   │   ├── vector_convert.py      Vector conversion to EPSG:4326 via DuckDB spatial
│   │   ├── utility.py             UtilityServer implementation (web search, geocode, measure)
│   │   ├── google.py              Google Maps API client and ContextVar token management
│   │   ├── http.py                Shared httpx async client with retries and connection pooling
│   │   ├── cache.py               Two-tier cache (in-memory LRU + SQLite)
│   │   ├── artifact_store.py      Artifact persistence in SQLite and filesystem
│   │   ├── worldpop.py            WorldPop API client
│   │   └── config.py              Model selection helper (model_config.json / OPENAI_MODEL)
│   └── tests/                     Pytest automated test suite
├── AGENTS.md                      Orientation for AI coding assistants
├── ARCHITECTURE.md                This document
├── FLAUDE.md                      AI assistant & developer reference handbook
├── FEATURE_IMPLEMENTATION_GUIDE.md Deep dive into core features & subsystems
└── README.md                      Project overview and setup instructions
```

## Process Model & Startup Lifecycle

```
Electron Main Process (apps/desktop/src/main/index.ts)
  ├─ Creates main BrowserWindow and loads React renderer
  ├─ Exposes IPC handlers (file dialogs, filesystem I/O, base64 reads, model switching) via preload
  └─ In Production: Spawns frozen backend binary (Resources/backend/backend --port 8765)
                    and polls GET /health (up to 30 retries, 500ms interval) before opening window

Renderer Process (Chromium) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws    (streaming chat, tools, actions)
  ├─ Backend over HTTP       http://localhost:8765/api/*        (10 mounted routers)
  └─ Electron Main via       window.electronAPI.*               (local OS access only)
```

In development (`pnpm dev`), `apps/desktop/src/main/index.ts:startBackend` is a no-op; uvicorn runs separately via `pnpm dev:backend` so both frontend and backend support hot reloading.

## Three Communication Channels

| Channel | Protocol / Route | Purpose |
|---|---|---|
| **WebSocket** | `ws://localhost:8765/api/chat/ws` | Bi-directional streaming for chat tokens, tool execution notifications, map action dispatch, interactive question cards, and deep-research events. |
| **HTTP** | `http://localhost:8765/api/*` | 10 modular FastAPI routers: `/api/files`, `/api/chat`, `/api/artifacts`, `/api/geocode`, `/api/streetview`, `/api/wms`, `/api/gee`, `/api/scenarios`, `/api/rag`, `/api/diagnostics`. |
| **Electron IPC** | `window.electronAPI.*` | Secure OS primitives: folder selection, workspace directory listing, file text/base64 I/O, model switching, and quit hooks. |

CORS middleware in `main.py` is strictly restricted to loopback origins (`file://`, `app://`, `http(s)://localhost`, `127.0.0.1`, `[::1]`).

## The Agentic Loop (`packages/backend/routers/chat.py`)

The core conversational reasoning engine runs inside `_run_agent`:

```
1. Receive incoming message payload (user text, map_context, image/attachments, history).
2. Retrieve relevant semantic text chunks from RAG index (.disha/rag_index.json) if workspace is active.
3. Append lightweight spatial metadata summary for selected map elements (~100 tokens).
4. Send full message history and flattened tool declarations to OpenAI (model_config.json / get_model()).
5. As response chunks stream in:
     - Text deltas → emitted over WebSocket as {"type": "stream", "content": ...}.
     - Tool-call deltas → accumulated in tool_calls_acc indexed by call index.
6. When stream chunking ends:
     - Append assistant message to history.
     - If no tool calls were made:
         * Run Hallucination Detector (checks if assistant claimed an artifact was saved without calling create_artifact).
         * If hallucinated, inject system correction and continue loop.
         * Otherwise, break loop and emit {"type": "end"}.
     - If tool calls were made:
         * Check Task Pipeline Orchestrator (needs_pipeline): if both asset tools and document compilation are present,
           order calls into Asset Queue Phase -> Document Heap Phase.
         * For each tool call:
             a. Emit {"type": "tool_use", "tool": name, "args": args}.
             b. If transitioning to document phase, patch real asset file paths into markdown content.
             c. Execute tool via _execute_tool (action tool OR Domain Hub OR deep research).
             d. Append tool result message (role: "tool", tool_call_id: id, content: json_str) to history.
         * Loop back to step 4 (up to max_rounds = 35).
```

### WebSocket Message Protocol

**Messages from Backend to Frontend:**
- `{"type": "stream", "content": "..."}` — Incremental assistant text delta.
- `{"type": "tool_use", "tool": "name", "args": {...}}` — Tool execution started.
- `{"type": "action", "action": "name", "payload": {...}}` — Map action forwarded to MapLibre.
- `{"type": "ask_question", "question": "...", "options": [...], "is_multi_select": bool}` — Interactive user prompt.
- `{"type": "research_start" | "research_step" | "research_reasoning_delta" | "research_text_delta" | "research_report" | "research_done"}` — Deep research events.
- `{"type": "error", "code": "auth"|"rate_limit"|"timeout"|"connection"|"upstream"|"internal", "message": "..."}` — Error status.
- `{"type": "end"}` — Turn execution completed.
- `{"type": "stopped"}` — User cancelled the running task.

**Messages from Frontend to Backend:**
- `{"type": "stop"}` — Aborts current streaming/tool task via `asyncio.Event`.
- `{"type": "reset_history"}` — Clears in-memory message history for current WebSocket connection.
- `{"type": "question_response", "response": "..." | [...]}` — User response to interactive question card.
- User Turn Payload: `{"content": "...", "map_context": {...}, "image": {...}, "chat_attachments": [...], "history": [...], "api_key": "...", "google_maps_api_key": "..."}`.

## The Action Contract

Actions are declarative UI/cartographic operations. When dispatched from backend tools or `ToolResult.map_action`, `chat.py` sends `{"type": "action", "action": "<name>", "payload": {...}}` over WebSocket.

Supported Actions:
```
fly_to · fit_bounds · add_marker · add_markers · clear_markers
draw_line · draw_polygon · draw_circle · add_geojson · add_geojson_file
highlight_features · set_layer_style · style_layer · toggle_layer · remove_layer
save_bookmark · go_to_bookmark · export_region_clip · export_map_png · export_map_jpeg · export_map_pdf
switch_basemap · add_gee_layer · add_raster_overlay
```

On the frontend, `App.tsx:handleMapAction` routes actions:
- **Layer mutations** (`add_geojson`, `add_geojson_file`, `toggle_layer`, `remove_layer`) update React `layers` state.
- **Symbology updates** (`style_layer`, `set_layer_style`) compute and apply `LayerStyleSpec`.
- **AI markers & drawings** (`add_marker`, `draw_polygon`) are promoted to persistent GeoJSON layers.
- **Camera & viewport actions** (`fly_to`, `fit_bounds`, `highlight_features`) are queued onto `mapActions` and drained by `MapView.tsx`.

## The 7+1 Domain Hub Architecture

All domain tools implement `BaseDomainHub` in `packages/backend/domains/protocol.py`:

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

1. **`SpatialHub`** (`domains/spatial_hub.py`): GIS analysis (`gis_buffer`, `gis_centroid`, `gis_area`, `gis_convex_hull`, `gis_intersection`, `gis_difference`, `gis_clip`, `gis_dissolve`, `gis_spatial_join`, `gis_nearest`), OSM boundaries (`osm_boundary`, `osm_boundary_union`), DataMeet catalog, WMS services, and Spatial Registry tools (`list_polygons`, `get_polygon`, `check_polygon_overlap`, `calculate_land_budget`).
2. **`MobilityHub`** (`domains/mobility_hub.py`): Street networks (`fetch_street_network`, `analyze_street_network`), Dijkstra/freight routing (`find_shortest_path`, `find_freight_route`, `route_multi_stop`), GTFS transit (`import_gtfs_feed`, `analyze_gtfs_service`, `analyze_gtfs_schedules`, `analyze_transit_catchment`), ITS signal timing (`optimize_traffic_signal`, `analyze_parking_requirements`), and OD flows (`import_od_matrix`, `generate_gravity_od_matrix`, `calculate_mode_choice`, `visualize_od_flows`).
3. **`EnvironmentHub`** (`domains/environment_hub.py`): GEE satellite indices (`get_gee_layer`, `get_population_layer`, `get_dem_layer`, `get_land_cover`, `analyze_lulc_change`, `analyze_land_use_zonal_stats`, `extract_land_use_polygons`, `get_ndvi_layer`), Open-Meteo (`get_weather`, `get_air_quality`), Google Solar/Elevation (`get_elevation`, `get_air_quality_google`, `get_solar_building`), and emissions (`estimate_scenario_emissions`).
4. **`PlanningHub`** (`domains/planning_hub.py`): Zoning compliance (`analyze_zones`, `detect_zone_overlaps`), document georeferencing (`georeference_active_document`), and feature digitization (`digitize_image_features`).
5. **`DemographicsHub`** (`domains/demographics_hub.py`): WorldPop population metrics (`get_demographics`), cohort-component forecasting (`project_population`), and employment density projections (`project_employment`).
6. **`PlacesHub`** (`domains/places_hub.py`): Google Places Platform (`places_autocomplete`, `place_details`, `nearby_places`, `nearby_places_in_polygon`, `places_density`) and Overture 3D buildings (`overture_places_search`, `overture_buildings_search`).
7. **`ScenariosHub`** (`domains/scenarios_hub.py`): Scenario generation (`generate_planning_scenarios`) and MCDA comparison (`compare_scenarios`).
8. **`UtilityHub`** (`domains/utility_hub.py`): `web_search`, `geocode`, `measure_distance`, `measure_area`, `create_plot`, `ask_question`, and artifact management (`create_artifact`, `list_artifacts`, `get_artifact`).

## Centralized Spatial & Polygon Registry (`tools/spatial_registry.py`)

Authoritative singleton tracking all polygon geometries in the workspace:
- **IoU Deduplication ($\ge 90\%$):** Calculates spatial Intersection-over-Union and normalized name similarity ($\ge 0.85$). When a match is found, reuses existing layer, highlights it, and returns exact metrics without duplicate layers.
- **Geodesic Accuracy:** Uses `pyproj.Geod(ellps="WGS84")` for ellipsoidal surface area ($\text{m}^2$, $\text{ha}$, $\text{km}^2$), perimeter, and centroid math.
- **Real-Time Layer Sync:** `sync_from_map_layers` continuously synchronizes with active map state on every chat turn.

## Task Pipeline & Multi-Format Export Engine

- **Task Pipeline Orchestrator (`tools/task_pipeline.py`):** Enforces dependency order when the AI generates multi-asset documents:
  1. Priority Queue Phase: Generates map snapshots (`export_map_jpeg`) and charts (`create_plot`), reserving artifact IDs and file paths.
  2. Document Heap Phase: Replaces placeholder image syntax with verified file paths before executing `create_artifact`.
- **Multi-Format Export Engine (`tools/export_engine.py`):** Pure Python document compilation engine supporting 8 formats: `PDF` (ReportLab `%PDF-1.4`), `Word (.docx)` (python-docx), `HTML` (markdown), `PNG`, `JPEG` (Pillow), `Excel (.xlsx)` (openpyxl), `JSON`, and `TXT`.

## RAG Indexing & Document Semantic Search (`routers/rag.py`)

- Parses workspace documents (`.pdf`, `.docx`, `.txt`, `.md`) into overlapping text chunks (1000 chars, 200 char overlap).
- Fetches OpenAI vector embeddings using `text-embedding-3-small` in batches of 100.
- Writes index to `<workspace>/.disha/rag_index.json`.
- Performs real-time cosine similarity search over indexed chunks and injects top-4 relevant segments into `SYSTEM_PROMPT` on every chat turn.

## Complete HTTP API Surface

| Method | Path | Router | Purpose |
|---|---|---|---|
| GET | `/health` | `main.py` | Liveness probe |
| GET | `/api/files?path=...&workspace=...` | `files.py` | List workspace files (path-restricted to workspace root) |
| GET | `/api/files/convert/probe` | `files.py` | Probe vector file and detect CSV lat/lng columns |
| POST | `/api/files/convert` | `files.py` | Convert shapefile/GPKG/KML/KMZ/GPX/CSV → WGS84 GeoJSON |
| WS | `/api/chat/ws` | `chat.py` | Agentic loop, streaming tokens, tools, map actions, deep research |
| POST | `/api/chat/validate-key` | `chat.py` | Verify OpenAI API key validity |
| GET | `/api/chat/key-status` | `chat.py` | Check configured status of OpenAI and Google Maps keys |
| GET | `/api/artifacts` | `artifacts.py` | List artifacts for active workspace |
| POST | `/api/artifacts` | `artifacts.py` | Create text/markdown artifact |
| POST | `/api/artifacts/upload` | `artifacts.py` | Multipart upload for image/figure artifacts |
| POST | `/api/artifacts/reorder` | `artifacts.py` | Update artifact ordering |
| GET | `/api/artifacts/{id}` | `artifacts.py` | Get artifact row |
| GET | `/api/artifacts/{id}/download` | `artifacts.py` | Download artifact in native format |
| GET | `/api/artifacts/{id}/docx` | `artifacts.py` | Download artifact as Word document |
| GET | `/api/artifacts/{id}/pdf` | `artifacts.py` | Download artifact as PDF document |
| GET | `/api/artifacts/{id}/latex` | `artifacts.py` | Download artifact as LaTeX document |
| GET/POST | `/api/artifacts/{id}/export` | `artifacts.py` | Export artifact across 8 formats via `export_engine.py` |
| POST | `/api/chat/internal_action` | `chat.py` | Internal loopback bridge: dispatches MapActions from OpenCode tool runs to active WebSockets |
| POST | `/api/chat/internal_question` | `chat.py` | Internal loopback bridge: dispatches interactive questions from OpenCode to WebSockets |
| PUT | `/api/artifacts/{id}` | `artifacts.py` | Update artifact title, content, or metadata |
| DELETE | `/api/artifacts/{id}` | `artifacts.py` | Delete artifact |
| GET | `/api/geocode?query=...` | `geocode.py` | Forward geocoding (Google → Photon → Nominatim) |
| GET | `/api/geocode/reverse?lat=...&lng=...` | `geocode.py` | Reverse geocoding (Nominatim) |
| GET | `/api/streetview/meta?lat=...&lng=...` | `streetview.py` | Keyless Street View metadata lookup (`streetlevel`) |
| GET | `/api/streetview/pano?lat=...&lng=...` | `streetview.py` | Keyless equirectangular JPEG panorama download |
| GET | `/api/wms/featureinfo` | `wms.py` | WMS GetFeatureInfo CORS proxy |
| GET | `/api/wms/capabilities` | `wms.py` | WMS GetCapabilities CORS proxy |
| POST | `/api/gee/credentials` | `gee.py` | Save or clear Google Earth Engine service account credentials |
| GET | `/api/gee/tiles/{map_id}/{z}/{x}/{y}` | `gee.py` | GEE XYZ tile proxy with OAuth2 Bearer token authentication |
| POST | `/api/scenarios/analyze` | `scenarios.py` | Fetch OSM metrics for Scenario Builder bounding box |
| POST | `/api/scenarios/generate` | `scenarios.py` | Generate structured planning scenarios |
| POST | `/api/scenarios/compare` | `scenarios.py` | Compare scenarios with MCDA scoring |
| POST | `/api/scenarios/save-artifact` | `scenarios.py` | Save scenario comparison report as an artifact |
| GET | `/api/rag/status` | `rag.py` | Check document indexing status in workspace |
| POST | `/api/rag/index` | `rag.py` | Chunk document, fetch embeddings, and write `rag_index.json` |
| GET | `/api/diagnostics` | `diagnostics.py` | Run system self-checks (OpenAI, Google, OSM, OSRM, weather, GIS libs) |

## OpenCode Agent Integration

Disha integrates the OpenCode agent runtime to provide autonomous, multi-step agent execution, context compaction, and session management while preserving Disha's native desktop UI, domain hubs, cartography, and task pipeline.

```
Frontend (Electron / React 19 / MapLibre)
               │
               │ WebSocket (/api/chat/ws)
               ▼
     FastAPI Backend (:8765)
               │
       ┌───────┴──────────────────────────────┐
       │ (Feature Flag: USE_OPENCODE=true)    │
       ▼                                      ▼
OpenCode Orchestrator             Legacy _run_agent() Fallback
(llm/opencode/orchestrator.py)    (USE_OPENCODE=false)
       │
       │ HTTP / SSE (/session, /event)
       ▼
Headless OpenCode Server (:4096)
       │
       │ stdio JSON-RPC 2.0 (MCP Protocol)
       ▼
Disha MCP Server (llm/opencode/mcp_server.py)
       │
       ├─► 24 Map Actions (fly_to, draw_polygon, export_map_jpeg) ──► HTTP Bridge ──► WebSocket
       ├─► 7+1 Domain Hubs (Spatial, Mobility, Environment, etc.)
       ├─► Google Earth Engine (GEE) Analytics
       ├─► Interactive Tools (ask_question, create_plot, create_artifact)
       └─► Spatial Registry (IoU deduplication, geodesic metrics)
```

### Key Ownership Matrix

| Responsibility | Owner | Implementation |
|---|---|---|
| **Agent Execution & Multi-Step Loop** | OpenCode | Headless `opencode serve` runtime |
| **Active Session & Conversation History** | OpenCode | `opencode_session_manager.py` (cached to `<workspace>/.disha/opencode_sessions.json`) |
| **Context-Window Compaction** | OpenCode | Native OpenCode context management |
| **Tool Selection & Reasoning** | OpenCode | OpenCode LLM orchestration |
| **UI, Frontend & Map Rendering** | Disha | React 19, MapLibre GL canvas, ChatPanel |
| **WebSocket Contract & Event Streaming** | Disha | FastAPI `/api/chat/ws` (`stream`, `tool_use`, `action`, `ask_question`, `end`) |
| **Domain Logic & GEE Analytics** | Disha | 7+1 Domain Hubs, GEEServer, NetworkX, DuckDB |
| **Map Actions & Visual Sync** | Disha | `action_utils.py` & `/internal_action` loopback endpoint |
| **Document Compilation & Task Pipeline** | Disha | `task_pipeline.py` & `artifact_store.py` |
| **RAG Retrieval & Spatial Optimization** | Disha | `routers/rag.py` & Token-Optimized Spatial Context Engine |

## Core Geospatial & Visualization Principles

### 1. Autonomous Execution & Implicit Authorization
- **Automatic Intermediate Operations:** When the user requests a document, report, map, plot, analysis, or other artifact that requires preliminary data retrieval or spatial calculation, the agent executes all intermediate operations automatically.
- **No Unnecessary Confirmation Prompts:** Do not stop to ask the user to confirm ("proceed", "yes") when requested outputs and geographic scope are clear. Do not ask users to choose administrative levels, datasets, or GIS tools unless genuinely ambiguous and materially affecting results.
- **Implicit Authorization:** The user's request to create a final deliverable implicitly authorizes all intermediate data retrieval, spatial analysis, visualization, and artifact-generation steps. Never invent figures or statistics; obtain them via available tools.

### 2. Geographic Interpretation & Boundary Containment
- **Containment Intent:** When a user asks for features "in" a named geographic place (e.g. "amenities in Mohali", "schools in Sector 17"), the system resolves the place boundary (`osm_boundary` / polygon geometry) and spatially filters the requested features to that actual boundary (using `nearby_places_in_polygon`, `gis_clip`, `gis_spatial_join`, or `gis_point_in_polygon`).
- **No Extent Substitution:** The geographic constraint implied by the user's wording must be preserved during tool selection, data retrieval, spatial processing, and visualization. Do not substitute a broad search extent, bounding box, viewport, or proximity radius search for an actual geographic boundary when the user's intent is containment.
- **Inferred Operations:** Intermediate GIS operations (boundary resolution, clipping, intersection, containment, or filtering) are inferred and performed internally without requiring the user to explicitly specify them or hardcoding places.

### 3. Document Visualization & Output Preservation
- **Independent Output Generation:** When the user requests multiple geographic analyses or visual outputs, independently produce each requested output and maintain its geographic and semantic scope. Do not combine, omit, substitute, or simplify requested outputs merely for implementation convenience.
- **Distinct Visuals per Heading:** When the user requests separate visuals under separate headings in a document or report, generate a separate distinct visual for each heading; do not combine or merge them unless explicitly requested.
- **Visual Isolation & Context:** Each visual must contain only the layers and information relevant to its corresponding request, with only necessary geographic context. Do not carry unrelated layers, markers, or visualizations from one requested section into another (clear or toggle off unrelated layers before capturing each section's map snapshot).
- **Document Asset Sequencing:** When compiling a document, infer the appropriate document structure from the user's requested headings and content, and generate all required underlying maps, plots, statistics, and other artifacts before assembling the document.

## Electron IPC Surface (`apps/desktop/src/preload/index.ts`)

Renderer interacts with Electron main via `window.electronAPI`:
- `selectWorkspace()`: Opens native folder dialog.
- `readDirectory(dirPath)`: Lists directory contents.
- `readFile(path)` / `writeFile(path, content)`: Text file I/O.
- `readFileBase64(path)`: Binary base64 reading for PDF rasterization and vision.
- `openFile({ filters })`: File picker with extension filters.
- `getLastWorkspace()` / `setLastWorkspace(path)`: Last workspace persistence.
- `getModels()` / `getCurrentModel()` / `switchModel(modelId)`: Model configuration management.
- `onAppBeforeQuit(callback)`: Flushes project saves before window unload.

## Persistence Subsystem

| Data | Location | Storage Format |
|---|---|---|
| Project State | `<workspace>/project.json` | JSON (layers, style specs, camera view, conversations, bookmarks, basemap) |
| Chat-Generated Layers | `<workspace>/.disha/layers/<id>.geojson` | EPSG:4326 GeoJSON files |
| OpenCode Session Mappings | `<workspace>/.disha/opencode_sessions.json` | JSON mapping of Disha conversation IDs to OpenCode session IDs |
| Workspace RAG Index | `<workspace>/.disha/rag_index.json` | JSON embeddings and document chunks |
| Workspace GEE Key | `<workspace>/.disha/ee-service-account.json` | Service Account JSON |
| Last-Opened Workspace | `userData/last-workspace.json` (prod) or `.tmp/last-workspace.json` (dev) | JSON string path |
| Artifacts Catalog | SQLite at `<workspace>/.disha/disha.db` (or `~/.disha/disha.db`) | SQLite database (WAL mode) |
| Artifact Physical Files | `<workspace>/.disha/artifacts_store/` (or `~/.disha/artifacts_store/`) | Physical binary & text files (`.png`, `.jpg`, `.pdf`, `.docx`) |
| HTTP Upstream Cache | SQLite `cache.db` (+ in-memory LRU) | SQLite key-value cache |
| Model Configuration | `packages/backend/model_config.json` | JSON (`{"model": "gpt-4o"}`) |

## Environment Variables

| Variable | Read In | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | `routers/chat.py`, `routers/rag.py`, `routers/diagnostics.py` | OpenAI Chat Completions, Embeddings, and Responses API |
| `OPENAI_MODEL` | `tools/config.py` | Fallback model if `model_config.json` is missing (default: `gpt-5.4-mini`) |
| `USE_OPENCODE` | `main.py`, `routers/chat.py` | Feature flag: `true` to enable OpenCode runtime orchestration, `false` for legacy agent loop |
| `OPENCODE_PORT` | `llm/opencode/server_manager.py` | Port for headless OpenCode server (default: `4096`) |
| `OPENCODE_HOST` | `llm/opencode/server_manager.py` | Hostname for headless OpenCode server (default: `127.0.0.1`) |
| `GOOGLE_MAPS_API_KEY` | `tools/google.py`, `routers/diagnostics.py` | Google Places Platform, Elevation, Air Quality, Solar (optional) |
| `GOOGLE_EARTH_ENGINE_CREDS` / `GEE_CREDENTIALS` | `main.py`, `routers/gee.py`, `mcp_servers/gee_server.py` | GEE Service account JSON or file path |
| `DISHA_DB` | `database.py` | Override global artifacts SQLite path |
| `LOG_LEVEL` / `DEBUG` | `main.py` | Backend logging verbosity |

## Run & Build Commands

```bash
# Development (starts backend uvicorn :8765 and electron-vite renderer)
pnpm dev

# Run tests
cd packages/backend
.buildenv/Scripts/pytest.exe tests/ -v

# Typecheck & Bundler Build Verification
pnpm --filter @disha/desktop exec tsc --noEmit
pnpm --filter @disha/desktop build

# Package full distribution installer
pnpm package
```
