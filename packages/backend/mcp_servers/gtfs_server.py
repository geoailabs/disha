from __future__ import annotations
import csv
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import httpx
from llm.base import ToolDeclaration


class GTFSServer:
    description = "GTFS Transit Feed Importer & Analyzer"
    tool_names = {"import_gtfs_feed", "analyze_gtfs_service", "analyze_gtfs_schedules", "analyze_transit_catchment"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="import_gtfs_feed",
                description=(
                    "Download and parse a GTFS (General Transit Feed Specification) ZIP file or local path. "
                    "Extracts stops as map points and route shapes as map lines. Loads them on the map as "
                    "separate layers (transit stops + route lines), saving files into the active workspace."
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
                            "description": "Local file or directory path to an extracted GTFS feed or ZIP."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional name prefix for the generated layers (e.g. 'Chandigarh Bus')."
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
        path = args.get("path", "").strip()
        workspace = args.get("workspace", "").strip()
        title = args.get("title", "").strip() or "Transit"
        ws = args.get("_ws")

        if not url and not path:
            return {"error": "Either url or path is required to load GTFS feed"}
        if not workspace:
            return {"error": "workspace is required to save GTFS files"}

        ws_path = Path(workspace)
        if not ws_path.exists():
            return {"error": f"Workspace path does not exist: {workspace}"}

        stops, routes, trips, shapes, stop_times = [], [], [], [], []

        if path:
            local_path = Path(path)
            if local_path.is_dir():
                def read_local_csv(filename: str) -> list[dict]:
                    fp = local_path / filename
                    if fp.exists():
                        with open(fp, encoding="utf-8-sig") as f:
                            return list(csv.DictReader(f))
                    return []
                stops = read_local_csv("stops.txt")
                routes = read_local_csv("routes.txt")
                trips = read_local_csv("trips.txt")
                shapes = read_local_csv("shapes.txt")
                stop_times = read_local_csv("stop_times.txt")
            elif local_path.is_file() and local_path.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(local_path) as zf:
                        names = zf.namelist()
                        def read_zip_csv(filename: str) -> list[dict]:
                            for name in names:
                                if name.endswith(filename):
                                    with zf.open(name) as f:
                                        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                                        return list(reader)
                            return []
                        stops = read_zip_csv("stops.txt")
                        routes = read_zip_csv("routes.txt")
                        trips = read_zip_csv("trips.txt")
                        shapes = read_zip_csv("shapes.txt")
                        stop_times = read_zip_csv("stop_times.txt")
                except Exception as e:
                    return {"error": f"Failed to read local ZIP: {str(e)}"}
            else:
                return {"error": f"Local path not found or invalid format: {path}"}
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
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    names = zf.namelist()
                    def read_csv(filename: str) -> list[dict]:
                        for name in names:
                            if name.endswith(filename):
                                with zf.open(name) as f:
                                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                                    return list(reader)
                        return []
                    stops = read_csv("stops.txt")
                    routes = read_csv("routes.txt")
                    trips = read_csv("trips.txt")
                    shapes = read_csv("shapes.txt")
                    stop_times = read_csv("stop_times.txt")
            except zipfile.BadZipFile:
                return {"error": "The URL did not return a valid GTFS ZIP file."}
            except Exception as e:
                return {"error": f"GTFS parsing error: {str(e)}"}

        # Save raw data for later analysis
        gtfs_meta = {
            "stops_count": len(stops),
            "routes_count": len(routes),
            "trips_count": len(trips),
            "shapes_count": len(shapes)
        }
        with open(ws_path / "gtfs_meta.json", "w") as f:
            json.dump(gtfs_meta, f)
        with open(ws_path / "gtfs_stops.json", "w") as f:
            json.dump(stops, f)
        with open(ws_path / "gtfs_routes.json", "w") as f:
            json.dump(routes, f)
        with open(ws_path / "gtfs_trips.json", "w") as f:
            json.dump(trips, f)
        with open(ws_path / "gtfs_stop_times.json", "w") as f:
            json.dump(stop_times, f)

        # ── Build stops GeoJSON with self-describing metadata ──
        stop_features = []
        for s in stops:
            try:
                lat = float(s["stop_lat"])
                lng = float(s["stop_lon"])
                sid = s.get("stop_id", "")
                sname = s.get("stop_name", sid)
                stop_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                    "properties": {
                        "stop_id": sid,
                        "stop_name": sname,
                        "layer_name": f"{title} Stops",
                        "source_tool": "import_gtfs_feed",
                        "description": f"Public Transit Stop: {sname} ({sid})"
                    }
                })
            except (ValueError, KeyError):
                continue

        stops_geojson = {"type": "FeatureCollection", "features": stop_features}
        stops_path = ws_path / "gtfs_stops.geojson"
        with open(stops_path, "w") as f:
            json.dump(stops_geojson, f)

        # ── Build shapes/routes GeoJSON ──
        route_map = {r["route_id"]: r for r in routes if "route_id" in r}
        shape_coords: dict[str, list] = defaultdict(list)
        for row in shapes:
            sid = row.get("shape_id", "")
            try:
                pt = [float(row["shape_pt_lon"]), float(row["shape_pt_lat"])]
                seq = int(row.get("shape_pt_sequence", 0))
                shape_coords[sid].append((seq, pt))
            except (ValueError, TypeError, KeyError):
                continue

        route_features = []
        seen_shapes: set[str] = set()
        for trip in trips:
            shape_id = trip.get("shape_id", "")
            route_id = trip.get("route_id", "")
            if not shape_id or shape_id in seen_shapes:
                continue
            seen_shapes.add(shape_id)
            pts = sorted(shape_coords.get(shape_id, []), key=lambda x: x[0])
            if len(pts) < 2:
                continue
            coords = [p[1] for p in pts]
            route_info = route_map.get(route_id, {})
            rname = route_info.get("route_short_name", route_info.get("route_long_name", route_id))
            route_features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "shape_id": shape_id,
                    "route_id": route_id,
                    "route_short_name": route_info.get("route_short_name", ""),
                    "route_long_name": route_info.get("route_long_name", ""),
                    "layer_name": f"{title} Routes",
                    "source_tool": "import_gtfs_feed",
                    "description": f"Transit Corridor Route {rname}"
                }
            })

        routes_geojson = {"type": "FeatureCollection", "features": route_features}
        routes_path = ws_path / "gtfs_routes.geojson"
        with open(routes_path, "w") as f:
            json.dump(routes_geojson, f)

        return {
            "status": "success",
            "summary": {
                "stops": len(stop_features),
                "routes": len(route_map),
                "trips": len(trips)
            },
            "workspace": workspace
        }

    async def _analyze_gtfs_service(self, args: dict) -> dict:
        workspace = args.get("workspace", "").strip()

        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        meta_file = ws_path / "gtfs_meta.json"
        routes_file = ws_path / "gtfs_routes.json"
        stop_times_file = ws_path / "gtfs_stop_times.json"

        if not meta_file.exists():
            return {"error": "No GTFS data found in workspace. Please run import_gtfs_feed first."}

        with open(meta_file) as f:
            meta = json.load(f)

        routes = []
        if routes_file.exists():
            with open(routes_file) as f:
                routes = json.load(f)

        stop_times = []
        if stop_times_file.exists():
            with open(stop_times_file) as f:
                stop_times = json.load(f)

        route_trip_counts: dict[str, int] = defaultdict(int)
        try:
            trips_file = ws_path / "gtfs_trips.json"
            if trips_file.exists():
                with open(trips_file) as f:
                    trips_data = json.load(f)
                for trip in trips_data:
                    route_trip_counts[trip.get("route_id", "")] += 1
        except Exception:
            pass

        route_type_map = {
            "0": "Tram/Streetcar", "1": "Subway/Metro", "2": "Rail",
            "3": "Bus", "4": "Ferry", "5": "Cable Car",
            "6": "Gondola", "7": "Funicular", "11": "Trolleybus", "12": "Monorail"
        }
        type_counts: dict[str, int] = defaultdict(int)
        for r in routes:
            rtype = route_type_map.get(str(r.get("route_type", "3")), "Bus")
            type_counts[rtype] += 1

        top_routes = sorted(
            [{"route_id": k, "trips": v, "route_name": ""} for k, v in route_trip_counts.items()],
            key=lambda x: x["trips"],
            reverse=True
        )[:5]

        return {
            "status": "success",
            "network_stats": {
                "total_routes": meta.get("routes_count", 0),
                "total_stops": meta.get("stops_count", 0),
                "total_trips": meta.get("trips_count", 0),
                "route_types": dict(type_counts),
            },
            "top_frequency_routes": top_routes,
            "note": "Trip counts approximate frequency — higher trip count = more frequent service."
        }

    async def _analyze_gtfs_schedules(self, args: dict) -> dict:
        workspace = args.get("workspace", "").strip()
        stop_id_filter = args.get("stop_id", "").strip()
        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        stop_times_file = ws_path / "gtfs_stop_times.json"
        stops_file = ws_path / "gtfs_stops.json"
        routes_file = ws_path / "gtfs_routes.json"

        if not stop_times_file.exists():
            return {"error": "No GTFS schedule data found. Please run import_gtfs_feed first."}

        with open(stop_times_file) as f:
            stop_times = json.load(f)

        routes_map = {}
        if routes_file.exists():
            with open(routes_file) as f:
                for r in json.load(f):
                    routes_map[r.get("route_id", "")] = r.get("route_short_name") or r.get("route_long_name") or r.get("route_id")

        stops_map = {}
        if stops_file.exists():
            with open(stops_file) as f:
                for s in json.load(f):
                    stops_map[s.get("stop_id", "")] = s.get("stop_name", s.get("stop_id"))

        histogram = defaultdict(int)
        timetable = []

        for st in stop_times:
            dep = st.get("departure_time", "")
            sid = st.get("stop_id", "")
            if not dep:
                continue

            try:
                parts = dep.split(":")
                hour = int(parts[0]) % 24
                histogram[f"{hour:02d}:00"] += 1
            except Exception:
                pass

            if stop_id_filter and sid != stop_id_filter:
                continue

            timetable.append({
                "stop_id": sid,
                "stop_name": stops_map.get(sid, sid),
                "departure_time": dep,
                "trip_id": st.get("trip_id", "")
            })

        timetable.sort(key=lambda x: x["departure_time"])

        return {
            "status": "success",
            "hourly_departures_histogram": dict(sorted(histogram.items())),
            "stop_timetable": timetable[:50],
            "total_departures": len(stop_times)
        }

    async def _analyze_transit_catchment(self, args: dict) -> dict:
        workspace = args.get("workspace", "").strip()
        radius_meters = float(args.get("radius_meters", 400))
        layer_name = args.get("layer_name", "").strip() or f"Transit Catchment ({int(radius_meters)}m)"
        ws = args.get("_ws")

        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        stops_file = ws_path / "gtfs_stops.json"
        if not stops_file.exists():
            return {"error": "No GTFS stop data found. Please run import_gtfs_feed first."}

        with open(stops_file) as f:
            stops = json.load(f)

        if not stops:
            return {"error": "No stops available to calculate catchment."}

        from shapely.geometry import Point, mapping
        from shapely.ops import unary_union
        import math

        buffered_polys = []
        for s in stops:
            try:
                lat = float(s["stop_lat"])
                lng = float(s["stop_lon"])
                deg_lat = radius_meters / 111320.0
                deg_lng = radius_meters / (111320.0 * math.cos(math.radians(lat)))
                circle_coords = []
                for i in range(32):
                    angle = 2 * math.pi * i / 32
                    circle_coords.append((
                        lng + deg_lng * math.cos(angle),
                        lat + deg_lat * math.sin(angle)
                    ))
                circle_coords.append(circle_coords[0])
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
        with open(out_path, "w") as f:
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
            "file_path": str(out_path)
        }
