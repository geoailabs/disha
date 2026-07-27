# Disha — Architecture & Features

A geospatial-first AI-driven IDE for urban planners. The user chats with an LLM that drives a live MapLibre map, runs OSM / Overture / Google / GIS queries, drafts zoning, imports real GIS files, styles layers, exports publication-ready figures, and saves planning artifacts — all inside an offline-capable Electron desktop app.

This document is split into two halves:

- **Part 1 — For Users.** What the app does and how to use it.
- **Part 2 — For Developers.** How the system is wired together.

If you only want the orientation needed to make code changes, jump to Part 2.

---

# Part 1 — For Users

## What it is

A desktop app (macOS / Windows / Linux) that combines four panes:

| Pane | Purpose |
|---|---|
| **Map** (center, Map mode) | Interactive MapLibre canvas with switchable basemaps, layer rendering, data-driven symbology + labels, drawing tools, marker pins, and a live legend |
| **Document view** (center, Document mode) | Drop in a planning PDF or map image and have the AI analyze it |
| **Left panel** | Files · Layers (+ Symbology / Attribute editors) · Bookmarks · Export · Zoning legend |
| **Right panel** | Chat · Artifacts |

You toggle between **Map** and **Document** modes from the title bar. Map mode is the primary surface; Document mode is for one-off analysis of external planning documents.

## Workspace

Open a folder via the title-bar button. The app:

- Lists files in **Files**. Click a `.geojson` to load it; click a `.shp` / `.gpkg` / `.kml` / `.kmz` / `.gpx` / `.csv` to import it (converted to WGS84 GeoJSON inside the workspace, then loaded).
- Auto-saves a `project.json` in the workspace folder containing map state, layers (with their styling), conversations, bookmarks, and basemap.
- Materializes any chat-generated layers into `<workspace>/.disha/layers/<id>.geojson` so they survive a reload.
- Remembers the last workspace and re-opens it on next launch.

Without a workspace open, the app still works for ad-hoc exploration, but nothing persists.

## Map mode features

### Layers

- Click a `.geojson` file in the Files pane to load it as a styled vector layer.
- The **Layers** pane shows count, visibility toggle, zoom-to, remove, and buttons to open the **Symbology** editor and **Attribute** table for a layer.
- AI-generated layers (from chat tool calls) appear here automatically.

### Vector import

- Clicking a `.shp`, `.gpkg`, `.kml`, `.kmz`, `.gpx`, or `.csv` file converts it to a WGS84 GeoJSON written alongside the source in the workspace, then loads it.
- The source CRS is auto-detected and reprojected to EPSG:4326; CSVs are turned into points from auto-detected lat/lng columns.
- Conversion runs on the backend (DuckDB `spatial` / `ST_Read` + `ST_Transform`) — requires an open workspace.

### Symbology & labels

Style any layer by its data, from the Symbology panel or by asking the assistant:

- **Categorized** — one color per distinct value of a string property (e.g. `zone_code`, `land_use`). Zone-named properties seed from the built-in zone palette.
- **Graduated** — a choropleth over a numeric property (e.g. `population`, `density`), with equal-interval or quantile class breaks (2–9 classes) and a named color ramp.
- **Labels** — draw any property as on-map text with configurable size/color (collision-aware, zoom-gated, capped at 3,000 features).

A live **Legend** overlay renders automatically for any visible categorized or graduated layer.

### Drawing & attributes

- Toolbar draw modes for **point**, **line**, and **polygon**. Click to place vertices, double-click / Enter to finish, Escape to cancel, Backspace to undo a vertex.
- A finished shape becomes a real layer and opens the **Attribute table** so you can tag it (e.g. set `zone_code`) before styling.
- The Attribute table edits any layer's properties — add/rename/delete columns, edit cells, delete rows.

### Basemaps

Seven free raster basemaps, switchable from the map UI: Street (OSM), Satellite (Esri World Imagery), Dark / Light (CartoDB), Terrain (OpenTopoMap), Topo (Esri), Humanitarian (OSM-HOT). No API key required.

### Bookmarks

Save the current map extent as a named bookmark. The assistant can also bookmark for you (`save_bookmark`) and fly to one (`go_to_bookmark`).

### Export

All export paths bake the same decorations (title block, legend, scale bar, north arrow, attribution) onto the figure:

- **Download PNG / PDF**: a decorated snapshot of the current map (PDF is landscape A4).
- **Save PNG / PDF to Artifacts**: same figure, stored as an image artifact.
- **Layer → GeoJSON file**: per-layer download.
- **Clip to current extent**: clip every loaded layer to the viewport and save as one GeoJSON layer in the workspace.
- **Save by region / boundary**: search an OSM boundary (Nominatim), preview it on the map, then clip all layers to it and save.

### Zoning

The Zones panel shows a built-in legend (R1, R2, C1, I1, G, MX, INST). Load a GeoJSON whose features have a `zone_code` property and ask the assistant to `analyze_zones` (per-zone area, density) or `detect_zone_overlaps` (where two different zones cover the same ground).

### Street View

Right-click anywhere on the map for a context menu: drop a marker (reverse-geocoded to an address), ask the chat about the location, or open an embedded 360° panorama. Street View is **keyless** — the nearest panorama is found and downloaded server-side via the `streetlevel` library and rendered with pannellum.

## Document mode

Drop in or open a planning document:

- **Image formats** (PNG, JPG, JPEG, WEBP, GIF, BMP) — sent directly to the model.
- **PDF** — rasterized client-side with `pdfjs-dist` to a capped 2200-pixel-longer-axis PNG and sent as vision input. Multi-page navigation is supported.

The AI is given a planning-analyst persona and can identify land use, zoning areas, transportation networks, infrastructure, density patterns, boundaries, and labels. Document mode also bridges to the live map — the model can `fly_to`, drop markers, run `osm_search`, and save findings as artifacts even while you're chatting about a document.

## AI chat

The chat panel on the right is the primary control surface. You can:

- Have multiple conversations (left rail of the chat panel). Each is persisted into `project.json`.
- Ask the assistant to navigate, fetch data, measure, draw, style layers, analyze overlaps, or generate a deep-research report.
- See tool calls inline as they execute — every OSM query, GIS operation, or map action is visible in the conversation.
- Watch **deep-research** progress: when you ask for a report, each web search step streams in and a cited Markdown report comes back (downloadable as `.md` or PDF).

Streaming text uses a WebSocket; replies appear token-by-token.

### What the assistant can do

| Capability | Tools |
|---|---|
| **Navigate** | `fly_to`, `fit_bounds`, `go_to_bookmark` |
| **Annotate** | `add_marker`, `add_markers`, `clear_markers`, `draw_line`, `draw_polygon`, `draw_circle` |
| **Layers & style** | `add_geojson`, `toggle_layer`, `remove_layer`, `set_layer_style` (flat), `style_layer` (categorized/graduated + labels), `highlight_features` |
| **Bookmarks & clip** | `save_bookmark`, `go_to_bookmark`, `export_region_clip` |
| **OSM data** | `osm_search`, `osm_boundary`, `osm_boundary_union`, `osm_reverse_geocode`, `osm_route_overview` |
| **Overture Maps** | `overture_places_search`, `overture_buildings_search` |
| **Google Places** *(needs key)* | `places_autocomplete`, `place_details`, `nearby_places`, `nearby_places_in_polygon`, `places_density` |
| **Google environment** *(needs key)* | `get_elevation`, `get_air_quality_google`, `get_solar_building` |
| **GIS analysis** | `gis_buffer`, `gis_centroid`, `gis_area`, `gis_convex_hull`, `gis_point_in_polygon`, `gis_bounding_box`, `gis_union` |
| **GIS overlay & relational** | `gis_intersection`, `gis_difference`, `gis_clip`, `gis_dissolve`, `gis_nearest`, `gis_spatial_join` |
| **Zoning** | `analyze_zones`, `detect_zone_overlaps` |
| **Demographics** | `get_demographics` (WorldPop, OSM fallback) |
| **Weather** | `get_weather`, `get_air_quality` |
| **Search & geocode** | `web_search`, `geocode`, `measure_distance`, `measure_area` |
| **Artifacts** | `create_artifact`, `list_artifacts`, `get_artifact` |
| **Reports** | `generate_report` (deep research) |

The current map state — viewport bounds, visible layers (with feature counts, property names, geometry data for small layers, and a styling summary), saved bookmarks — is appended to every prompt, so the assistant is always aware of what you're looking at.

## Artifacts

Long-form notes and analyses the assistant generates (or you ask it to save) live in a SQLite database and appear in the **Artifacts** panel: title, content, type, format (markdown / table / geojson / image), timestamps, plus full CRUD via the panel's HTTP API. Exported figures and GeoJSON can be saved as artifacts, and a GeoJSON artifact can be re-added to the map.

---

# Part 2 — For Developers

## Tech stack

| Layer | Stack |
|---|---|
| Desktop shell | Electron |
| Renderer | React 19 + Vite (electron-vite) + TypeScript |
| Map | MapLibre GL + Turf.js + pannellum |
| Backend | Python 3.11+, FastAPI, uvicorn |
| LLM | OpenAI Chat Completions (streaming, tool calling) + Responses API (`o4-mini-deep-research`) |
| Geo APIs | Overpass, Nominatim, OSRM, Open-Meteo, Overture, WorldPop, Photon, Google Maps Platform |
| Geometry | Shapely + pyproj (server, geodesic), Turf.js (client) |
| Vector ingestion | DuckDB `spatial` (`ST_Read` + `ST_Transform`) |
| Storage | SQLite (artifacts + HTTP cache) + JSON files in workspace (project state) |
| Packaging | electron-builder + PyInstaller (frozen backend binary) |

## Top-level layout

```
.
├── apps/desktop/                  Electron + React frontend
│   ├── src/main/index.ts          Electron main: window, IPC, backend spawn, model switch
│   ├── src/preload/index.ts       contextBridge IPC surface
│   └── src/renderer/              React UI
│       ├── App.tsx                State container; map ↔ chat ↔ panels
│       ├── types.ts               MapAction union, LayerStyleSpec, basemaps, zone presets
│       ├── lib/
│       │   ├── classify.ts        Color ramps, class breaks, category palettes
│       │   ├── compose-figure.ts  Publication figure compositor (title/legend/scale/arrow)
│       │   └── legend-data.ts     buildLegendEntries — shared by Legend + export
│       └── components/            MapView, ChatPanel, SymbologyPanel, AttributeTable,
│                                  Legend, ExportPanel, StreetViewDialog, FileTree, …
├── packages/backend/              Python FastAPI backend
│   ├── main.py                    App + CORS + router includes
│   ├── cli.py                     PyInstaller entry point (uvicorn launcher)
│   ├── database.py                SQLite + migrations
│   ├── routers/
│   │   ├── chat.py                ★ Agentic loop, tool registry, action contract, deep research
│   │   ├── files.py               Workspace listing + vector convert/probe
│   │   ├── artifacts.py           Artifact CRUD + upload + download
│   │   ├── geocode.py             Forward + reverse geocode proxy
│   │   └── streetview.py          Keyless Street View metadata + panorama
│   ├── mcp_servers/               One class per domain (OSM, GIS, weather, zoning, demographics,
│   │                              Overture, Google Places, Google env, GEE, OD flow, network routing,
│   │                              public catalogs/DataMeet, GTFS transit, WMS, scenarios)
│   └── tools/
│       ├── geo.py                 Geodesic area/perimeter/buffer (pyproj WGS84)
│       ├── vector_convert.py      Shapefile/GPKG/KML/KMZ/GPX/CSV → WGS84 GeoJSON
│       ├── utility.py             UtilityServer (search, geocode, measure, artifacts)
│       ├── google.py              Google Maps Platform client + has_key()
│       ├── http.py                Shared httpx client (timeouts, backoff, rate limits)
│       ├── cache.py               Two-tier TTL cache (LRU + SQLite)
│       ├── artifact_store.py      Artifact persistence (row + on-disk file)
│       ├── worldpop.py            WorldPop population API client
│       └── config.py              Model selection (model_config.json / OPENAI_MODEL)
├── ARCHITECTURE.md                This file
├── CLAUDE.md                      Orientation for AI coding agents
└── README.md                      Setup & build commands
```

## Process model

```
Electron main process (apps/desktop/src/main/index.ts)
  ├─ creates BrowserWindow → loads renderer
  ├─ exposes IPC (file dialogs, read dir, base64 read, switch model) via preload
  └─ in production only: spawns the PyInstaller-frozen backend binary
                          (`Resources/backend/backend --port 8765`),
                          polling GET /health (up to 30×, 500ms) before opening the window

Renderer (Chromium) talks to:
  ├─ Backend  ws://localhost:8765/api/chat/ws    ← streaming chat & tool calls
  ├─ Backend  http://localhost:8765/api/*        ← files, artifacts, geocode, streetview
  └─ Electron main via window.electronAPI       ← OS access only
```

In **dev mode** (`pnpm dev`), Electron's `startBackend` is a no-op — `pnpm dev:backend` runs uvicorn separately so you get hot reload on both sides. The backend port (`8765`) is hardcoded in both the main process and `cli.py`.

## Three communication channels

| Channel | Endpoint / API | Purpose |
|---|---|---|
| **WebSocket** | `ws://localhost:8765/api/chat/ws` | Streaming chat tokens, tool-use events, action dispatch, deep-research progress |
| **HTTP** | `/api/files`, `/api/artifacts`, `/api/geocode`, `/api/streetview`, `/health` | File listing/convert, artifact CRUD/upload/download, geocode, Street View |
| **Electron IPC** | `window.electronAPI.*` | Local OS only — file picker, read dir, base64-read for vision, last-workspace, model switch |

CORS is locked to loopback origins (`file://`, `app://`, `http(s)://localhost`, `127.0.0.1`, `[::1]`) — see `packages/backend/main.py`.

## The agentic loop

The heart of the AI behavior lives in `packages/backend/routers/chat.py:_run_agent`. For each user turn:

```
1. Send messages + tool defs to OpenAI (streaming).
2. As deltas arrive:
     - text deltas → forwarded to frontend as {"type": "stream", "content": …}
     - tool-call deltas → accumulated in tool_calls_acc keyed by index
3. When the stream ends, append the assistant message to history.
4. If the model called tools:
     a. Send {"type": "tool_use", "tool", "args"} per call.
     b. Execute each tool via _execute_tool (action OR MCP server OR deep research).
     c. Append tool results back into history.
     d. Loop back to step 1.
5. Otherwise, break. Send {"type": "end"}.
```

A safety cap of `max_rounds = 10` prevents runaway loops. Tool-call argument JSON that gets cut off mid-stream is returned as a structured error so the next turn stays well-formed (every `tool_call_id` must have a matching tool message).

The connection holds a per-WebSocket message history. The renderer can also pass `history` on a turn to replay a prior conversation — this is how conversation switching and model switching work without losing context.

### Deep research

`generate_report` is special-cased in `_execute_tool`: it runs `_run_deep_research`, which calls the OpenAI **Responses API** (`o4-mini-deep-research`) with the `web_search_preview` tool (up to 30 searches) and streams progress over the WebSocket as `research_start` → `research_step` (one per query) → `research_report` (markdown + citations) → `research_done`, with `research_heartbeat` keep-alives. `ChatPanel` renders this in a dedicated research bubble with `.md` / PDF download.

## The action contract

Some tools are **map actions** rather than data fetches. When the model calls one, the backend doesn't compute anything — it just forwards the call to the renderer:

```json
{ "type": "action", "action": "fly_to", "payload": { "lat": 30.7, "lng": 76.8, "zoom": 13 } }
```

The set lives in `_ACTION_TOOLS` (`routers/chat.py`):

```
fly_to · fit_bounds
add_marker · add_markers · clear_markers
draw_line · draw_polygon · draw_circle · add_geojson
highlight_features · set_layer_style · style_layer · toggle_layer · remove_layer
save_bookmark · go_to_bookmark · export_region_clip
```

On the frontend, `App.tsx:handleMapAction` routes each action:

- **Layer mutations** (`add_geojson`, `toggle_layer`, `remove_layer`) → mutate the canonical `layers` React state directly so they appear in `mapContext` on the next turn.
- **`style_layer`** → computes a `LayerStyleSpec` (category palette or numeric breaks read from the layer's feature values) and stores it on the layer; `MapView` translates it into MapLibre paint expressions and a label `symbol` layer.
- **AI markers** → merged into a single `"AI Markers"` Point layer (so they survive reload, show in `mapContext`, and persist to `project.json`).
- **AI-drawn shapes** (`draw_line`, `draw_polygon`, `draw_circle`) → promoted to real layers with `source: "ai_draw"` so the assistant can reference them next turn.
- **Bookmarks / region clip / refresh_artifacts** → handled in React.
- **Everything else** (`fly_to`, `fit_bounds`, `set_view`, `highlight_features`, `set_layer_style`) → queued onto `mapActions[]`, consumed by `MapView.tsx`, drained via `onActionsProcessed`.

To add a new action you must touch all three of: backend tool def + dispatch (`chat.py`), `MapAction` union (`types.ts`), action switch (`MapView.tsx` and/or `App.tsx`). The `add-map-action` skill in `.claude/skills/` encodes the procedure.

## The MCP server pattern

Each domain server in `packages/backend/mcp_servers/` is a class with three things:

```python
class FooServer:
    description: str
    tool_names: set[str]                                # {"foo_x", "foo_y"}
    def get_declarations(self) -> list[ToolDeclaration]: ...
    async def execute(self, tool_name: str, args: dict) -> dict: ...
```

Servers live in `routers/chat.py:_servers` and their declarations are flattened into the OpenAI tool list by `_build_tools()`. There is **no external MCP stdio bridge** — the in-app chat is the only surface.

| Server | File | Tools |
|---|---|---|
| `OSMServer` | `osm_server.py` | `osm_search`, `osm_boundary`, `osm_boundary_union`, `osm_reverse_geocode`, `osm_route_overview` |
| `GISServer` | `gis_server.py` | `gis_buffer`, `gis_centroid`, `gis_area`, `gis_convex_hull`, `gis_point_in_polygon`, `gis_bounding_box`, `gis_union`, `gis_intersection`, `gis_difference`, `gis_clip`, `gis_dissolve`, `gis_nearest`, `gis_spatial_join` |
| `WeatherServer` | `weather_server.py` | `get_weather`, `get_air_quality` |
| `ZoningServer` | `zoning_server.py` | `analyze_zones`, `detect_zone_overlaps` |
| `DemographicsServer` | `demographics_server.py` | `get_demographics` (WorldPop 100m grid, OSM fallback), `project_population` |
| `OvertureServer` | `overture_server.py` | `overture_places_search`, `overture_buildings_search` (DuckDB over public S3 parquet) |
| `GooglePlacesServer` | `google_places_server.py` | `places_autocomplete`, `place_details`, `nearby_places`, `nearby_places_in_polygon`, `places_density` |
| `GoogleEnvironmentServer` | `google_environment_server.py` | `get_elevation`, `get_air_quality_google`, `get_solar_building` |
| `NetworkServer` | `network_server.py` | `fetch_street_network`, `analyze_street_network`, `find_shortest_path`, `find_freight_route`, `route_multi_stop`, `assign_traffic_flows` |
| `ODServer` | `od_server.py` | `import_od_matrix`, `generate_gravity_od_matrix`, `calculate_mode_choice`, `visualize_od_flows` |
| `ITSServer` | `its_server.py` | `optimize_traffic_signal`, `analyze_parking_requirements` |
| `EmissionsServer` | `emissions_server.py` | `estimate_scenario_emissions` |
| `GEEServer` | `gee_server.py` | `get_gee_layer`, `get_population_layer`, `get_dem_layer`, `get_land_cover`, `analyze_lulc_change`, `get_ndvi_layer`, `add_gee_layer` |
| `DataMeetServer` | `datameet_server.py` | `browse_datameet_catalog`, `import_datameet_boundary`, `import_public_dataset` |
| `GTFSServer` | `gtfs_server.py` | `import_gtfs_feed`, `analyze_gtfs_service` |
| `WMSServer` | `wms_server.py` | `add_wms_layer`, `list_wms_layers` |
| `ScenarioServer` | `scenario_server.py` | `generate_planning_scenarios`, `compare_scenarios` |
| `UtilityServer` | `tools/utility.py` | `web_search`, `geocode`, `measure_distance`, `measure_area`, `create_artifact`, `list_artifacts`, `get_artifact`, `georeference_active_document`, `digitize_image_features` |

`generate_report` (deep research) is registered directly in `_build_tools()`, not via a server.

Adding a domain tool means editing one server class — the flatten step picks it up automatically. Cross-cutting tools (search, geocode, measure, artifacts) belong in `UtilityServer`. The `add-mcp-tool` skill in `.claude/skills/` encodes the procedure.

The Google servers degrade gracefully: `tools/google.py` raises `GoogleUnavailable` when `GOOGLE_MAPS_API_KEY` is unset, and every Google tool catches it and returns `{"error": ..., "code": "upstream_unavailable"}`. The system prompt instructs the model to fall back to OSM/Overture in that case.

### Auto-display side effects

Some tools have post-execution side effects in `_execute_tool` so the model doesn't have to chain a second call. In each case the heavy geometry is rendered on the map and only a trimmed summary goes back to the model:

- `osm_search` with results → auto-`add_geojson`; summary = count + first 50 names/coords.
- `osm_boundary` / `osm_boundary_union` → auto-`add_geojson`, plus centroid, bbox, and (for unions) area breakdown + resolved/failed place lists go back to the model so it can chain `gis_buffer`, `gis_area`, etc.
- `overture_places_search` / `overture_buildings_search` → auto-`add_geojson`; trimmed summary.
- `nearby_places` / `nearby_places_in_polygon` (Google) → auto-`add_geojson`; trimmed summary + polygon-clip metadata.
- `osm_route_overview` → auto-`draw_line` with the route geometry.
- `gis_buffer`, `gis_convex_hull`, `gis_union` → auto-`add_geojson` of the result.
- `gis_intersection`, `gis_difference`, `gis_clip`, `gis_dissolve`, `gis_spatial_join` → result normalized to a FeatureCollection, auto-`add_geojson`, and collapsed to area/kept/group_count/points/joined summary fields.
- `create_artifact` → fires a `refresh_artifacts` action so the panel re-fetches.

## Geospatial conventions

- **The map and all GeoJSON in flight are EPSG:4326 lng/lat.**
- **Imported files are reprojected to 4326 on ingest.** `tools/vector_convert.py` detects the source CRS via DuckDB `ST_Read_Meta` and applies `ST_Transform(..., always_xy := true)` so authority-axis-order CRSs still emit GeoJSON-correct `[lng, lat]`. KML/GPX (always WGS84) and files with missing CRS metadata are assumed already lng/lat.
- **Area, perimeter, and buffer math are geodesic.** `tools/geo.py` uses pyproj's WGS84 ellipsoid (`Geod.geometry_area_perimeter`) for area/perimeter — handling holes and MultiPolygons natively — and projects to the local UTM zone for metric buffers. `gis_area`, `measure_area`, and the boundary-union area breakdown all route through it. Accurate at any latitude.
- **Tile sources are free raster XYZ.** No Mapbox token, no PMTiles, no MBTiles. Defined in `apps/desktop/src/renderer/types.ts:BASEMAPS`.
- **OSM data path:** Overpass API → ring-merge for ways → GeoJSON Feature. Boundary fetches additionally fall through to Nominatim with `polygon_geojson=1`.
- **Overture data path:** DuckDB queries the public Overture S3 parquet release directly; first query per region is a cold scan (1–2 min), then cached.
- **Frontend geometry ops use Turf.js** (`@turf/turf`) — e.g. clip-to-bbox, point-in-polygon, circle generation, bbox for auto-fit.

## Symbology & legend (frontend)

`LayerStyleSpec` (in `types.ts`) is a serializable description of a layer's styling — it lives on the layer and in `project.json`. Three pieces consume it:

- **`MapView.tsx`** translates it into MapLibre paint expressions: a `match` expression for categorized mode, a `step` expression for graduated mode, both wrapped in `coalesce` so per-feature color overrides win. Labels become a `symbol` layer (`text-field` from a property, collision detection, zoom-gated, capped at 3,000 features).
- **`lib/classify.ts`** computes the inputs: `computeBreaks` (equal-interval / quantile), `buildCategories` (distinct values → colors, zone-aware), `rampColorsForClasses`, and the `COLOR_RAMPS` palettes.
- **`lib/legend-data.ts:buildLegendEntries`** is the single source of truth for legend content, used by both the live `Legend` overlay and the export compositor so they never drift.

Both the AI path (`style_layer` → `App.tsx:buildStyleSpec`) and the manual `SymbologyPanel` write the same `LayerStyleSpec`.

## Export (frontend)

`lib/compose-figure.ts:composeFigure` paints a publication-ready figure onto a fresh canvas from the live MapLibre canvas: title band, map image, Web-Mercator-accurate scale bar, bearing-aware north arrow, legend card (from `buildLegendEntries`), and attribution footer — no extra runtime deps. (MapLibre is created with `preserveDrawingBuffer: true` so the canvas is readable.) All four export paths in `App.tsx` (PNG/PDF download, PNG/PDF to artifact) share it; PDF wraps it with `jspdf` on landscape A4.

## Frontend state

Pure React `useState`/`useRef`. No Zustand, no Redux, no Context. All state lives in `App.tsx` and flows down as props:

```
App.tsx state:
  appMode               'map' | 'document'
  workspacePath         folder absolute path or null
  layers                GeoJSONLayer[]   ← canonical layer store (data + styleSpec)
  mapViewState          { center, zoom, bearing, pitch }
  mapBounds             current viewport
  basemap               key into BASEMAPS
  conversations         Conversation[]   ← persisted in project.json
  bookmarks             MapBookmark[]
  mapActions            queue → drained by MapView
  stylingLayerId        layer open in SymbologyPanel
  attrLayerId           layer open in AttributeTable
  artifactsRevision     bump to force ArtifactsPanel refresh
```

`MapView` exposes a ref (`MapViewHandle`) for canvas access (used for PNG/PDF export). `mapActions` is a queue array; `MapView` processes and clears via `onActionsProcessed`. **Don't add a state library** — match the existing pattern.

## Persistence

| What | Where | Format |
|---|---|---|
| Project state (layers + styleSpec, map view, conversations, bookmarks, basemap) | `<workspace>/project.json` | JSON, debounced 800ms after any change, also flushed on app quit |
| Chat-generated layers | `<workspace>/.disha/layers/<id>.geojson` | Materialized when project saves |
| Imported / clipped layers | `<workspace>/<name>.geojson` | Written by vector convert and the clip/region-save flows |
| Last-opened workspace | `userData/last-workspace.json` (prod) or `.tmp/last-workspace.json` (dev) | Auto-restored on launch |
| Artifacts | SQLite at `packages/backend/disha.db` (override with `DISHA_DB`); image/file artifacts also written under `artifacts_store/` | WAL-mode, migrations in `database.py` |
| HTTP cache | SQLite `cache.db` (+ in-memory LRU) | TTL cache for upstream API responses |
| Selected model | `packages/backend/model_config.json` (prod: `Resources/backend/`) | Read by both Electron and Python |

`project.json` stores layer file paths **relative to the workspace** so moving the workspace folder doesn't break it. Absolute paths from older projects keep working.

The artifacts table (see `database.py`) has: `id`, `title`, `content`, `artifact_type`, `format` (markdown/table/image/geojson), `file_path`, `meta` (JSON), `created_at`, `updated_at`.

## HTTP API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/api/files?path=…&workspace=…` | List workspace files (path-restricted to the workspace root) |
| GET | `/api/files/convert/probe` | Pre-flight a vector file; for CSV reports detected lat/lng columns |
| POST | `/api/files/convert` | Convert shapefile/GPKG/KML/KMZ/GPX/CSV → WGS84 GeoJSON in the workspace |
| GET | `/api/geocode?query=…` | Forward geocode (Google → Photon → Nominatim) |
| GET | `/api/geocode/reverse?lat=…&lng=…` | Reverse geocode (Nominatim) |
| GET | `/api/artifacts` · POST · POST `/upload` · GET `/{id}` · GET `/{id}/download` · PUT · DELETE | Artifact CRUD, multipart upload (images), native-format download |
| GET | `/api/streetview/meta?lat=…&lng=…` | Nearest panorama metadata (keyless, `streetlevel`) |
| GET | `/api/streetview/pano?lat=…&lng=…` | Nearest panorama as equirectangular JPEG |
| WS | `/api/chat/ws` | Chat + tool calls + map actions + deep-research report generation (the main loop) |

> Report generation has **no HTTP endpoint** — it runs inside the chat WebSocket loop. When the model calls the `generate_report` tool, `chat.py:_run_deep_research` streams `research_*` events back over the same socket (see [Deep research](#deep-research) above).

Every request is constrained to loopback origins by CORS.

## Electron IPC surface

Defined in `apps/desktop/src/preload/index.ts`. Renderer accesses these via `window.electronAPI.*`:

```
selectWorkspace()              → opens folder picker
readDirectory(dirPath)         → list directory entries
readFile(path) / writeFile     → text I/O (writeFile mkdirs recursively)
readFileBase64(path)           → for PDF rasterization & vision
openFile({filters})            → file picker with extension filter
getLastWorkspace / setLastWorkspace
getModels / getCurrentModel / switchModel   → model_config.json
onAppBeforeQuit(handler)       → flush project save before quit
```

Model switching writes `model_config.json` (dev: `packages/backend/`; prod: `Resources/backend/`); the Python backend reads the same file via `tools/config.py:get_model`, so both processes share the selection.

## Environment variables

| Variable | Read in | Gates |
|---|---|---|
| `OPENAI_API_KEY` | `routers/chat.py` | Chat assistant + deep-research report generation |
| `OPENAI_MODEL` | `tools/config.py` | Default model when `model_config.json` is absent (`gpt-4o-mini`) |
| `GOOGLE_MAPS_API_KEY` | `tools/google.py` | All Google Maps Platform calls + Google-first geocoding (optional) |
| `DISHA_DB` | `database.py` | Overrides the artifacts SQLite path |

## Run

```bash
pnpm install                            # once
cd packages/backend && python -m venv .buildenv \
  && source .buildenv/bin/activate \
  && pip install -r requirements.txt    # once
export OPENAI_API_KEY=...

pnpm dev                                # backend (uvicorn :8765) + renderer
```

## Build for distribution

```bash
# 1. Freeze the Python backend
cd packages/backend
source .buildenv/bin/activate
pip install pyinstaller
pyinstaller backend.spec --noconfirm

# 2. Package the Electron app
cd apps/desktop
npx electron-vite build
npx electron-builder
# → apps/desktop/release/
```

In production, `apps/desktop/src/main/index.ts:startBackend` spawns the PyInstaller binary at `Resources/backend/backend`.

## Where to read first (in order)

1. `packages/backend/routers/chat.py` — agentic loop, action contract, tool registry, deep research. **The heart of the AI behavior.**
2. `apps/desktop/src/renderer/App.tsx` — single state container, component wiring, action routing, persistence.
3. `apps/desktop/src/renderer/components/MapView.tsx` — MapLibre setup, symbology/label expressions, draw tools, right-click menu, action handlers.
4. `apps/desktop/src/renderer/components/ChatPanel.tsx` — WebSocket client, streaming + deep-research render.
5. `packages/backend/mcp_servers/osm_server.py` — canonical MCP server example with the most logic.
6. `apps/desktop/src/renderer/types.ts` — shared interfaces, `LayerStyleSpec`, basemap defs, zone presets, the `MapAction` union.
7. `packages/backend/tools/geo.py` + `tools/vector_convert.py` — geodesic math and the import/reprojection path.
8. `apps/desktop/src/preload/index.ts` — full IPC surface between renderer and Electron main.

## Known gaps

- **No tests.** Anywhere. The agent loop, OSM ring-merge, and geometry math are entirely untested.
- **Overture cold start.** The first query for a region scans public S3 parquet (1–2 min); subsequent queries are cached.
- **Vision is rasterize-then-send.** Large multi-page PDFs are capped per page (2200px long axis).
- **DuckDB `spatial` extension** must be reachable (or pre-bundled) for vector import; first use triggers `INSTALL spatial`.
- **No PMTiles / MBTiles / vector tile support.** All basemaps are external raster XYZ.
