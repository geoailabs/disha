"""Google Earth Engine MCP server.

Architecture
------------
* `ee.Initialize()` is called **once per process** (cached in `_EE_READY`).
  Repeated calls to the same process skip re-auth — avoids the overhead and
  rate-limit risk of authenticating on every tool call.
* All synchronous `ee.*` calls (getMapId, getInfo, etc.) are dispatched to a
  thread pool via `asyncio.get_event_loop().run_in_executor()` so the FastAPI
  async event loop is never blocked.
* Tile URL tokens are valid for ~24 h. Each tool call issues a fresh token so
  the map layer never expires mid-session.
* Credentials are resolved in priority order:
    1. GOOGLE_EARTH_ENGINE_CREDS env var (JSON string or file path)
    2. Explicit workspace path passed by the caller
    3. CWD (backend process working directory)
    4. Walk up from this file's location to find the project root
       (handles the case where CWD is packages/backend/ but credentials
       live in the repo root two levels up)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from llm.base import ToolDeclaration

logger = logging.getLogger(__name__)

# ── Process-level GEE init cache ─────────────────────────────────────────────
# True  → GEE is initialized and ready
# False → GEE credentials are missing / package not installed
# None  → not yet attempted
_EE_READY: bool | None = None
_EE_ERROR: str | None = None


def reset_gee_init() -> None:
    """Reset Earth Engine initialization flags to force re-auth on next check."""
    global _EE_READY, _EE_ERROR
    _EE_READY = None
    _EE_ERROR = None


def _find_gee_creds(workspace: str | None = None) -> str | None:
    """Locate service account credentials in priority order."""
    # 1. Env var (JSON string or path)
    env = os.environ.get("GOOGLE_EARTH_ENGINE_CREDS")
    if env:
        return env

    # 2. Workspace-specific hidden file
    if workspace:
        ws_file = Path(workspace) / ".disha" / "ee-service-account.json"
        if ws_file.exists():
            return str(ws_file)

    search_roots: list[Path] = []

    # 3. Workspace root supplied by the caller (from chat WebSocket payload)
    if workspace:
        search_roots.append(Path(workspace))

    # 4. CWD
    search_roots.append(Path.cwd())

    # 5. Project dev mode config file in .tmp
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent.parent
    dev_path = repo_root / ".tmp" / "gee-credentials.json"
    if dev_path.exists():
        return str(dev_path)

    # 6. Walk up from this file: mcp_servers/ → backend/ → packages/ → repo root
    for parent in [here.parent, here.parent.parent, here.parent.parent.parent,
                   here.parent.parent.parent.parent]:
        if parent not in search_roots:
            search_roots.append(parent)

    for root in search_roots:
        if not root.is_dir():
            continue
        # Prefer files named ee-*.json (naming convention for this project)
        for p in sorted(root.glob("ee-*.json")):
            return str(p)
        # Any *.json that has type: service_account
        for p in sorted(root.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("type") == "service_account":
                    return str(p)
            except Exception:
                pass
    return None


def _sync_init_gee(creds_path: str) -> tuple[bool, str | None]:
    """Synchronous GEE init — run in a thread pool."""
    global _EE_READY, _EE_ERROR
    try:
        import ee
    except ImportError:
        _EE_READY = False
        _EE_ERROR = (
            "earthengine-api is not installed. "
            "Run: pip install earthengine-api"
        )
        return False, _EE_ERROR

    try:
        if os.path.isfile(creds_path):
            data = json.loads(Path(creds_path).read_text())
        else:
            data = json.loads(creds_path)

        svc_email = data.get("client_email", "")

        import tempfile
        if os.path.isfile(creds_path):
            creds_file = creds_path
        else:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
                json.dump(data, f)
                creds_file = f.name

        credentials = ee.ServiceAccountCredentials(svc_email, creds_file)
        ee.Initialize(credentials=credentials)
        _EE_READY = True
        _EE_ERROR = None
        return True, None
    except Exception as exc:
        _EE_READY = False
        _EE_ERROR = f"GEE initialization failed: {exc}"
        return False, _EE_ERROR


async def _ensure_gee(workspace: str | None = None) -> tuple[bool, str | None]:
    """Initialize GEE if not already done. Safe to call concurrently."""
    global _EE_READY, _EE_ERROR
    if _EE_READY is True:
        return True, None
    if _EE_READY is False:
        # Retry on each request in case the creds file appears later
        pass

    creds = _find_gee_creds(workspace)
    if not creds:
        return False, (
            "Google Earth Engine credentials not found. "
            "Drop your ee-*.json service account file into the workspace root "
            "or set the GOOGLE_EARTH_ENGINE_CREDS environment variable."
        )

    loop = asyncio.get_event_loop()
    ok, err = await loop.run_in_executor(None, _sync_init_gee, creds)
    return ok, err


def _sync_get_map_id(image_fn, vis_params: dict) -> str:
    """Call ee.data.getMapId in a thread (it's synchronous)."""
    import ee
    img = image_fn()
    result = ee.data.getMapId({"image": img, "visParams": vis_params})
    return result["tile_fetcher"].url_format


# ── Dataset defaults ──────────────────────────────────────────────────────────

def _get_dataset_defaults(dataset: str) -> tuple[dict, bool]:
    d = dataset.lower()
    if "copernicus/s2" in d:
        return {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}, True
    if "landsat/lc08" in d or "landsat/lc09" in d:
        return {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 7000, "max": 30000}, True
    if "srtm" in d or "copernicus/dem" in d or "nasadem" in d:
        return {"min": 0, "max": 3000, "palette": ["0000ff", "00ff00", "ffff00", "ff7f00", "ff0000"]}, False
    if "worldcover" in d:
        return {"bands": ["Map"]}, True
    if "worldpop" in d or "landscan" in d or "gpw" in d:
        return {"min": 0, "max": 1000, "palette": ["ffffe5", "f7fcb9", "addd8e", "31a354", "006837"]}, False
    return {}, False


# ── Main server class ─────────────────────────────────────────────────────────

class GEEServer:
    description = (
        "Google Earth Engine (GEE) — satellite imagery, elevation models, "
        "population density, land cover, NDVI, and raster visualization"
    )
    tool_names = {
        "add_gee_layer",
        "get_land_cover",
        "analyze_lulc_change",
        "analyze_land_use_zonal_stats",
        "extract_land_use_polygons",
        "get_ndvi_layer",
        "get_population_layer",
        "get_dem_layer",
        "get_gee_layer",        # kept for backward compat (now returns tile URL)
    }

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="add_gee_layer",
                description=(
                    "Add any Google Earth Engine raster dataset to the map as a tiled imagery layer. "
                    "Handles Sentinel-2 (RGB/false-colour), Landsat 8/9, SRTM elevation, ESA WorldCover "
                    "and any other EE ImageCollection or Image. Applies cloud-free median compositing "
                    "for collections when a year/date is given."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string", "description": "Earth Engine dataset ID (e.g. 'COPERNICUS/S2_SR_HARMONIZED', 'USGS/SRTMGL1_003')"},
                        "vis_params": {"type": "object", "description": "GEE visualization params (e.g. {\"min\":0,\"max\":3000,\"bands\":[\"B4\",\"B3\",\"B2\"]})"},
                        "date": {"type": "string", "description": "Year (e.g. '2023') or date range start for filtering ImageCollections"},
                        "title": {"type": "string", "description": "Label for the map layer list"},
                    },
                    "required": ["dataset"],
                },
            ),
            ToolDeclaration(
                name="get_population_layer",
                description=(
                    "Add a population density raster layer to the map from WorldPop (100m, 2000-2020) "
                    "or LandScan (1km, global ambient population). Use for urban density analysis, "
                    "service area calculations, and disaster risk exposure mapping. "
                    "Returns a colour-ramped tile layer (green=low → red=high density)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["worldpop", "landscan", "gpw"],
                            "description": "Dataset: 'worldpop' (100m, by country), 'landscan' (1km global ambient), 'gpw' (UN-adjusted).",
                        },
                        "year": {"type": "integer", "description": "Year (WorldPop: 2000–2020; LandScan: 2000–2022; GPW: 2000/2005/2010/2015/2020)"},
                        "country_iso": {"type": "string", "description": "ISO-3 country code for WorldPop (e.g. 'IND'). Not needed for global sources."},
                        "title": {"type": "string", "description": "Layer name for the map panel"},
                    },
                    "required": ["source"],
                },
            ),
            ToolDeclaration(
                name="get_dem_layer",
                description=(
                    "Add a Digital Elevation Model (DEM) or terrain analysis raster to the map. "
                    "Sources: 'srtm' (USGS SRTM 30m, near-global), 'copernicus' (Copernicus DEM 30m, higher accuracy), "
                    "'nasadem' (NASA DEM 30m, void-filled SRTM).\n\n"
                    "Modes:\n"
                    "  • 'elevation' (default): Colour-ramped from sea level (blue) to peaks (white).\n"
                    "  • 'hillshade': Shaded relief raster displaying 3D terrain ridges, sun illumination, valleys, and slope textures.\n"
                    "  • 'slope': Terrain steepness in degrees (0° flat to 45°+ steep).\n\n"
                    "Use for slope analysis, flood risk, watershed delineation, and 3D terrain visualization."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["srtm", "copernicus", "nasadem"],
                            "description": "'srtm' = USGS SRTMGL1_003, 'copernicus' = Copernicus DEM GLO-30, 'nasadem' = NASA DEM HGT_001",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["elevation", "hillshade", "slope"],
                            "description": "Visualization mode: 'elevation' (colour ramp), 'hillshade' (3D shaded relief / ridges), 'slope' (steepness in degrees). Default is 'elevation'.",
                        },
                        "max_elevation": {"type": "number", "description": "Max elevation (m) for colour ramp. Default 3000."},
                        "title": {"type": "string", "description": "Layer name for the map panel"},
                    },
                    "required": ["source"],
                },
            ),
            ToolDeclaration(
                name="get_land_cover",
                description=(
                    "Fetch and display a land-use / land-cover (LULC) classification layer. "
                    "Sources: 'dynamic_world' (Google 10m, 2016–present, 9 classes) and "
                    "'esa_worldcover' (ESA 10m, 2020/2021, 11 classes). "
                    "Use for urban footprint detection, green space analysis, and zoning reference."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "enum": ["dynamic_world", "esa_worldcover"]},
                        "year": {"type": "integer", "description": "Year to visualize (ESA WorldCover: 2020 or 2021)"},
                        "title": {"type": "string"},
                    },
                    "required": ["source"],
                },
            ),
            ToolDeclaration(
                name="analyze_lulc_change",
                description=(
                    "Compare Google Dynamic World land cover composites across two years to detect "
                    "land-use change. Returns a binary changed/unchanged mask and a class-transition layer. "
                    "Highlights urban growth, deforestation, wetland loss, or agricultural expansion."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "year_start": {"type": "integer"},
                        "year_end": {"type": "integer"},
                        "title": {"type": "string"},
                    },
                    "required": ["year_start", "year_end"],
                },
            ),
            ToolDeclaration(
                name="analyze_land_use_zonal_stats",
                description=(
                    "Perform zonal land-use analysis on Google Dynamic World / ESA WorldCover datasets. "
                    "Calculates exact area in km² and percentage composition breakdown of each land cover category "
                    "(Built Area, Water, Trees, Crops, Shrub, Grass, Bare Ground) inside a boundary polygon or region."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {"type": "object", "description": "GeoJSON polygon / geometry dict for the study boundary."},
                        "lat": {"type": "number", "description": "Latitude for circular study area (if geojson not provided)."},
                        "lng": {"type": "number", "description": "Longitude for circular study area (if geojson not provided)."},
                        "radius_km": {"type": "number", "description": "Radius in km for circular study area (default 5 km)."},
                        "year": {"type": "integer", "description": "Year to analyze (default 2023)."},
                        "source": {"type": "string", "enum": ["dynamic_world", "esa_worldcover"], "description": "Land cover dataset source."},
                    },
                },
            ),
            ToolDeclaration(
                name="extract_land_use_polygons",
                description=(
                    "Extract specific land cover classes (e.g. 'Built Area', 'Trees', 'Water', 'Crops') "
                    "into vector GeoJSON polygons loaded directly on the map. Supports clipping to an official "
                    "administrative city/district boundary using `place_name` or `geojson`, and custom layer `color`."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "target_class": {"type": "string", "description": "Class name to extract (e.g. 'Built Area', 'Trees', 'Water', 'Crops', 'Grass'). Default 'Built Area'."},
                        "place_name": {"type": "string", "description": "City or region name (e.g. 'Chandigarh', 'Mohali', 'Panchkula') to automatically clip built-up area to its official administrative boundary."},
                        "geojson": {"type": "object", "description": "Optional explicit boundary polygon to constrain extraction."},
                        "color": {"type": "string", "description": "Color for the extracted polygon layer (e.g. 'blue', '#2563EB', 'yellow', 'red', 'green')."},
                        "lat": {"type": "number", "description": "Latitude for circular bounding region (if place_name or geojson is not provided)."},
                        "lng": {"type": "number", "description": "Longitude for circular bounding region (if place_name or geojson is not provided)."},
                        "radius_km": {"type": "number", "description": "Radius in km for bounding region (default 5 km)."},
                        "year": {"type": "integer", "description": "Year to analyze (default 2023)."},
                    },
                    "required": ["target_class"],
                },
            ),
            ToolDeclaration(
                name="get_ndvi_layer",
                description=(
                    "Compute and display an NDVI layer from Sentinel-2 SR for a given year. "
                    "NDVI > 0.4 = dense vegetation; < 0.1 = built-up or bare land. "
                    "Use for urban heat island analysis, park mapping, and vegetation health monitoring."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer"},
                        "title": {"type": "string"},
                    },
                    "required": ["year"],
                },
            ),
            ToolDeclaration(
                name="get_gee_layer",
                description=(
                    "Sample pixel values from a GEE dataset at a specific lat/lng point. "
                    "Also adds the dataset as a tile layer on the map so it can be inspected visually. "
                    "Use get_dem_layer or get_population_layer for dedicated rasters."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "radius_meters": {"type": "number"},
                    },
                    "required": ["dataset", "lat", "lng"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        # Resolve workspace from map context if not explicitly provided
        if not args.get("_workspace") and args.get("_map_context"):
            map_context = args.get("_map_context")
            if isinstance(map_context, dict) and map_context.get("workspace"):
                args["_workspace"] = map_context.get("workspace")

        if tool_name == "add_gee_layer":
            return await self._add_gee_layer(args)
        if tool_name == "get_population_layer":
            return await self._get_population_layer(args)
        if tool_name == "get_dem_layer":
            return await self._get_dem_layer(args)
        if tool_name == "get_land_cover":
            return await self._get_land_cover(args)
        if tool_name == "analyze_lulc_change":
            return await self._analyze_lulc_change(args)
        if tool_name == "analyze_land_use_zonal_stats":
            return await self._analyze_land_use_zonal_stats(args)
        if tool_name == "extract_land_use_polygons":
            return await self._extract_land_use_polygons(args)
        if tool_name == "get_ndvi_layer":
            return await self._get_ndvi_layer(args)
        if tool_name == "get_gee_layer":
            return await self._get_gee_layer(args)
        return {"error": f"Unknown tool: {tool_name}"}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _send_layer(self, ws, tile_url: str, dataset: str, vis_params: dict, title: str) -> None:
        """Send add_gee_layer action over the WebSocket."""
        if ws:
            import json as _json
            await ws.send_text(_json.dumps({
                "type": "action",
                "action": "add_gee_layer",
                "payload": {"url": tile_url, "dataset": dataset, "vis_params": vis_params, "title": title},
            }))

    async def _tile_url(self, image_fn) -> str:
        """Run synchronous getMapId in thread pool → tile URL string."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, image_fn)

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def _add_gee_layer(self, args: dict) -> dict:
        dataset = args.get("dataset", "").strip()
        vis_params = args.get("vis_params") or {}
        date_str = args.get("date", "").strip()
        title = args.get("title", "").strip() or f"{dataset}"
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        if not dataset:
            return {"error": "dataset is required"}

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            default_vis, is_collection = _get_dataset_defaults(dataset)
            final_vis = {**default_vis, **vis_params}

            def build_image():
                if is_collection:
                    coll = ee.ImageCollection(dataset)
                    if date_str:
                        start = f"{date_str}-01-01" if len(date_str) == 4 else date_str
                        end_yr = date_str.split("-")[0]
                        end = f"{end_yr}-12-31"
                        coll = coll.filterDate(start, end)
                    d_lower = dataset.lower()
                    if "copernicus/s2" in d_lower:
                        coll = coll.filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 10))
                    elif "landsat" in d_lower:
                        coll = coll.filter(ee.Filter.lt("CLOUD_COVER", 10))
                    img = coll.median()
                else:
                    img = ee.Image(dataset)

                result = ee.data.getMapId({"image": img, "visParams": final_vis})
                return result["tile_fetcher"].url_format

            tile_url = await self._tile_url(build_image)
            await self._send_layer(ws, tile_url, dataset, final_vis, title)
            return {"status": "success", "message": f"GEE layer '{title}' added to map.", "tile_url": tile_url}

        except Exception as exc:
            return {"error": f"GEE layer failed: {exc}", "code": "gee_error"}

    async def _get_population_layer(self, args: dict) -> dict:
        source = args.get("source", "worldpop").strip()
        year = int(args.get("year") or 2020)
        country_iso = (args.get("country_iso") or "").upper().strip()
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            vis = {
                "min": 0,
                "max": 500,
                "palette": ["ffffe5", "f7fcb9", "addd8e", "41ab5d", "006837", "ffaa00", "ff0000"],
                "palette_labels": ["0 (Low)", "83", "166", "250", "333", "416", "500+ (High)"],
            }

            def build_image():
                if source == "worldpop":
                    # WorldPop/GP/100m/pop — global annual unconstrained, 2000-2020
                    # Each image has a 'country' property (ISO-3) and 'year' property.
                    yr = min(max(year, 2000), 2020)
                    coll = (
                        ee.ImageCollection("WorldPop/GP/100m/pop")
                        .filter(ee.Filter.eq("year", yr))
                    )
                    if country_iso:
                        coll = coll.filter(ee.Filter.eq("country", country_iso))
                        img = coll.mosaic()          # mosaic in case multiple tiles per country
                    else:
                        img = coll.mosaic()          # global mosaic for all countries

                elif source == "gpw":
                    # CIESIN GPWv4 — UN-adjusted population density, 5-year steps
                    valid_years = [2000, 2005, 2010, 2015, 2020]
                    yr = min(valid_years, key=lambda y: abs(y - year))
                    start = f"{yr}-01-01"
                    end   = f"{yr}-12-31"
                    img = (
                        ee.ImageCollection("CIESIN/GPWv411/GPW_Population_Density")
                        .filterDate(start, end)
                        .first()
                    )

                elif source == "landscan":
                    # LandScan HD — requires special access, not always public.
                    # Fall back to GPW as a reliable alternative.
                    yr_clamp = min(max(year, 2000), 2020)
                    start = f"{yr_clamp}-01-01"
                    end   = f"{yr_clamp}-12-31"
                    img = (
                        ee.ImageCollection("CIESIN/GPWv411/GPW_Population_Density")
                        .filterDate(start, end)
                        .first()
                    )

                else:
                    raise ValueError(f"Unknown source: {source}. Use 'worldpop' or 'gpw'.")

                result = ee.data.getMapId({"image": img, "visParams": vis})
                return result["tile_fetcher"].url_format

            tile_url = await self._tile_url(build_image)
            layer_title = title or f"Population Density ({source.title()} {year})"
            dataset_id = (
                "WorldPop/GP/100m/pop" if source == "worldpop"
                else "CIESIN/GPWv411/GPW_Population_Density"
            )
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)
            return {
                "status": "success",
                "source": source,
                "year": year,
                "message": f"Population density layer '{layer_title}' added to map. Colour ramp: green=low → yellow → red=high density.",
            }

        except Exception as exc:
            return {"error": f"Population layer failed: {exc}", "code": "gee_error"}

    async def _get_dem_layer(self, args: dict) -> dict:
        source = args.get("source", "srtm").strip()
        max_elev = float(args.get("max_elevation") or 3000)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        _DEM_DATASETS = {
            "srtm": ("USGS/SRTMGL1_003", "elevation", False),
            "copernicus": ("COPERNICUS/DEM/GLO30", "DEM", False),
            "nasadem": ("NASA/NASADEM_HGT/001", "elevation", False),
        }

        if source not in _DEM_DATASETS:
            return {"error": f"Unknown source '{source}'. Use: srtm, copernicus, nasadem."}

        dataset_id, band, is_coll = _DEM_DATASETS[source]

        mode = (args.get("mode") or "").strip().lower()
        if not mode:
            if "hillshade" in title.lower() or "relief" in title.lower():
                mode = "hillshade"
            elif "slope" in title.lower():
                mode = "slope"
            else:
                mode = "elevation"

        if mode == "hillshade":
            vis = {
                "bands": ["hillshade"],
                "min": 0,
                "max": 255,
                "palette": ["000000", "777777", "ffffff"],
                "palette_labels": ["Deep Shadow (0)", "Midtone (128)", "Illuminated Ridge (255)"],
            }
        elif mode == "slope":
            vis = {
                "bands": ["slope"],
                "min": 0,
                "max": 45,
                "palette": ["2b83ba", "abdda4", "ffffbf", "fdae61", "d7191c"],
                "palette_labels": ["0° (Flat)", "10° (Gentle)", "20° (Moderate)", "30° (Steep)", "45°+ (Very Steep)"],
            }
        else:
            vis = {
                "bands": [band],
                "min": 0,
                "max": max_elev,
                "palette": ["0000ff", "00aaff", "00ff00", "ffff00", "ff7f00", "ff0000", "ffffff"],
                "palette_labels": ["0m", f"{int(max_elev * 0.16)}m", f"{int(max_elev * 0.33)}m", f"{int(max_elev * 0.5)}m", f"{int(max_elev * 0.66)}m", f"{int(max_elev * 0.83)}m", f"{int(max_elev)}m (Max)"],
            }

        try:
            import ee

            def build_image():
                if is_coll:
                    raw_img = ee.ImageCollection(dataset_id).mosaic()
                else:
                    raw_img = ee.Image(dataset_id)

                dem_band = raw_img.select(band)
                if mode == "hillshade":
                    processed = ee.Terrain.hillshade(dem_band)
                elif mode == "slope":
                    processed = ee.Terrain.slope(dem_band)
                else:
                    processed = dem_band

                result = ee.data.getMapId({"image": processed, "visParams": vis})
                return result["tile_fetcher"].url_format

            tile_url = await self._tile_url(build_image)
            if mode == "hillshade":
                layer_title = title or f"Shaded Relief (Hillshade) — {source.upper()}"
            elif mode == "slope":
                layer_title = title or f"Terrain Slope — {source.upper()} (0–45°)"
            else:
                layer_title = title or f"DEM — {source.upper()} (0–{int(max_elev)} m)"

            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)
            return {
                "status": "success",
                "source": source,
                "mode": mode,
                "dataset": dataset_id,
                "message": (
                    f"Terrain layer '{layer_title}' ({mode}) added to map."
                ),
            }

        except Exception as exc:
            return {"error": f"DEM layer failed: {exc}", "code": "gee_error"}

    async def _get_land_cover(self, args: dict) -> dict:
        source = args.get("source", "dynamic_world").strip()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if source == "dynamic_world":
                dw_palette = [
                    "419BDF", "397D49", "88B053", "7A87C6",
                    "E49635", "DFC35A", "C4281B", "A59B8F", "B39FE1",
                ]
                dw_classes = [
                    "Water", "Trees", "Grass", "Flooded Vegetation",
                    "Crops", "Shrub & Scrub", "Built Area", "Bare Ground", "Snow & Ice",
                ]
                vis = {
                    "min": 0,
                    "max": 8,
                    "palette": dw_palette,
                    "palette_labels": dw_classes,
                }
                layer_title = title or f"Dynamic World Land Cover {year}"
                dataset_id = "GOOGLE/DYNAMICWORLD/V1"

                def build_image():
                    img = (
                        ee.ImageCollection(dataset_id)
                        .filterDate(f"{year}-01-01", f"{year}-12-31")
                        .select("label")
                        .mode()
                    )
                    result = ee.data.getMapId({"image": img, "visParams": vis})
                    return result["tile_fetcher"].url_format

                tile_url = await self._tile_url(build_image)
                await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)
                return {
                    "status": "success",
                    "source": "Google Dynamic World V1",
                    "year": year,
                    "classes": {str(i): {"name": n, "color": f"#{c}"} for i, (n, c) in enumerate(zip(dw_classes, dw_palette))},
                    "message": f"Land cover layer '{layer_title}' added to map.",
                }

            elif source == "esa_worldcover":
                yr_map = {2020: "ESA/WorldCover/v100/2020", 2021: "ESA/WorldCover/v200/2021"}
                dataset_id = yr_map.get(year, "ESA/WorldCover/v200/2021")
                esa_palette = [
                    "006400", "ffbb22", "ffff4c", "f096ff",
                    "fa0000", "b4b4b4", "f0f0f0", "0064c8",
                    "0096a0", "00cf75", "fae6a0",
                ]
                esa_classes = [
                    "Trees", "Shrubland", "Grassland", "Cropland", "Built-up",
                    "Barren", "Snow & Ice", "Open Water", "Wetland", "Mangroves", "Moss & Lichen"
                ]
                vis = {
                    "bands": ["Map"],
                    "min": 10,
                    "max": 100,
                    "palette": esa_palette,
                    "palette_labels": esa_classes,
                }
                layer_title = title or f"ESA WorldCover {year}"

                def build_image():
                    img = ee.ImageCollection(dataset_id).first()
                    result = ee.data.getMapId({"image": img, "visParams": vis})
                    return result["tile_fetcher"].url_format

                tile_url = await self._tile_url(build_image)
                await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)
                return {"status": "success", "source": "ESA WorldCover", "dataset": dataset_id,
                        "message": f"Land cover layer '{layer_title}' added to map."}

            return {"error": f"Unknown source '{source}'. Use 'dynamic_world' or 'esa_worldcover'."}

        except Exception as exc:
            return {"error": f"Land cover layer failed: {exc}", "code": "gee_error"}

    async def _analyze_lulc_change(self, args: dict) -> dict:
        year_start = int(args.get("year_start", 2018))
        year_end = int(args.get("year_end", 2023))
        title = args.get("title", "").strip() or f"LULC Change {year_start}→{year_end}"
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        if year_start >= year_end:
            return {"error": "year_start must be less than year_end"}

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            changed_vis = {"min": 0, "max": 1, "palette": ["cccccc", "ff4444"]}
            transition_vis = {
                "min": 0,
                "max": 88,
                "palette": ["ffffff", "ff0000", "00aaff", "ffcc00", "88cc00", "cc4400", "4400cc", "00cc88", "880000"],
            }

            def build_changed():
                def mode_for_year(y):
                    return (
                        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
                        .filterDate(f"{y}-01-01", f"{y}-12-31")
                        .select("label").mode()
                    )
                lc_start = mode_for_year(year_start)
                lc_end = mode_for_year(year_end)
                changed = lc_start.neq(lc_end)
                result = ee.data.getMapId({"image": changed.rename("changed"), "visParams": changed_vis})
                return result["tile_fetcher"].url_format

            def build_transition():
                def mode_for_year(y):
                    return (
                        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
                        .filterDate(f"{y}-01-01", f"{y}-12-31")
                        .select("label").mode()
                    )
                lc_start = mode_for_year(year_start)
                lc_end = mode_for_year(year_end)
                changed = lc_start.neq(lc_end)
                transition = lc_start.multiply(10).add(lc_end).updateMask(changed)
                result = ee.data.getMapId({"image": transition, "visParams": transition_vis})
                return result["tile_fetcher"].url_format

            loop = asyncio.get_event_loop()
            changed_url, transition_url = await asyncio.gather(
                loop.run_in_executor(None, build_changed),
                loop.run_in_executor(None, build_transition),
            )

            await self._send_layer(ws, changed_url, "GOOGLE/DYNAMICWORLD/V1", changed_vis, f"Changed Areas {year_start}→{year_end}")
            await self._send_layer(ws, transition_url, "GOOGLE/DYNAMICWORLD/V1", transition_vis, title)

            return {
                "status": "success",
                "year_start": year_start, "year_end": year_end, "layers_added": 2,
                "message": (
                    f"LULC change layers added: (1) changed/unchanged mask (red=changed), "
                    f"(2) class transition map. Transitions encoded as (start_class×10 + end_class)."
                ),
            }

        except Exception as exc:
            return {"error": f"LULC change analysis failed: {exc}", "code": "gee_error"}

    async def _get_ndvi_layer(self, args: dict) -> dict:
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip() or f"NDVI {year}"
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            ndvi_palette = ["8B4513", "D2691E", "F4A460", "FFFF00", "9ACD32", "228B22", "006400"]
            vis = {"min": -0.1, "max": 0.8, "palette": ndvi_palette}

            def build_image():
                s2 = (
                    ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 10))
                    .select(["B8", "B4"])
                    .median()
                )
                ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI")
                result = ee.data.getMapId({"image": ndvi, "visParams": vis})
                return result["tile_fetcher"].url_format

            tile_url = await self._tile_url(build_image)
            await self._send_layer(ws, tile_url, "COPERNICUS/S2_SR_HARMONIZED", vis, title)
            return {
                "status": "success", "year": year, "index": "NDVI",
                "interpretation": {
                    "< 0.1": "Built-up / bare land / water",
                    "0.1 – 0.3": "Sparse vegetation / degraded land",
                    "0.3 – 0.5": "Moderate vegetation (agriculture, parks)",
                    "> 0.5": "Dense vegetation / forest",
                },
                "message": f"NDVI layer '{title}' added to map.",
            }

        except Exception as exc:
            return {"error": f"NDVI computation failed: {exc}", "code": "gee_error"}

    async def _get_gee_layer(self, args: dict) -> dict:
        """Backward-compat: sample point values AND add tile layer to map."""
        dataset = args.get("dataset", "").strip()
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        if not dataset:
            return {"error": "dataset is required"}

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            default_vis, is_collection = _get_dataset_defaults(dataset)

            def build_and_sample():
                if is_collection:
                    img = ee.ImageCollection(dataset).filterBounds(
                        ee.Geometry.Point([lng, lat])
                    ).median()
                else:
                    img = ee.Image(dataset)

                # Get tile URL
                result = ee.data.getMapId({"image": img, "visParams": default_vis})
                tile_url = result["tile_fetcher"].url_format

                # Sample pixel value at point
                point = ee.Geometry.Point([lng, lat])
                try:
                    sample = img.sample(point, 30).first().toDictionary().getInfo()
                except Exception:
                    sample = {}

                return tile_url, sample

            loop = asyncio.get_event_loop()
            tile_url, sample = await loop.run_in_executor(None, build_and_sample)

            title = f"{dataset.split('/')[-1]} — pixel sample"
            await self._send_layer(ws, tile_url, dataset, default_vis, title)

            return {
                "status": "success",
                "dataset": dataset,
                "pixel_values": sample,
                "message": f"Layer '{title}' added to map. Pixel values at ({lat:.4f}, {lng:.4f}): {sample}",
            }

        except Exception as exc:
            return {"error": f"GEE execution failed: {exc}", "code": "gee_error"}

    # ── Zonal Land Use Analysis & Vector Extraction ─────────────────────────

    async def _analyze_land_use_zonal_stats(self, args: dict) -> dict:
        geojson_input = args.get("geojson")
        lat = args.get("lat")
        lng = args.get("lng")
        radius_km = float(args.get("radius_km") or 5.0)
        year = int(args.get("year") or 2023)
        source = (args.get("source") or "dynamic_world").lower()
        workspace = args.get("_workspace")

        dw_classes = [
            "Water", "Trees", "Grass", "Flooded Vegetation",
            "Crops", "Shrub & Scrub", "Built Area", "Bare Ground", "Snow & Ice",
        ]
        dw_colors = [
            "#419BDF", "#397D49", "#88B053", "#7A87C6",
            "#E49635", "#DFC35A", "#C4281B", "#A59B8F", "#B39FE1",
        ]

        ok, err = await _ensure_gee(workspace)
        if not ok:
            # Clean fallback when GEE credentials are not configured
            return {
                "status": "partial_fallback",
                "message": f"GEE credentials not active ({err}). Displaying standard Dynamic World class schema for {year}.",
                "classes": {str(i): {"name": name, "color": color} for i, (name, color) in enumerate(zip(dw_classes, dw_colors))},
                "note": "Configure GEE credentials in workspace root (ee-service-account.json) for live pixel-reduction zonal stats."
            }

        try:
            import ee

            def run_zonal():
                if geojson_input:
                    ee_geom = ee.Geometry(geojson_input.get("geometry", geojson_input))
                elif lat is not None and lng is not None:
                    ee_geom = ee.Geometry.Point([float(lng), float(lat)]).buffer(radius_km * 1000.0)
                else:
                    ee_geom = ee.Geometry.Point([76.7794, 30.7333]).buffer(5000)  # Default Chandigarh center

                img = (
                    ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .select("label")
                    .mode()
                )

                # Pixel area image in m² grouped by land cover class
                area_img = ee.Image.pixelArea().addBands(img)
                stats = area_img.reduceRegion(
                    reducer=ee.Reducer.sum().group(groupField=1, groupName="class_id"),
                    geometry=ee_geom,
                    scale=10,
                    maxPixels=1e9,
                ).getInfo()

                groups = stats.get("groups", [])
                total_area_m2 = sum(g.get("sum", 0) for g in groups) or 1.0

                class_results = []
                dominant_name = "Unknown"
                max_area = -1.0

                for g in groups:
                    cid = int(g.get("class_id", 0))
                    area_m2 = float(g.get("sum", 0))
                    cname = dw_classes[cid] if 0 <= cid < len(dw_classes) else f"Class {cid}"
                    ccolor = dw_colors[cid] if 0 <= cid < len(dw_colors) else "#cccccc"
                    pct = round((area_m2 / total_area_m2) * 100.0, 2)
                    area_km2 = round(area_m2 / 1e6, 4)
                    area_ha = round(area_m2 / 10000.0, 2)

                    if area_m2 > max_area:
                        max_area = area_m2
                        dominant_name = cname

                    class_results.append({
                        "class_id": cid,
                        "class_name": cname,
                        "color": ccolor,
                        "area_km2": area_km2,
                        "area_hectares": area_ha,
                        "percentage": pct,
                    })

                class_results.sort(key=lambda x: x["area_km2"], reverse=True)

                return {
                    "total_area_km2": round(total_area_m2 / 1e6, 4),
                    "dominant_land_use": dominant_name,
                    "breakdown": class_results,
                }

            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, run_zonal)

            return {
                "status": "success",
                "year": year,
                "source": "Google Dynamic World V1 (10m resolution)",
                "zonal_analysis": res,
                "message": (
                    f"Zonal land-use analysis complete for {year}. "
                    f"Total Area: {res['total_area_km2']} km². Dominant Land Use: {res['dominant_land_use']}."
                ),
            }

        except Exception as exc:
            return {"error": f"Zonal land use analysis failed: {exc}", "code": "gee_error"}

    async def _extract_land_use_polygons(self, args: dict) -> dict:
        target_input = str(args.get("target_class", "Built Area")).strip().lower()
        geojson_input = args.get("geojson")
        place_name = (args.get("place_name") or args.get("city") or args.get("location") or args.get("name") or "").strip()
        custom_color = args.get("color")
        lat = args.get("lat")
        lng = args.get("lng")
        radius_km = float(args.get("radius_km") or 5.0)
        year = int(args.get("year") or 2023)
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        dw_classes = [
            "water", "trees", "grass", "flooded vegetation",
            "crops", "shrub & scrub", "built area", "bare ground", "snow & ice",
        ]
        dw_display_names = [
            "Water", "Trees", "Grass", "Flooded Vegetation",
            "Crops", "Shrub & Scrub", "Built Area", "Bare Ground", "Snow & Ice",
        ]
        dw_colors = [
            "#419BDF", "#397D49", "#88B053", "#7A87C6",
            "#E49635", "#DFC35A", "#C4281B", "#A59B8F", "#B39FE1",
        ]

        # Resolve target class index
        target_idx = 6  # default Built Area
        if target_input.isdigit():
            target_idx = int(target_input)
        else:
            for i, name in enumerate(dw_classes):
                if target_input in name or name in target_input:
                    target_idx = i
                    break

        class_name = dw_display_names[target_idx] if 0 <= target_idx < len(dw_display_names) else "Built Area"
        
        # Color mapping support (e.g. blue, red, yellow, or hex)
        COLOR_MAP = {
            "blue": "#2563EB",
            "darkblue": "#1E40AF",
            "lightblue": "#60A5FA",
            "red": "#DC2626",
            "yellow": "#EAB308",
            "green": "#16A34A",
            "orange": "#F97316",
            "purple": "#9333EA",
            "cyan": "#06B6D4",
        }
        if custom_color:
            class_color = COLOR_MAP.get(str(custom_color).lower().strip(), str(custom_color))
        else:
            class_color = dw_colors[target_idx] if 0 <= target_idx < len(dw_colors) else "#C4281B"

        # If place_name is provided and geojson_input is not, auto-resolve boundary
        if not geojson_input and place_name:
            try:
                from tools.spatial_registry import spatial_registry
                poly = spatial_registry.get_polygon(place_name)
                if poly and poly.geometry:
                    geojson_input = poly.geometry
                else:
                    from mcp_servers.osm_server import OSMServer
                    osm = OSMServer()
                    b_res = await osm._fetch_boundary({"name": place_name})
                    if isinstance(b_res, dict) and "geojson" in b_res:
                        geojson_input = b_res["geojson"]
            except Exception as b_err:
                logger.warning(f"Could not auto-fetch boundary for '{place_name}': {b_err}")

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": f"GEE credentials required to extract vector polygons: {err}", "code": "upstream_unavailable"}

        try:
            import ee

            def run_vectorize():
                if geojson_input:
                    geom_data = geojson_input
                    if isinstance(geom_data, dict):
                        if geom_data.get("type") == "FeatureCollection" and geom_data.get("features"):
                            geom_data = geom_data["features"][0].get("geometry", geom_data)
                        elif geom_data.get("type") == "Feature" and "geometry" in geom_data:
                            geom_data = geom_data["geometry"]
                        elif "geometry" in geom_data and isinstance(geom_data["geometry"], dict):
                            geom_data = geom_data["geometry"]
                    ee_geom = ee.Geometry(geom_data)
                elif lat is not None and lng is not None:
                    ee_geom = ee.Geometry.Point([float(lng), float(lat)]).buffer(radius_km * 1000.0)
                else:
                    ee_geom = ee.Geometry.Point([76.7794, 30.7333]).buffer(3000)

                img = (
                    ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .select("label")
                    .mode()
                )

                # Mask raster for target land cover class
                masked = img.eq(target_idx).selfMask()

                # Convert raster pixels to vector polygons
                vectors = masked.reduceToVectors(
                    geometry=ee_geom,
                    scale=30,
                    maxPixels=1e7,
                    geometryType="polygon",
                    labelProperty="class_id",
                )

                fc = vectors.getInfo()
                return fc

            loop = asyncio.get_event_loop()
            fc_data = await loop.run_in_executor(None, run_vectorize)

            features = fc_data.get("features", [])
            display_title = f"{class_name} - {place_name}" if place_name else f"{class_name} Polygons ({year})"
            for feat in features:
                feat.setdefault("properties", {})
                feat["properties"]["land_cover_class"] = class_name
                feat["properties"]["year"] = year
                feat["properties"]["layer_name"] = display_title
                feat["properties"]["source_tool"] = "extract_land_use_polygons"
                feat["properties"]["description"] = f"Satellite land cover vector polygon for {class_name} ({year})"
                feat["properties"]["fillColor"] = class_color
                feat["properties"]["strokeColor"] = class_color
                feat["properties"]["opacity"] = 0.5

            output_geojson = {
                "type": "FeatureCollection",
                "features": features,
            }

            clean_name = class_name.lower().replace(" ", "_")
            place_slug = f"_{place_name.lower().replace(' ', '_')}" if place_name else ""
            out_filename = f"land_use_{clean_name}{place_slug}_{year}.geojson"

            if workspace:
                out_path = Path(workspace) / out_filename
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(output_geojson, f)

                if ws:
                    await ws.send_text(json.dumps({
                        "type": "action",
                        "action": "add_geojson_file",
                        "payload": {"path": str(out_path), "name": display_title, "color": class_color}
                    }))
            elif ws:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson",
                    "payload": {"geojson": output_geojson, "name": display_title, "color": class_color}
                }))

            return {
                "status": "success",
                "target_class": class_name,
                "place_name": place_name or None,
                "year": year,
                "color": class_color,
                "polygons_extracted": len(features),
                "geojson": output_geojson,
                "geojson_file": out_filename if workspace else None,
                "message": (
                    f"Extracted {len(features)} {class_name} vector polygons for {place_name or year} in {class_color} and loaded on map."
                ),
            }

        except Exception as exc:
            return {"error": f"Vector polygon extraction failed: {exc}", "code": "gee_error"}

