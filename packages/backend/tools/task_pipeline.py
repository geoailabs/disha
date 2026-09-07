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
    Replace placeholder image references in markdown content with real
    artifact paths returned from asset tool executions.

    asset_results: maps tool_call_id → parsed result dict from _execute_tool
    """
    if not content:
        return content

    # Build a map of placeholders → real paths from asset results
    # Each asset result may contain: {artifact_id, file_path, title}
    real_paths: list[str] = []
    for tc_id, result in asset_results.items():
        if isinstance(result, dict):
            fpath = result.get("file_path")
            if fpath and fpath.startswith("artifacts_store/"):
                real_paths.append(fpath)

    if not real_paths:
        return content

    # Pattern 1: Replace generic placeholder markers like ![...](map_snapshot)
    # or ![...](artifacts_store/placeholder.jpg)
    placeholder_pattern = re.compile(
        r'!\[([^\]]*)\]\((map_snapshot|placeholder[^)]*|artifacts_store/0\.\w+)\)',
        re.IGNORECASE,
    )

    real_path_iter = iter(real_paths)

    def _replace_placeholder(m):
        try:
            rpath = next(real_path_iter)
            return f"![{m.group(1)}]({rpath})"
        except StopIteration:
            return m.group(0)

    content = placeholder_pattern.sub(_replace_placeholder, content)
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
