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
