from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
from llm.base import ToolDeclaration

logger = logging.getLogger(__name__)

ROUTE_PALETTE = [
    "#E11D48",  # Rose Red
    "#2563EB",  # Royal Blue
    "#059669",  # Emerald Green
    "#D97706",  # Amber / Orange
    "#7C3AED",  # Purple
    "#0891B2",  # Cyan
    "#EA580C",  # Tangerine
    "#4F46E5",  # Indigo
    "#16A34A",  # Forest Green
    "#DB2777",  # Pink
    "#0284C7",  # Sky Blue
    "#CA8A04",  # Yellow Gold
    "#9333EA",  # Electric Violet
    "#0D9488",  # Teal
    "#DC2626",  # Crimson
    "#475569",  # Slate
]

ROUTE_TYPE_NAMES = {
    "0": "Tram / Streetcar",
    "1": "Subway / Metro",
    "2": "Rail / Train",
    "3": "Bus",
    "4": "Ferry",
    "5": "Cable Tram",
    "6": "Aerial Lift",
    "7": "Funicular",
    "11": "Trolleybus",
    "12": "Monorail",
}


def _col(row: dict[str, Any], *candidates: str, default: str = "") -> str:
    """Case-insensitive flexible column lookup across aliases."""
    normalized = {str(k).lower().strip(): v for k, v in row.items() if v is not None}
    for c in candidates:
        cl = c.lower().strip()
        if cl in normalized:
            val = str(normalized[cl]).strip()
            if val != "":
                return val
    return default


def _resolve_feed_source(raw_path: str, workspace: str | None = None) -> Path | None:
    """
    Universally resolves GTFS zip or directory paths across relative, absolute,
    workspace, downloads, and candidate filenames.
    """
    if not raw_path:
        return None
    cleaned = raw_path.strip().strip("\"'`")
    p = Path(cleaned)

    # 1. Direct path check
    if p.exists():
        return p

    # 2. Check workspace relative
    if workspace:
        ws_p = Path(workspace)
        if (ws_p / cleaned).exists():
            return ws_p / cleaned
        if (ws_p / p.name).exists():
            return ws_p / p.name

    # 3. Candidate search directories
    search_dirs: list[Path] = []
    for d in [Path("D:/downloads"), Path.home() / "Downloads", Path.cwd(), Path(workspace) if workspace else None]:
        if d and d.exists() and d not in search_dirs:
            search_dirs.append(d)

    stem = p.stem.lower()
    candidate_names = [
        p.name,
        f"{p.name}.zip",
        f"{stem}.zip",
        f"gtfs_{stem}.zip",
        f"gtfs{stem}.zip",
        f"{stem}_gtfs.zip",
        stem,
    ]
    for d in search_dirs:
        for cname in candidate_names:
            target = d / cname
            if target.exists():
                return target

    # 4. Case-insensitive substring match in search directories for .zip files
    for d in search_dirs:
        try:
            for item in d.iterdir():
                if item.is_file() and item.suffix.lower() == ".zip":
                    item_stem = item.stem.lower()
                    if stem in item_stem or item_stem in stem:
                        return item
                elif item.is_dir():
                    item_name = item.name.lower()
                    if stem in item_name or item_name in stem:
                        return item
        except Exception:
            continue

    return None


def _find_zip_entry(zf: zipfile.ZipFile, table_name: str) -> str | None:
    """Finds entry in zip by exact name, subfolder path, or case-insensitive name."""
    names = zf.namelist()
    t_lower = table_name.lower()
    for n in names:
        nl = n.lower()
        if nl == t_lower or nl.endswith("/" + t_lower) or nl.endswith("\\" + t_lower):
            return n
    return None


def _read_table_rows(
    source_path: Path,
    table_name: str,
    zf: zipfile.ZipFile | None = None,
    max_rows: int | None = None,
) -> list[dict[str, str]]:
    """Reads CSV rows from a local directory or ZIP file with BOM handling."""
    if zf is not None:
        entry = _find_zip_entry(zf, table_name)
        if not entry:
            return []
        with zf.open(entry) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            if max_rows is not None:
                rows = []
                for idx, row in enumerate(reader):
                    if idx >= max_rows:
                        break
                    rows.append(row)
                return rows
            return list(reader)

    if source_path.is_dir():
        candidates = [source_path / table_name]
        try:
            for sub in source_path.iterdir():
                if sub.is_dir():
                    candidates.append(sub / table_name)
        except Exception:
            pass
        for cand in candidates:
            if cand.exists():
                with open(cand, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    if max_rows is not None:
                        rows = []
                        for idx, row in enumerate(reader):
                            if idx >= max_rows:
                                break
                            rows.append(row)
                        return rows
                    return list(reader)
    return []


def _format_gtfs_time(raw: str) -> str:
    """Formats HH:MM:SS into readable 12-hour format e.g. 4:27 PM."""
    if not raw:
        return ""
    parts = raw.split(":")
    if len(parts) < 2:
        return raw
    try:
        h = int(parts[0])
        m = int(parts[1])
        suffix = "AM"
        if h >= 24:
            h = h % 24
            suffix = "AM (next day)"
        elif h >= 12:
            suffix = "PM"
            if h > 12:
                h -= 12
        elif h == 0:
            h = 12
        return f"{h}:{m:02d} {suffix}"
    except Exception:
        return raw


def _stream_stop_times(
    source_path: Path,
    zf: zipfile.ZipFile | None,
    trip_to_route: dict[str, str],
    routes_needing_fallback: set[str],
    sample_trip_ids: set[str],
    schedule_trip_ids: set[str] | None = None,
):
    """
    Streams stop_times.txt line by line.
    Returns:
      stop_routes: dict[stop_id, set[route_id]]
      trip_stop_seqs: dict[trip_id, list[(seq, stop_id)]]
      histogram: dict[str, int]
      total_stop_times: int
      sample_records: list[dict]
      route_schedule_stops: dict[trip_id, list[(seq, stop_id, dep)]]
    """
    schedule_trip_ids = schedule_trip_ids or set()
    stop_routes: dict[str, set[str]] = defaultdict(set)
    trip_stop_seqs: dict[str, list[tuple[int, str]]] = defaultdict(list)
    route_schedule_stops: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    histogram: dict[str, int] = defaultdict(int)
    total_stop_times = 0
    sample_records: list[dict[str, str]] = []

    def process_row(row: dict[str, str]):
        nonlocal total_stop_times
        total_stop_times += 1
        tid = _col(row, "trip_id", "trip")
        sid = _col(row, "stop_id", "stop")
        if not tid or not sid:
            return

        rid = trip_to_route.get(tid)
        if rid:
            stop_routes[sid].add(rid)

        dep = _col(row, "departure_time", "arrival_time")
        if dep:
            try:
                hour = int(dep.split(":")[0]) % 24
                histogram[f"{hour:02d}:00"] += 1
            except Exception:
                pass

        if tid in schedule_trip_ids:
            try:
                seq = int(_col(row, "stop_sequence", "sequence", default="0"))
                route_schedule_stops[tid].append((seq, sid, dep))
            except Exception:
                pass

        if tid in sample_trip_ids and rid in routes_needing_fallback:
            try:
                seq = int(_col(row, "stop_sequence", "sequence", default="0"))
                trip_stop_seqs[tid].append((seq, sid))
            except Exception:
                pass

        if len(sample_records) < 5000:
            sample_records.append({
                "trip_id": tid,
                "stop_id": sid,
                "departure_time": dep,
                "stop_sequence": _col(row, "stop_sequence", default="0"),
            })

    if zf is not None:
        entry = _find_zip_entry(zf, "stop_times.txt")
        if entry:
            with zf.open(entry) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    process_row(row)
    elif source_path.is_dir():
        candidates = [source_path / "stop_times.txt"]
        try:
            for sub in source_path.iterdir():
                if sub.is_dir():
                    candidates.append(sub / "stop_times.txt")
        except Exception:
            pass
        for cand in candidates:
            if cand.exists():
                with open(cand, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        process_row(row)
                break

    return stop_routes, trip_stop_seqs, histogram, total_stop_times, sample_records, route_schedule_stops


def _stream_shapes(
    source_path: Path,
    zf: zipfile.ZipFile | None,
    selected_shapes: set[str],
) -> dict[str, list[tuple[int, list[float]]]]:
    """
    Streams shapes.txt and only retains points for selected_shapes.
    Returns: shape_coords: dict[shape_id, list[(seq, [lon, lat])]]
    """
    shape_coords: dict[str, list[tuple[int, list[float]]]] = defaultdict(list)
    if not selected_shapes:
        return shape_coords

    def process_row(row: dict[str, str]):
        sid = _col(row, "shape_id", "shape")
        if sid in selected_shapes:
            try:
                lat = float(_col(row, "shape_pt_lat", "lat", "latitude"))
                lon = float(_col(row, "shape_pt_lon", "lon", "lng", "longitude"))
                seq = int(_col(row, "shape_pt_sequence", "sequence", default="0"))
                shape_coords[sid].append((seq, [lon, lat]))
            except Exception:
                pass

    if zf is not None:
        entry = _find_zip_entry(zf, "shapes.txt")
        if entry:
            with zf.open(entry) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    process_row(row)
    elif source_path.is_dir():
        candidates = [source_path / "shapes.txt"]
        try:
            for sub in source_path.iterdir():
                if sub.is_dir():
                    candidates.append(sub / "shapes.txt")
        except Exception:
            pass
        for cand in candidates:
            if cand.exists():
                with open(cand, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        process_row(row)
                break

    return shape_coords


class GTFSServer:
    description = "GTFS Transit Feed Importer & Analyzer"
    tool_names = {"import_gtfs_feed", "analyze_gtfs_service", "analyze_gtfs_schedules", "analyze_transit_catchment"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="import_gtfs_feed",
                description=(
                    "Download and parse a GTFS (General Transit Feed Specification) ZIP file or local path. "
                    "Extracts stops as map points and route shapes as map lines with distinct per-route colors. "
                    "Loads them on the map as separate layers (transit stops + route lines), saving GeoJSON files "
                    "into the active workspace."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to download the GTFS ZIP feed file from."
                        },
                        "path": {
                            "type": "string",
                            "description": "Local file or directory path to an extracted GTFS feed or ZIP (e.g. 'D:/downloads/gtfs_subway.zip')."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional name prefix for the generated layers (e.g. 'MTA Subway', 'Metro-North')."
                        }
                    },
                    "required": ["workspace"]
                }
            ),
            ToolDeclaration(
                name="analyze_gtfs_service",
                description=(
                    "Analyze a previously imported GTFS feed stored in the workspace. "
                    "Returns service statistics: total routes, stops, trips, average headways, "
                    "highest-frequency corridors, and stop accessibility coverage."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder containing imported GTFS files."
                        }
                    },
                    "required": ["workspace"]
                }
            ),
            ToolDeclaration(
                name="analyze_gtfs_schedules",
                description=(
                    "Analyze 24-hour departure schedules, trip frequencies, and stop timetables from GTFS data. "
                    "Generates hourly departure histograms (AM/PM peak hours) and top frequency corridors."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder containing imported GTFS files."
                        },
                        "stop_id": {
                            "type": "string",
                            "description": "Optional stop_id to filter schedule timetable for a specific stop."
                        }
                    },
                    "required": ["workspace"]
                }
            ),
            ToolDeclaration(
                name="analyze_transit_catchment",
                description=(
                    "Compute walking reachability catchments (e.g. 400m or 800m buffers) around GTFS transit stops. "
                    "Merges overlapping stop circles into service coverage polygons and calculates total area in km²."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to active workspace folder containing imported GTFS data."
                        },
                        "radius_meters": {
                            "type": "number",
                            "description": "Walking buffer distance in meters (default: 400)."
                        },
                        "layer_name": {
                            "type": "string",
                            "description": "Optional layer name prefix (default: 'Transit Catchment (400m)')."
                        }
                    },
                    "required": ["workspace"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "import_gtfs_feed":
            return await self._import_gtfs_feed(args)
        if tool_name == "analyze_gtfs_service":
            return await self._analyze_gtfs_service(args)
        if tool_name == "analyze_gtfs_schedules":
            return await self._analyze_gtfs_schedules(args)
        if tool_name == "analyze_transit_catchment":
            return await self._analyze_transit_catchment(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _import_gtfs_feed(self, args: dict) -> dict:
        url = args.get("url", "").strip()
        raw_path = args.get("path", "").strip() or args.get("gtfs_path", "").strip()
        workspace = (args.get("workspace") or args.get("_workspace") or "").strip()
        user_title = args.get("title", "").strip()

        if not url and not raw_path:
            return {"error": "Either url or path is required to load GTFS feed"}
        if not workspace:
            default_ws = Path.home() / ".disha" / "workspace"
            default_ws.mkdir(parents=True, exist_ok=True)
            workspace = str(default_ws)

        ws_path = Path(workspace)
        if not ws_path.exists():
            try:
                ws_path.mkdir(parents=True, exist_ok=True)
            except Exception:
                return {"error": f"Workspace path does not exist: {workspace}"}

        source_path: Path | None = None
        zip_obj: zipfile.ZipFile | None = None

        if raw_path:
            source_path = _resolve_feed_source(raw_path, workspace)
            if not source_path:
                return {"error": f"Local GTFS file or folder not found: {raw_path}. Checked workspace and downloads."}
            if source_path.is_file() and source_path.suffix.lower() == ".zip":
                try:
                    zip_obj = zipfile.ZipFile(source_path)
                except Exception as e:
                    return {"error": f"Failed to read local ZIP: {str(e)}"}
            elif not source_path.is_dir():
                return {"error": f"Invalid GTFS source format: {source_path}"}
        else:
            # Download ZIP from URL
            try:
                async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
                    response = await client.get(url)
                    if response.status_code != 200:
                        return {"error": f"Failed to download GTFS: HTTP {response.status_code}"}
                    zip_bytes = response.content
            except Exception as e:
                return {"error": f"Download error: {str(e)}"}

            try:
                zip_obj = zipfile.ZipFile(io.BytesIO(zip_bytes))
            except zipfile.BadZipFile:
                return {"error": "The URL did not return a valid GTFS ZIP file."}
            except Exception as e:
                return {"error": f"GTFS parsing error: {str(e)}"}

        try:
            # 1. Read core metadata tables
            agency_rows = _read_table_rows(source_path or ws_path, "agency.txt", zip_obj)
            routes = _read_table_rows(source_path or ws_path, "routes.txt", zip_obj)
            trips = _read_table_rows(source_path or ws_path, "trips.txt", zip_obj)
            stops = _read_table_rows(source_path or ws_path, "stops.txt", zip_obj)

            if not routes and not stops:
                return {"error": "GTFS feed missing routes.txt and stops.txt"}

            # 2. Derive agency & feed title
            agency_name = ""
            if agency_rows:
                agency_name = _col(agency_rows[0], "agency_name", "name")

            feed_title = user_title
            if not feed_title:
                if agency_name:
                    feed_title = agency_name
                elif source_path:
                    stem = source_path.stem.replace("gtfs_", "").replace("gtfs", "").replace("_gtfs", "").replace("-", " ")
                    feed_title = stem.title() if stem else "Transit"
                else:
                    feed_title = "Transit"

            feed_slug = re.sub(r"[^a-zA-Z0-9]+", "_", feed_title.lower()).strip("_") or "transit"

            # 3. Build route lookup and trip relationships
            route_map = {_col(r, "route_id", "route"): r for r in routes if _col(r, "route_id", "route")}
            trip_to_route: dict[str, str] = {}
            route_trips: dict[str, list[str]] = defaultdict(list)
            route_dir_shapes: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
            routes_with_shapes: set[str] = set()

            for t in trips:
                rid = _col(t, "route_id", "route")
                tid = _col(t, "trip_id", "trip")
                sid = _col(t, "shape_id", "shape")
                did = _col(t, "direction_id", "direction", default="0")
                if rid and tid:
                    trip_to_route[tid] = rid
                    route_trips[rid].append(tid)
                    if sid:
                        route_dir_shapes[(rid, did)][sid] += 1
                        routes_with_shapes.add(rid)

            # Pick primary representative shapes (top trip shape per route and direction)
            selected_shapes: set[str] = set()
            shape_to_route_dir: dict[str, tuple[str, str]] = {}
            for (rid, did), shapes_dict in route_dir_shapes.items():
                if shapes_dict:
                    # Select most frequent shape for this direction
                    best_shape = max(shapes_dict.items(), key=lambda x: x[1])[0]
                    selected_shapes.add(best_shape)
                    shape_to_route_dir[best_shape] = (rid, did)

            # Determine routes needing stop_times fallback geometry
            all_rids = set(route_map.keys())
            routes_needing_fallback = all_rids - routes_with_shapes
            sample_trip_ids: set[str] = set()
            for rid in routes_needing_fallback:
                t_list = route_trips.get(rid, [])
                if t_list:
                    sample_trip_ids.add(t_list[0])

            # Select representative trip per route for timetable schedule display
            route_primary_trips: dict[str, str] = {}
            trip_headsign: dict[str, str] = {}
            for t in trips:
                rid = _col(t, "route_id", "route")
                tid = _col(t, "trip_id", "trip")
                hs = _col(t, "trip_headsign", "headsign")
                if tid and hs:
                    trip_headsign[tid] = hs
                if rid and tid and rid not in route_primary_trips:
                    route_primary_trips[rid] = tid

            schedule_trip_ids = set(route_primary_trips.values())

            # 4. Stream stop_times.txt (fast line-by-line streaming)
            (
                stop_routes,
                trip_stop_seqs,
                histogram,
                total_stop_times,
                sample_records,
                route_schedule_stops,
            ) = _stream_stop_times(
                source_path or ws_path,
                zip_obj,
                trip_to_route,
                routes_needing_fallback,
                sample_trip_ids,
                schedule_trip_ids,
            )

            # 5. Stream shapes.txt for selected shapes
            shape_coords = _stream_shapes(source_path or ws_path, zip_obj, selected_shapes)

            # 6. Assign unique high-contrast colors per route
            route_colors: dict[str, str] = {}
            for idx, (rid, r_info) in enumerate(route_map.items()):
                c = _col(r_info, "route_color", "color").lstrip("#")
                if len(c) in (3, 6) and all(ch in "0123456789abcdefABCDEF" for ch in c):
                    route_colors[rid] = f"#{c}"
                else:
                    route_colors[rid] = ROUTE_PALETTE[idx % len(ROUTE_PALETTE)]

            # 7. Parent station and platform hierarchy
            parent_stations: dict[str, dict[str, str]] = {}
            child_stops: list[dict[str, str]] = []

            for s in stops:
                loc_type = _col(s, "location_type", default="0")
                sid = _col(s, "stop_id", "stop")
                if not sid:
                    continue
                if loc_type == "1":
                    parent_stations[sid] = s
                elif loc_type in ("", "0"):
                    child_stops.append(s)

            # Propagate route connectivity from child platforms to parent stations
            for c in child_stops:
                cid = _col(c, "stop_id", "stop")
                pid = _col(c, "parent_station")
                if pid and pid in parent_stations:
                    stop_routes[pid].update(stop_routes[cid])

            # Determine which stop records to emit
            stops_to_render: list[dict[str, str]] = []
            if parent_stations:
                # Add all parent stations
                stops_to_render.extend(parent_stations.values())
                # Add child stops that do NOT have a parent station
                for c in child_stops:
                    pid = _col(c, "parent_station")
                    if not pid or pid not in parent_stations:
                        stops_to_render.append(c)
            else:
                stops_to_render.extend(child_stops)

            # 8. Build stops GeoJSON features
            stop_features: list[dict[str, Any]] = []
            seen_stop_coords: set[tuple[int, int]] = set()

            for s in stops_to_render:
                try:
                    lat_str = _col(s, "stop_lat", "lat", "latitude")
                    lon_str = _col(s, "stop_lon", "lon", "lng", "longitude")
                    if not lat_str or not lon_str:
                        continue
                    lat = float(lat_str)
                    lng = float(lon_str)

                    # Deduplicate overlapping coordinates
                    coord_key = (int(round(lat * 10000)), int(round(lng * 10000)))
                    if coord_key in seen_stop_coords:
                        continue
                    seen_stop_coords.add(coord_key)

                    sid = _col(s, "stop_id", "stop")
                    sname = _col(s, "stop_name", "name", default=sid)
                    scode = _col(s, "stop_code", "code")
                    is_station = _col(s, "location_type") == "1"

                    served_rids = stop_routes.get(sid, set())
                    served_names = [
                        _col(route_map[r], "route_short_name") or _col(route_map[r], "route_long_name") or r
                        for r in served_rids if r in route_map
                    ]
                    routes_str = (
                        ", ".join(sorted(served_names)[:8]) + ("..." if len(served_names) > 8 else "")
                        if served_names else "Transit"
                    )

                    if len(served_rids) >= 2 or is_station:
                        stop_color = "#F59E0B"  # Golden Amber transfer hub
                        stop_role = f"Transfer Hub ({len(served_rids)} routes)" if len(served_rids) >= 2 else "Station"
                        stop_radius = 6.5
                    elif len(served_rids) == 1:
                        single_rid = next(iter(served_rids))
                        stop_color = route_colors.get(single_rid, "#2563EB")
                        stop_role = "Transit Stop"
                        stop_radius = 5.5
                    else:
                        stop_color = "#2563EB"
                        stop_role = "Transit Stop"
                        stop_radius = 5.0

                    desc = f"{stop_role}: {sname} ({sid})"
                    if routes_str and routes_str != "Transit":
                        desc += f" · Routes: {routes_str}"

                    stop_features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lng, lat]},
                        "properties": {
                            "name": sname,
                            "title": f"Stop: {sname}",
                            "stop_id": sid,
                            "stop_name": sname,
                            "stop_code": scode,
                            "routes_served": routes_str,
                            "route_count": len(served_rids),
                            "hub_type": stop_role,
                            "color": stop_color,
                            "fillColor": stop_color,
                            "strokeColor": "#FFFFFF",
                            "circleRadius": stop_radius,
                            "circleOpacity": 1.0,
                            "circleStrokeOpacity": 1.0,
                            "opacity": 1.0,
                            "layer_name": f"{feed_title} Stops",
                            "agency_name": agency_name or feed_title,
                            "source_tool": "import_gtfs_feed",
                            "description": desc,
                        }
                    })
                except Exception:
                    continue

            # 9. Build route lines GeoJSON features
            route_features: list[dict[str, Any]] = []
            rendered_shapes: set[str] = set()

            for shape_id in selected_shapes:
                pts = sorted(shape_coords.get(shape_id, []), key=lambda x: x[0])
                if len(pts) < 2:
                    continue
                coords = [p[1] for p in pts]
                rid, did = shape_to_route_dir.get(shape_id, ("", "0"))
                route_info = route_map.get(rid, {})

                r_short = _col(route_info, "route_short_name")
                r_long = _col(route_info, "route_long_name")
                r_color = route_colors.get(rid, ROUTE_PALETTE[len(route_features) % len(ROUTE_PALETTE)])
                r_type = ROUTE_TYPE_NAMES.get(_col(route_info, "route_type", default="3"), "Bus")
                trips_count = len(route_trips.get(rid, []))

                if r_short and r_long:
                    r_title = f"Route {r_short}: {r_long}"
                elif r_short:
                    r_title = f"Route {r_short}"
                elif r_long:
                    r_title = r_long
                else:
                    r_title = f"Route {rid}"

                rendered_shapes.add(shape_id)
                route_features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "name": r_title,
                        "title": r_title,
                        "route_id": rid,
                        "shape_id": shape_id,
                        "direction": "Outbound" if did == "0" else "Inbound",
                        "route_short_name": r_short,
                        "route_long_name": r_long,
                        "route_type": r_type,
                        "daily_trips": trips_count,
                        "color": r_color,
                        "strokeColor": r_color,
                        "route_color": r_color,
                        "lineWidth": 4.5,
                        "lineOpacity": 0.85,
                        "layer_name": f"{feed_title} Routes",
                        "agency_name": agency_name or feed_title,
                        "source_tool": "import_gtfs_feed",
                        "description": f"{r_type} Line {r_title} · {trips_count} daily trips ({agency_name or feed_title})",
                    }
                })

            # Geometry fallback for routes without shapes
            stop_id_coords = {
                f["properties"]["stop_id"]: f["geometry"]["coordinates"]
                for f in stop_features
            }
            for rid in routes_needing_fallback:
                t_list = route_trips.get(rid, [])
                if not t_list:
                    continue
                tid = t_list[0]
                seq_pts = sorted(trip_stop_seqs.get(tid, []), key=lambda x: x[0])
                coords = [stop_id_coords[sid] for _, sid in seq_pts if sid in stop_id_coords]
                if len(coords) < 2:
                    continue

                route_info = route_map.get(rid, {})
                r_short = _col(route_info, "route_short_name")
                r_long = _col(route_info, "route_long_name")
                r_color = route_colors.get(rid, ROUTE_PALETTE[len(route_features) % len(ROUTE_PALETTE)])
                r_type = ROUTE_TYPE_NAMES.get(_col(route_info, "route_type", default="3"), "Bus")
                trips_count = len(route_trips.get(rid, []))

                if r_short and r_long:
                    r_title = f"Route {r_short}: {r_long}"
                elif r_short:
                    r_title = f"Route {r_short}"
                elif r_long:
                    r_title = r_long
                else:
                    r_title = f"Route {rid}"

                route_features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "name": r_title,
                        "title": r_title,
                        "route_id": rid,
                        "shape_id": f"fallback_{rid}",
                        "route_short_name": r_short,
                        "route_long_name": r_long,
                        "route_type": r_type,
                        "daily_trips": trips_count,
                        "color": r_color,
                        "strokeColor": r_color,
                        "route_color": r_color,
                        "lineWidth": 4.5,
                        "lineOpacity": 0.85,
                        "layer_name": f"{feed_title} Routes",
                        "agency_name": agency_name or feed_title,
                        "source_tool": "import_gtfs_feed",
                        "description": f"{r_type} Line {r_title} · {trips_count} daily trips ({agency_name or feed_title})",
                    }
                })

            # 10. Persist GeoJSON and analysis data
            stops_geojson = {"type": "FeatureCollection", "features": stop_features}
            routes_geojson = {"type": "FeatureCollection", "features": route_features}

            # Feed-specific filenames to prevent cross-feed layer collision
            feed_routes_path = ws_path / f"gtfs_{feed_slug}_routes.geojson"
            feed_stops_path = ws_path / f"gtfs_{feed_slug}_stops.geojson"

            with open(feed_routes_path, "w", encoding="utf-8") as f:
                json.dump(routes_geojson, f)
            with open(feed_stops_path, "w", encoding="utf-8") as f:
                json.dump(stops_geojson, f)

            # Also maintain canonical default filenames for standard analysis tools
            with open(ws_path / "gtfs_routes.geojson", "w", encoding="utf-8") as f:
                json.dump(routes_geojson, f)
            with open(ws_path / "gtfs_stops.geojson", "w", encoding="utf-8") as f:
                json.dump(stops_geojson, f)

            # Build ordered route schedules for interactive timetable display
            route_schedules: list[dict[str, Any]] = []
            child_to_parent = {
                _col(c, "stop_id", "stop"): _col(c, "parent_station")
                for c in child_stops
                if _col(c, "parent_station")
            }
            stop_dict = {_col(s, "stop_id", "stop"): s for s in stops if _col(s, "stop_id", "stop")}

            for rid, r_info in route_map.items():
                t_list = route_trips.get(rid, [])
                if not t_list:
                    continue

                chosen_tid = None
                for cand_tid in [route_primary_trips.get(rid), t_list[0]]:
                    if cand_tid and cand_tid in route_schedule_stops and len(route_schedule_stops[cand_tid]) > 0:
                        chosen_tid = cand_tid
                        break
                if not chosen_tid and t_list:
                    for cand_tid in t_list:
                        if cand_tid in route_schedule_stops and len(route_schedule_stops[cand_tid]) > 0:
                            chosen_tid = cand_tid
                            break

                if not chosen_tid or chosen_tid not in route_schedule_stops:
                    continue

                raw_stops = sorted(route_schedule_stops[chosen_tid], key=lambda x: x[0])
                formatted_stops: list[dict[str, Any]] = []
                for seq, sid, dep in raw_stops:
                    pid = child_to_parent.get(sid)
                    s_rec = parent_stations.get(pid) or stop_dict.get(sid, {})
                    sname = _col(s_rec, "stop_name", "name", default=sid)

                    coords = [0.0, 0.0]
                    if sid in stop_id_coords:
                        coords = stop_id_coords[sid]
                    elif pid and pid in stop_id_coords:
                        coords = stop_id_coords[pid]

                    served_rids = stop_routes.get(pid or sid, set())
                    formatted_stops.append({
                        "sequence": seq,
                        "stop_id": sid,
                        "stop_name": sname,
                        "departure_time": dep,
                        "formatted_time": _format_gtfs_time(dep),
                        "coordinates": coords,
                        "is_transfer": len(served_rids) >= 2,
                        "transfer_count": len(served_rids),
                    })

                r_short = _col(r_info, "route_short_name")
                r_long = _col(r_info, "route_long_name")
                r_color = route_colors.get(rid, "#2563EB")
                r_type = ROUTE_TYPE_NAMES.get(_col(r_info, "route_type", default="3"), "Bus")
                trips_count = len(t_list)
                headsign = trip_headsign.get(chosen_tid, "")

                if r_short and r_long:
                    r_title = f"{r_short}: {r_long}"
                elif r_short:
                    r_title = r_short
                elif r_long:
                    r_title = r_long
                else:
                    r_title = f"Route {rid}"

                route_schedules.append({
                    "route_id": rid,
                    "route_short_name": r_short,
                    "route_long_name": r_long,
                    "title": r_title,
                    "badge": r_short or rid,
                    "color": r_color,
                    "route_type": r_type,
                    "daily_trips": trips_count,
                    "headsign": headsign or (f"to {formatted_stops[-1]['stop_name']}" if formatted_stops else ""),
                    "agency_name": agency_name or feed_title,
                    "total_stops": len(formatted_stops),
                    "stops": formatted_stops,
                })

            feed_schedules_path = ws_path / f"gtfs_{feed_slug}_schedules.json"
            with open(feed_schedules_path, "w", encoding="utf-8") as f:
                json.dump(route_schedules, f)
            with open(ws_path / "gtfs_route_schedules.json", "w", encoding="utf-8") as f:
                json.dump(route_schedules, f)

            # Metadata and schedule records
            gtfs_meta = {
                "agency_name": agency_name,
                "feed_title": feed_title,
                "stops_count": len(stop_features),
                "routes_count": len(route_map),
                "trips_count": len(trips),
                "total_stop_times": total_stop_times,
            }
            with open(ws_path / "gtfs_meta.json", "w", encoding="utf-8") as f:
                json.dump(gtfs_meta, f)
            with open(ws_path / f"gtfs_{feed_slug}_meta.json", "w", encoding="utf-8") as f:
                json.dump(gtfs_meta, f)

            with open(ws_path / "gtfs_stops.json", "w", encoding="utf-8") as f:
                json.dump(stops_to_render, f)
            with open(ws_path / "gtfs_routes.json", "w", encoding="utf-8") as f:
                json.dump(routes, f)
            with open(ws_path / "gtfs_trips.json", "w", encoding="utf-8") as f:
                json.dump(trips[:10000], f)
            with open(ws_path / "gtfs_stop_times.json", "w", encoding="utf-8") as f:
                json.dump(sample_records, f)
            with open(ws_path / "gtfs_schedule_histogram.json", "w", encoding="utf-8") as f:
                json.dump(histogram, f)

            # 11. Bounding box computation
            bbox = None
            if stop_features:
                stop_lons = [f["geometry"]["coordinates"][0] for f in stop_features]
                stop_lats = [f["geometry"]["coordinates"][1] for f in stop_features]
                bbox = [min(stop_lons), min(stop_lats), max(stop_lons), max(stop_lats)]

            routes_layer_name = f"{feed_title} Routes"
            stops_layer_name = f"{feed_title} Stops"

            return {
                "status": "success",
                "agency_name": agency_name,
                "feed_title": feed_title,
                "summary": {
                    "stops": len(stop_features),
                    "routes": len(route_map),
                    "trips": len(trips),
                },
                "routes_file": str(feed_routes_path) if route_features else None,
                "stops_file": str(feed_stops_path) if stop_features else None,
                "schedules_file": str(feed_schedules_path) if route_schedules else None,
                "schedules": route_schedules,
                "routes_layer_name": routes_layer_name,
                "stops_layer_name": stops_layer_name,
                "bbox": bbox,
                "workspace": workspace,
                "displayed_on_map": True,
                "message": (
                    f"Successfully imported {feed_title} GTFS feed with {len(stop_features)} stops "
                    f"and {len(route_map)} routes, loaded on the map."
                ),
            }
        finally:
            if zip_obj:
                try:
                    zip_obj.close()
                except Exception:
                    pass

    async def _analyze_gtfs_service(self, args: dict) -> dict:
        workspace = (args.get("workspace") or args.get("_workspace") or "").strip()
        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        meta_file = ws_path / "gtfs_meta.json"
        routes_file = ws_path / "gtfs_routes.json"

        if not meta_file.exists():
            return {"error": "No GTFS data found in workspace. Please run import_gtfs_feed first."}

        with open(meta_file, encoding="utf-8") as f:
            meta = json.load(f)

        routes = []
        if routes_file.exists():
            with open(routes_file, encoding="utf-8") as f:
                routes = json.load(f)

        route_trip_counts: dict[str, int] = defaultdict(int)
        trips_file = ws_path / "gtfs_trips.json"
        if trips_file.exists():
            try:
                with open(trips_file, encoding="utf-8") as f:
                    for trip in json.load(f):
                        route_trip_counts[_col(trip, "route_id", "route")] += 1
            except Exception:
                pass

        type_counts: dict[str, int] = defaultdict(int)
        for r in routes:
            rtype = ROUTE_TYPE_NAMES.get(_col(r, "route_type", default="3"), "Bus")
            type_counts[rtype] += 1

        top_routes = sorted(
            [{"route_id": k, "trips": v, "route_name": ""} for k, v in route_trip_counts.items()],
            key=lambda x: x["trips"],
            reverse=True,
        )[:5]

        return {
            "status": "success",
            "network_stats": {
                "agency_name": meta.get("agency_name", ""),
                "feed_title": meta.get("feed_title", "Transit"),
                "total_routes": meta.get("routes_count", len(routes)),
                "total_stops": meta.get("stops_count", 0),
                "total_trips": meta.get("trips_count", 0),
                "route_types": dict(type_counts),
            },
            "top_frequency_routes": top_routes,
            "note": "Trip counts approximate frequency — higher trip count = more frequent service.",
        }

    async def _analyze_gtfs_schedules(self, args: dict) -> dict:
        workspace = (args.get("workspace") or args.get("_workspace") or "").strip()
        stop_id_filter = args.get("stop_id", "").strip()
        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        hist_file = ws_path / "gtfs_schedule_histogram.json"
        stop_times_file = ws_path / "gtfs_stop_times.json"
        stops_file = ws_path / "gtfs_stops.json"
        routes_file = ws_path / "gtfs_routes.json"

        if not stop_times_file.exists() and not hist_file.exists():
            return {"error": "No GTFS schedule data found. Please run import_gtfs_feed first."}

        histogram: dict[str, int] = {}
        if hist_file.exists():
            try:
                with open(hist_file, encoding="utf-8") as f:
                    histogram = json.load(f)
            except Exception:
                pass

        routes_map: dict[str, str] = {}
        if routes_file.exists():
            try:
                with open(routes_file, encoding="utf-8") as f:
                    for r in json.load(f):
                        rid = _col(r, "route_id", "route")
                        routes_map[rid] = _col(r, "route_short_name") or _col(r, "route_long_name") or rid
            except Exception:
                pass

        stops_map: dict[str, str] = {}
        if stops_file.exists():
            try:
                with open(stops_file, encoding="utf-8") as f:
                    for s in json.load(f):
                        sid = _col(s, "stop_id", "stop")
                        stops_map[sid] = _col(s, "stop_name", "name", default=sid)
            except Exception:
                pass

        timetable: list[dict[str, str]] = []
        if stop_times_file.exists():
            try:
                with open(stop_times_file, encoding="utf-8") as f:
                    for st in json.load(f):
                        sid = _col(st, "stop_id", "stop")
                        dep = _col(st, "departure_time", "arrival_time")
                        if not dep:
                            continue
                        if not histogram:
                            try:
                                hour = int(dep.split(":")[0]) % 24
                                histogram[f"{hour:02d}:00"] = histogram.get(f"{hour:02d}:00", 0) + 1
                            except Exception:
                                pass
                        if stop_id_filter and sid != stop_id_filter:
                            continue
                        timetable.append({
                            "stop_id": sid,
                            "stop_name": stops_map.get(sid, sid),
                            "departure_time": dep,
                            "trip_id": _col(st, "trip_id", "trip"),
                        })
            except Exception:
                pass

        timetable.sort(key=lambda x: x["departure_time"])

        return {
            "status": "success",
            "hourly_departures_histogram": dict(sorted(histogram.items())),
            "stop_timetable": timetable[:50],
            "total_departures": sum(histogram.values()) if histogram else len(timetable),
        }

    async def _analyze_transit_catchment(self, args: dict) -> dict:
        workspace = (args.get("workspace") or args.get("_workspace") or "").strip()
        radius_meters = float(args.get("radius_meters", 400))
        layer_name = args.get("layer_name", "").strip() or f"Transit Catchment ({int(radius_meters)}m)"
        ws = args.get("_ws")

        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        stops_file = ws_path / "gtfs_stops.json"
        if not stops_file.exists():
            return {"error": "No GTFS stop data found. Please run import_gtfs_feed first."}

        with open(stops_file, encoding="utf-8") as f:
            stops = json.load(f)

        if not stops:
            return {"error": "No stops available to calculate catchment."}

        from shapely.geometry import Point, mapping
        from shapely.ops import unary_union

        buffered_polys = []
        for s in stops:
            try:
                lat_str = _col(s, "stop_lat", "lat", "latitude")
                lon_str = _col(s, "stop_lon", "lon", "lng", "longitude")
                if not lat_str or not lon_str:
                    continue
                lat = float(lat_str)
                lng = float(lon_str)
                deg_lat = radius_meters / 111320.0
                deg_lng = radius_meters / (111320.0 * math.cos(math.radians(lat)))
                buffered_polys.append(Point(lng, lat).buffer(max(deg_lat, deg_lng)))
            except Exception:
                continue

        if not buffered_polys:
            return {"error": "Failed to create stop catchment buffers."}

        union_geom = unary_union(buffered_polys)

        from tools.geo import geodesic_area_m2
        total_area_m2 = geodesic_area_m2(mapping(union_geom))
        total_area_km2 = round(total_area_m2 / 1e6, 3)

        feature = {
            "type": "Feature",
            "geometry": mapping(union_geom),
            "properties": {
                "layer_name": layer_name,
                "source_tool": "analyze_transit_catchment",
                "description": f"{int(radius_meters)}m walking catchment area for {len(stops)} stops",
                "radius_meters": radius_meters,
                "stop_count": len(stops),
                "total_area_km2": total_area_km2,
            }
        }

        fc = {"type": "FeatureCollection", "features": [feature]}
        out_path = ws_path / f"gtfs_catchment_{int(radius_meters)}m.geojson"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fc, f)

        if ws:
            try:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(out_path),
                        "name": layer_name,
                        "color": "#3b82f6"
                    }
                }))
            except Exception:
                pass

        return {
            "status": "success",
            "displayed_on_map": True,
            "stops_buffered": len(stops),
            "radius_meters": radius_meters,
            "service_coverage": {
                "area_km2": total_area_km2,
                "area_hectares": round(total_area_m2 / 1e4, 2)
            },
            "layer_name": layer_name,
            "file_path": str(out_path),
            "output_file": str(out_path),
            "output_layer": layer_name
        }
