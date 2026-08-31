# Disha

**A geospatial-first, AI-native desktop IDE for urban and regional planners.**

Disha unifies an interactive spatial map canvas with a multi-domain AI reasoning engine. Planners can explore, analyze, model, and document complex urban environments through natural conversation and direct spatial interaction — bridging computational GIS, planning analytics, and cartography into a unified desktop workspace.

> **Architecture:** Electron + React + MapLibre desktop frontend connected to a Python FastAPI backend powered by **7 Core Urban Planning Domains + 1 Cross-Cutting Utility Engine**.

---

## Highlights

- **Agentic chat over a live map** — natural-language requests turn into real map actions (fly, draw, mark, style layers) and data fetches, streamed token-by-token with every tool call visible inline.
- **Rich geospatial toolset** — OpenStreetMap (Overpass/Nominatim), Overture Maps, Google Places & environment, GIS geometry + overlay analysis (buffer, hull, area, intersection, difference, clip, dissolve, spatial join, nearest), zoning analysis, demographics (WorldPop), weather & air quality.
- **Import real GIS data** — drop a shapefile, GeoPackage, KML/KMZ, GPX, or CSV into the workspace and it's reprojected to WGS84 and loaded as a layer (DuckDB `spatial`, no GDAL binary to bundle).
- **Data-driven symbology + labels** — categorize by a string property or graduate a numeric property into a choropleth, add on-map text labels, and read it all back in a live legend. Drive it from chat or the Symbology panel.
- **Manual drawing + attribute editing** — draw points/lines/polygons on the map, then edit their attributes in a spreadsheet-style table.
- **Publication-ready export** — PNG / PDF figures with a baked-in title block, legend, scale bar, north arrow, and attribution.
- **Document analysis mode** — drop in a planning PDF or map image and have the AI read land use, zoning, transport networks, and labels via vision.
- **Workspace persistence** — open a folder and your layers, map view, conversations, bookmarks, styling, and basemap auto-save to `project.json`.
- **Optional Google Maps Platform** — Places autocomplete/details/nearby/density, elevation, air quality, solar potential (gracefully degrades when no key is set).
- **Offline-friendly basemaps** — seven free raster basemaps, no API token required for the core experience.

---

## Features

### 🗺️ Map mode (the primary surface)

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

### 📄 Document mode

Drop in or open a planning document for AI analysis:

- **Images** (PNG, JPG, JPEG, WEBP, GIF, BMP) — sent directly to the model's vision input.
- **PDF** — rasterized client-side with `pdfjs-dist` (capped at 2200px on the long axis) and sent as vision input, with multi-page navigation.

The AI takes on a planning-analyst persona and can identify land use, zoning areas, transportation networks, infrastructure, density patterns, boundaries, and labels. Document mode still bridges to the live map — the assistant can fly, drop markers, run OSM searches, and save artifacts while you discuss a document.

### 🤖 AI chat assistant

The chat panel on the right is the main control surface:

- **Multiple conversations** — each persisted into `project.json`.
- **Natural-language commands** — navigate (*"fly to Chandigarh"*), fetch (*"show all schools in Sector 22"*), measure (*"area of this polygon"*), draw (*"mark a 2 km buffer around the airport"*), style (*"color the parcels by zone_code and label them"*), analyze (*"which flood-zone area falls inside ward 12?"*), or document (*"save these findings as an artifact"*).
- **Visible tool calls** — every OSM query, GIS op, or map action shows inline as it executes.
- **Streaming** — replies arrive token-by-token over a WebSocket.
- **Deep research** — ask for a report and the assistant runs a multi-search deep-research pass (OpenAI `o4-mini-deep-research` + web search), streaming each search step and returning a cited Markdown report you can download as `.md` or PDF.
- **Map-aware context & Interactive Selection** — the current viewport bounds, visible layers, selected feature/layer highlights (with centroid, bounding box, properties, and file path), small-layer geometry, and saved bookmarks are appended to prompts, allowing the AI to immediately analyze selected map shapes without exceeding token limits.

#### The 7+1 Domain Hub Architecture

The assistant's capabilities are organized across **7 core urban planning disciplines** powered by **1 cross-cutting utility engine**:

| Domain Hub | Planning Discipline | Core Capabilities |
|---|---|---|
| **1. SpatialHub** | Spatial Geometry & Land Management | Central polygon registry (deduplication & reuse), geodesic buffering/areas, spatial overlays (intersection, difference, clip, dissolve, spatial join), OSM/DataMeet administrative boundaries, WMS raster layers. |
| **2. MobilityHub** | Multimodal Transportation & Transit | Street network graphs, Dijkstra/freight routing, GTFS transit schedules & 400m/800m catchment buffers, ITS signal timing optimization, origin-destination (OD) gravity matrices & flow assignment. |
| **3. EnvironmentHub** | Climate, Remote Sensing & Emissions | Google Earth Engine LULC & NDVI satellite indices, Open-Meteo weather & air quality, solar building analysis, digital elevation models (DEM), fleet emissions modeling. |
| **4. PlanningHub** | Zoning & Plan Digitization | Zoning code compliance, zone density & overlap detection, master plan georeferencing, and image feature digitization. |
| **5. DemographicsHub** | Population & Economic Forecasting | WorldPop 100m grid population metrics, cohort-component demographic forecasting, employment density projections. |
| **6. PlacesHub** | Built Form & Urban POIs | Google Places search/details/density, Overture 3D building footprints and heights. |
| **7. ScenariosHub** | Scenario Planning & Evaluation | Alternative planning scenario generation, Multi-Criteria Decision Analysis (MCDA) scoring and matrix comparisons. |
| **+1. UtilityHub** | Shared System Infrastructure | Cross-cutting forward/reverse geocoding, live web research, geodesic distance/area measurements, and artifact persistence. |

### 📌 Artifacts

Long-form notes and analyses the assistant generates (or that you ask it to save) live in a local SQLite database and appear in the **Artifacts** panel with full CRUD — title, content, type, format (markdown / table / geojson / image), and timestamps. Exported figures (PNG/PDF) and GeoJSON can be saved here too, and a GeoJSON artifact can be re-added to the map with one click.

### 💾 Workspace & persistence

Open a folder via the title-bar button and the app:

- Lists files in the **Files** pane (click a `.geojson` to load it; click a shapefile/GPKG/KML/KMZ/GPX/CSV to import it).
- Auto-saves a `project.json` containing map state, layers (with styling), conversations, bookmarks, and basemap (debounced, also flushed on quit).
- Materializes chat-generated layers into `<workspace>/.disha/layers/<id>.geojson` so they survive reloads.
- Remembers the last workspace and re-opens it on next launch.

Without a workspace open, the app still works for ad-hoc exploration — nothing persists.

---

## Prerequisites

- **Node.js** ≥ 18 (with **pnpm** ≥ 8)
- **Python** ≥ 3.11
- *(Optional)* **Pango library** for WeasyPrint PDF report exports:
  - **macOS**: `brew install pango`
  - **Linux**: `sudo apt install libpango1.0-dev`

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
cd ..
```

> **Note on Vector Imports**: Vector ingestion uses DuckDB's `spatial` extension, auto-downloaded on first use. All core GIS libraries (`geopandas`, `fiona`, `shapely`, `pyproj`, `duckdb`) are included in `requirements.txt`.

### 3. Configure environment variables & launch

```bash
export OPENAI_API_KEY="sk-..."
export GOOGLE_MAPS_API_KEY="..."   # Optional

pnpm dev
```

## Development

Start the backend and Electron app together:

```bash
pnpm dev
```

Or run them separately:

```bash
# Terminal 1 — backend (uvicorn, hot reload)
cd packages/backend
source .buildenv/bin/activate
python -m uvicorn main:app --reload --port 8765

# Terminal 2 — desktop (electron-vite, hot reload)
cd apps/desktop
npx electron-vite dev
```

> In dev mode, Electron does **not** spawn the backend — `pnpm dev:backend` runs uvicorn separately so both sides hot-reload independently.

## Build for distribution

### 1. Freeze the Python backend (PyInstaller)

```bash
cd packages/backend
source .buildenv/bin/activate
pip install pyinstaller
pyinstaller backend.spec --noconfirm
```

### 2. Package the Electron app

```bash
cd apps/desktop
npx electron-vite build
npx electron-builder
```

Output is written to `apps/desktop/release/`. In production, Electron spawns the frozen backend binary from `Resources/backend/backend`.

The root `package.json` also wraps these:

```bash
pnpm build          # build the desktop renderer
pnpm build:backend  # freeze the Python backend
pnpm package        # backend + electron-builder, end to end
```

---

## Architecture at a glance

```
Electron main (apps/desktop/src/main/index.ts)
  ├─ spawns the FastAPI backend on :8765 (PyInstaller-frozen in prod, uvicorn in dev)
  └─ creates a BrowserWindow → loads the React renderer

Renderer (apps/desktop/src/renderer/) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws   ← streaming chat + tool calls + map actions
  ├─ Backend over HTTP       /api/files /api/artifacts /api/geocode /api/streetview
  └─ Electron main over IPC  (file dialogs, read directory, persist last-workspace, switch model)

Backend (packages/backend/) talks to:
  └─ OpenAI HTTPS (key from OPENAI_API_KEY)
     + Overpass, Nominatim, OSRM, Open-Meteo, Overture, WorldPop, Photon, streetlevel, DuckDuckGo  (free, keyless)
     + Google Maps Platform  (optional, key from GOOGLE_MAPS_API_KEY)
```

### Three communication channels

| Channel | Used for |
|---|---|
| **WebSocket** (renderer ↔ backend) | Streaming chat, tool calls, map actions, and deep-research progress. |
| **HTTP** (renderer ↔ backend) | List/convert workspace files, CRUD + upload/download on artifacts, forward/reverse geocoding, Street View panoramas. |
| **Electron IPC** (renderer ↔ main) | Local OS only — file picker, read directory, base64 file read for vision, last-workspace, model switch. |

### Tech stack

| Layer | Stack |
|---|---|
| Desktop shell | Electron |
| Renderer | React 19 + Vite (electron-vite) + TypeScript |
| Map | MapLibre GL + Turf.js + pannellum (Street View) |
| Backend | Python 3.11+, FastAPI, uvicorn |
| LLM | OpenAI Chat Completions (streaming, tool calling) + Responses API (deep research) |
| Geo APIs | Overpass, Nominatim, OSRM, Open-Meteo, Overture, WorldPop, Photon, Google Maps Platform |
| Geometry | Shapely + pyproj (server, geodesic), Turf.js (client) |
| Vector ingestion | DuckDB `spatial` (shapefile/GPKG/KML/KMZ/GPX/CSV → WGS84 GeoJSON) |
| Storage | SQLite (artifacts + HTTP cache) + JSON files in the workspace (project state) |
| Packaging | electron-builder + PyInstaller (frozen backend binary) |

> **The map works in EPSG:4326 lat/lng.** Imported files are reprojected to 4326 on ingest (DuckDB `ST_Transform`). Area, perimeter, and buffer math are geodesic on the WGS84 ellipsoid (`pyproj`), so they're accurate at any latitude and handle holes and MultiPolygons.

## Project structure

```
.
├── apps/desktop/                  Electron + React frontend
│   ├── src/main/index.ts          Electron main: window, IPC, backend spawn, model switch
│   ├── src/preload/index.ts       contextBridge IPC surface
│   └── src/renderer/              React UI
│       ├── App.tsx                Single state container; map ↔ chat ↔ panels
│       ├── types.ts               MapAction union, LayerStyleSpec, basemaps, zone presets
│       ├── lib/                    classify (breaks/ramps), compose-figure (export), legend-data
│       └── components/            MapView, ChatPanel, SymbologyPanel, AttributeTable, Legend,
│                                  ExportPanel, StreetViewDialog, FileTree, …
├── packages/backend/              Python FastAPI backend
│   ├── main.py                    App + CORS + router includes
│   ├── cli.py                     PyInstaller entry point (uvicorn launcher)
│   ├── database.py                SQLite + migrations
│   ├── routers/                   chat, files, artifacts, geocode, streetview
│   ├── domains/                   7+1 Domain Hubs (Spatial, Mobility, Environment, Planning,
│   │                              Demographics, Places, Scenarios, Utility) & ToolResult protocol
│   ├── mcp_servers/               Underlying domain servers (OSM, GIS, weather, zoning, etc.)
│   ├── tools/                     SpatialRegistry, UtilityServer, geodesic geo helpers,
│   │                              vector_convert, Google/HTTP wrappers, cache, artifact store
│   └── tests/                     Automated pytest test suite (all hubs, registry, websocket)
├── ARCHITECTURE.md                Deep dive — features + system wiring
├── CLAUDE.md                      Orientation for AI coding agents
└── README.md                      This file
```

For a deeper dive into the agentic loop, the action contract, the 7+1 Domain Hub architecture, spatial registry deduplication, and persistence, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Known gaps

- **PDF vision is rasterize-then-send** — large multi-page PDFs are capped per page.
- **Overture cold start** — the first Overture query for a region scans public S3 parquet and can take 1–2 minutes; subsequent queries are cached.
- **Raster basemaps only** — no Mapbox token, PMTiles, MBTiles, or vector tiles.
- **DuckDB `spatial` extension** must be reachable (or pre-bundled) for vector import to work offline.
