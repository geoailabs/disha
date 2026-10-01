# CLAUDE.md

Orientation and reference handbook for AI coding assistants working in the Disha repository.

## 🧭 Repository Documentation Map

- **[AGENTS.md](file:///Users/smriti/Documents/GitHub/disha/AGENTS.md)** — Architectural orientation, invariants, communication channels, 7+1 Domain Hubs, and coding rules.
- **[ARCHITECTURE.md](file:///Users/smriti/Documents/GitHub/disha/ARCHITECTURE.md)** — In-depth architectural design, user/developer guides, and API route index.
- **[FLAUDE.md](file:///Users/smriti/Documents/GitHub/disha/FLAUDE.md)** — Quick reference cheat sheet, critical invariants, and command cheat sheet.
- **[FEATURE_IMPLEMENTATION_GUIDE.md](file:///Users/smriti/Documents/GitHub/disha/FEATURE_IMPLEMENTATION_GUIDE.md)** — Exhaustive deep dive on all 22 core platform capabilities, subsystems, and mathematical models.
- **[.agents/AGENTS.md](file:///Users/smriti/Documents/GitHub/disha/.agents/AGENTS.md)** — Workspace-specific rules, race condition fixes, and GIS best practices.

---

## ⚡ Quick Start & Development Commands

```bash
# Start frontend and backend in development mode
pnpm dev

# Run full backend pytest suite (all 8 domain hubs, spatial registry, exports)
cd packages/backend
.buildenv/bin/pytest tests/ -v

# Frontend type checking
pnpm --filter @disha/desktop exec tsc --noEmit

# Mandatory Vite production bundle verification (ALWAYS run after editing .tsx/.ts)
pnpm --filter @disha/desktop build
```

---

## 🏛️ Architecture in Brief

- **Shell:** Electron 34+ spawning FastAPI on port `:8765` (frozen in prod, hot-reloading uvicorn in dev).
- **Renderer:** React 19 + TypeScript + MapLibre GL 4+ with pure React state (`useState`/`useRef` in `App.tsx`).
- **Backend:** Python 3.11+ FastAPI structured across **7 Planning Domains + 1 Utility Hub** returning typed `ToolResult`.
- **Runtime:** Optional OpenCode Agent runtime (`USE_OPENCODE=true` on port `:4096`) or legacy fallback agent loop in `routers/chat.py`.
- **Cartography:** EPSG:4326 WGS84 GeoJSON throughout; DuckDB `spatial` vector ingestion; WGS84 geodesic calculations (`pyproj.Geod`).
- **UI Architecture:** Floating glassmorphic shell with Canva Sans typography, zero-overlap workspace layout insets (`.mundi-workspace-view`), unified top-right navigation stack with click-to-North flat 2D reset, categorized 11-format artifact export dropdown, and drag-and-drop document dropzone.

---

## 🚨 Critical Invariants & Rules

1. **Workspace Auto-Save Guard (`isClosingRef`):** Always set `isClosingRef.current = true` before calling `resetWorkspaceState()` in `App.tsx` and await all pending saves. Never remove `isClosingRef` — doing so corrupts `project.json` and `documents.json`.
2. **Model Metric Preservation:** Never strip computed spatial metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`) from tool result dictionaries returned to the LLM loop in `packages/backend/routers/chat.py`.
3. **Prompt Location Neutrality:** Prompts in `chat.py` must remain 100% location-neutral and globally applicable. Never hardcode test-case city names or entities.
4. **Token-Optimized Spatial Context:** Pass compact spatial summaries (~100 tokens) rather than raw geometry coordinate arrays (~274k tokens) to prevent LLM context window overflow.
5. **No External State Stores:** Keep all state strictly in React `useState`/`useRef` within `App.tsx`. Do NOT introduce Redux, Zustand, or React Context.
6. **Autonomous Execution & Implicit Authorization:** Automatically execute all intermediate data retrieval and spatial operations before compiling requested deliverables without asking for confirmation ("proceed", "yes") when scope is clear.
7. **Geographic Containment:** Spatially filter features to resolved administrative boundaries whenever features "in" a place are requested; do not substitute broad bounding boxes or radial proximity.
8. **Document Heading Visual Independence:** Generate separate distinct visuals for each requested document heading. Use `layers_to_show` during map exports to isolate heading visuals without removing canvas layers.
9. **Mandatory Production Bundler Verification:** Always run `pnpm --filter @disha/desktop build` after modifying desktop code. TypeScript `tsc --noEmit` alone does not detect all bundler parsing issues.
