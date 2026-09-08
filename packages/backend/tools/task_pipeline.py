"""
Task Pipeline Orchestrator — Heap & Queue based document compilation.

When the AI requests a complex document (Word/PDF) that depends on map exports
and chart images, this module:

1. Detects that the assistant message contains BOTH asset-generation calls
   (export_map_png/jpeg, create_plot) AND a document compilation call
   (create_artifact / edit_artifact).

2. Builds a dependency graph:
   - PRIORITY QUEUE  (Phase 1): map exports, plot generation — run first
   - DOCUMENT HEAP   (Phase 2): create_artifact / edit_artifact — run after queue drains

3. Executes Phase 1 completely, collecting real artifact_ids and file_paths.

4. Injects those real paths into the document content markdown before executing
   create_artifact in Phase 2.

5. Always forces create_artifact to create a BRAND NEW artifact (no stale reuse).
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Tools that must complete BEFORE document compilation
_ASSET_TOOLS = {
    "export_map_png",
    "export_map_jpeg",
    "export_map_pdf",
    "create_plot",
}

# Tools that compile documents — must run AFTER assets
_DOCUMENT_TOOLS = {
    "create_artifact",
    "edit_artifact",
}


def classify_tool_calls(tool_calls: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Split a list of tool calls into (asset_phase, document_phase).
    Returns (asset_calls, document_calls).
    """
    asset_calls = []
    document_calls = []
    for tc in tool_calls:
        name = tc.get("name", "")
        if name in _ASSET_TOOLS:
            asset_calls.append(tc)
        elif name in _DOCUMENT_TOOLS:
            document_calls.append(tc)
        else:
            # Other tools (geocode, fit_bounds, osm_boundary…) go to asset phase
            # so they execute before document compilation
            asset_calls.append(tc)
    return asset_calls, document_calls


def patch_content_with_real_paths(
    content: str,
    asset_results: dict[str, dict],
) -> str:
    """
    Replace placeholder image references or unresolved targets in markdown content
    with real artifact paths returned from asset tool executions.
    """
    if not content:
        return content

    assets: list[dict] = []
    for tc_id, result in asset_results.items():
        if isinstance(result, dict):
            fpath = result.get("file_path")
            if fpath and fpath.startswith("artifacts_store/"):
                assets.append(result)

    if not assets:
        return content

    # All generated real paths
    known_real_paths = {a["file_path"] for a in assets}

    img_pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
    used_asset_indices: set[int] = set()

    def _match_asset_for_ref(alt: str, src: str) -> Optional[str]:
        # If src is already one of the freshly generated asset paths and not reused, keep it
        if src in known_real_paths:
            return None

        comb_text = f"{alt} {src}".lower().replace("_", " ").replace("-", " ")
        
        # 1. Match by specific keywords in title
        for idx, a in enumerate(assets):
            if idx in used_asset_indices:
                continue
            title = (a.get("title") or "").lower().replace("_", " ").replace("-", " ")
            title_words = [w for w in title.split() if len(w) > 3 and w not in ("area", "map", "figure", "boundary", "plot", "chart", "distribution")]
            if any(w in comb_text for w in title_words):
                used_asset_indices.add(idx)
                return a["file_path"]

        # 2. Match sequentially for generic placeholders or filenames
        for idx, a in enumerate(assets):
            if idx not in used_asset_indices:
                used_asset_indices.add(idx)
                return a["file_path"]

        return None

    def _replace_img(m: re.Match) -> str:
        alt = m.group(1)
        src = m.group(2)
        matched_path = _match_asset_for_ref(alt, src)
        if matched_path:
            return f"![{alt}]({matched_path})"
        return m.group(0)

    content = img_pattern.sub(_replace_img, content)
    return content


def needs_pipeline(tool_calls: list[dict]) -> bool:
    """
    Returns True if this batch of tool calls has BOTH asset tools AND
    document tools — meaning we need to enforce the pipeline ordering.
    """
    names = {tc.get("name", "") for tc in tool_calls}
    has_assets = bool(names & _ASSET_TOOLS)
    has_docs = bool(names & _DOCUMENT_TOOLS)
    return has_assets and has_docs


def inject_new_artifact_instruction(tool_calls: list[dict]) -> list[dict]:
    """
    For every create_artifact call in the batch, ensure the args do NOT
    reference an existing artifact_id (force creation of a fresh document).
    """
    patched = []
    for tc in tool_calls:
        if tc.get("name") == "create_artifact":
            try:
                args = json.loads(tc.get("arguments", "{}"))
                # Remove any stale artifact_id that would cause a reuse
                args.pop("artifact_id", None)
                args.pop("id", None)
                tc = {**tc, "arguments": json.dumps(args)}
            except Exception:
                pass
        patched.append(tc)
    return patched
