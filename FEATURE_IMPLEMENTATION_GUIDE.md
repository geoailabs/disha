# 🚀 Disha Feature Implementation & Subsystem Architecture Guide

## Domain Hubs, Spatial Registry, Multi-Format Exports, Task Pipeline, & Spatial Context Engine

This document provides a comprehensive, in-depth technical guide detailing the core architectures, subsystems, and feature implementations powering the **Disha AI Desktop IDE for Urban and Regional Planners**.

---

## 📌 Executive Summary

Urban and regional planning software requires unified coordination between high-performance interactive cartography (MapLibre GL), agentic AI reasoning across diverse planning disciplines, centralized geospatial entity tracking, and production-grade exportable deliverables.

We implemented and hardened twelve core platform capabilities:

1. **7+1 Domain Hub Architecture & ToolResult Protocol**: Replaces unorganized flat tool collections with cohesive domain subsystems (`Spatial`, `Mobility`, `Environment`, `Planning`, `Demographics`, `Places`, `Scenarios`, and `Utility`), returning typed execution packets (`ToolResult`) with automated side-effect routing.
2. **Central Spatial & Polygon Registry**: Single source of truth for all study areas, zoning parcels, and boundaries, enforcing $\ge 90\%$ Intersection-over-Union (IoU) deduplication, geodesic ellipsoidal calculations (`pyproj.Geod`), and live map layer synchronization.
3. **Token-Optimized Spatial Context Engine**: Converts complex GeoJSON layers (which previously triggered `400 context_length_exceeded` errors at ~274,000 tokens) into compact, semantically rich spatial metadata (~100 tokens, a $\mathbf{99.96\%}$ reduction).
4. **Task Pipeline Orchestrator (`task_pipeline.py`)**: Implements a Priority-Queue (Asset Phase) and Document-Heap (Compilation Phase) dependency execution model that prevents document hallucination by generating real map/chart assets before compiling documents.
5. **Multi-Format Artifact Export Engine (`export_engine.py`)**: Enables single-click and chat-driven exports across **8 modalities**: `PDF` (`ReportLab` native `%PDF-1.4`), `Word (.docx)`, `HTML`, `PNG Image`, `JPEG Image`, `Excel (.xlsx)`, `JSON`, and `TXT`.
6. **Plot & Histogram MCP Server (`PlotServer`)**: Integrated into `UtilityHub` to generate dark- and light-themed publication charts (`bar`, `histogram`, `pie`, `line`, `scatter`) via Matplotlib and persist them directly into the artifact catalog.
7. **Uncropped Bounding-Box Map Composer**: Calculates exact layer bounding coordinates, applies an **$18\%$ geographic margin padding on all four cardinal directions**, and flushes the WebGL frame buffer for zero-crop map snapshots with true planar aspect ratios.
8. **RAG Vector Search & Document Indexing Subsystem (`routers/rag.py`)**: Automatically parses workspace documents (`.pdf`, `.docx`, `.txt`, `.md`), computes OpenAI vector embeddings via `text-embedding-3-small`, and injects top-ranked chunks into chat context.
9. **GTFS Transit & Satellite Land Use Analytics**: Ingests local GTFS transit packages with automated 400m/800m geodesic walking catchment buffers, alongside Google Earth Engine (GEE) Dynamic World zonal land-use statistics.
10. **Workspace Concurrency & Auto-Save Guardrails**: Hardened state-transition lifecycles using `isClosingRef` guards in `App.tsx` to prevent race-condition workspace corruption during project switches.
11. **OpenCode Agent Runtime & MCP Tool Adapter**: Autonomous multi-step orchestration via headless `opencode serve` and stdio JSON-RPC MCP adapter.
12. **Geographic Interpretation & Boundary Containment**: Resolves administrative boundaries and enforces spatial polygon containment without substituting broad search extents, bounding boxes, or radial proximity.
13. **Document Visualization & Section Heading Independence**: Generates separate, dedicated map figures per requested document heading with strict layer isolation.

---

## 🏗️ Architectural Overview & System Flow

```mermaid
flowchart TD
    subgraph Frontend ["Electron Renderer (React 19 + MapLibre GL)"]
        UserSel["User Selects GeoJSON Feature / Layer Collection"]
        MapCanvas["MapLibre WebGL Canvas"]
        Composer["composeFigure() + fitBboxAndSnapshot()"]
        ArtPanel["ArtifactsPanel (8 Multi-Format Buttons)"]
        ChatUI["ChatPanel.tsx (Prompt & Context Pill)"]
    end

    subgraph Backend ["Python FastAPI Backend (:8765)"]
        WS["WebSocket Router (/api/chat/ws)"]
        ChatLoop["routers/chat.py (_run_agent)"]
        TaskPipe["tools/task_pipeline.py (Queue & Heap Orchestrator)"]
        SpatialReg["tools/spatial_registry.py (IoU >= 90% Deduplication)"]
        DomainHubs["7+1 Domain Hubs (BaseDomainHub)"]
        RAGRouter["routers/rag.py (Vector Search & Embeddings)"]
        PlotMCP["PlotServer (create_plot)"]
        ExpEngine["tools/export_engine.py (Doc Compiler)"]
        ArtStore["tools/artifact_store.py (SQLite DB)"]
    end

    subgraph LLM ["AI Reasoning Engine (OpenAI API)"]
        Agent["Autonomous Agent Loop"]
    end

    UserSel -->|Extract Centroid, Bbox & Summary| ChatUI
    ChatUI -->|Send Lightweight Prompt + Metadata| WS
    WS --> ChatLoop
    ChatLoop --> RAGRouter
    ChatLoop --> SpatialReg
    ChatLoop -->|Flatten Declarations| Agent
    Agent -->|Execute Tool Call| TaskPipe
    TaskPipe -->|1. Asset Phase: Maps & Plots| DomainHubs
    TaskPipe -->|2. Doc Phase: Patch Real Paths| DomainHubs
    DomainHubs -->|Typed ToolResult| ChatLoop
    DomainHubs -->|Generate Plots| PlotMCP
    PlotMCP -->|Save Image Artifact| ArtStore
    Composer -->|Capture 18% Padded Canvas| ExpEngine
    ExpEngine -->|Generate PDF / DOCX / HTML / XLSX| ArtStore
    ArtStore -->|HTTP /export Endpoint| ArtPanel
    ChatLoop -->|Auto Map Action (WebSocket)| MapCanvas
```

---

## 🏛️ 1. The 7+1 Domain Hub Architecture & ToolResult Protocol

### The Architectural Evolution
In earlier designs, tools were maintained as loose, uncoordinated endpoints in flat dictionary structures. This introduced namespace collisions, unclear ownership of side effects, and brittle prompt-generation logic. 

Disha standardizes all analytical tools under **7 Core Planning Domains and 1 Cross-Cutting Utility Engine**, inheriting from `BaseDomainHub` in `packages/backend/domains/protocol.py`:

```python
class BaseDomainHub(ABC):
    name: str
    description: str
    tool_names: set[str]

    @abstractmethod
    def get_declarations(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def execute(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult: ...
```

### The Standardized `ToolResult` Contract
Each domain tool returns a typed `ToolResult` object:
- **`data`**: Clean analytical dictionary returned directly to the model context.
- **`map_action`**: Optional map action payload (e.g. `{"action": "add_geojson", "payload": {...}}`) dispatched over the active WebSocket.
- **`artifact`**: Optional markdown report (e.g. `{"title": "...", "content": "...", "artifact_type": "report"}`) saved automatically to disk and SQLite without secondary tool invocations.
- **`status` / `error`**: Execution status tracking (`"success" | "error" | "cancelled"`).

### The 8 Domain Hubs Breakdown

| Domain Hub | File Location | Subsystems & Responsibilities |
|---|---|---|
| **`SpatialHub`** | `packages/backend/domains/spatial_hub.py` | OpenStreetMap administrative boundaries, DataMeet national datasets, GIS geometric clipping/buffering/filtering, WMS imagery, and Central Spatial Registry queries (`list_polygons`, `get_polygon`, `check_polygon_overlap`, `calculate_land_budget`). |
| **`MobilityHub`** | `packages/backend/domains/mobility_hub.py` | Street networks, Dijkstra/freight routing with bridge/tunnel Z-level modeling, GTFS transit schedules & 400m/800m walking buffers, traffic signal timing, and Origin-Destination (OD) gravity models. |
| **`EnvironmentHub`** | `packages/backend/domains/environment_hub.py` | Google Earth Engine (GEE) satellite land cover/NDVI analysis, Open-Meteo weather & air quality indices, solar potential, elevation contours, and fleet emissions. |
| **`PlanningHub`** | `packages/backend/domains/planning_hub.py` | Zoning regulation classification, planning document georeferencing, and raster image digitization. |
| **`DemographicsHub`** | `packages/backend/domains/demographics_hub.py` | WorldPop population extraction, cohort-component demographic forecasts, employment density, and social infrastructure capacity. |
| **`PlacesHub`** | `packages/backend/domains/places_hub.py` | Google Places API amenities, POI pinning, and Overture 3D building heights. |
| **`ScenariosHub`** | `packages/backend/domains/scenarios_hub.py` | Multi-criteria decision analysis (MCDA) scoring, scenario comparison matrices, and urban growth simulations. |
| **`UtilityHub`** | `packages/backend/domains/utility_hub.py` | Geocoding, reverse geocoding, web search, geodesic distance & area measurements, `PlotServer` charting, interactive questions (`ask_question`), and artifact CRUD storage. |

---

## 🧭 2. Centralized Spatial & Polygon Registry

Located in `packages/backend/tools/spatial_registry.py`, the Central Spatial Registry serves as the authoritative single source of truth for all spatial entities in an urban study area.

### 1. Intersection-over-Union (IoU) Deduplication ($\ge 90\%$)
To eliminate "layer spam" when AI models or users execute repetitive boundary queries:
$$\text{IoU}(A, B) = \frac{\text{Area}(A \cap B)}{\text{Area}(A \cup B)}$$
- If $\text{IoU} \ge 0.90$ or normalized place names match, the system **reuses** the existing registered entry.
- The existing layer is highlighted on the canvas with computed metrics returned to the model, preventing duplicate polygons from cluttering the map.

### 2. True Geodesic WGS84 Calculations
Unlike naive Euclidean calculations that distort planar surface areas at higher latitudes, all area and perimeter metrics are computed using the ellipsoidal WGS84 model via `pyproj.Geod(ellps="WGS84")`:
- Computes geodesic area in square meters ($\text{m}^2$), hectares ($\text{ha}$), and square kilometers ($\text{km}^2$).
- In accordance with Workspace Invariant 9, calculated analytical metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`) are **never stripped** from model tool results.

### 3. Bidirectional Layer Synchronization
On every chat turn, `SpatialRegistry` syncs with active map layers via `map_context["layers"]`, registering new user-drawn features and pruning removed layers in real time.

---

## 📑 3. Interactive Feature Selection & Token Context Engine

### The Problem
When a user selected complex spatial layers (e.g. 89 built-up area polygons comprising thousands of coordinate pairs), passing raw geometry arrays directly inside the chat prompt exceeded LLM context window budgets ($274,307$ tokens), crashing the conversation with `400 context_length_exceeded`.

### The Technical Solution
Instead of serializing raw `geometry.coordinates`, Disha computes a lightweight **Spatial Metadata Summary** in `App.tsx` and `types.ts`:

1. **Client-Side Summarization (`App.tsx`)**:
   - `centroid`: `[lng, lat]` center point calculated via `@turf/centroid`.
   - `bbox`: `[west, south, east, north]` bounding box calculated via `@turf/bbox`.
   - `featureCount`: Total features contained in the selected layer.
   - `filePath`: Absolute disk path to the source GeoJSON file on the local machine.
   - `properties`: Relevant key attribute summary (e.g. `land_cover_class: "Built Area"`, `year: 2023`).

2. **UI Selection Chip (`ChatPanel.tsx`)**:
   - Displayed as an interactive context badge above the input prompt: `📍 Selected: Built Area Polygons (2023)`.
   - Allows users to clear selection or select entire layer collections at once.

3. **Backend Injection (`routers/chat.py`)**:
   Structured cleanly into the system prompt:
   ```text
   [USER SELECTED MAP ELEMENTS / HIGHLIGHTED LAYERS]
   - Selected Element/Layer: land_use_built_area_2023
     File Path: /workspace/land_use_built_area_2023.geojson
     Feature Count: 89
     Centroid: [lng=76.77733, lat=30.72908]
     Bounding Box: [W=76.70381, S=30.66551, E=76.84961, N=30.79487]
     Properties: {"land_cover_class": "Built Area", "year": 2023}
   ```
   **Outcome**: Token consumption dropped from **~274,000 tokens** down to **~100 tokens** ($\mathbf{99.96\%}$ reduction).

---

## ⚙️ 4. Task Pipeline Orchestrator (`tools/task_pipeline.py`)

When an LLM produces a comprehensive planning report, it often attempts to call asset-generation tools (`export_map_jpeg`, `create_plot`) and document-compilation tools (`create_artifact`) in the same turn. If executed out of order, the document compiler encounters hallucinated placeholder paths (e.g. `![Map](map_snapshot)`).

`task_pipeline.py` solves this via two execution phases:
1. **Priority Queue Phase (Assets):**
   - Classifies tools into `_ASSET_TOOLS` and `_DOCUMENT_TOOLS`.
   - Executes all asset-generation tools first.
   - Collects verified artifact IDs and physical file paths (`artifacts_store/<id>.jpg`).
2. **Document Heap Phase (Compilation):**
   - `patch_content_with_real_paths` scans document markdown and replaces placeholder references with actual resolved file paths.
   - Executes `create_artifact`, ensuring fully embedded images in Word and PDF outputs.

---

## 📊 5. Plot & Histogram MCP Server (`PlotServer`)

Implemented in `packages/backend/mcp_servers/plot_server.py` and exposed via `UtilityHub`:

- **Supported Chart Formats**: `bar`, `histogram`, `pie`, `line`, and `scatter`.
- **Urban Planning Theme**: Configured with dark aesthetics tailored for map IDEs (`#0f172a` canvas, `#1e293b` axes, and high-contrast color palettes like `teal`, `coral`, `indigo`, and `landuse`).
- **High-Resolution Graphics**: Rendered at $200$–$300$ DPI into memory byte buffers, saved directly to the workspace artifact directory, and cataloged in the SQLite database as an image artifact.

---

## 📄 6. Multi-Format Artifact Export Engine (`tools/export_engine.py`)

The multi-format compiler in `packages/backend/tools/export_engine.py` allows any planning report, spatial summary, table, or map view to be exported into 8 distinct formats:

| Format | Technology / Engine | Key Capabilities |
|---|---|---|
| **PDF (`.pdf`)** | `ReportLab` | Native `%PDF-1.4` binary stream; includes document title, formatted paragraphs, bullet lists, and embedded map figure. Pure Python, requiring zero system C-libraries. |
| **Word (`.docx`)** | `python-docx` | Native Microsoft Word document formatting; includes H1/H2 headings, table grids, bullet points, and centered map image figures. |
| **HTML (`.html`)** | `markdown` | Self-contained, responsive HTML report styled with modern CSS typography and base64-embedded map snapshots. |
| **PNG (`.png`)** | `Pillow` (PIL) | High-resolution raster map image snapshot with legend, scale bar, and compass rose. |
| **JPEG (`.jpg`)** | `Pillow` (PIL) | Compressed RGB JPEG map snapshot ($95\%$ quality). |
| **Excel (`.xlsx`)** | `openpyxl` | Formatted multi-column workbook containing feature properties, attribute tables, and zonal data. |
| **JSON (`.json`)** | Standard `json` | Raw structured metadata and GeoJSON feature collections. |
| **TXT (`.txt`)** | Standard I/O | Plain text document export. |

---

## 🗺️ 7. Uncropped Bounding-Box Map Composer

### The Solution Implementation

1. **True Planar Proportions (`export_engine.py`)**:
   Inspects the natural pixel width ($W_{orig}$) and height ($H_{orig}$) of the captured image:
   $$\text{Aspect Ratio } AR = \frac{W_{orig}}{H_{orig}}$$
   Image dimensions inside the PDF/Word layout dynamically adapt to maintain strict $AR$ geometry.

2. **$18\%$ Geographic Padding on All Four Bounds (`MapView.tsx`)**:
   `fitBboxAndSnapshot()` in `MapView.tsx` computes bounding coordinates and applies an $18\%$ buffer:
   $$\text{Pad}_{\text{West}} = \text{West} - 0.18 \times \Delta \text{Lng}$$
   $$\text{Pad}_{\text{East}} = \text{East} + 0.18 \times \Delta \text{Lng}$$
   $$\text{Pad}_{\text{South}} = \text{South} - 0.18 \times \Delta \text{Lat}$$
   $$\text{Pad}_{\text{North}} = \text{North} + 0.18 \times \Delta \text{Lat}$$

3. **Synchronous WebGL Frame Flush**:
   Invokes `map._render()` to force an immediate WebGL draw buffer repaint before snapshot serialization, resetting camera viewports 150ms after capture.

---

## 🔍 8. Document RAG Indexing & Vector Search Subsystem (`routers/rag.py`)

Implemented in `packages/backend/routers/rag.py`:
- **Document Chunking:** Extracts text from `.pdf` (page-by-page via `pypdf`), `.docx` (via `python-docx`), `.txt`, and `.md` into 1000-character chunks with 200-character overlap.
- **Batch Embedding:** Embeds chunks via OpenAI `text-embedding-3-small` in batches of 100.
- **Persistence:** Writes vector embeddings and metadata to `<workspace>/.disha/rag_index.json`.
- **Async Vector Search:** Uses unit-normalized dot-product cosine similarity to retrieve top-4 relevant chunks for active user queries during chat.

---

## 🚌 9. GTFS Transit & Satellite Land Use Analytics

### GTFS Transit Analysis (`gtfs_server.py`)
- **Feed Ingestion**: Parses `.zip` archives or directories containing GTFS data (`stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`, `frequencies.txt`).
- **Catchment Buffer Modeling**: Generates standard urban pedestrian walking sheds:
  - **400m Buffer**: ~5-minute first-mile/last-mile walk shed.
  - **800m Buffer**: ~10-minute primary transit catchment shed.
- **Service Frequencies**: Computes hourly trip departures and headway metrics across 24-hour service profiles.

### GEE Dynamic World Zonal Land Use (`gee_server.py`)
- Calculates land cover distributions across 9 discrete classes (`water`, `trees`, `grass`, `flooded_vegetation`, `crops`, `shrub_and_scrub`, `built`, `bare`, `snow_and_ice`).
- Computes both absolute metric areas ($\text{km}^2$) and percentage distributions for custom study boundaries.

---

## 🔒 10. Workspace Concurrency & Auto-Save Guardrails

To eliminate data corruption during workspace resets or project loading, Disha implements strict lifecycle guards in `App.tsx`:

- **The `isClosingRef` Guard**: Whenever closing or switching workspaces, `isClosingRef.current = true` is asserted **prior** to state resets.
- **Auto-Save Protection**: Asynchronous debounced saves (`project.json` and `documents.json`) abort immediately if `isClosingRef.current` is set, preventing blank default state from overwriting saved project data.
- **Artifacts Double-Effect Guard**: `fetchArtifacts` verifies `workspacePath` presence before issuing network calls, clearing state synchronously when closed.

---

## 🤖 11. OpenCode Agent Runtime & MCP Tool Adapter

To enable autonomous, multi-step agent reasoning without sacrificing Disha's native cartography, task pipeline, or domain logic, Disha integrates the OpenCode agent runtime:

### 1. Headless Server & Process Lifecycle (`server_manager.py`)
- Automatically generates `opencode.json` with permissions and local stdio `disha_tools` MCP server command.
- Spawns and manages headless `opencode serve --port 4096 --hostname 127.0.0.1` upon startup when `USE_OPENCODE=true`.
- Gracefully terminates child process on FastAPI application shutdown.

### 2. Standard JSON-RPC 2.0 Stdio MCP Server (`mcp_server.py`)
- Exposes all 24 Map Actions, 8 Domain Hubs (~45 tools), interactive tools (`ask_question`, `create_plot`, `create_artifact`), GEE analytics, and the Spatial Registry.
- Preserves all `ToolResult` data structures, ensuring spatial metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`) and layer reuse triggers remain intact.
- Features internal loopback HTTP bridges (`/api/chat/internal_action` and `/api/chat/internal_question`) to push live MapActions and interactive question cards to active WebSocket clients.

### 3. Session Persistence & SSE Event Stream Translation (`session_manager.py`, `orchestrator.py`)
- Maps Disha frontend conversation IDs to OpenCode session IDs and persists them in `<workspace>/.disha/opencode_sessions.json`.
- Consumes the OpenCode Server `/event` Server-Sent Events (SSE) stream, seamlessly translating:
  - `message.part.delta` $\longrightarrow$ `{"type": "stream", "content": delta}`
  - `message.part.updated` (`tool-invocation`) $\longrightarrow$ `{"type": "tool_use", "tool": name, "args": args}`
  - `session.idle` $\longrightarrow$ `{"type": "end"}`
- Supports immediate Stop button cancellation via `POST /session/{id}/abort`.

---

## ⚡ 12. Autonomous Execution & Implicit Authorization

When the user requests a document, report, map, plot, analysis, or other deliverable:
- **Automatic Intermediate Operations:** Intermediate data retrieval, spatial processing, and preliminary figure generation execute automatically before assembling final artifacts.
- **No Redundant Confirmation Interrogations:** The agent does not prompt the user to say "proceed", "yes", or choose intermediate administrative levels/datasets when scope and intent are reasonably clear.
- **Implicit Authorization:** The user's request implicitly authorizes all intermediate data retrieval and spatial analysis. Real tools are used to obtain actual data—never inventing statistics or figures.

---

## 🗺️ 13. Geographic Interpretation & Boundary Containment

When a user requests features, amenities, or spatial analyses "in" a named geographic place:
- **Strict Boundary Containment:** The agent resolves the place boundary polygon (via `osm_boundary` or spatial boundary datasets) and strictly filters spatial queries to that boundary (`nearby_places_in_polygon`, `gis_clip`, `gis_spatial_join`, `gis_point_in_polygon`) without substituting broad bounding boxes or proximity circles.
- **Autonomous Inference:** The agent does not prompt the user to specify intermediate GIS operations, administrative levels, datasets, or spatial relationships when these can be reasonably inferred from context.
- **Universal & Place-Agnostic:** Implementation remains 100% location-neutral and works consistently across all geographic scales and regions.

---

## 📊 14. Document Visualization & Output Preservation

When compiling multi-section urban planning deliverables with maps and statistics:
- **Independent Output Generation:** When the user requests multiple geographic analyses or visual outputs, each requested output is produced independently, maintaining its full geographic and semantic scope without merging, omitting, or simplifying for convenience.
- **Heading-Level Visual Independence:** When the user requests separate visuals under separate headings, each heading receives its own dedicated visual asset.
- **Layer Isolation per Section:** Before capturing a map figure for a specific heading, unrelated layers, route lines, or temporary markers from other sections are cleared or toggled off, ensuring each visual presents only pertinent layers with necessary geographic context.
- **Document Asset Sequencing:** The appropriate document structure is inferred from requested headings, and all required underlying maps, plots, statistics, and image artifacts are generated before assembling the document.
