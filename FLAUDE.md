# FLAUDE.md — AI Coding Assistant Reference

**Fast reference handbook for AI pair programmers working on Disha.**

---

## 1. Quick Orientation

Disha is a desktop IDE for urban and regional planners combining an interactive **MapLibre GL** canvas with a Python **FastAPI** backend structured into **7 Core Planning Domain Hubs and 1 Cross-Cutting Utility Hub**.

- **Frontend:** Electron + React 19 + TypeScript (`apps/desktop/src/renderer`)
- **Backend:** Python 3.11+ FastAPI on port `8765` (`packages/backend`)
- **Communication:** WebSocket `ws://localhost:8765/api/chat/ws` (streaming chat & map actions) + HTTP `/api/*` (10 routers) + Electron IPC (`window.electronAPI`)

---

## 2. Standard Development & Verification Commands

```bash
# Start dev server (backend on :8765 + electron-vite frontend)
pnpm dev

# Backend pytest suite (all 8 domain hubs, spatial registry, websockets, exports)
cd packages/backend
.buildenv/bin/pytest tests/

# Frontend typecheck
pnpm --filter @disha/desktop exec tsc --noEmit

# Mandatory Vite production bundle verification
pnpm --filter @disha/desktop build
```

---

## 3. Directory Layout & Key Locations

| Subsystem | Key Files | Responsibility |
|---|---|---|
| **OpenCode Runtime** | `packages/backend/llm/opencode/` | Headless OpenCode server lifecycle, session manager, SSE translator, and stdio MCP tool server (`mcp_server.py`). |
| **Agentic Loop** | `packages/backend/routers/chat.py` | WebSocket handler, `run_opencode_agent` / `_run_agent`, tool schema building, map action dispatch, deep research. |
| **Domain Hubs** | `packages/backend/domains/` | 8 Domain Hubs implementing `BaseDomainHub` in `domains/protocol.py`, returning typed `ToolResult`. |
| **Spatial Registry** | `packages/backend/tools/spatial_registry.py` | Authoritative polygon singleton, IoU $\ge 90\%$ deduplication, geodesic math (`pyproj.Geod`). |
| **Task Pipeline** | `packages/backend/tools/task_pipeline.py` | Queue-before-Heap dependency ordering for map exports and document compilation. |
| **Export Engine** | `packages/backend/tools/export_engine.py` | Multi-format compiler for 8 formats (`.pdf`, `.docx`, `.html`, `.png`, `.jpg`, `.xlsx`, `.json`, `.txt`). |
| **RAG Indexing** | `packages/backend/routers/rag.py` | Workspace document parsing, OpenAI embeddings, and semantic vector search. |
| **State Container** | `apps/desktop/src/renderer/App.tsx` | Pure React state (`useState`/`useRef`), action routing, workspace auto-save lifecycle guards. |
| **Map Component** | `apps/desktop/src/renderer/components/MapView.tsx` | MapLibre GL setup, paint expressions, drawing tools, uncropped 18% padded snapshot composer. |
| **Chat Component** | `apps/desktop/src/renderer/components/ChatPanel.tsx` | WebSocket client, streaming markdown, question option cards, deep research UI. |
| **Preload IPC** | `apps/desktop/src/preload/index.ts` | IPC bridge between Chromium renderer and Electron main process. |

---

## 4. The 7+1 Domain Hubs

1. **`SpatialHub`** (`domains/spatial_hub.py`): GIS analysis, administrative boundaries (OSM, DataMeet), WMS raster services, Central Spatial Registry.
2. **`MobilityHub`** (`domains/mobility_hub.py`): Road networks, Dijkstra/freight routing with Z-levels, GTFS transit & walking sheds, ITS signal optimization, OD gravity flows.
3. **`EnvironmentHub`** (`domains/environment_hub.py`): Google Earth Engine LULC & NDVI indices, Open-Meteo weather & air quality, Google Solar/Elevation, fleet emissions.
4. **`PlanningHub`** (`domains/planning_hub.py`): Zoning classification & overlaps, document georeferencing, image feature digitization.
5. **`DemographicsHub`** (`domains/demographics_hub.py`): WorldPop population metrics, cohort-component demographic forecasts, employment density.
6. **`PlacesHub`** (`domains/places_hub.py`): Google Places Platform and Overture 3D buildings & POIs.
7. **`ScenariosHub`** (`domains/scenarios_hub.py`): Planning scenario generation and MCDA scoring matrices.
8. **`UtilityHub`** (`domains/utility_hub.py`): Forward/reverse geocoding, live web research, measurements, Matplotlib plotting (`create_plot`), interactive questions (`ask_question`), artifact CRUD.

---

## 5. Map Actions Contract

When the AI calls an action tool or a hub returns a `map_action`, it is dispatched over WebSocket as:
```json
{ "type": "action", "action": "<name>", "payload": { ... } }
```

**Supported Map Actions (24 tools):**
`fly_to`, `fit_bounds`, `add_marker`, `add_markers`, `clear_markers`, `draw_line`, `draw_polygon`, `draw_circle`, `add_geojson`, `add_geojson_file`, `highlight_features`, `set_layer_style`, `style_layer`, `toggle_layer`, `remove_layer`, `save_bookmark`, `go_to_bookmark`, `export_region_clip`, `export_map_png`, `export_map_jpeg`, `export_map_pdf`, `switch_basemap`, `add_gee_layer`, `add_raster_overlay`.

---

## 6. Critical Invariants (Never Violate)

1. **Workspace Auto-Save Guard (`isClosingRef`):**
   In `App.tsx`, whenever resetting workspace state, ALWAYS assert `isClosingRef.current = true` before state resets and await all saves. Removing or bypassing `isClosingRef` silently corrupts `project.json`.
2. **Model Metric Preservation:**
   Never strip calculated spatial metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`) from tool result dictionaries in `chat.py`. The LLM requires these metrics to confirm tool success.
3. **Prompt Location Neutrality:**
   Prompts in `chat.py` must remain 100% location-neutral and globally applicable. Never hardcode specific test-case cities or entities.
4. **Token-Optimized Spatial Context:**
   Pass lightweight spatial metadata summaries (~100 tokens) rather than raw GeoJSON coordinate arrays (~274k tokens) in prompts to prevent context window overflow.
5. **No External State Libraries:**
   Maintain pure React `useState`/`useRef` in `App.tsx`. Do NOT introduce Zustand, Redux, or React Context.
6. **Autonomous Execution & Implicit Authorization:**
   When a user requests a document, report, map, plot, analysis, or artifact requiring preliminary data, execute all necessary intermediate operations automatically before producing the artifact. Never stop to ask the user to confirm ("proceed", "yes") when outputs and scope are already clear. Never ask for administrative levels, datasets, or GIS operations unless genuinely ambiguous. The user's request implicitly authorizes all intermediate retrieval, analysis, visualization, and generation steps.
7. **Geographic Interpretation & Boundary Containment:**
   When a user asks for features "in" a named geographic place, resolve the place boundary and spatially filter the requested features to that boundary. Preserve the containment constraint across tool selection, data retrieval, and spatial processing without substituting broad bounding boxes or proximity radii. Infer all intermediate GIS steps internally.
8. **Document Visualization & Output Preservation:**
   When separate visuals are requested under separate headings in a document, generate a separate distinct visual for each heading (do not combine them). Each visual must contain only layers and information relevant to its specific heading without carrying unrelated layers from other sections. Generate all required underlying maps, plots, and statistics before assembling the document.
