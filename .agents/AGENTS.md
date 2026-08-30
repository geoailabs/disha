# Workspace Rules: Disha

This file documents rules and guidelines for pair programming on this repository.

## GIS Desktop App Patterns

### 1. Windows Quarantine & Distribution
* **Avoid Installer Deletions:** Unsigned `.exe` installers built with PyInstaller/Electron frequently get quarantined by Windows Defender. Always bundle a `.zip` target in `electron-builder.yml` alongside the installer.
* **Extraction Guide:** Double-clicking the executable inside the `.zip` without extraction runs it in a temp directory, breaking relative backend bindings. Instruct users to select "Extract All..." before running.

### 2. Multi-Runner GitHub Actions Releases
* **Avoid Cleanup Race Conditions:** When building on parallel runners (Mac and Windows), the step to delete prior assets must run sequentially or be restricted to the first runner. Subsequent runners must only upload to the created release to avoid deleting each other's uploaded artifacts.

### 3. Spatial Data Layer Transfers
* **Local Workspace Loading:** Do not send raw GeoJSON collections larger than a few kilobytes directly over the WebSocket. Instead, write the file to the workspace directory on the backend and send an `add_geojson_file` MapAction with the absolute path, allowing the frontend to load it locally using Electron's file API.
* **Size-Gated Context Properties:** For LLM context window efficiency, map layers must truncate properties list to keys-only. However, for layers with <= 100 features, populate a `features_data` field with complete key-value structures to allow tools like attribute table extraction to run locally.

## Code Safety & Verification

### 4. JavaScript Hoisting & Ref Scope
* **Verify Declaration Hoisting:** Avoid referencing lexical variables (`const` or `let` arrow functions and hooks) before they are initialized in the component layout. Always place auxiliary helper functions and hooks higher up in the component definition than the functions referencing them.
* **Double-Check Redeclarations:** Never duplicate component-scoped ref or state declarations. Keep variable names clean and inspect for block-scope redeclaration errors.

### 5. Runtime Execution & Dev Server Checks
* **Validate dev builds before final delivery:** Do not rely solely on static checks (e.g., `tsc --noEmit`). If React code has been modified, run the dev server (`pnpm dev` or similar dev script) or start a browser subagent to verify that the app builds, renders successfully, and exhibits no runtime crashes or blank screens in the console.

### 6. Workspace Transition Auto-Save Race Condition
* **Root cause pattern:** In `App.tsx`, `resetWorkspaceState()` resets `layers`, `conversations`, `bookmarks`, `openDocs`, etc. These are all dependency-array entries of the debounced auto-save `useEffect`s. Because React state updates are asynchronous, `workspacePath` is still non-null when those effects re-run after a reset. This causes the auto-save to write **empty data** to `project.json` and `documents.json`, silently corrupting the workspace.
* **The fix — always use `isClosingRef`:** Any function that calls `resetWorkspaceState()` (i.e. `handleCloseWorkspace`, `handleSelectWorkspace`) MUST:
  1. Set `isClosingRef.current = true` **before** calling `resetWorkspaceState()`.
  2. Await all saves (`saveProjectRef.current(true)`, `saveDocumentsToWorkspace(...)`) before the reset.
  3. Call `resetWorkspaceState()` only after saves complete.
  4. Release the guard with `setTimeout(() => { isClosingRef.current = false }, 100)` after setting the new `workspacePath`.
* **Both auto-save effects must check this guard:**
  ```ts
  // Project auto-save
  if (!workspacePath || isLoadingRef.current || isSavingRef.current || isClosingRef.current) return
  // Docs auto-save
  if (!workspacePath || isLoadingRef.current || isSavingDocs || isClosingRef.current) return
  ```
* **ArtifactsPanel double-effect race:** `fetchArtifacts` must guard on `workspacePath` being non-null before hitting the API. If `workspacePath` is null, it must clear state immediately and return — never call `fetch()`. A separate `useEffect` that clears on workspace-close will race with the fetch callback and lose. The guard must live inside `fetchArtifacts` itself.
* **Never revert these guards.** Removing `isClosingRef` from any of the auto-save effects or `fetchArtifacts` will silently re-introduce data corruption that is very hard to reproduce or notice.

## Agent Prompting & Backend GIS Invariants

### 7. System Prompt Neutrality & Zero Test-Case Bias
* **Universal Applicability:** Prompts in `packages/backend/routers/chat.py` (`SYSTEM_PROMPT`, `_RESEARCH_SYSTEM`, and tool descriptions) must remain 100% location-agnostic, neutral, and globally applicable to any city, region, or planning authority worldwide.
* **No Hardcoded Test-Case Entities:** Never inject specific city names, state names, transit terminal acronyms, chowk/junction names, or test-case entities (e.g. "Chandigarh", "Delhi", "Munnar", "Sundarbans", "ISBT", "Tamil Nadu") as specialized rules or examples in `chat.py`. Use generic illustrative placeholders (e.g. "City A and City B", "Times Square", "transit terminals", "commercial parcels").
* **Sub-City Boundaries Rule:** Sub-city spatial queries (neighborhoods, sectors, wards, quarters, suburbs) must be guided by generic GIS principles (OSM `place=*` tag variations and alphanumeric suffixes) rather than region-specific assumptions.

### 8. Case-Insensitive & Exact-Key Matching in GIS Operations
* **Exact-Key Prioritization:** In `gis_filter` and all attribute querying tools, always evaluate exact property key matches (`k.lower() == target_prop.lower()`) before falling back to substring matching. This prevents catastrophic key collisions (such as a search for `state` matching the numeric `statecode` property first).
* **Case & Whitespace Invariance:** Compare string attribute values case-insensitively and trim leading/trailing whitespace (`val.strip().lower() in target_set`).
* **Non-Empty String Matching:** When checking substring containment (`ts in st_name`), always verify that both strings are non-empty (`bool(st_name.strip())`) to prevent empty strings from matching everything.

### 9. Model Context Metric Preservation in `chat.py`
* **Never Strip Calculated Tool Metrics:** When formatting tool outputs returned to the LLM agent loop in `packages/backend/routers/chat.py` (e.g., `osm_boundary`, `osm_boundary_union`, `gis_filter`), never strip calculated quantitative metrics (`area_km2`, `area_hectares`, `centroid`, `bbox`).
* **Root Cause Prevention:** If the model does not see the computed area or centroid in the tool output payload, it assumes the tool failed and panics into external web searches or outputs false failure messages. Always preserve analytical metrics in the model-visible result dictionary.

### 10. Artifact Persistence Guardrails
* **Substantive Reports Only:** Automated artifact persistence (Rule 20) and backend interceptors must only save substantive planning reports, demographic profiles, weather & air quality forecast cards, scenario evaluations, and GIS summaries.
* **Prohibit Error/Failure Artifacts:** Never save error messages, tool failure alerts, failed request traces, or clarifying prompts as artifacts.
* **In-Place Deduplication:** All artifact storage must enforce `(title, artifact_type)` deduplication in `packages/backend/tools/artifact_store.py` to prevent duplicate sidebar entries when updating or refining existing findings.
