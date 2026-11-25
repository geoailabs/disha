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
from pathlib import Path
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
    used_paths: set[str] = set()

    def _match_asset_for_ref(alt: str, src: str) -> Optional[str]:
        # If src is already one of the freshly generated asset paths and not yet used in another section, keep it
        if src in known_real_paths and src not in used_paths:
            used_paths.add(src)
            for idx, a in enumerate(assets):
                if a.get("file_path") == src:
                    used_asset_indices.add(idx)
                    break
            return None

        comb_text = f"{alt} {src}".lower().replace("_", " ").replace("-", " ")
        
        # 1. Match by specific keywords in title
        for idx, a in enumerate(assets):
            fpath = a.get("file_path", "")
            if idx in used_asset_indices or fpath in used_paths:
                continue
            title = (a.get("title") or "").lower().replace("_", " ").replace("-", " ")
            title_words = [w for w in title.split() if len(w) > 3 and w not in ("area", "map", "figure", "boundary", "plot", "chart", "distribution")]
            if any(w in comb_text for w in title_words):
                used_asset_indices.add(idx)
                used_paths.add(fpath)
                return fpath

        # 2. Match sequentially for generic placeholders, filenames, or duplicate real paths
        for idx, a in enumerate(assets):
            fpath = a.get("file_path", "")
            if idx not in used_asset_indices and fpath not in used_paths:
                used_asset_indices.add(idx)
                used_paths.add(fpath)
                return fpath

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


_PLOT_VERBS = re.compile(
    r"\b(plot|show|map|mark|display|draw|extract|fetch|get|load|visuali[sz]e|highlight|add|find|list|count|overlay)\b"
)
_ROUTE_WORDS = re.compile(r"\b(route|routes|directions?|shortest path|travel time|from\s+\S+.*\s+to\s+\S+)\b")
_ROAD_WORDS = re.compile(r"\b(roads?|streets?|road network|street network|road map|highways?|street grid)\b")


def _tool_calls_this_turn(recent: list[dict]) -> list[tuple[str, dict, dict]]:
    """[(tool_name, args, result)] for every tool call answered in this turn."""
    names: dict[str, tuple[str, dict]] = {}
    for msg in recent:
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            names[tc.get("id")] = (fn.get("name") or "", args)
    out = []
    for msg in recent:
        if msg.get("role") != "tool":
            continue
        name, args = names.get(msg.get("tool_call_id"), ("", {}))
        try:
            res = json.loads(msg.get("content") or "{}")
        except Exception:
            res = {}
        out.append((name, args, res if isinstance(res, dict) else {}))
    return out


def requested_feature_gaps(user_request: str, calls: list[tuple[str, dict, dict]]) -> list[str]:
    """Map features the user asked to see that no successful tool call produced.

    Deterministic guard against answers such as "the boundary has been plotted"
    when the user asked for the roads (or hospitals, schools, …) inside it.
    """
    text = (user_request or "").lower()
    if not _PLOT_VERBS.search(text):
        return []

    def ok(res: dict) -> bool:
        return not res.get("error") and res.get("status") not in ("error", "cancelled", "blocked")

    gaps = []
    if _ROAD_WORDS.search(text) and not _ROUTE_WORDS.search(text):
        has_roads = any(
            ok(res) and (
                name == "fetch_street_network"
                or (name == "osm_search" and "highway" in json.dumps(args).lower())
            )
            for name, args, res in calls
        )
        if not has_roads:
            gaps.append(
                "requested road/street network was not plotted — call fetch_street_network(place_name='<place>') "
                "(it outlines the boundary AND draws the roads inside it)"
            )

    try:
        from tools.osm_categories import ALIASES, OSM_CATEGORIES, normalise_category
    except Exception:
        return gaps
    words = set(re.findall(r"[a-z_]+", text))
    tokens = [re.sub(r"[^a-z]", "", t) for t in text.split()]
    pairs = {f"{a}_{b}" for a, b in zip(tokens, tokens[1:])}
    # Words that are usually modifiers or parts of other phrases ("government schools",
    # "river bank", "post office") are not treated as separate category requests.
    ambiguous = {"government", "bank", "industrial", "worship", "fuel", "market", "office"}
    if pairs & {"post_office", "post_offices"}:
        ambiguous.add("offices")
    phrases = {w for w in words if w not in ambiguous} | pairs
    wanted = set()
    for token in phrases:
        token = re.sub(r"[^a-z_]", "", token)
        if token in OSM_CATEGORIES or token in ALIASES:
            key = normalise_category(token)
            if key and OSM_CATEGORIES[key]["mode"] == "point":
                wanted.add(key)
    for key in sorted(wanted):
        produced = False
        for name, args, res in calls:
            if not ok(res):
                continue
            if name == "osm_search":
                cats = [args.get("category")] + list(args.get("categories") or [])
                if any(normalise_category(c) == key for c in cats if c):
                    produced = True
            elif name in ("nearby_places", "nearby_places_in_polygon", "overture_places_search", "places_density"):
                produced = True  # explicit alternative source chosen by the model
        if not produced:
            gaps.append(
                f"requested '{OSM_CATEGORIES[key]['label']}' were not plotted — call osm_search(category='{key}', place_name='<place>')"
            )
    return gaps


def assess_task_completion(messages: list[dict], since: int = 0, workspace: str | None = None) -> dict:
    """Run a cheap deterministic postcondition check for the current turn.

    This is deliberately independent of the model: a response is only marked
    verified when tool results are successful, generated files exist, and no
    tool was cancelled or returned an error.
    """
    recent = messages[since:]
    # Only the user's own request — not the system correction messages injected later
    # in the turn (they mention tools/features and would create false requirements).
    user_text = " ".join(
        str(msg.get("content") or "")
        for msg in recent
        if msg.get("role") == "user" and not str(msg.get("content") or "").lstrip().startswith("[SYSTEM")
    ).lower()
    calls = _tool_calls_this_turn(recent)
    requested_gif = bool(re.search(r"\bgif\b", user_text))
    requested_modis_fire = bool(
        re.search(r"\b(?:modis|stubble(?:[- ]burning)?|fire(?:s| history)?|burn(?:ing|ed) area)\b", user_text)
    )
    requested_fire_comparison = requested_modis_fire and bool(
        re.search(r"\b(compar\w*|differen\w*|vs|versus|history|trend|report|change)\b", user_text)
    )
    requested_animation = requested_gif and bool(
        re.search(r"\b(animated?|animation|year[- ]by[- ]year|frame|timeline|over the next)\b", user_text)
    )
    year_match = re.search(r"\b(\d+)\s*[- ]?(?:year|frame)", user_text)
    range_match = re.search(r"\b(20\d{2})\s+through\s+(20\d{2})\b", user_text)
    requested_frame_count = int(year_match.group(1)) if requested_animation and year_match else 2
    if requested_animation and range_match:
        requested_frame_count = max(
            requested_frame_count,
            abs(int(range_match.group(2)) - int(range_match.group(1))) + 1,
        )
    tool_results = []
    for msg in recent:
        if msg.get("role") != "tool":
            continue
        try:
            value = json.loads(msg.get("content") or "{}")
        except Exception:
            value = {"status": "error", "error": "Malformed tool result"}
        tool_results.append(value)

    failures = []
    missing_files = []
    generated_paths = []
    gif_paths = []
    modis_results = [
        result for result in tool_results
        if isinstance(result.get("results"), list)
        and result.get("start_year") is not None
        and result.get("end_year") is not None
    ]
    for result in tool_results:
        status = result.get("status")
        if result.get("error") or status in ("error", "cancelled"):
            failures.append(result.get("error") or status)
        file_path = result.get("file_path")
        if not file_path and isinstance(result.get("artifact"), dict):
            file_path = result["artifact"].get("file_path")
        if file_path:
            # GIF frame exports are deliberately deleted after encoding. They
            # are staging inputs, not user-facing deliverables, so they must
            # not make the final completion check fail after cleanup.
            if result.get("temporary_gif_frame"):
                continue
            normalized_path = str(file_path).lower()
            generated_paths.append(normalized_path)
            if normalized_path.endswith(".gif"):
                gif_paths.append(str(file_path))
            candidate = Path(file_path)
            exists = candidate.is_file() and candidate.stat().st_size > 0
            if not exists and not candidate.is_absolute() and str(file_path).startswith("artifacts_store/"):
                try:
                    from tools.artifact_store import get_artifacts_dir
                    resolved = get_artifacts_dir(workspace) / candidate.name
                    exists = resolved.is_file() and resolved.stat().st_size > 0
                except Exception:
                    exists = False
            if not exists:
                missing_files.append(file_path)

    # A GIF request has a concrete binary postcondition even if the model
    # creates an intermediate scenario plan or storyboard first.
    if requested_gif and not any(path.endswith(".gif") for path in generated_paths):
        missing_files.append("requested GIF artifact")

    if requested_fire_comparison and not any(result.get("results") for result in modis_results):
        missing_files.append("MODIS fire comparison results (call compare_modis_fire_history once with all places)")
    elif requested_modis_fire and not requested_fire_comparison and not any(
        name in ("get_modis_layer", "compare_modis_fire_history") and not res.get("error")
        for name, _a, res in calls
    ):
        missing_files.append("MODIS fire layer (call get_modis_layer with product='active_fires' or 'burned_area')")

    feature_gaps = requested_feature_gaps(user_text, calls)

    # A temporal/animated request must not be satisfied by a one-frame GIF
    # labelled as a storyboard. Static GIFs remain valid for ordinary GIF
    # requests; animation language makes the stronger postcondition explicit.
    if requested_animation and gif_paths:
        animated = False
        try:
            from PIL import Image
            from tools.artifact_store import get_artifacts_dir

            for raw_path in gif_paths:
                candidate = Path(raw_path)
                if not candidate.is_file() and not candidate.is_absolute() and raw_path.startswith("artifacts_store/"):
                    candidate = get_artifacts_dir(workspace) / candidate.name
                if not candidate.is_file():
                    continue
                with Image.open(candidate) as image:
                    frame_count = int(getattr(image, "n_frames", 1))
                    if frame_count < requested_frame_count:
                        continue
                    # Count distinct rendered states as well as GIF frames;
                    # repeating one frame under multiple year labels is not a
                    # valid year-by-year animation.
                    import hashlib
                    distinct_states = set()
                    for frame_index in range(frame_count):
                        image.seek(frame_index)
                        rendered = image.convert("RGB")
                        distinct_states.add(hashlib.sha256(rendered.tobytes()).digest())
                    if len(distinct_states) >= requested_frame_count:
                        animated = True
                        break
        except Exception as exc:
            logger.warning("Could not inspect GIF animation frames: %s", exc)
        if not animated:
            missing_files.append(
                f"requested animated GIF must contain at least {requested_frame_count} frames"
            )

    if failures:
        state = "failed"
    elif missing_files or feature_gaps:
        state = "failed"
        failures.extend(f"missing file: {p}" for p in missing_files)
        failures.extend(f"missing map feature: {g}" for g in feature_gaps)
    elif tool_results:
        state = "verified"
    else:
        state = "not_applicable"
    return {
        "status": state,
        "checks": {
            "tool_results_present": bool(tool_results),
            "all_tool_results_successful": not failures,
            "artifact_files_exist": not missing_files,
            "requested_features_present": not feature_gaps,
        },
        "failures": failures,
    }
