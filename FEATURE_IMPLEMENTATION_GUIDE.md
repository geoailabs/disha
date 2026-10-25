# 🚀 Disha Feature Implementation & Subsystem Architecture Guide

[![Release](https://img.shields.io/badge/release-v0.1.8-blue.svg)](https://github.com/geoailabs/disha/releases/tag/v0.1.8)
[![Version](https://img.shields.io/badge/version-0.1.8-emerald.svg)](https://github.com/geoailabs/disha/releases)

**Current Version:** `v0.1.8` (Developer Preview)

## Domain Hubs, Spatial Registry, Multi-Format Exports, Task Pipeline, Navigation Stack & Zero-Overlap UI

This document provides a comprehensive, in-depth technical guide detailing the core architectures, subsystems, and feature implementations powering the **Disha AI Desktop IDE for Urban and Regional Planners**.

---

## 📌 Executive Summary

Urban and regional planning software requires unified coordination between high-performance interactive cartography (MapLibre GL 5+), agentic AI reasoning across diverse planning disciplines, centralized geospatial entity tracking, and production-grade exportable deliverables.

We implemented and hardened twenty-six core platform capabilities:

1. **7+1 Domain Hub Architecture & ToolResult Protocol**: Replaces unorganized flat tool collections with cohesive domain subsystems (`Spatial`, `Mobility`, `Environment`, `Planning`, `Demographics`, `Places`, `Scenarios`, and `Utility`), returning typed execution packets (`ToolResult`) with automated side-effect routing.
2. **Central Spatial & Polygon Registry**: Single source of truth for all study areas, zoning parcels, and boundaries, enforcing $\ge 90\%$ Intersection-over-Union (IoU) deduplication, geodesic ellipsoidal calculations (`pyproj.Geod`), and live map layer synchronization.
3. **Token-Optimized Spatial Context Engine**: Converts complex GeoJSON layers (which previously triggered `400 context_length_exceeded` errors at ~274,000 tokens) into compact, semantically rich spatial metadata (~100 tokens, a $\mathbf{99.96\%}$ reduction).
4. **Task Pipeline Orchestrator (`task_pipeline.py`)**: Implements a Priority-Queue (Asset Phase) and Document-Heap (Compilation Phase) dependency execution model that prevents document hallucination by generating real map/chart assets before compiling documents.
5. **Multi-Format Artifact Export Engine (`export_engine.py`)**: Enables single-click and chat-driven exports across **11 modalities**: `PDF` (`ReportLab` native `%PDF-1.4` with automated Mermaid diagram compilation), `Word (.docx)`, `HTML`, `Markdown (.md)`, `PNG Image`, `JPEG Image`, `SVG`, `TIFF`, `WebP`, `GeoJSON`, `Excel (.xlsx)`, `JSON`, and `TXT`.
6. **Plot & Histogram MCP Server (`PlotServer`)**: Integrated into `UtilityHub` to generate dark- and light-themed publication charts (`bar`, `histogram`, `pie`, `line`, `scatter`) via Matplotlib and persist them directly into the artifact catalog.
7. **Uncropped Bounding-Box Map Composer**: Calculates exact layer bounding coordinates, applies an **$18\%$ geographic margin padding on all four cardinal directions**, and flushes the WebGL frame buffer for zero-crop map snapshots with true planar aspect ratios.
8. **RAG Vector Search & Document Indexing Subsystem (`routers/rag.py`)**: Automatically parses workspace documents (`.pdf`, `.docx`, `.txt`, `.md`), computes OpenAI vector embeddings via `text-embedding-3-small`, and injects top-ranked chunks into chat context.
9. **GTFS Transit & Satellite Land Use Analytics**: Ingests local GTFS transit packages with automated 400m/800m geodesic walking catchment buffers, alongside Google Earth Engine (GEE) Dynamic World zonal land-use statistics.
10. **Workspace Concurrency & Auto-Save Guardrails**: Hardened state-transition lifecycles using `isClosingRef` guards in `App.tsx` to prevent race-condition workspace corruption during project switches.
11. **OpenCode Agent Runtime & MCP Tool Adapter**: Autonomous multi-step orchestration via headless `opencode serve` and stdio JSON-RPC MCP adapter.
12. **Geographic Interpretation & Boundary Containment**: Resolves administrative boundaries and enforces spatial polygon containment without substituting broad search extents, bounding boxes, or radial proximity.
13. **Document Visualization & Section Heading Independence**: Generates separate, dedicated map figures per requested document heading with strict layer isolation.
14. **End-to-End Planning Scenario & MCDA Reports (`scenarios_hub.py`)**: Multi-Criteria Decision Analysis scoring, scenario generation, and automated markdown reports with spatial indicators.
15. **Unified Map Navigation Stack & Interactive Compass Rose (`MapView.tsx`)**: Consolidated top-right glassmorphic navigation pill pairing a rotating compass rose with `+`/`−` zoom buttons. Clicking the compass rose smoothly resets bearing and pitch to North (`mapRef.current.easeTo({ bearing: 0, pitch: 0, duration: 800 })`).
16. **Zero-Overlap Workspace Layout Insets & Frosted Glassmorphism (`App.css`, `DocumentView.css`, `ArtifactsPanel.css`)**: Dynamic geometric insets on `.mundi-workspace-view` (`left: calc(var(--sidebar-width) + 26px)`, `right: var(--chat-drawer-offset)`, `top: 14px`, `bottom: 14px`), preventing workspace views from overlapping with the floating `AppSidebar` or `ChatDrawer`. Styled with Canva Sans typography, 20px rounded cards, and frosted backdrop blur.
17. **Categorized 11-Format Export Dropdown & Header Sources Popover (`ArtifactsPanel.tsx`)**: Replaces sprawling bottom action bars and legacy format buttons with a sleek top-left categorized download dropdown (Documents, Images, Data) and a compact header "Sources" popover dropdown for spatial provenance.
18. **Interactive Drag-and-Drop DocumentView Dropzone & RAG Vector Toolbar (`DocumentView.tsx`)**: Reusable empty-state dropzone supporting native file browsing and drag-and-drop for `PDF`, `TIFF`, `PNG`, `JPEG`, and `WEBP`, coupled with segmented PDF page controls and a glowing vector RAG status pill.
19. **Interactive Policy Levers & Multi-Row Trade-Off Matrix (`ScenarioBuilderPanel.tsx`)**: Full-screen scenario review workspace (`is-scenarios`) featuring interactive policy sliders (`HyperparameterSliders`: Target FAR, Green Space Quota %, Transit Mode Share %, Electric Vehicle Share % EV), resource balance sheets (GFA, Population Capacity, Water Demand MLD, Mobility CO₂), and highlighted recommended best-fit scenarios.
20. **Client-Side SVG Mermaid Decision Flowchart Engine (`ArtifactsPanel.tsx`)**: Native client-side SVG renderer for decision trees, alternatives analysis, and multi-stage planning processes directly within generated reports.
21. **Modal-Driven Publication Map Exporter & Spatial Clip (`MapExportModal.tsx`, `SpatialClipModal.tsx`)**: Dedicated modal windows for configuring cartographic title blocks, scale bars, north arrows, layers, and bounding-box spatial clipping.
22. **Native Floating Layer Context Menus & Direct GeoJSON Feature Export (`FloatingLayerCard.tsx`, `AttributeTable.tsx`)**: Portal-rendered right-click context menu offering instant color swatches, opacity sliders, layer drag-and-drop reordering, and direct single-click GeoJSON export for selected features.
23. **Resizable Multi-Panel IDE Layout & 50% Default Layer Opacity (`App.tsx`, `App.css`, `FloatingLayerCard.tsx`)**: Smooth interactive dragging dividers between left panel, map canvas, and chat drawer, with stacked polygon layers defaulting to 50% opacity to preserve multi-layer geographic legibility.
24. **Hardware-Backed Credential Security with Electron `safeStorage` & OS Keychain (`apps/desktop/src/main/index.ts`)**: Hardware-accelerated API key encryption using OS keychain services with automatic non-ASCII character sanitization and graceful plaintext fallback for headless/containerized workflows.
25. **Resilient WebSocket Auto-Reconnect & Enhanced Diagnostics (`ChatPanel.tsx`, `routers/diagnostics.py`)**: Automatic exponential backoff reconnection for WebSocket connections, diagnostic badge overflow protection, and live validation checks for AI, GIS, and tile services.
26. **Continuous Hero Demo Video & High-Motion Documentation Hub (`docs/index.html`, `docs/js/components.js`)**: Interactive documentation portal featuring seamless autoplaying app walkthroughs, Recordly-style fluid spring animations, and instant full-text search across all 7+1 domain tools.

---

## 🏗️ Architectural Overview & System Flow

```mermaid
flowchart TD
    subgraph Frontend ["Electron Renderer (React 19 + MapLibre GL)"]
        UserSel["User Selects GeoJSON Feature / Layer Collection"]
        MapCanvas["MapLibre WebGL Canvas"]
        NavStack["Unified Map Nav Stack (Compass Rose + Zoom Controls)"]
        Composer["composeFigure() + fitBboxAndSnapshot()"]
        ArtPanel["ArtifactsPanel (Categorized 11-Format Dropdown + Sources Popover)"]
        DocView["DocumentView (Glassmorphic Dropzone + RAG Toolbar)"]
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
        ExpEngine["tools/export_engine.py (11-Format Doc Compiler + Mermaid)"]
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
    ExpEngine -->|Generate PDF / DOCX / HTML / XLSX / Images| ArtStore
    ArtStore -->|HTTP /export Endpoint| ArtPanel
    ChatLoop -->|Auto Map Action (WebSocket)| MapCanvas
    NavStack -.->|Ease to North / Pitch 0 / Zoom| MapCanvas
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

The multi-format compiler in `packages/backend/tools/export_engine.py` allows any planning report, spatial summary, table, or map view to be exported across **11 distinct formats**:

| Format | Technology / Engine | Key Capabilities |
|---|---|---|
| **PDF (`.pdf`)** | `ReportLab` + `mermaid_renderer.py` | Native `%PDF-1.4` binary stream with embedded maps, tables, headers, and pre-compiled high-res PNG renders of Mermaid flowcharts/diagrams. Pure Python base with zero required C-libraries. |
| **Word (`.docx`)** | `python-docx` | Native Microsoft Word document formatting; includes H1/H2 headings, table grids, bullet points, and centered map image figures. |
| **HTML (`.html`)** | `markdown` | Self-contained, responsive HTML report styled with modern CSS typography and base64-embedded map snapshots. |
| **Markdown (`.md`)** | Native Markdown | Clean GFM (GitHub Flavored Markdown) text stream with relative asset references. |
| **PNG (`.png`)** | `Pillow` (PIL) | High-resolution raster map image snapshot with legend, scale bar, and compass rose. |
| **JPEG (`.jpg`)** | `Pillow` (PIL) | Compressed RGB JPEG map snapshot ($95\%$ quality). |
| **SVG (`.svg`)** | Native Vector XML | Scalable vector graphics export for diagrams, plots, and layout figures. |
| **TIFF (`.tif`)** | `Pillow` (PIL) | High-fidelity uncompressed raster export suitable for print publishing and GIS overlay workflows. |
| **WebP (`.webp`)** | `Pillow` (PIL) | Modern web-optimized lossy/lossless image format with high compression ratios. |
| **GeoJSON (`.geojson`)** | Standard `json` / DuckDB | Full spatial vector geometry and feature attribute properties (EPSG:4326). |
| **Excel (`.xlsx`)** | `openpyxl` | Formatted multi-column workbook containing feature properties, attribute tables, and zonal data. |
| **JSON (`.json`)** | Standard `json` | Raw structured metadata and GeoJSON feature collections. |
| **TXT (`.txt`)** | Standard I/O | Plain text document export. |

### Mermaid Diagram Compilation for PDF (`tools/mermaid_renderer.py`)
To render rich architectural flows, scenario comparisons, and decision trees directly in exported PDF documents, `mermaid_renderer.py`:
1. Scans Markdown content for ````mermaid ... ```` code blocks.
2. Compiles diagrams into standalone HTML/SVG wrappers using headless Chromium/Playwright or CLI mermaid compilers (`mmdc`), falling back to clean high-contrast text boxes if graphics engines are unavailable.
3. Injects high-resolution rasterized diagrams into the ReportLab story flow, ensuring identical visual fidelity between interactive chat views and exported PDF deliverables.

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
- **Layer Isolation per Section:** When capturing a map figure for a specific heading, pass `layers_to_show` to `export_map_jpeg`/`export_map_png`/`export_map_pdf` containing only that section's target layers and background boundary outline. This isolates section visuals while preserving all created layers on the interactive map canvas (without deleting or removing canvas layers).
- **Document Asset Sequencing:** The appropriate document structure is inferred from requested headings, and all required underlying maps, plots, statistics, and image artifacts are generated before assembling the document.

---

## 🧭 15. Unified Map Navigation Stack & Interactive Compass Rose

### The Challenge
In earlier versions, map orientation and zoom controls were fragmented across unstyled MapLibre defaults (`NavigationControl`) and separate floating indicators. The compass was static or purely visual, and controls occupied scattered corners of the canvas without consistent glassmorphic styling.

### The Solution Implementation
1. **Consolidated Glassmorphic Pill (`MapView.tsx`, `MapView.css`)**:
   - The default MapLibre `NavigationControl` was removed in favor of a custom, unified React component: `.map-nav-stack`.
   - Anchored to the top-right of the map canvas (`top: 18px`, `right: 18px`), matching the IDE's floating dark glass aesthetic (`rgba(15, 23, 42, 0.78)` background, `backdrop-filter: blur(16px)`, `1px solid rgba(255, 255, 255, 0.12)`, `border-radius: 24px`).
2. **Interactive Compass Rose (Click-to-North Reset)**:
   - Houses a rotating SVG compass rose (`.compass-btn`) that dynamically reflects the map's current camera bearing (`transform: rotate(${-bearing}deg)`).
   - Clicking the compass triggers smooth camera easing back to true North in a 2D flat perspective:
     ```typescript
     mapRef.current.easeTo({
       bearing: 0,
       pitch: 0,
       duration: 800,
     })
     ```
   - Features glowing blue cardinal points, an orange-red North needle tip (`#ef4444`), and subtle hover scale animations.
3. **Integrated Zoom Controls**:
   - Positioned directly below the compass rose, separated by a subtle 1px translucent divider (`rgba(255, 255, 255, 0.08)`).
   - Features `+` (`mapRef.current.zoomIn()`) and `−` (`mapRef.current.zoomOut()`) buttons with active tactile states and smooth MapLibre camera transitions.

---

## 📐 16. Zero-Overlap Workspace Layout Insets & Frosted Glassmorphism

### The Layout Conflict
When switching between map view and workspace modes (`DocumentView`, `ArtifactsPanel`, `ScenarioBuilderPanel`, `DiagnosticsPanel`), full-width panels previously extended from screen edge to screen edge. This caused content to slide underneath the floating `AppSidebar` on the left and the sliding `ChatDrawer` on the right, obscuring buttons, scrollbars, and document margins.

### The Geometric Inset Solution (`App.css`, `App.tsx`)
Disha implements dynamic safe offsets on `.mundi-workspace-view`:
```css
.mundi-workspace-view {
  position: absolute;
  top: 14px;
  bottom: 14px;
  left: calc(var(--sidebar-width) + 26px);
  right: var(--chat-drawer-offset);
  z-index: 15;
  transition: right 0.28s cubic-bezier(0.16, 1, 0.3, 1),
              left 0.28s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  flex-direction: column;
}
```
- **Left Safe Inset:** `calc(var(--sidebar-width) + 26px)` provides an air gap between the floating navigation rail (`72px`) and the workspace container.
- **Right Safe Inset:** Dynamically tied to `--chat-drawer-offset` (which expands from `20px` when closed to `440px+` when open), ensuring the workspace smoothly resizes as the user opens or closes the chat drawer without any visual overlap.
- **Frosted Glass Container:** Rounded with `20px` border-radii, `backdrop-filter: blur(28px)`, Canva Sans typography, and deep elevation shadows (`box-shadow: 0 24px 60px -12px rgba(0, 0, 0, 0.65)`).

---

## 📦 17. Categorized 11-Format Export Dropdown & Header Sources Popover (`ArtifactsPanel.tsx`)

### Streamlined Artifact Header
The previous layout featured a cluttered row of 8 individual export buttons along the bottom of the artifact detail pane. This consumed vertical reading space and forced users to scroll past long markdown reports to export files.

### The Modern Header Architecture
1. **Categorized Download Dropdown**:
   - Consolidated into a single sleek dropdown button (`⬇ Download`) in the artifact header.
   - Categorized into three logical groups with distinct visual tags:
     - **Documents**: PDF (`.pdf`), Word (`.docx`), HTML (`.html`), Markdown (`.md`).
     - **Images**: PNG (`.png`), JPEG (`.jpg`), SVG (`.svg`), TIFF (`.tif`), WebP (`.webp`).
     - **Data**: GeoJSON (`.geojson`), Excel (`.xlsx`), JSON (`.json`), Plain Text (`.txt`).
2. **Compact Header "Sources" Popover**:
   - Replaces the legacy full-width inline provenance card.
   - Displays a clean pill badge `ℹ Sources` in the header next to the download button.
   - Clicking opens a glassmorphic popover listing spatial source datasets, boundary coordinates, coordinate reference systems (EPSG:4326), and processing timestamps.
3. **Elimination of Bottom Action Bars**:
   - Cleaned up bottom action bars from all detail views (`report`, `figure`, `table`, `scenario`), granting full unhindered vertical space to document reading and data inspection.

---

## 📥 18. Interactive Drag-and-Drop DocumentView Dropzone & RAG Vector Toolbar

### Upgraded Document Surface (`DocumentView.tsx`, `DocumentView.css`)
In Document Mode, users examine master plans, zoning maps, regional PDFs, and aerial imagery. The view now features:

1. **Interactive Empty-State Dropzone**:
   - Designed as a centered glassmorphic card with subtle dashed borders and active drag states (`dragover` pulse animation).
   - Highlights supported file extensions with colorful badges: `PDF`, `TIFF`, `PNG`, `JPEG`, `WEBP`.
   - Supports both native OS drag-and-drop and a direct "Browse Files" button invoking `window.electronAPI.openFile()`.
2. **Glassmorphic Document Toolbar**:
   - Houses a segmented PDF pager with previous/next controls, direct page number input, and total page count.
   - Displays zoom controls (`+`, `−`, `Reset`) and current zoom percentage badge.
3. **Glowing RAG Vector Status Indicator**:
   - An intelligent pill badge in the document header reflecting real-time indexing status:
     - 🟢 **`Indexed (Vector RAG Active)`**: Indicates document embeddings are computed in `<workspace>/.disha/rag_index.json` and actively fueling chat retrieval.
     - ⚪ **`Unindexed`**: Offers single-click background vectorization via `/api/rag/index`.

---

## 📊 19. Interactive Policy Levers & Multi-Row Trade-Off Matrix (`ScenarioBuilderPanel.tsx`)

### The Challenge
Urban planners evaluating master plan alternatives need to dynamically manipulate policy levers (FAR, green space quotas, transit mode shares) and immediately quantify the resource trade-offs without manually re-running full simulation pipelines.

### The Solution Implementation
1. **Full-Screen Scenario Review Mode (`.is-scenarios`)**:
   - Expands the scenario review interface into a dedicated planning canvas, eliminating cramped sidebar scrolling.
2. **Deep-Research Policy Levers (`HyperparameterSliders`)**:
   - Live sliders for Target FAR (0.5 – 12.0), Green Space Quota (5% – 50%), Transit Mode Share (10% – 80%), and Electric Vehicle Share (0% – 100%).
3. **Multi-Row Trade-Off Balance Sheet**:
   - Comparative matrix computing Gross Floor Area ($\text{m}^2$), Population Capacity, Daily Water Demand (MLD), and Annual Mobility $\text{CO}_2$ (t/yr) across baseline and alternative scenarios.
4. **Recommended Best-Fit Scenario Scoring**:
   - Automated multi-criteria evaluation calculating composite scores out of 10 and rendering prominent `#1` badges and teal column highlights on the highest-ranking proposal.

---

## 🌲 20. Client-Side SVG Mermaid Decision Flowchart Engine (`ArtifactsPanel.tsx`)

### The Challenge
Planning reports frequently contain approval workflows, stage-gate decision trees, and alternative evaluation rubrics. Standard markdown renderers display these as raw text blocks (`mermaid`), degrading the visual polish of generated reports.

### The Solution Implementation
1. **Native Client-Side SVG Compilation**:
   - Integrated client-side Mermaid parser within `ArtifactsPanel.tsx` that intercepts `mermaid` code blocks and compiles them directly into scalable SVGs.
2. **Dark & Light Theme Harmony**:
   - Applies matching CSS variables to flowchart nodes, strokes, and text labels, ensuring crisp rendering across dark glassmorphic themes.
3. **PDF Export Parity**:
   - Paired with backend `mermaid_renderer.py` via Playwright/Chromium to guarantee identical flowchart rendering in compiled `%PDF-1.4` publication exports.

---

## 🗺️ 21. Modal-Driven Publication Map Exporter & Spatial Clip (`MapExportModal.tsx`, `SpatialClipModal.tsx`)

### The Challenge
Publishing GIS maps for council hearings or technical appendices requires strict cartographic elements: scale bars, true north indicators, title blocks, and study-area boundary clipping.

### The Solution Implementation
1. **Dedicated Publication Modals**:
   - `MapExportModal.tsx`: Configures paper sizes (A4, Letter, Poster), orientation (portrait/landscape), resolution (DPI), title block metadata, and layer visibility toggles.
   - `SpatialClipModal.tsx`: Allows users to define study area bounding boxes or select an administrative boundary polygon to clip active layers.
2. **True Geodesic Scale Bar & North Arrow**:
   - Computes accurate Web-Mercator scale bar divisions based on center latitude using WGS84 ellipsoidal math.
   - North arrow dynamically orients to the map camera bearing.
3. **18% Geographic Boundary Padding**:
   - Automatically calculates layer bounds and pads extents by 18% on all four cardinal directions, preventing edge clipping on exported figures.

---

## 📑 22. Native Floating Layer Context Menus & Direct GeoJSON Feature Export (`FloatingLayerCard.tsx`, `AttributeTable.tsx`)

### The Challenge
Layer controls in GIS sidebars often require deep menu navigation to perform quick operations like color tweaking, opacity adjustments, or exporting a filtered subset of features.

### The Solution Implementation
1. **React Portal Floating Context Menu**:
   - Right-clicking any layer card opens a portal-rendered floating menu positioned accurately at the cursor coordinates.
   - Includes instant 8-color quick swatches for instantaneous layer recoloring.
   - Includes an inline opacity slider (0% to 100%) with real-time WebGL paint property updates.
2. **Direct GeoJSON Feature Selection Export**:
   - In `AttributeTable.tsx`, selected rows can be exported directly to a standalone GeoJSON file with a single click, saving the selection as a persistent layer.

---

## 📐 23. Resizable Multi-Panel IDE Layout & 50% Default Layer Opacity (`App.tsx`, `App.css`, `FloatingLayerCard.tsx`)

### The Challenge
Planners frequently switch focus between deep chat reasoning, expansive map inspection, and multi-column scenario comparisons. Fixed-width sidebars either cramped the map canvas on laptop screens or left excessive unused margins on ultra-wide monitors. Furthermore, overlapping full-opacity polygon layers obscured underlying basemaps and zoning parcels.

### The Solution Implementation
1. **Interactive Draggable Layout Dividers**:
   - Implemented smooth draggable dividers between the left tool panel, central map canvas, and right chat drawer.
   - Constrained with minimum safe widths (`--sidebar-min-width: 280px`, `--chat-min-width: 380px`) and maximum thresholds to prevent viewport collapse.
2. **50% Default Layer Opacity**:
   - All newly loaded vector layers (`.geojson`, `.shp`, `.gpkg`) and AI-generated spatial boundaries default to `0.50` fill opacity.
   - Ensures underlying street grids, satellite basemaps, and intersecting parcels remain immediately visible without manual slider adjustments.

---

## 🔐 24. Hardware-Backed Credential Security with Electron `safeStorage` & OS Keychain (`apps/desktop/src/main/index.ts`)

### The Challenge
AI-native desktop tools require sensitive credentials (OpenAI API key, Google Maps Platform token, Earth Engine service account keys). Storing these in plaintext configuration files creates security liabilities, while naive encryption breaks in headless or containerized environments. Furthermore, raw clipboard paste often introduces invisible non-ASCII characters or trailing whitespace that trigger Python `UnicodeDecodeError: 'ascii' codec can't decode byte` crashes.

### The Solution Implementation
1. **Hardware-Accelerated Encryption**:
   - Uses Electron's native `safeStorage` API backed by macOS Keychain, Windows DPAPI, or Linux Secret Service.
   - Verifies `safeStorage.isEncryptionAvailable()` before encryption; gracefully falls back to encrypted base64 storage if running in containerized or headless environments.
2. **String Sanitization & Codec Protection**:
   - Implemented `sanitizeApiKey()` in `main/index.ts` to strip non-ASCII bytes, carriage returns, and whitespace before saving or passing keys to backend subprocesses.
3. **IPC Key Synchronization**:
   - Exposes `getAPIKey()`, `setAPIKey()`, `getKeyStatus()`, `getGoogleMapsKey()`, `setGoogleMapsKey()`, `getGEEKey()`, and `setGEEKey()` via preload IPC.
   - Emits `onAPIKeysUpdated` events so the frontend instantly re-evaluates system health without restarting the application.

---

## 🔄 25. Resilient WebSocket Auto-Reconnect & Enhanced Diagnostics (`ChatPanel.tsx`, `routers/diagnostics.py`)

### The Challenge
When users put their computer to sleep or when the Python backend undergoes uvicorn hot-reloads during development, WebSocket connections disconnect abruptly. Without automatic recovery, users are forced to refresh the application, losing draft prompts and transient UI state.

### The Solution Implementation
1. **Exponential Backoff Auto-Reconnect**:
   - `ChatPanel.tsx` monitors WebSocket connection lifecycles and automatically attempts reconnection with jittered exponential backoff (1s, 2s, 4s, 8s).
   - Preserves message queues and conversation thread state across temporary reconnects.
2. **System Diagnostics Self-Checks (`routers/diagnostics.py`, `DiagnosticsPanel.tsx`)**:
   - Dedicated startup diagnostic suite probing:
     - OpenAI API connectivity and token quota.
     - Google Maps Platform API keys (Places, Elevation, Air Quality).
     - Google Earth Engine service account authentication.
     - Local GIS runtimes: DuckDB spatial extension, Shapely, pyproj geodesic engine, ReportLab.
     - Free upstream geospatial endpoints: Overpass OSM, Nominatim, OSRM, Open-Meteo.
   - Badge overflow prevention ensures status pills remain scannable regardless of display resolution.

---

## 🎬 26. Continuous Hero Demo Video & High-Motion Documentation Hub (`docs/index.html`, `docs/js/components.js`)

### The Challenge
Static mockups fail to convey the dynamic, real-time feel of an AI agent streaming map actions, drawing polygons, and compiling reports over a live MapLibre GL canvas.

### The Solution Implementation
1. **High-Definition Autoplay Walkthrough Video**:
   - Embedded a lossless desktop demonstration recording directly into the website hero section (`docs/assets/desktop-demo.mp4`).
   - Configured with `autoplay`, `loop`, `muted`, `playsinline`, and `pointer-events: none` to ensure smooth, non-intrusive continuous playback without OS video controls.
2. **Recordly-Style Spring Motion Reveals**:
   - Integrated lightweight CSS spring transitions (`cubic-bezier(0.16, 1, 0.3, 1)`) and hover button dynamics across the feature catalog.
3. **Synchronized Documentation Portal**:
   - Automated via `scripts/sync-docs.mjs` to keep the technical reference hub (`docs/docs.html`) synchronized with the 7+1 Domain Hubs, Central Spatial Registry, and prompt engineering handbook on every release.

---

## 📦 27. Native macOS DMG Drag-and-Drop Installer & Multi-Platform Executable Pipeline (`apps/desktop/electron-builder.yml`)

### The Challenge
Distributing desktop applications for planners on macOS and Windows requires native, friction-free packaging. On macOS, users expect a visual disk image (`.dmg`) with a branded background and an intuitive drag-and-drop shortcut directly into `/Applications`. On Windows, unsigned installer executables frequently trigger false-positive antivirus quarantines from Windows Defender unless bundled with portable ZIP extraction guides.

### The Solution Implementation
1. **Branded macOS Disk Image (`.dmg`)**:
   - Configured `electron-builder.yml` with a customized $540 \times 380$ window layout, custom background graphic (`apps/desktop/build/background.png` and retina `@2x.png`), positioned application icon at $(130, 220)$, and `/Applications` folder alias at $(410, 220)$.
   - Target configuration builds both `.dmg` and `.zip` for instant portable execution.
2. **PyInstaller Backend Freezing**:
   - Freezes Python 3.11+ backend dependencies (FastAPI, DuckDB spatial, Shapely, pyproj, ReportLab) into a self-contained binary (`packages/backend/dist/backend`), which Electron unpacks into `Resources/backend/backend` in production.
3. **Multi-Platform Release Strategy**:
   - Supports parallel GitHub Actions runners for macOS (`mac zip + dmg`) and Windows (`win zip + nsis`).

---

## 🛑 28. Graceful macOS `Cmd + Q` Lifecycle, Auto-Save Flush & Clean Process Termination (`apps/desktop/src/main/index.ts`, `App.tsx`)

### The Challenge
In a dual-process desktop architecture (Electron frontend + Python FastAPI backend), hitting `Cmd + Q` on macOS or clicking "Quit" in the Dock could abruptly terminate the application while workspace auto-save operations were still in flight. This risk corrupted `project.json` or left zombie Python backend processes occupying port `:8765`. Conversely, closing a window (`Cmd + W`) should not kill the app or backend on macOS.

### The Solution Implementation
1. **Native Application Menu & Accelerator**:
   - Configured `Menu.setApplicationMenu()` in `src/main/index.ts` with standard macOS shortcuts, mapping `CommandOrControl+Q` directly to `app.quit()`.
   - Wired in-app MenuBar "Quit Disha" and a global `(e.metaKey || e.ctrlKey) && e.key === 'q'` window listener to `window.electronAPI.quitApp()`.
2. **Graceful Asynchronous Auto-Save Flush**:
   - When `app.quit()` is triggered, `app.on('before-quit')` sets an internal `isQuitting = true` flag and broadcasts `app-before-quit` to the renderer over IPC.
   - The renderer awaits all pending workspace project and document saves (`saveProjectRef.current(true)`).
   - Enforces a 3-second safety timer: if the renderer takes longer than 3 seconds or is unresponsive, the main process forcefully proceeds to shutdown.
3. **Clean Process Termination**:
   - Once saves are confirmed via `app-quit-flush-done` or timer expiration, the main process signals the FastAPI backend process (`SIGTERM` / `SIGKILL`) and destroys all windows.
4. **Dock Invariance (`Cmd + W`)**:
   - Standard window close (`Cmd + W` or red titlebar button) leaves the app resident in the macOS Dock, allowing instant window re-opening without restarting the backend.

---

## 🔑 29. Universal 4-Credential Dynamic API Key Architecture (`ChatPanel.tsx`, `DiagnosticsPanel.tsx`, `chat.py`)

### The Challenge
Urban planners interact with multiple disparate spatial APIs: OpenAI for reasoning, Google Maps Platform for Street View and Places, Google Earth Engine for satellite LULC and NDVI, and Mapillary for crowd-sourced street-level imagery. Users frequently copy keys formatted with shell statements (`export OPENAI_API_KEY="..."`), quotes, or `Bearer ` prefixes. In addition, uncontrolled DOM inputs (`defaultValue` and `document.getElementById`) would reset user-typed keys during re-renders, while strict online validation probes would block valid keys if scoped permissions (e.g. project keys without `models:read`) returned 403 or if the network timed out.

### The Solution Implementation
1. **Unified Controlled React State**:
   - Replaced all uncontrolled DOM queries with React state (`value={...}`, `onChange={...}`) across both `ChatPanel.tsx` and `DiagnosticsPanel.tsx`.
   - Added Show/Hide password visibility toggle buttons next to all password fields.
2. **Multi-Source Normalization Engine**:
   - Frontend and backend normalizers (`normalizeApiKey` / `normalizeGEEKey`) automatically strip:
     - Shell statements: `export KEY=`, `Bearer `
     - Surrounding quotes: `"..."`, `'...'`, `` `...` ``
     - Trailing whitespace, line returns, and non-ASCII bytes.
3. **Immediate Local Persistence**:
   - Saves immediately to Electron `safeStorage` (with base64 fallback so local saving is never blocked by OS keychain permissions).
4. **Dynamic Backend Environment Synchronization (`/api/chat/sync-keys`)**:
   - Injects credentials into `os.environ` of the active Python backend process in real time without restarting the application.
   - Emits `disha-api-keys-updated` across components so that `ChatPanel`, `DiagnosticsPanel`, and the main process remain synchronized.
5. **Non-Blocking Verification Probes**:
   - Updated `/api/chat/validate-key` with a 3.5s timeout on `models.list()` and permissive handling for scoped project keys or offline networks, ensuring valid keys are never discarded or blocked.
6. **One-Click GEE JSON Importer**:
   - Integrated native file dialog file picker for `.json` service account files into both panels, automatically validating and formatting the JSON payload.



