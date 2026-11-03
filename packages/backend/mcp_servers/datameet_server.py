from __future__ import annotations
import json
from pathlib import Path
import httpx
from llm.base import ToolDeclaration
from tools.action_utils import send_action

# ── DataMeet & Public India GIS Dataset Catalog ───────────────────────────────
# A curated catalog of publicly available Indian GIS datasets
# keyed by short identifiers the AI can use.

DATAMEET_CATALOG = {
    # Administrative boundaries
    "india_states": {
        "title": "India State Boundaries",
        "description": "State-level administrative boundaries for all 28 states and 8 UTs",
        "source": "datta07/INDIAN-SHAPEFILES",
        "url": "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/INDIA/INDIA_STATES.geojson",
        "category": "administrative",
        "tags": ["states", "boundaries", "india"],
    },
    "india_districts": {
        "title": "India District Boundaries",
        "description": "District-level administrative boundaries (~700+ districts)",
        "source": "datta07/INDIAN-SHAPEFILES",
        "url": "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/INDIA/INDIA_DISTRICTS.geojson",
        "category": "administrative",
        "tags": ["districts", "boundaries", "india"],
    },
    "india_assembly_constituencies": {
        "title": "Vidhan Sabha Constituencies",
        "description": "State legislative assembly constituency boundaries",
        "source": "datameet/maps",
        "url": "https://raw.githubusercontent.com/datameet/maps/master/assembly-constituencies/assembly_constituencies.geojson",
        "category": "political",
        "tags": ["elections", "constituencies", "boundaries"],
    },
    "india_parliamentary_constituencies": {
        "title": "Lok Sabha Constituencies",
        "description": "Parliamentary constituency boundaries for 543 Lok Sabha seats",
        "source": "datameet/maps",
        "url": "https://raw.githubusercontent.com/datameet/maps/master/lok-sabha-constituencies/lok_sabha.geojson",
        "category": "political",
        "tags": ["elections", "parliament", "constituencies"],
    },
    "india_urban_agglomerations": {
        "title": "Urban Agglomerations",
        "description": "Urban agglomeration boundaries from Census 2011",
        "source": "datameet/maps",
        "url": "https://raw.githubusercontent.com/datameet/maps/master/urban-agglomerations/urban_agglomerations.geojson",
        "category": "urban",
        "tags": ["urban", "cities", "census"],
    },
    "india_rivers": {
        "title": "Major River Networks",
        "description": "Major river and stream networks across India",
        "source": "datameet/maps",
        "url": "https://raw.githubusercontent.com/datameet/maps/master/rivers/india-rivers.geojson",
        "category": "environment",
        "tags": ["rivers", "hydrology", "water"],
    },
    "india_railway_lines": {
        "title": "Indian Railway Network",
        "description": "Railway line network including broad gauge, meter gauge, and narrow gauge",
        "source": "datameet/railways",
        "url": "https://raw.githubusercontent.com/datameet/railways/master/trains/trains.geojson",
        "category": "transport",
        "tags": ["railways", "transport", "infrastructure"],
    },
    "india_railway_stations": {
        "title": "Railway Stations",
        "description": "Indian railway station locations with station codes and names",
        "source": "datameet/railways",
        "url": "https://raw.githubusercontent.com/datameet/railways/master/stations/stations.geojson",
        "category": "transport",
        "tags": ["railways", "stations", "transport"],
    },
    "chandigarh_boundary": {
        "title": "Chandigarh Tricity Boundary",
        "description": "Chandigarh, Panchkula, and Mohali municipal boundaries",
        "source": "opendata",
        "url": "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/STATES/CHANDIGARH.geojson",
        "category": "urban",
        "tags": ["chandigarh", "tricity", "punjab"],
    },
    "india_national_highways": {
        "title": "National Highway Network",
        "description": "National highway alignments across India",
        "source": "datameet/maps",
        "url": "https://raw.githubusercontent.com/datameet/maps/master/national_highways/national_highways.geojson",
        "category": "transport",
        "tags": ["roads", "highways", "transport"],
    },
}

# State code → shapefile mappings for village-level data
STATE_VILLAGE_CODES = {
    "ka": "Karnataka", "mh": "Maharashtra", "gj": "Gujarat",
    "rj": "Rajasthan", "up": "Uttar Pradesh", "mp": "Madhya Pradesh",
    "tn": "Tamil Nadu", "ap": "Andhra Pradesh", "ts": "Telangana",
    "kl": "Kerala", "wb": "West Bengal", "od": "Odisha",
    "pb": "Punjab", "hr": "Haryana", "br": "Bihar",
    "jh": "Jharkhand", "as": "Assam", "hp": "Himachal Pradesh",
    "uk": "Uttarakhand", "ch": "Chandigarh", "ga": "Goa", "sk": "Sikkim",
}

STATE_NAME_TO_CODE = {v.lower(): k for k, v in STATE_VILLAGE_CODES.items()}
STATE_NAME_TO_CODE.update({
    "punjab": "pb", "kerala": "kl", "karnataka": "ka", "maharashtra": "mh",
    "gujarat": "gj", "rajasthan": "rj", "uttar pradesh": "up", "madhya pradesh": "mp",
    "tamil nadu": "tn", "tamilnadu": "tn", "andhra pradesh": "ap", "telangana": "ts",
    "west bengal": "wb", "odisha": "od", "orissa": "od", "haryana": "hr", "bihar": "br",
    "jharkhand": "jh", "assam": "as", "himachal pradesh": "hp", "uttarakhand": "uk",
    "chandigarh": "ch", "goa": "ga", "sikkim": "sk"
})


def _candidate_state_codes(state_code: str = "", state_name: str = "") -> list[str]:
    """Return a state search order that prioritizes the named state but searches the full supported registry."""
    sc = (state_code or "").strip().lower()
    if not sc and state_name:
        sc = STATE_NAME_TO_CODE.get(state_name.strip().lower(), "")

    codes = list(STATE_VILLAGE_CODES.keys())
    if sc and sc in STATE_VILLAGE_CODES:
        return [sc] + [code for code in codes if code != sc]
    return codes


def _resolve_workspace(workspace_arg: str) -> str:
    """Resolve workspace path to absolute folder or fallback to workspace root."""
    arg = (workspace_arg or "").strip()
    if not arg or arg == "/workspace" or arg == "." or not Path(arg).is_absolute():
        here = Path(__file__).resolve()
        # packages/backend/mcp_servers/datameet_server.py -> repo root
        return str(here.parent.parent.parent.parent)
    return arg


class DatameetServer:
    description = "DataMeet & public India GIS dataset browser and downloader"
    tool_names = {"import_datameet_boundary", "browse_datameet_catalog", "import_public_dataset"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="import_datameet_boundary",
                description=(
                    "Fetch and display state, district, or individual village boundaries from Datameet Indian map data. "
                    "When level is 'village', pass village_name (and optional state/district) to extract and display ONLY that specific village polygon on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": ["state", "district", "village"],
                            "description": "Administrative level to retrieve"
                        },
                        "state": {
                            "type": "string",
                            "description": "State name (e.g. 'Kerala', 'Punjab', 'Maharashtra'). Automatically resolves state code.",
                        },
                        "state_code": {
                            "type": "string",
                            "description": "ISO state code (e.g. 'kl', 'ka', 'mh', 'gj', 'rj', 'pb', 'br', 'ga', 'sk').",
                        },
                        "village_name": {
                            "type": "string",
                            "description": "Specific village name to extract and display ONLY that village boundary polygon instead of the full state."
                        },
                        "district": {
                            "type": "string",
                            "description": "Optional district name to filter or disambiguate villages."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder"
                        },
                    },
                    "required": ["level"],
                },
            ),
            ToolDeclaration(
                name="browse_datameet_catalog",
                description=(
                    "Browse the catalog of available public India GIS datasets. "
                    "Returns a list of dataset IDs, titles, descriptions, categories, and tags. "
                    "Use this before import_public_dataset to discover what's available. "
                    "Can filter by category (administrative, transport, urban, environment, political)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["all", "administrative", "transport", "urban", "environment", "political"],
                            "description": "Filter datasets by category. Use 'all' to see everything."
                        },
                        "search": {
                            "type": "string",
                            "description": "Optional keyword to filter by (e.g. 'railway', 'river', 'highway')."
                        }
                    },
                    "required": []
                }
            ),
            ToolDeclaration(
                name="import_public_dataset",
                description=(
                    "Download and load a named public India GIS dataset from the DataMeet / open-data catalog "
                    "directly onto the map. Use browse_datameet_catalog first to get available dataset_ids. "
                    "Examples: 'india_states', 'india_districts', 'india_railway_lines', "
                    "'india_rivers', 'india_national_highways', 'chandigarh_boundary'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset_id": {
                            "type": "string",
                            "description": "The dataset identifier from browse_datameet_catalog (e.g. 'india_railway_lines')."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        }
                    },
                    "required": ["dataset_id", "workspace"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "import_datameet_boundary":
            return await self._import_boundary(args)
        if tool_name == "browse_datameet_catalog":
            return await self._browse_catalog(args)
        if tool_name == "import_public_dataset":
            return await self._import_public_dataset(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _browse_catalog(self, args: dict) -> dict:
        category = args.get("category", "all").strip().lower()
        search = args.get("search", "").strip().lower()

        results = []
        for dataset_id, meta in DATAMEET_CATALOG.items():
            # Category filter
            if category != "all" and meta.get("category") != category:
                continue
            # Keyword search
            if search:
                searchable = (
                    dataset_id + " " + meta["title"] + " " + meta["description"] + " " +
                    " ".join(meta.get("tags", []))
                ).lower()
                if search not in searchable:
                    continue
            results.append({
                "dataset_id": dataset_id,
                "title": meta["title"],
                "description": meta["description"],
                "category": meta["category"],
                "tags": meta.get("tags", []),
                "source": meta.get("source", ""),
            })

        categories = list({m["category"] for m in DATAMEET_CATALOG.values()})

        return {
            "status": "success",
            "total": len(results),
            "datasets": results,
            "available_categories": sorted(categories),
            "note": "Use import_public_dataset with the dataset_id to load any of these onto the map."
        }

    async def _import_public_dataset(self, args: dict) -> dict:
        dataset_id = args.get("dataset_id", "").strip()
        workspace = _resolve_workspace(args.get("workspace", ""))
        ws = args.get("_ws")

        if not dataset_id:
            return {"error": "dataset_id is required. Use browse_datameet_catalog to discover available datasets."}

        if dataset_id not in DATAMEET_CATALOG:
            close = [k for k in DATAMEET_CATALOG if dataset_id.lower() in k or k in dataset_id.lower()]
            return {
                "error": f"Unknown dataset_id: '{dataset_id}'.",
                "suggestions": close[:5] if close else list(DATAMEET_CATALOG.keys())[:8],
                "note": "Use browse_datameet_catalog to see all available datasets."
            }

        meta = DATAMEET_CATALOG[dataset_id]
        url = meta["url"]
        filename = f"{dataset_id}.geojson"
        workspace_path = Path(workspace)
        workspace_path.mkdir(parents=True, exist_ok=True)
        target_file = workspace_path / filename

        # Serve from cache if already downloaded
        if target_file.exists():
            if ws:
                try:
                    await send_action(ws, "add_geojson_file", {
                        "path": str(target_file.resolve()),
                        "name": meta["title"]
                    })
                except Exception:
                    pass
            return {
                "status": "already_cached",
                "displayed_on_map": True,
                "dataset_id": dataset_id,
                "title": meta["title"],
                "path": str(target_file.resolve()),
                "message": f"'{meta['title']}' was already in workspace and loaded onto the map."
            }

        # Download using async iteration (aiter_bytes)
        try:
            async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        return {
                            "error": f"Failed to download '{meta['title']}'. HTTP {response.status_code}",
                            "url": url
                        }
                    tmp = workspace_path / f"{filename}.tmp"
                    with open(tmp, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                    tmp.rename(target_file)
        except Exception as e:
            return {"error": f"Download failed for '{meta['title']}': {e}"}

        if ws:
            try:
                await send_action(ws, "add_geojson_file", {
                    "path": str(target_file.resolve()),
                    "name": meta["title"]
                })
            except Exception:
                pass

        return {
            "status": "success",
            "displayed_on_map": True,
            "dataset_id": dataset_id,
            "title": meta["title"],
            "description": meta["description"],
            "path": str(target_file.resolve()),
            "message": f"'{meta['title']}' downloaded and loaded onto the map."
        }

    async def _import_boundary(self, args: dict) -> dict:
        level = args.get("level", "").strip().lower()
        state_code = (args.get("state_code") or "").strip().lower()
        state = (args.get("state") or args.get("states") or "").strip()
        village_name = (args.get("village_name") or args.get("village") or args.get("name") or "").strip()
        district = (args.get("district") or "").strip()
        workspace = _resolve_workspace(args.get("workspace", ""))
        ws = args.get("_ws")

        workspace_path = Path(workspace)
        workspace_path.mkdir(parents=True, exist_ok=True)

        if level == "village" and not state_code and state:
            state_code = STATE_NAME_TO_CODE.get(state.lower().strip(), "")

        if level == "state":
            url = "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/INDIA/INDIA_STATES.geojson"
            filename = "india_states.geojson"
        elif level == "district":
            url = "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/INDIA/INDIA_DISTRICTS.geojson"
            filename = "india_districts.geojson"
        elif level == "village":
            if not state_code and not state:
                return {
                    "error": "state_code or state is required for village boundaries",
                    "available_states": STATE_VILLAGE_CODES
                }
            if not state_code:
                return {
                    "error": f"Unknown state code for '{state}'. Available states: {list(STATE_VILLAGE_CODES.values())}",
                    "available_states": STATE_VILLAGE_CODES
                }
            url = f"https://raw.githubusercontent.com/datameet/indian_village_boundaries/master/{state_code}/{state_code}.geojson"
            filename = f"village_boundaries_{state_code}.geojson"
        else:
            return {"error": f"Invalid level: '{level}'. Must be 'state', 'district', or 'village'."}

        target_file = workspace_path / filename

        # Ensure base national/state file exists
        if not target_file.exists():
            try:
                async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code != 200:
                            return {"error": f"Failed to download boundary from {url}. HTTP {response.status_code}"}
                        tmp = workspace_path / f"{filename}.tmp"
                        with open(tmp, "wb") as f:
                            async for chunk in response.aiter_bytes(chunk_size=65536):
                                f.write(chunk)
                        tmp.rename(target_file)
            except Exception as e:
                return {"error": f"Download failed: {e}"}

        # If village level and specific village requested: create individual village feature subset
        if level == "village" and village_name:
            target_villages = [v.strip().lower() for v in village_name.replace(";", ",").split(",") if v.strip()]
            try:
                data = json.loads(target_file.read_text(encoding="utf-8"))
                matched = []
                for f in data.get("features", []):
                    props = f.get("properties", {})
                    v_name = (props.get("NAME") or props.get("name") or props.get("VILL_NAME") or "").strip().lower()
                    d_name = (props.get("DISTRICT") or props.get("district") or props.get("DIST_NAME") or "").strip().lower()
                    if district and district.lower().strip() not in d_name:
                        continue
                    if any(tv == v_name or tv in v_name or v_name in tv for tv in target_villages):
                        matched.append(f)

                if matched:
                    matched_names = [f.get("properties", {}).get("NAME", "Village") for f in matched]
                    safe_label = "_".join(n.lower().replace(" ", "_") for n in matched_names[:3])
                    v_filename = f"village_{safe_label}_{state_code}.geojson"
                    v_file = workspace_path / v_filename
                    v_fc = {"type": "FeatureCollection", "features": matched}
                    v_file.write_text(json.dumps(v_fc, ensure_ascii=False), encoding="utf-8")
                    
                    layer_title = f"Village — {', '.join(matched_names[:3])}"
                    if ws:
                        try:
                            await send_action(ws, "add_geojson_file", {
                                "path": str(v_file.resolve()),
                                "name": layer_title
                            })
                        except Exception:
                            pass

                    # Compute geodesic area and centroid
                    centroid = None
                    area_km2 = None
                    try:
                        from shapely.geometry import shape
                        from tools.geo import geodesic_area_m2
                        s = shape(matched[0]["geometry"])
                        area_km2 = round(geodesic_area_m2(matched[0]["geometry"]) / 1e6, 3)
                        centroid = {"lng": round(s.centroid.x, 6), "lat": round(s.centroid.y, 6)}
                        minx, miny, maxx, maxy = s.bounds
                        if ws:
                            if abs(maxx - minx) > 1e-5 and abs(maxy - miny) > 1e-5:
                                await send_action(ws, "fit_bounds", {
                                    "west": round(minx, 6),
                                    "south": round(miny, 6),
                                    "east": round(maxx, 6),
                                    "north": round(maxy, 6),
                                    "bounds": [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)],
                                })
                            elif centroid:
                                await send_action(ws, "fly_to", {
                                    "lng": centroid["lng"],
                                    "lat": centroid["lat"],
                                    "center": [centroid["lng"], centroid["lat"]],
                                    "zoom": 14,
                                })
                    except Exception:
                        pass

                    return {
                        "status": "success",
                        "level": "village",
                        "village_name": ", ".join(matched_names),
                        "state": STATE_VILLAGE_CODES.get(state_code, state_code.upper()),
                        "district": matched[0].get("properties", {}).get("DISTRICT", ""),
                        "sub_district": matched[0].get("properties", {}).get("SUB_DIST") or matched[0].get("properties", {}).get("SUB_DISTRICT", ""),
                        "area_km2": area_km2,
                        "centroid": centroid,
                        "path": str(v_file.resolve()),
                        "geojson": v_fc,
                        "message": f"Extracted boundary for village '{', '.join(matched_names)}' ({matched[0].get('properties', {}).get('DISTRICT', '')}, {STATE_VILLAGE_CODES.get(state_code, state_code.upper())}) and loaded onto map."
                    }
                else:
                    return {
                        "status": "error",
                        "error": f"Village '{village_name}' not found in DataMeet village boundaries for {STATE_VILLAGE_CODES.get(state_code, state_code.upper())}."
                                + (f" (Filtered by district: {district})" if district else "")
                    }
            except Exception as e:
                return {"error": f"Failed to filter village boundary: {e}"}

        # If district level and specific states requested: create lightweight filtered subset
        if level == "district" and (state or (state_code and state_code in STATE_VILLAGE_CODES)):
            target_states: list[str] = []
            if state:
                for s in state.replace(";", ",").split(","):
                    if s.strip():
                        target_states.append(s.strip().upper())
            if state_code:
                for sc in state_code.replace(";", ",").split(","):
                    code = sc.strip().lower()
                    if code in STATE_VILLAGE_CODES:
                        target_states.append(STATE_VILLAGE_CODES[code].upper())

            if target_states:
                try:
                    data = json.loads(target_file.read_text(encoding="utf-8"))
                    matched = []
                    for f in data.get("features", []):
                        props = f.get("properties", {})
                        st_name = (props.get("state") or props.get("st_nm") or "").strip().upper()
                        if st_name and any(ts == st_name or ts in st_name for ts in target_states):
                            matched.append(f)

                    if matched:
                        safe_label = "_".join(ts.lower().replace(" ", "_") for ts in target_states[:3])
                        subset_filename = f"districts_{safe_label}.geojson"
                        subset_file = workspace_path / subset_filename
                        subset_fc = {"type": "FeatureCollection", "features": matched}
                        subset_file.write_text(json.dumps(subset_fc, ensure_ascii=False), encoding="utf-8")
                        
                        layer_title = f"Districts — {', '.join(t.title() for t in target_states)}"
                        if ws:
                            try:
                                await send_action(ws, "add_geojson_file", {
                                    "path": str(subset_file.resolve()),
                                    "name": layer_title
                                })
                            except Exception:
                                pass

                        return {
                            "status": "success",
                            "level": "district",
                            "states": target_states,
                            "district_count": len(matched),
                            "path": str(subset_file.resolve()),
                            "message": f"Loaded {len(matched)} districts for {', '.join(t.title() for t in target_states)} onto map."
                        }
                except Exception as e:
                    # Fallback to full file if subsetting fails
                    pass

        # Default full file load
        if ws:
            try:
                await send_action(ws, "add_geojson_file", {
                    "path": str(target_file.resolve()),
                    "name": filename.replace(".geojson", "").replace("_", " ").title()
                })
            except Exception:
                pass

        return {
            "status": "success",
            "path": str(target_file.resolve()),
            "message": f"'{filename}' downloaded and loaded onto the map."
        }

    async def lookup_village_boundary(
        self,
        village_name: str,
        state_name: str = "",
        state_code: str = "",
        district: str = "",
        workspace: str = "",
    ) -> dict | None:
        """Lookup an Indian village boundary polygon from DataMeet datasets."""
        if not village_name:
            return None
        clean_vname = village_name.strip().lower().replace("village", "").strip()
        sc = state_code.strip().lower()
        if not sc and state_name:
            sc = STATE_NAME_TO_CODE.get(state_name.strip().lower(), "")

        candidate_codes = _candidate_state_codes(sc, state_name)

        workspace_path = Path(_resolve_workspace(workspace))
        workspace_path.mkdir(parents=True, exist_ok=True)

        for c in candidate_codes:
            filename = f"village_boundaries_{c}.geojson"
            target_file = workspace_path / filename
            url = f"https://raw.githubusercontent.com/datameet/indian_village_boundaries/master/{c}/{c}.geojson"

            if not target_file.exists():
                try:
                    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            target_file.write_bytes(resp.content)
                        else:
                            continue
                except Exception:
                    continue

            if not target_file.exists():
                continue

            try:
                data = json.loads(target_file.read_text(encoding="utf-8"))
                for f in data.get("features", []):
                    props = f.get("properties", {})
                    v_name = (props.get("NAME") or props.get("name") or "").strip().lower()
                    d_name = (props.get("DISTRICT") or props.get("district") or "").strip().lower()
                    if district and district.lower().strip() not in d_name:
                        continue
                    if clean_vname == v_name or clean_vname in v_name or v_name in clean_vname:
                        # Found matching village polygon!
                        return {
                            "type": "Feature",
                            "geometry": f["geometry"],
                            "properties": {
                                "name": props.get("NAME", village_name),
                                "village_name": props.get("NAME", village_name),
                                "district": props.get("DISTRICT", ""),
                                "sub_district": props.get("SUB_DIST") or props.get("SUB_DISTRICT", ""),
                                "state": props.get("STATE", STATE_VILLAGE_CODES.get(c, c.upper())),
                                "census_code": props.get("CEN_2001") or props.get("CENSUS_CODE_2001") or "",
                                "source": "datameet/indian_village_boundaries",
                            }
                        }
            except Exception:
                continue

        return None


datameet_server = DatameetServer()

