"""
OpenCode Query Rewriter — Disha Pre-Pass Module

Intercepts raw user prompts BEFORE they reach the OpenCode agent runtime.
For multi-section document/report requests, expands the prompt into an explicit
numbered STEP plan that tells OpenCode exactly which tool to call, which layers to
show, and how to isolate each map snapshot.

Simple one-shot queries ("fly to Delhi", "show hospitals in Mumbai") are passed
through unchanged.

Architecture:
  chat.py WebSocket handler
      |-- [if USE_OPENCODE] rewrite_query_for_opencode(user_content, map_context, api_key)
             |-- gpt-4o-mini call (~200 token output, ~50ms latency)
             |-- returns structured STEP plan OR original prompt (on failure / simple query)
      |-- run_opencode_agent(rewritten_content, ...)
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("disha.opencode.query_rewriter")

# Rewriter system prompt
_REWRITER_SYSTEM = """You are a GIS task planner for Disha, an AI-powered urban planning desktop IDE.
Your job is to convert a user's raw prompt into a precise, numbered execution plan that an autonomous agent will follow step-by-step.

AVAILABLE TOOL CATEGORIES (for planning purposes):
- Boundary: osm_boundary(place_name, country_code)
- Land cover (single class): extract_land_use_polygons(target_class, place_name) -- use for "built-up area", "water bodies", "forest", "cropland"
- Full LULC raster: get_land_cover(source) -- ONLY if user wants all land classes at once
- Route: osm_route_overview(origin, destination)
- Amenities/POIs: osm_search(query, boundary_name) or nearby_places(query, lat, lng)
- Demographics: project_population(place_name) or get_worldpop_data(lat, lng)
- Export map (isolated): export_map_jpeg(title, save_to_artifacts=True, layers_to_show=[<only this section's layers>])
- Create document: create_artifact(title, format, content)
- Edit document: edit_artifact(artifact_id, section_heading, image_artifact_id, content)
- Charts: create_plot(plot_type, title, x_data, y_data)
- View: fit_bounds() after fetching any boundary or large layer

RULES FOR STEP PLAN OUTPUT:
1. Detect if the query is a MULTI-SECTION request (report/document with multiple headings, multiple map figures, "add section X then Y").
   - If YES: output a numbered STEP plan.
   - If NO (simple one-shot): output the query EXACTLY as received, no changes.

2. For MULTI-SECTION requests, each STEP must follow this pattern:
   STEP N -- <Section Title>:
     Tool calls: <list the exact tools to call in order>
     Map export: export_map_jpeg(title='<title>', save_to_artifacts=True, layers_to_show=['<ONLY this section layer>', '<boundary layer>'])
     Note: <any clarifying instruction>

3. CRITICAL -- layers_to_show MUST contain ONLY:
   - The feature layer generated in THIS step (use the expected layer name as it would appear on the map)
   - The study area boundary layer (if one exists from Step 1)
   - NOTHING ELSE -- no routes from other sections, no markers from other steps

4. Always end the plan with a FINAL STEP that calls create_artifact or edit_artifact to assemble the document.
   Embed each section's image using the file_path returned by that section's export_map_jpeg call.

5. Do NOT add steps the user did not ask for. Do NOT omit steps the user explicitly requested.

6. If the study area/boundary is not yet on the map, STEP 1 must fetch it first.

7. For edit_artifact requests (adding to an existing document), still follow FETCH -> ISOLATE -> EMBED for each new section.

OUTPUT FORMAT:
- For multi-section: numbered STEP blocks as described above, followed by RULES section.
- For simple queries: the exact original query, unchanged.
"""

_REWRITER_USER_TEMPLATE = """Current map state (layers already on canvas):
{map_summary}

User prompt:
{user_content}

Produce the structured execution plan or pass through the query unchanged."""


def _summarize_map_context(map_context: dict[str, Any] | None) -> str:
    """Produce a compact map summary for the rewriter (layer names + center only)."""
    if not map_context:
        return "No active map context."
    center = map_context.get("center", [])
    zoom = map_context.get("zoom", "?")
    layers = map_context.get("layers", [])
    summary_parts = [f"Center: {center}, Zoom: {zoom}"]
    if layers:
        layer_names = [lay.get("name", "unnamed") for lay in layers[:20]]
        summary_parts.append(f"Active layers: {', '.join(layer_names)}")
    else:
        summary_parts.append("Active layers: none")
    return "\n".join(summary_parts)


def _is_complex_request(user_content: str) -> bool:
    """
    Fast heuristic to decide if rewriting is worthwhile.
    Avoids an API call for clearly simple one-shot queries.
    """
    lower = user_content.lower()
    document_signals = [
        "report", "pdf", "docx", "document", "word doc",
        "add section", "add to", "insert", "heading",
        "then add", "followed by", "after that",
        "section 1", "section 2", "first add", "next add",
        "multiple", "several sections",
    ]
    return any(sig in lower for sig in document_signals)


async def rewrite_query_for_opencode(
    user_content: str,
    map_context: dict[str, Any] | None = None,
    api_key: str = "",
) -> str:
    """
    Rewrite a raw user prompt into a structured step-by-step execution plan
    suitable for the OpenCode agent runtime.

    Returns the rewritten plan, or the original prompt unchanged on failure
    or for simple one-shot queries.
    """
    if not user_content.strip():
        return user_content

    # Fast-path: skip API call for clearly simple queries
    if not _is_complex_request(user_content):
        logger.debug("[QueryRewriter] Simple query detected -- passing through unchanged.")
        return user_content

    if not api_key:
        logger.warning("[QueryRewriter] No API key -- skipping rewrite, using raw prompt.")
        return user_content

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        map_summary = _summarize_map_context(map_context)
        user_message = _REWRITER_USER_TEMPLATE.format(
            map_summary=map_summary,
            user_content=user_content,
        )

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _REWRITER_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=1200,
            timeout=15.0,
        )

        rewritten = response.choices[0].message.content or ""
        rewritten = rewritten.strip()

        if not rewritten:
            logger.warning("[QueryRewriter] Empty rewrite response -- using raw prompt.")
            return user_content

        logger.info(
            f"[QueryRewriter] Rewrote prompt ({len(user_content)} chars) -> "
            f"structured plan ({len(rewritten)} chars)"
        )
        logger.debug(f"[QueryRewriter] Plan:\n{rewritten}")

        return rewritten

    except Exception as e:
        # Never let the rewriter break the main flow -- always fall back
        logger.warning(f"[QueryRewriter] Rewrite failed ({type(e).__name__}: {e}) -- using raw prompt.")
        return user_content
