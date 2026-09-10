# Disha

**A geospatial-first, AI-native desktop IDE for urban and regional planners.**

Disha unifies an interactive spatial map canvas with a multi-domain AI reasoning engine. Planners can explore, analyze, model, and document complex urban environments through natural conversation and direct spatial interaction — bridging computational GIS, planning analytics, and cartography into a unified desktop workspace.

> **Architecture:** Electron + React 19 + MapLibre GL desktop frontend connected to a Python FastAPI backend powered by **7 Core Urban Planning Domains + 1 Cross-Cutting Utility Engine**.

---

## Highlights

- **Agentic chat over a live map** — Natural-language requests turn into real map actions (fly, draw, mark, style layers) and data fetches, streamed token-by-token with every tool call visible inline.
- **Rich 7+1 domain geospatial toolset** — OpenStreetMap (Overpass/Nominatim), Overture Maps, Google Places & environment, GIS geometry + overlay analysis (buffer, hull, area, intersection, difference, clip, dissolve, spatial join, nearest), zoning analysis, demographics (WorldPop), weather & air quality, GEE satellite imagery, GTFS transit feeds, and OD matrices.
- **Import real GIS data** — Drop a shapefile, GeoPackage, KML/KMZ, GPX, or CSV into the workspace and it's reprojected to WGS84 and loaded as a layer (DuckDB `spatial`, no GDAL binary to bundle).
- **Data-driven symbology + labels** — Categorize by a string property or graduate a numeric property into a choropleth, add on-map text labels, and read it all back in a live legend. Drive it from chat or the Symbology panel.
- **Manual drawing + attribute editing** — Draw points/lines/polygons on the map, then edit their attributes in a spreadsheet-style table.
- **Multi-format publication exports** — Export planning reports, figures, and tables into **8 modalities**: PDF (`ReportLab` native `%PDF-1.4`), Word (`.docx`), HTML, PNG Image, JPEG Image, Excel (`.xlsx`), JSON, and TXT.
- **Document analysis & digitization mode** — Drop in a planning PDF or map image; the AI analyzes land use, zoning, transport networks, and labels via vision, with georeferencing and vector digitization tools.
- **Centralized Spatial & Polygon Registry** — Tracks study areas and boundaries with $\ge 90\%$ IoU deduplication, WGS84 ellipsoidal geodesic math (`pyproj.Geod`), and live map synchronization.
- **Autonomous execution & implicit authorization** — Automatically executes all required intermediate data fetches, boundary resolutions, and spatial operations without stopping to ask for user permission ("proceed", "yes") or confirmation.
- **Geographic containment & boundary resolution** — Automatically resolves administrative boundary polygons and enforces spatial containment filtering (`nearby_places_in_polygon`, `gis_clip`, `gis_spatial_join`, `gis_point_in_polygon`) whenever features "in" a place are requested.
- **Preserved outputs & section visual independence** — Independently executes every requested analysis and visual without omitting or merging, generating dedicated, isolated map figures and plots per requested document heading.
- **Workspace RAG & persistence** — Open a folder and your layers, map view, conversations, bookmarks, styling, and basemap auto-save to `project.json`, while documents are indexed for semantic vector search (`.disha/rag_index.json`).
- **Offline-friendly basemaps** — Seven free raster basemaps, no API token required for the core experience.

---

## Features

### 🗺️ Map Mode (the primary surface)

| Feature | What it does |
|---|---|
| **Layers** | Click a `.geojson` in the Files pane to load it as a styled vector layer. The Layers pane gives count, visibility toggle, zoom-to, remove, symbology editor, and attribute editor. AI-generated layers appear here automatically. |
| **Vector import** | Click a `.shp`, `.gpkg`, `.kml`, `.kmz`, `.gpx`, or `.csv` in the Files pane and it's converted to WGS84 GeoJSON in your workspace and loaded as a layer. CRS is auto-detected and reprojected; CSVs are point-mapped from auto-detected lat/lng columns. |
| **Symbology** | Style any layer by data: **categorized** (color by a string property like `zone_code`), **graduated** (choropleth by a numeric property like `population`, equal-interval or quantile), plus on-map **text labels** from any property. Edit in the Symbology panel or ask the assistant to `style_layer`. |
| **Legend** | A live floating legend renders automatically whenever a visible layer has categorized or graduated styling. |
| **Drawing** | Draw points, lines, and polygons directly on the map; each becomes a real layer and opens an attribute table so you can tag it (e.g. set `zone_code`) before styling. |
| **Attribute table** | Spreadsheet-style editor for any layer's feature properties — add/rename/delete columns, edit cells, delete rows. |
| **Basemaps** | Seven free raster basemaps — Street (OSM), Satellite (Esri), Dark/Light (CartoDB), Terrain (OpenTopoMap), Topo (Esri), Humanitarian (OSM-HOT). No API key needed. |
| **Bookmarks** | Save the current extent as a named bookmark; the assistant can save and fly to bookmarks too. |
| **Export** | Publication-ready **PNG** and **PDF** figures (title, legend, scale bar, north arrow, attribution baked in), saved to disk or to Artifacts; per-layer **GeoJSON** download; **clip to extent**; and **save-by-region** (search an OSM boundary, preview it, and clip all layers to it). |
| **Zoning** | Built-in legend (R1, R2, C1, I1, G, MX, INST). Load a GeoJSON with a `zone_code` property and ask the assistant to analyze per-zone area/density or detect overlapping zones. |
| **Street View** | Right-click anywhere on the map to drop a pin, ask the assistant about the spot, or open an embedded 360° panorama (keyless — panoramas come from the `streetlevel` library, rendered with pannellum). |

### 📄 Document Mode

Drop in or open a planning document for AI analysis:
- **Images** (PNG, JPG, JPEG, WEBP, GIF, BMP) — Sent directly to the model's vision input.
- **PDF** — Rasterized client-side with `pdfjs-dist` (capped at 2200px on the long axis) and sent as vision input, with multi-page navigation.
- **Georeferencing & Digitization** — Identify visual landmarks, georeference the document, and digitize visual boundaries and POIs into real map layers.

### 🤖 AI Chat Assistant & 7+1 Planning Domains

The chat panel on the right is the main control surface:
- **Multiple conversations** — Persisted into `project.json`.
- **Interactive Question Cards** — Interactive single-choice or multi-select cards (`ask_question`) directly in the chat stream.
- **Visible tool calls** — Every OSM query, GIS op, or map action shows inline as it executes.
- **Streaming** — Replies arrive token-by-token over a WebSocket.
- **Deep research** — Ask for a report and the assistant runs a multi-search deep-research pass (OpenAI `o4-mini-deep-research` + web search), streaming each search step and returning a cited Markdown report.
- **Token-Optimized Spatial Context** — Viewport bounds, visible layers, and selected feature highlights are appended as lightweight summaries (~100 tokens), preventing context overflow.

#### The 7+1 Domain Hub Architecture

| Domain Hub | Planning Discipline | Core Capabilities |
|---|---|---|
| **1. SpatialHub** | Spatial Geometry & Land Management | Central polygon registry (deduplication & reuse), geodesic buffering/areas, spatial overlays (intersection, difference, clip, dissolve, spatial join), OSM/DataMeet administrative boundaries, WMS raster layers. |
| **2. MobilityHub** | Multimodal Transportation & Transit | Street network graphs, Dijkstra/freight routing, GTFS transit schedules & 400m/800m catchment buffers, ITS signal timing optimization, origin-destination (OD) gravity matrices & flow assignment. |
| **3. EnvironmentHub** | Climate, Remote Sensing & Emissions | Google Earth Engine LULC & NDVI satellite indices, Open-Meteo weather & air quality, solar building analysis, digital elevation models (DEM), fleet emissions modeling. |
| **4. PlanningHub** | Zoning & Plan Digitization | Zoning code compliance, zone density & overlap detection, master plan georeferencing, and image feature digitization. |
| **5. DemographicsHub** | Population & Economic Forecasting | WorldPop 100m grid population metrics, cohort-component demographic forecasting, employment density projections. |
| **6. PlacesHub** | Built Form & Urban POIs | Google Places search/details/density, Overture 3D building footprints and heights. |
| **7. ScenariosHub** | Scenario Planning & Evaluation | Alternative planning scenario generation, Multi-Criteria Decision Analysis (MCDA) scoring and matrix comparisons. |
| **+1. UtilityHub** | Shared System Infrastructure | Cross-cutting forward/reverse geocoding, live web research, geodesic distance/area measurements, Matplotlib plotting (`create_plot`), and artifact persistence. |

---

## Prerequisites

- **Node.js** ≥ 18 (with **pnpm** ≥ 8)
- **Python** ≥ 3.11

## Setup & First-Time Installation

### 1. Clone the repository & install Node dependencies

```bash
git clone https://github.com/geoailabs/disha.git
cd disha
pnpm install
```

### 2. Set up Python backend virtual environment & dependencies

```bash
cd packages/backend
python -m venv .buildenv
source .buildenv/bin/activate   # Windows: .buildenv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
cd ../..
```

### 3. Configure environment variables & launch

```bash
export OPENAI_API_KEY="sk-..."
export GOOGLE_MAPS_API_KEY="..."   # Optional
export USE_OPENCODE=true          # Optional: true to enable OpenCode runtime orchestration

pnpm dev
```

## Development

Start the backend and Electron app together:

```bash
pnpm dev
```

Or run them in separate terminals:

```bash
# Terminal 1 — backend (uvicorn, hot reload)
cd packages/backend
source .buildenv/bin/activate
python -m uvicorn main:app --reload --port 8765

# Terminal 2 — desktop (electron-vite, hot reload)
cd apps/desktop
npx electron-vite dev
```

## Build for Distribution

```bash
# 1. Freeze the Python backend (PyInstaller)
cd packages/backend
source .buildenv/bin/activate
pip install pyinstaller
pyinstaller backend.spec --noconfirm

# 2. Package the Electron app
cd ../../apps/desktop
npx electron-vite build
npx electron-builder
```

---

## Architecture at a Glance

```
Electron main (apps/desktop/src/main/index.ts)
  ├─ spawns the FastAPI backend on :8765 (PyInstaller-frozen in prod, uvicorn in dev)
  └─ creates a BrowserWindow → loads the React renderer

Renderer (apps/desktop/src/renderer/) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws   ← streaming chat + tool calls + map actions
  ├─ Backend over HTTP       http://localhost:8765/api/*        ← 10 mounted API routers
  └─ Electron main over IPC  (file dialogs, read/write directory, persist last-workspace, switch model)

Backend (packages/backend/) talks to:
  ├─ OpenCode Agent Runtime (:4096)  ← Autonomous multi-step orchestration via stdio MCP (USE_OPENCODE=true)
  └─ OpenAI API & Geospatial APIs (legacy fallback, RAG embeddings, deep research)
     + Overpass, Nominatim, OSRM, Open-Meteo, Overture, WorldPop, Photon, Google Earth Engine
     + Google Maps Platform (optional)
```

### Communication Channels

| Channel | Used for |
|---|---|
| **WebSocket** (renderer ↔ backend) | Streaming chat, tool calls, map actions, interactive question cards, and deep-research progress. |
| **HTTP** (renderer ↔ backend) | 10 modular routers: `/api/files`, `/api/chat`, `/api/artifacts`, `/api/geocode`, `/api/streetview`, `/api/wms`, `/api/gee`, `/api/scenarios`, `/api/rag`, `/api/diagnostics`. |
| **OpenCode MCP & SSE** (backend ↔ runtime) | Autonomous multi-step agent execution, context compaction, and tool dispatch via `packages/backend/llm/opencode/`. |
| **Electron IPC** (renderer ↔ main) | Local OS only — folder picker, file read/write, base64 file read for vision, last-workspace, model switch. |

### Tech Stack

| Layer | Stack |
|---|---|
| Desktop shell | Electron 34+ |
| Renderer | React 19 + Vite (electron-vite) + TypeScript |
| Map | MapLibre GL 4+ + Turf.js + pannellum (Street View) |
| Backend | Python 3.11+, FastAPI, uvicorn |
| LLM | OpenAI Chat Completions (streaming, tool calling) + Responses API (deep research) + Embeddings (`text-embedding-3-small`) |
| Geo APIs | Overpass, Nominatim, OSRM, Open-Meteo, Overture, WorldPop, Photon, Google Earth Engine, Google Maps Platform |
| Geometry | Shapely + pyproj (server, geodesic), Turf.js (client) |
| Vector ingestion | DuckDB `spatial` (shapefile/GPKG/KML/KMZ/GPX/CSV → WGS84 GeoJSON) |
| Storage | SQLite (artifacts + HTTP cache) + JSON files in the workspace (project state) |
| Packaging | electron-builder + PyInstaller (frozen backend binary) |

---

## Known Gaps

- **PDF vision is rasterize-then-send** — Large multi-page PDFs are capped per page.
- **Overture cold start** — The first Overture query for a region scans public S3 parquet and can take 1–2 minutes; subsequent queries are cached.
- **Raster basemaps only** — Free XYZ raster tiles; no PMTiles or vector basemap server bundled.
- **DuckDB `spatial` extension** — Auto-installed on first vector import; requires network on first run.
