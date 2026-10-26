"""Google Earth Engine MCP server.

Architecture
------------
* `ee.Initialize()` is called once per process (cached in `_EE_READY`), specifying
  the GCP project to support both modern and legacy Earth Engine project maps.
* All synchronous `ee.*` calls (getMapId, getInfo, reduceRegion, etc.) are dispatched
  to a thread pool via `asyncio.get_event_loop().run_in_executor()` so the FastAPI
  async event loop is never blocked.
* Tile URLs are returned pointing to the backend proxy:
  `http://localhost:{port}/api/gee/tiles/{map_id}/{z}/{x}/{y}`.
  This ensures that MapLibre GL in Electron/browser receives valid tiles with server-side
  Bearer authentication without risking 401 Unauthorized errors from direct Google endpoints.
* Credentials are resolved in priority order:
    1. GOOGLE_EARTH_ENGINE_CREDS env var (JSON string, file path, or fallback dict)
    2. Explicit workspace path passed by caller (.disha/ee-service-account.json or *.json)
    3. CWD (backend process working directory)
    4. Dev credentials in .tmp/gee-credentials.json (supporting base64 fallback wrapper)
    5. Parent directories up to the repo root
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from llm.base import ToolDeclaration

logger = logging.getLogger(__name__)

# ── Process-level GEE init cache ─────────────────────────────────────────────
_EE_READY: bool | None = None
_EE_ERROR: str | None = None
_EE_PROJECT_ID: str | None = None


def reset_gee_init() -> None:
    """Reset Earth Engine initialization flags to force re-auth on next check."""
    global _EE_READY, _EE_ERROR, _EE_PROJECT_ID
    _EE_READY = None
    _EE_ERROR = None
    _EE_PROJECT_ID = None


def parse_gee_credentials_data(creds_input: str | Path | dict | None) -> dict | None:
    """Parse credentials from a file path, JSON string, or dict, handling base64 fallback wrapper."""
    if not creds_input:
        return None
    try:
        if isinstance(creds_input, Path) or (isinstance(creds_input, str) and os.path.isfile(str(creds_input))):
            data = json.loads(Path(creds_input).read_text(encoding="utf-8"))
        elif isinstance(creds_input, str):
            data = json.loads(creds_input)
        elif isinstance(creds_input, dict):
            data = creds_input
        else:
            return None

        if isinstance(data, dict) and "fallback" in data:
            data = json.loads(base64.b64decode(data["fallback"]).decode("utf-8"))

        if isinstance(data, dict) and data.get("type") == "service_account":
            return data
    except Exception as exc:
        logger.debug(f"Failed to parse GEE credentials data: {exc}")
    return None


def _find_gee_creds(workspace: str | None = None) -> str | None:
    """Locate service account credentials in priority order, returning path or JSON string."""
    env = os.environ.get("GOOGLE_EARTH_ENGINE_CREDS")
    if env and parse_gee_credentials_data(env):
        return env

    search_roots: list[Path] = []
    if workspace:
        ws_file = Path(workspace) / ".disha" / "ee-service-account.json"
        if ws_file.exists() and parse_gee_credentials_data(ws_file):
            return str(ws_file)
        for p in sorted(Path(workspace).glob("ee-*.json")):
            if parse_gee_credentials_data(p):
                return str(p)
        search_roots.append(Path(workspace))

    search_roots.append(Path.cwd())

    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent.parent
    dev_path = repo_root / ".tmp" / "gee-credentials.json"
    if dev_path.exists() and parse_gee_credentials_data(dev_path):
        return str(dev_path)

    for parent in [here.parent, here.parent.parent, here.parent.parent.parent, repo_root]:
        if parent not in search_roots and parent.is_dir():
            search_roots.append(parent)

    for root in search_roots:
        if not root.is_dir():
            continue
        for p in sorted(root.glob("ee-*.json")):
            if parse_gee_credentials_data(p):
                return str(p)
        for p in sorted(root.glob("*.json")):
            if parse_gee_credentials_data(p):
                return str(p)
    return None


def _sync_init_gee(creds_path: str) -> tuple[bool, str | None]:
    """Synchronous GEE init — run in a thread pool."""
    global _EE_READY, _EE_ERROR, _EE_PROJECT_ID
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
        data = parse_gee_credentials_data(creds_path)
        if not data:
            _EE_READY = False
            _EE_ERROR = "Invalid or missing Google Earth Engine service account credentials."
            return False, _EE_ERROR

        svc_email = data.get("client_email", "")
        project_id = data.get("project_id")
        _EE_PROJECT_ID = project_id

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(data, f)
            creds_file = f.name

        credentials = ee.ServiceAccountCredentials(svc_email, creds_file)
        if project_id:
            ee.Initialize(credentials=credentials, project=project_id)
        else:
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

    creds = _find_gee_creds(workspace)
    if not creds:
        return False, (
            "Google Earth Engine credentials not found. "
            "Place your ee-*.json service account file in your workspace root, "
            "in .tmp/gee-credentials.json, or configure the GOOGLE_EARTH_ENGINE_CREDS environment variable."
        )

    loop = asyncio.get_event_loop()
    ok, err = await loop.run_in_executor(None, _sync_init_gee, creds)
    return ok, err


def _clean_geojson_coords(c: Any) -> Any:
    """Recursively clean coordinates to [float(x), float(y)] 2D lists."""
    if isinstance(c, (list, tuple)):
        if len(c) >= 2 and isinstance(c[0], (int, float)) and isinstance(c[1], (int, float)):
            return [round(float(c[0]), 6), round(float(c[1]), 6)]
        return [_clean_geojson_coords(x) for x in c]
    return c


def _simplify_geom_if_needed(geom: dict, max_coords: int = 1500) -> dict:
    """Ensure geometry has manageable coordinate count for GEE clipping without losing shape accuracy."""
    try:
        from shapely.geometry import shape, mapping
        s = shape(geom)
        coord_count = 0
        if hasattr(s, "geoms"):
            for p in s.geoms:
                coord_count += len(p.exterior.coords) if hasattr(p, "exterior") else 0
        elif hasattr(s, "exterior"):
            coord_count += len(s.exterior.coords)
        if coord_count > max_coords:
            simplified = s.simplify(0.0005, preserve_topology=True)
            return mapping(simplified)
    except Exception:
        pass
    return geom


def _geojson_to_ee_geometry(geojson_data: dict | None) -> Any:
    """Convert GeoJSON FeatureCollection, Feature, or Geometry dict to an ee.Geometry."""
    if not geojson_data or not isinstance(geojson_data, dict):
        return None
    try:
        import ee
        from shapely.geometry import shape, mapping
        from shapely.ops import unary_union

        gtype = geojson_data.get("type")
        if gtype == "FeatureCollection":
            features = geojson_data.get("features", [])
            if not features:
                return None
            geoms = []
            for f in features:
                fg = f.get("geometry")
                if fg:
                    try:
                        s = shape(fg)
                        if not s.is_empty:
                            if not s.is_valid:
                                s = s.buffer(0)
                            geoms.append(s)
                    except Exception:
                        pass
            if not geoms:
                return None
            merged = unary_union(geoms) if len(geoms) > 1 else geoms[0]
            geom_dict = mapping(merged)
            geom_dict = _simplify_geom_if_needed(geom_dict)
            clean_dict = {
                "type": geom_dict["type"],
                "coordinates": _clean_geojson_coords(geom_dict["coordinates"]),
            }
            return ee.Geometry(clean_dict)

        elif gtype == "Feature":
            fg = geojson_data.get("geometry")
            if not fg:
                return None
            s = shape(fg)
            if not s.is_valid:
                s = s.buffer(0)
            geom_dict = mapping(s)
            geom_dict = _simplify_geom_if_needed(geom_dict)
            clean_dict = {
                "type": geom_dict["type"],
                "coordinates": _clean_geojson_coords(geom_dict["coordinates"]),
            }
            return ee.Geometry(clean_dict)

        elif gtype in ("Polygon", "MultiPolygon", "Point", "MultiPoint", "LineString", "MultiLineString", "GeometryCollection"):
            s = shape(geojson_data)
            if not s.is_valid:
                s = s.buffer(0)
            geom_dict = mapping(s)
            geom_dict = _simplify_geom_if_needed(geom_dict)
            clean_dict = {
                "type": geom_dict["type"],
                "coordinates": _clean_geojson_coords(geom_dict["coordinates"]),
            }
            return ee.Geometry(clean_dict)

        elif "geometry" in geojson_data and isinstance(geojson_data["geometry"], dict):
            return _geojson_to_ee_geometry(geojson_data["geometry"])

    except Exception as exc:
        logger.warning(f"Error converting geojson to ee.Geometry: {exc}")
    return None


def _sync_get_map_id(image_fn, vis_params: dict, ee_geom: Any = None) -> tuple[str, str]:
    """Call ee.data.getMapId in a thread. Returns (map_id, proxy_tile_url)."""
    import ee
    img = image_fn()
    if ee_geom is not None:
        try:
            img = img.clip(ee_geom)
        except Exception as clip_err:
            logger.debug(f"Image clipping note in _sync_get_map_id: {clip_err}")
    if vis_params:
        valid_keys = {"bands", "min", "max", "gain", "bias", "gamma", "palette", "opacity", "forceRgbOutput"}
        clean_vis = {k: v for k, v in vis_params.items() if k in valid_keys}
        try:
            vis_img = img.visualize(**clean_vis)
            result = ee.data.getMapId({"image": vis_img})
        except Exception as exc:
            logger.debug(f"Direct img.visualize failed, falling back to visParams dict: {exc}")
            result = ee.data.getMapId({"image": img, "visParams": vis_params})
    else:
        result = ee.data.getMapId({"image": img})
    map_id = result.get("mapid", "")
    port = int(os.environ.get("DISHA_BACKEND_PORT", "8765"))
    proxy_url = f"http://localhost:{port}/api/gee/tiles/{map_id}/{{z}}/{{x}}/{{y}}"
    return map_id, proxy_url



# ── Dataset Defaults & Catalog Information ────────────────────────────────────

def _get_dataset_defaults(dataset: str) -> tuple[dict, bool]:
    """Return default vis_params and boolean indicating whether dataset is an ImageCollection."""
    d = dataset.lower()
    
    # 1. Sentinel-2
    if "copernicus/s2" in d:
        return {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}, True

    # 2. Landsat 8/9
    if "landsat/lc08" in d or "landsat/lc09" in d:
        return {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 7000, "max": 16000}, True
    if "landsat/le07" in d or "landsat/lt05" in d:
        return {"bands": ["SR_B3", "SR_B2", "SR_B1"], "min": 7000, "max": 16000}, True

    # 3. Elevation & Terrain
    if "srtm" in d or "copernicus/dem" in d or "nasadem" in d or "aw3d30" in d:
        return {"min": 0, "max": 3000, "palette": ["0000ff", "00ff00", "ffff00", "ff7f00", "ff0000"]}, False

    # 4. Land Cover
    if "worldcover" in d:
        return {"bands": ["Map"]}, True
    if "dynamicworld" in d:
        return {
            "min": 0, "max": 8,
            "palette": ["419BDF", "397D49", "88B053", "7A87C6", "E49635", "DFC35A", "C4281B", "A59B8F", "B39FE1"],
        }, True
    if "mcd12q1" in d:
        return {"bands": ["LC_Type1"], "min": 1, "max": 17}, True

    # 5. Population
    if "worldpop" in d or "landscan" in d or "gpw" in d:
        return {"min": 0, "max": 500, "palette": ["ffffe5", "f7fcb9", "addd8e", "31a354", "006837", "ff0000"]}, False

    # 6. Surface Temperature (LST)
    if "mod11a1" in d or "myd11a1" in d:
        return {"bands": ["LST_Day_1km"], "min": 13000, "max": 16500, "palette": ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000"]}, True

    # 7. Atmospheric & Pollution (Sentinel-5P)
    if "s5p" in d:
        if "no2" in d:
            return {"bands": ["tropospheric_NO2_column_number_density"], "min": 0, "max": 0.0002, "palette": ["black", "blue", "purple", "cyan", "green", "yellow", "red"]}, True
        if "co" in d:
            return {"bands": ["CO_column_number_density"], "min": 0, "max": 0.05, "palette": ["black", "blue", "purple", "cyan", "green", "yellow", "red"]}, True
        if "so2" in d:
            return {"bands": ["SO2_column_number_density"], "min": 0, "max": 0.0005, "palette": ["black", "blue", "purple", "cyan", "green", "yellow", "red"]}, True
        if "o3" in d:
            return {"bands": ["O3_column_number_density"], "min": 0.12, "max": 0.16, "palette": ["black", "blue", "purple", "cyan", "green", "yellow", "red"]}, True
        if "aer_ai" in d:
            return {"bands": ["absorbing_aerosol_index"], "min": -1, "max": 3, "palette": ["black", "blue", "purple", "cyan", "green", "yellow", "red"]}, True

    # 8. Weather & Climate (ERA5-Land & TerraClimate)
    if "era5" in d:
        return {"bands": ["temperature_2m"], "min": 260, "max": 315, "palette": ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000"]}, True
    if "terraclimate" in d:
        return {"bands": ["pr"], "min": 0, "max": 250, "palette": ["ffffd9", "7fcdbb", "1d91c0", "081d58"]}, True

    # 9. Agriculture & Soil
    if "cdl" in d:
        return {"bands": ["cropland"], "min": 1, "max": 254}, True
    if "smap" in d:
        return {"bands": ["ssm"], "min": 0, "max": 25, "palette": ["f7fcb9", "addd8e", "41ab5d", "006837", "081d58"]}, True

    # 10. Water & Nighttime Lights
    if "globalsurfacewater" in d:
        return {"bands": ["occurrence"], "min": 0, "max": 100, "palette": ["ffffff", "ffddaa", "a6bddb", "3690c0", "081d58"]}, False
    if "viirs" in d:
        return {"bands": ["avg_rad"], "min": 0, "max": 60, "palette": ["000000", "111133", "224488", "ffff77", "ffffff"]}, True

    return {}, False


# ── Main Server Class ─────────────────────────────────────────────────────────

class GEEServer:
    description = (
        "Google Earth Engine (GEE) — comprehensive planetary remote sensing, satellite imagery, "
        "surface temperature, climate, atmospheric chemistry, weather, Landsat, Sentinel, "
        "high-resolution aerial imagery, MODIS, terrain, land cover, agriculture, and geophysical data."
    )
    tool_names = {
        "add_gee_layer",
        "get_surface_temperature_layer",
        "get_climate_layer",
        "get_atmospheric_layer",
        "get_weather_layer",
        "get_landsat_layer",
        "get_sentinel_layer",
        "get_high_resolution_imagery",
        "get_modis_layer",
        "get_dem_layer",
        "get_land_cover",
        "get_agriculture_layer",
        "get_geophysical_layer",
        "search_gee_datasets",
        "get_gee_zonal_stats",
        "get_population_layer",
        "analyze_lulc_change",
        "analyze_land_use_zonal_stats",
        "extract_land_use_polygons",
        "get_ndvi_layer",
        "get_gee_layer",
    }

    def get_declarations(self) -> list[ToolDeclaration]:
        place_param = {
            "type": "string",
            "description": "City or region name (e.g. 'City A', 'London'). When provided, the official boundary is fetched and the layer is strictly clipped to this place boundary.",
        }
        geojson_param = {
            "type": "object",
            "description": "Optional boundary polygon GeoJSON geometry or FeatureCollection to clip the layer strictly to.",
        }

        return [
            ToolDeclaration(
                name="add_gee_layer",
                description=(
                    "Add any Google Earth Engine raster dataset to the map as a tiled layer. "
                    "Supports Sentinel-2, Landsat, SRTM, ESA WorldCover, ERA5, MODIS, and any other "
                    "EE ImageCollection or Image. Applies cloud-free median compositing when dates are specified. "
                    "When place_name or geojson is provided, the layer is strictly clipped to that boundary."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string", "description": "Earth Engine dataset ID (e.g. 'COPERNICUS/S2_SR_HARMONIZED', 'LANDSAT/LC09/C02/T1_L2', 'USGS/SRTMGL1_003')."},
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "vis_params": {"type": "object", "description": "GEE visualization params (e.g. {\"min\":0,\"max\":3000,\"bands\":[\"B4\",\"B3\",\"B2\"]})."},
                        "date": {"type": "string", "description": "Year (e.g. '2023') or start date (YYYY-MM-DD) for collection filtering."},
                        "title": {"type": "string", "description": "Title label for the map layer panel."},
                    },
                    "required": ["dataset"],
                },
            ),
            ToolDeclaration(
                name="get_surface_temperature_layer",
                description=(
                    "Add a Land Surface Temperature (LST) raster layer to the map in Celsius. "
                    "Essential for Urban Heat Island (UHI) analysis, microclimate studies, and heat vulnerability mapping. "
                    "Sources: 'landsat' (Landsat 8/9 Thermal Band ST_B10, 30m resolution), 'modis' (MODIS Terra/Aqua Daily LST, 1km), "
                    "or 'era5_land' (ECMWF ERA5-Land 9km skin temperature)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "source": {
                            "type": "string",
                            "enum": ["landsat", "modis", "era5_land"],
                            "description": "'landsat' (30m high-res), 'modis' (1km daily), or 'era5_land' (9km climate). Default is 'landsat'.",
                        },
                        "year": {"type": "integer", "description": "Year to analyze (default 2023)."},
                        "min_temp": {"type": "number", "description": "Min temperature in Celsius for colour ramp (default 15°C)."},
                        "max_temp": {"type": "number", "description": "Max temperature in Celsius for colour ramp (default 45°C)."},
                        "title": {"type": "string", "description": "Custom layer title for map display."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_climate_layer",
                description=(
                    "Add climate, water balance, and bioclimatic raster layers to the map from TerraClimate, ERA5-Land, WorldClim, or CHIRPS. "
                    "Use for climate resilience planning, drought risk, water resources, and ecological zoning."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "source": {
                            "type": "string",
                            "enum": ["terraclimate", "era5_land", "worldclim", "chirps"],
                            "description": "'terraclimate' (monthly water balance & drought), 'era5_land' (reanalysis), 'worldclim' (bioclimatic), or 'chirps' (precipitation).",
                        },
                        "variable": {
                            "type": "string",
                            "enum": ["precipitation", "max_temperature", "min_temperature", "drought_pdsi", "soil_moisture", "runoff", "vapor_pressure_deficit"],
                            "description": "Climate indicator to visualize. Default is 'precipitation'.",
                        },
                        "year": {"type": "integer", "description": "Year to visualize (default 2023)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_atmospheric_layer",
                description=(
                    "Add atmospheric composition and air pollutant concentration layers from Sentinel-5P TROPOMI or MODIS. "
                    "Monitors Nitrogen Dioxide (NO2 from traffic & power generation), Carbon Monoxide (CO), Sulfur Dioxide (SO2), "
                    "Ozone (O3), Absorbing Aerosol Index (particulate & dust), Formaldehyde (HCHO), Methane (CH4), and MODIS AOD."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "pollutant": {
                            "type": "string",
                            "enum": ["no2", "co", "so2", "o3", "aerosol_index", "formaldehyde", "methane", "modis_aod"],
                            "description": "Air quality indicator or pollutant. Default is 'no2'.",
                        },
                        "year": {"type": "integer", "description": "Year to evaluate (default 2023)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_weather_layer",
                description=(
                    "Add gridded weather reanalysis or forecast layers from ECMWF ERA5-Land or NOAA GFS. "
                    "Visualizes 2m air temperature (°C), precipitation (mm), 10m wind velocity (m/s), and incoming solar radiation (W/m²)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "variable": {
                            "type": "string",
                            "enum": ["temperature_2m", "precipitation", "wind_speed", "solar_radiation"],
                            "description": "Weather variable. Default is 'temperature_2m'.",
                        },
                        "source": {"type": "string", "enum": ["era5_land", "gfs"], "description": "Weather source (default 'era5_land')."},
                        "year": {"type": "integer", "description": "Year (default 2023)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_landsat_layer",
                description=(
                    "Add multispectral Landsat imagery (Landsat 9, Landsat 8, Landsat 7, or Landsat 5) with calibrated band combinations. "
                    "Presets: 'true_color' (natural RGB), 'false_color_nir' (vegetation/urban), 'swir_geology' (moisture/burn scars), "
                    "'agriculture' (crop vigor), 'thermal' (surface temperature ST_B10 in °C), and 'ndvi'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "satellite": {
                            "type": "string",
                            "enum": ["landsat_9", "landsat_8", "landsat_7", "landsat_5"],
                            "description": "Landsat satellite mission. Default is 'landsat_9'.",
                        },
                        "preset": {
                            "type": "string",
                            "enum": ["true_color", "false_color_nir", "swir_geology", "agriculture", "thermal", "ndvi"],
                            "description": "Band combination preset. Default is 'true_color'.",
                        },
                        "year": {"type": "integer", "description": "Year to visualize (default 2023)."},
                        "max_cloud_cover": {"type": "number", "description": "Maximum cloudy pixel percentage (default 15)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_sentinel_layer",
                description=(
                    "Add European Space Agency (ESA) Sentinel imagery: Sentinel-2 optical multispectral (10m-20m) "
                    "or Sentinel-1 Synthetic Aperture Radar (SAR, 10m all-weather radar backscatter). "
                    "Presets for Sentinel-2: 'true_color', 'false_color_nir', 'agriculture', 'swir', 'ndvi', 'ndwi'. "
                    "Presets for Sentinel-1: 'sar_vv', 'sar_vh', 'sar_dual' (flood and structural roughness mapping)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "mission": {
                            "type": "string",
                            "enum": ["sentinel_2", "sentinel_1_sar"],
                            "description": "'sentinel_2' (optical 10m) or 'sentinel_1_sar' (radar 10m). Default is 'sentinel_2'.",
                        },
                        "preset": {
                            "type": "string",
                            "enum": ["true_color", "false_color_nir", "agriculture", "swir", "ndvi", "ndwi", "sar_vv", "sar_vh", "sar_dual"],
                            "description": "Band preset. Default is 'true_color'.",
                        },
                        "year": {"type": "integer", "description": "Year (default 2023)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_high_resolution_imagery",
                description=(
                    "Add high-resolution sub-meter aerial or fine satellite imagery to the map. "
                    "Sources: 'naip' (USDA NAIP 0.6m-1m true-color & color-infrared aerial orthoimagery across the US) "
                    "or 'sentinel_10m' (cloudless 10m global composite)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "source": {"type": "string", "enum": ["naip", "sentinel_10m"], "description": "Imagery source. Default 'naip'."},
                        "preset": {"type": "string", "enum": ["true_color", "color_infrared"], "description": "Preset for NAIP: 'true_color' (RGB) or 'color_infrared' (CIR)."},
                        "year": {"type": "integer", "description": "Year (default 2022)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_modis_layer",
                description=(
                    "Add moderate-resolution planetary monitoring rasters from NASA MODIS (Terra & Aqua). "
                    "Products: 'reflectance' (500m true/false color), 'ndvi_evi' (250m vegetation index), "
                    "'surface_temperature' (1km daily LST in °C), 'active_fires' (thermal anomaly hotspots), "
                    "'snow_cover' (daily snow extent), 'burned_area' (monthly burn date), and 'land_cover' (IGBP 500m annual)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "product": {
                            "type": "string",
                            "enum": ["reflectance", "ndvi_evi", "surface_temperature", "active_fires", "snow_cover", "burned_area", "land_cover"],
                            "description": "MODIS product. Default is 'ndvi_evi'.",
                        },
                        "year": {"type": "integer", "description": "Year (default 2023)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_dem_layer",
                description=(
                    "Add a Digital Elevation Model (DEM) or terrain analysis raster to the map. "
                    "Sources: 'srtm' (USGS SRTM 30m), 'copernicus' (Copernicus DEM 30m GLO-30), 'nasadem' (NASA DEM void-filled), "
                    "or 'alos' (JAXA ALOS AW3D30 30m).\n\n"
                    "Modes:\n"
                    "  • 'elevation': Colour-ramped from sea level to peaks.\n"
                    "  • 'hillshade': 3D shaded relief displaying ridges, valleys, and slope textures.\n"
                    "  • 'slope': Terrain steepness in degrees (0° flat to 45°+ steep).\n"
                    "  • 'aspect': Compass facing orientation in degrees (0°–360°) for solar exposure and microclimate planning."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "source": {
                            "type": "string",
                            "enum": ["srtm", "copernicus", "nasadem", "alos"],
                            "description": "DEM dataset source. Default is 'srtm'.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["elevation", "hillshade", "slope", "aspect"],
                            "description": "Visualization mode. Default is 'elevation'.",
                        },
                        "max_elevation": {"type": "number", "description": "Max elevation in meters for colour ramp (default 3000m)."},
                        "title": {"type": "string", "description": "Layer name."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_land_cover",
                description=(
                    "Add a full land-use / land-cover (LULC) raster tile layer showing ALL land classes simultaneously. "
                    "Sources: 'dynamic_world' (Google 10m, 9 classes), 'esa_worldcover' (ESA 10m, 11 classes), "
                    "'modis_landcover' (MODIS 500m, 17 IGBP classes for multi-decadal trends), or 'copernicus_landcover' (100m)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "source": {
                            "type": "string",
                            "enum": ["dynamic_world", "esa_worldcover", "modis_landcover", "copernicus_landcover"],
                            "description": "Land cover dataset. Default is 'dynamic_world'.",
                        },
                        "year": {"type": "integer", "description": "Year to visualize (default 2023)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_agriculture_layer",
                description=(
                    "Add specialized agricultural monitoring and crop intelligence raster layers. "
                    "Indicators: 'cropland_classes' (USDA NASS CDL 30m detailed crop classification: Corn, Soybeans, Wheat, Cotton, Rice, etc.), "
                    "'soil_moisture' (NASA-USDA SMAP 10km soil moisture), 'evapotranspiration' (MODIS 500m water consumption), "
                    "'crop_health_ndre' (Sentinel-2 Normalized Difference Red Edge index for chlorophyll/nitrogen vigor), "
                    "'crop_water_stress' (NDWI canopy moisture), and 'enhanced_vegetation_index' (EVI)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "indicator": {
                            "type": "string",
                            "enum": ["cropland_classes", "soil_moisture", "evapotranspiration", "crop_health_ndre", "crop_water_stress", "enhanced_vegetation_index"],
                            "description": "Agricultural indicator. Default is 'cropland_classes'.",
                        },
                        "year": {"type": "integer", "description": "Year (default 2023)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="get_geophysical_layer",
                description=(
                    "Add key planetary geophysical and socio-economic Earth observation datasets from the Earth Engine catalog. "
                    "Types: 'surface_water' (JRC Global Surface Water occurrence 0-100%), 'water_seasonality' (permanent vs seasonal water), "
                    "'nighttime_lights' (NOAA VIIRS Nighttime DNB luminosity), 'forest_canopy_cover' (Hansen Tree Canopy Cover % 0-100), "
                    "'forest_loss' (Hansen Global Forest Loss), and 'active_fires' (FIRMS fire hotspots)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "dataset_type": {
                            "type": "string",
                            "enum": ["surface_water", "water_seasonality", "nighttime_lights", "forest_canopy_cover", "forest_loss", "active_fires"],
                            "description": "Geophysical dataset type. Default is 'surface_water'.",
                        },
                        "year": {"type": "integer", "description": "Year (default 2021)."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="search_gee_datasets",
                description=(
                    "Search and discover datasets from the Google Earth Engine catalog. "
                    "Returns dataset asset IDs, descriptions, spatial resolution, temporal availability, and recommended visualization parameters."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keyword search (e.g. 'temperature', 'sentinel', 'rain', 'elevation', 'flood')."},
                        "category": {
                            "type": "string",
                            "enum": ["surface_temperature", "climate", "atmospheric", "weather", "landsat", "sentinel", "high_resolution", "modis", "terrain", "landcover", "agriculture", "geophysical"],
                            "description": "Optional category filter.",
                        },
                    },
                },
            ),
            ToolDeclaration(
                name="get_gee_zonal_stats",
                description=(
                    "Calculate quantitative zonal summary statistics (mean, min, max, stdDev) for ANY Earth Engine dataset "
                    "inside a boundary polygon or circular radius (e.g. mean surface temperature, average elevation, total rainfall, mean NDVI)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string", "description": "Dataset ID (e.g. 'USGS/SRTMGL1_003', 'LANDSAT/LC09/C02/T1_L2', 'MODIS/061/MOD11A1')."},
                        "place_name": place_param,
                        "band": {"type": "string", "description": "Band to analyze (e.g. 'elevation', 'ST_B10', 'LST_Day_1km', 'pr')."},
                        "geojson": {"type": "object", "description": "Optional boundary polygon GeoJSON."},
                        "lat": {"type": "number", "description": "Latitude for circular study area."},
                        "lng": {"type": "number", "description": "Longitude for circular study area."},
                        "radius_km": {"type": "number", "description": "Radius in km for study circle (default 5.0)."},
                        "year": {"type": "integer", "description": "Year for ImageCollections (default 2023)."},
                    },
                    "required": ["dataset"],
                },
            ),
            ToolDeclaration(
                name="get_population_layer",
                description=(
                    "Add a high-resolution population density raster layer to the map from WorldPop (100m grid, 2000-2020) "
                    "or CIESIN GPWv4 / LandScan. ALWAYS use this for 'population raster', 'population density map', 'WorldPop', "
                    "or urban density visualization requests."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "source": {"type": "string", "enum": ["worldpop", "landscan", "gpw"], "description": "Dataset source (default 'worldpop')."},
                        "year": {"type": "integer", "description": "Year between 2000 and 2020 (default 2020)."},
                        "country_iso": {"type": "string", "description": "ISO-3 country code for WorldPop (e.g. 'IND', 'USA', 'GBR')."},
                        "lat": {"type": "number", "description": "Latitude for study area location."},
                        "lng": {"type": "number", "description": "Longitude for study area location."},
                        "title": {"type": "string", "description": "Optional custom layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="analyze_lulc_change",
                description=(
                    "Compare Google Dynamic World land cover composites across two years to detect "
                    "land-use change. Returns a binary changed/unchanged mask and a class-transition layer."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
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
                    "Calculates exact area in km² and percentage composition breakdown of each land cover category."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": {"type": "object", "description": "GeoJSON polygon for study boundary."},
                        "lat": {"type": "number", "description": "Latitude for circular study area."},
                        "lng": {"type": "number", "description": "Longitude for circular study area."},
                        "radius_km": {"type": "number", "description": "Radius in km (default 5 km)."},
                        "year": {"type": "integer", "description": "Year (default 2023)."},
                        "source": {"type": "string", "enum": ["dynamic_world", "esa_worldcover"]},
                    },
                },
            ),
            ToolDeclaration(
                name="extract_land_use_polygons",
                description=(
                    "Extract a SINGLE specific land cover class as vector GeoJSON polygon features loaded directly on the map canvas. "
                    "Use whenever the user asks for: built-up area, urban footprint, trees/forest, water bodies, cropland, or grassland."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "target_class": {"type": "string", "description": "The land cover class (e.g. 'Built Area', 'Trees', 'Water', 'Crops')."},
                        "place_name": place_param,
                        "geojson": {"type": "object", "description": "Optional boundary polygon GeoJSON."},
                        "color": {"type": "string", "description": "Layer colour."},
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "radius_km": {"type": "number"},
                        "year": {"type": "integer"},
                    },
                    "required": ["target_class"],
                },
            ),
            ToolDeclaration(
                name="get_ndvi_layer",
                description=(
                    "Compute and display an NDVI layer from Sentinel-2 SR for a given year. "
                    "NDVI > 0.4 = dense vegetation; < 0.1 = built-up or bare land."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "year": {"type": "integer"},
                        "title": {"type": "string"},
                    },
                    "required": ["year"],
                },
            ),
            ToolDeclaration(
                name="get_gee_layer",
                description=(
                    "Sample pixel values from a GEE dataset at a specific lat/lng point and add as a tile layer."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string"},
                        "place_name": place_param,
                        "geojson": geojson_param,
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

        # Routing to tool handlers
        if tool_name == "add_gee_layer":
            return await self._add_gee_layer(args)
        if tool_name == "get_surface_temperature_layer":
            return await self._get_surface_temperature_layer(args)
        if tool_name == "get_climate_layer":
            return await self._get_climate_layer(args)
        if tool_name == "get_atmospheric_layer":
            return await self._get_atmospheric_layer(args)
        if tool_name == "get_weather_layer":
            return await self._get_weather_layer(args)
        if tool_name == "get_landsat_layer":
            return await self._get_landsat_layer(args)
        if tool_name == "get_sentinel_layer":
            return await self._get_sentinel_layer(args)
        if tool_name == "get_high_resolution_imagery":
            return await self._get_high_resolution_imagery(args)
        if tool_name == "get_modis_layer":
            return await self._get_modis_layer(args)
        if tool_name == "get_dem_layer":
            return await self._get_dem_layer(args)
        if tool_name == "get_land_cover":
            return await self._get_land_cover(args)
        if tool_name == "get_agriculture_layer":
            return await self._get_agriculture_layer(args)
        if tool_name == "get_geophysical_layer":
            return await self._get_geophysical_layer(args)
        if tool_name == "search_gee_datasets":
            return await self._search_gee_datasets(args)
        if tool_name == "get_gee_zonal_stats":
            return await self._get_gee_zonal_stats(args)
        if tool_name == "get_population_layer":
            return await self._get_population_layer(args)
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

    async def _send_action(self, ws, action: str, payload: dict) -> None:
        """Send a map action over WebSocket if connected."""
        if ws:
            try:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": action,
                    "payload": payload,
                }))
            except Exception as _e:
                logger.debug(f"Failed to send {action} over WS: {_e}")

    async def _send_layer(self, ws, tile_url: str, dataset: str, vis_params: dict, title: str) -> None:
        """Send add_gee_layer action over WebSocket if connected."""
        await self._send_action(ws, "add_gee_layer", {
            "url": tile_url,
            "dataset": dataset,
            "vis_params": vis_params,
            "title": title,
        })

    async def _tile_proxy(self, image_fn, vis_params: dict, ee_geom: Any = None) -> tuple[str, str]:
        """Run synchronous getMapId in thread pool → (map_id, proxy_tile_url)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_get_map_id, image_fn, vis_params, ee_geom)

    async def _resolve_place_boundary(
        self, args: dict
    ) -> tuple[dict | None, Any, str | None, dict | None]:
        """
        Resolves boundary for a specific place if requested or present in args/context.
        1. Checks explicit 'geojson' or 'place_name' in args (or aliases).
        2. If place_name is provided, checks Central SpatialRegistry and active map layers.
        3. If not found, fetches the official boundary polygon via OSMServer.
        4. When a boundary is newly fetched, registers it in SpatialRegistry and dispatches
           'add_geojson' and 'fit_bounds' to the map.
        5. Converts the GeoJSON geometry to an ee.Geometry for Earth Engine clipping.
        Returns: (boundary_geojson, ee_geom, matched_name, bbox_dict)
        """
        geojson_input = args.get("geojson")
        place_name = (
            args.get("place_name")
            or args.get("city")
            or args.get("location")
            or args.get("study_area")
            or args.get("boundary_name")
            or args.get("boundary")
            or args.get("place")
            or ""
        ).strip()
        country_code = (args.get("country_code") or args.get("country_iso") or "").strip()
        ws = args.get("_ws")
        map_context = args.get("_map_context") or {}

        # If place_name not explicitly set, check title for a place indicator (e.g. 'NDVI - Paris')
        if not place_name and not geojson_input:
            title = (args.get("title") or "").strip()
            if " - " in title:
                candidate = title.split(" - ")[-1].strip()
                if candidate and len(candidate) > 2 and not candidate.isdigit():
                    place_name = candidate

        # If still no place_name or geojson, check if there is an active registered study area boundary
        if not place_name and not geojson_input:
            try:
                from tools.spatial_registry import spatial_registry
                active_polys = spatial_registry.list_polygons()
                study_polys = [p for p in active_polys if p.get("source") in ("osm_boundary", "ai_draw", "user_draw")]
                if len(study_polys) == 1:
                    geojson_input = study_polys[0].get("geometry")
                    place_name = study_polys[0].get("name")
            except Exception:
                pass

        matched_name = place_name or None
        bbox = None
        centroid = None

        # 1. If explicit GeoJSON provided, use it
        if geojson_input:
            if isinstance(geojson_input, str):
                try:
                    geojson_input = json.loads(geojson_input)
                except Exception:
                    pass
            try:
                from shapely.geometry import shape
                s = shape(geojson_input if geojson_input.get("type") != "FeatureCollection" else geojson_input["features"][0]["geometry"])
                minx, miny, maxx, maxy = s.bounds
                bbox = {"west": round(minx, 6), "south": round(miny, 6), "east": round(maxx, 6), "north": round(maxy, 6)}
                c = s.centroid
                centroid = {"lat": round(c.y, 6), "lng": round(c.x, 6)}
            except Exception:
                pass

        # 2. If place_name provided and no GeoJSON yet:
        elif place_name:
            # Check SpatialRegistry
            try:
                from tools.spatial_registry import spatial_registry
                poly = spatial_registry.get_polygon(place_name)
                if poly and poly.geometry:
                    geojson_input = poly.geometry
                    matched_name = poly.name
                    bbox = poly.bbox
                    centroid = poly.centroid
            except Exception as _reg_err:
                logger.debug(f"Spatial registry check failed: {_reg_err}")

            # Check active map layers
            if not geojson_input and map_context.get("layers"):
                p_lower = place_name.lower().strip()
                for layer in map_context["layers"]:
                    lname = (layer.get("name") or "").lower().strip()
                    if p_lower in lname or lname in p_lower:
                        ldata = layer.get("data")
                        if isinstance(ldata, dict) and ldata.get("features"):
                            geojson_input = ldata
                            matched_name = layer.get("name")
                            break

            # If still not found, fetch official boundary from OSM
            if not geojson_input:
                try:
                    from mcp_servers.osm_server import OSMServer
                    osm = OSMServer()
                    b_res = await osm._fetch_boundary({
                        "name": place_name,
                        "country_code": country_code,
                        "_map_context": map_context,
                    })
                    if isinstance(b_res, dict) and "geojson" in b_res:
                        geojson_input = b_res["geojson"]
                        matched_name = b_res.get("name") or place_name
                        centroid = b_res.get("centroid")

                        # Register in central spatial registry
                        try:
                            from tools.spatial_registry import spatial_registry
                            spatial_registry.register_or_get(
                                name=matched_name,
                                geometry=geojson_input,
                                source="osm_boundary",
                            )
                        except Exception as reg_exc:
                            logger.warning(f"Failed to register boundary in spatial_registry: {reg_exc}")

                        # Send boundary to map canvas so user sees the boundary polygon!
                        boundary_title = f"{matched_name} Boundary"
                        await self._send_action(ws, "add_geojson", {
                            "geojson": geojson_input,
                            "name": boundary_title,
                            "color": "#3b82f6",
                        })

                        # Frame camera to the boundary
                        try:
                            from shapely.geometry import shape
                            s = shape(geojson_input if geojson_input.get("type") != "FeatureCollection" else geojson_input["features"][0]["geometry"])
                            minx, miny, maxx, maxy = s.bounds
                            bbox = {"west": round(minx, 6), "south": round(miny, 6), "east": round(maxx, 6), "north": round(maxy, 6)}
                            await self._send_action(ws, "fit_bounds", {
                                "bounds": [bbox["west"], bbox["south"], bbox["east"], bbox["north"]],
                            })
                        except Exception:
                            if centroid:
                                await self._send_action(ws, "fly_to", {
                                    "center": [centroid["lng"], centroid["lat"]],
                                    "zoom": 12,
                                })
                except Exception as b_err:
                    logger.warning(f"Could not auto-fetch boundary for '{place_name}': {b_err}")

        # Convert to Earth Engine geometry
        ee_geom = None
        if geojson_input:
            ee_geom = _geojson_to_ee_geometry(geojson_input)

        return geojson_input, ee_geom, matched_name, bbox

    # ── 1. Universal GEE Layer ────────────────────────────────────────────────

    async def _add_gee_layer(self, args: dict) -> dict:
        dataset = args.get("dataset", "").strip()
        vis_params = args.get("vis_params") or {}
        date_str = args.get("date", "").strip()
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        if not dataset:
            return {"error": "dataset is required"}

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        if not title:
            title = f"{dataset} - {place_nm}" if place_nm else f"{dataset}"
        elif place_nm and place_nm.lower() not in title.lower():
            title = f"{title} - {place_nm}"

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
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    if date_str:
                        start = f"{date_str}-01-01" if len(date_str) == 4 else date_str
                        end_yr = date_str.split("-")[0]
                        end = f"{end_yr}-12-31"
                        coll = coll.filterDate(start, end)
                    d_lower = dataset.lower()
                    if "copernicus/s2" in d_lower:
                        coll = coll.filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 15))
                    elif "landsat" in d_lower:
                        coll = coll.filter(ee.Filter.lt("CLOUD_COVER", 20))
                    return coll.median()
                return ee.Image(dataset)

            map_id, tile_url = await self._tile_proxy(build_image, final_vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset, final_vis, title)
            return {
                "status": "success",
                "message": f"GEE layer '{title}' added to map" + (f" for {place_nm}." if place_nm else "."),
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset,
                "vis": final_vis,
                "layer_title": title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
            }

        except Exception as exc:
            return {"error": f"GEE layer failed: {exc}", "code": "gee_error"}

    # ── 2. Surface Temperature (LST) ──────────────────────────────────────────

    async def _get_surface_temperature_layer(self, args: dict) -> dict:
        source = (args.get("source") or "landsat").strip().lower()
        year = int(args.get("year") or 2023)
        min_temp = float(args.get("min_temp") or 15.0)
        max_temp = float(args.get("max_temp") or 45.0)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"Surface Temperature ({source.title()} {year}) - {place_nm}" if place_nm else f"Surface Temperature ({source.title()} {year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            thermal_palette = ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000", "770000"]
            vis = {
                "min": min_temp,
                "max": max_temp,
                "palette": thermal_palette,
                "palette_labels": [f"{min_temp}°C", f"{(min_temp+max_temp)/2:.1f}°C", f"{max_temp}°C"],
            }

            def build_lst():
                if source == "landsat":
                    dataset_id = "LANDSAT/LC09/C02/T1_L2"
                    coll = (
                        ee.ImageCollection(dataset_id)
                        .filterDate(f"{year}-01-01", f"{year}-12-31")
                        .filter(ee.Filter.lt("CLOUD_COVER", 20))
                    )
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    # Convert Landsat Thermal ST_B10 to Celsius
                    return (
                        coll.median()
                        .select("ST_B10")
                        .multiply(0.00341802)
                        .add(149.0)
                        .subtract(273.15)
                        .rename("LST_Celsius")
                    )
                elif source == "modis":
                    dataset_id = "MODIS/061/MOD11A1"
                    coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    # Convert MODIS Kelvin scale factor (0.02) to Celsius
                    return (
                        coll.select("LST_Day_1km")
                        .mean()
                        .multiply(0.02)
                        .subtract(273.15)
                        .rename("LST_Celsius")
                    )
                elif source == "era5_land":
                    dataset_id = "ECMWF/ERA5_LAND/HOURLY"
                    coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-06-01", f"{year}-08-31")
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    return coll.select("skin_temperature").mean().subtract(273.15).rename("LST_Celsius")
                else:
                    raise ValueError(f"Unknown source '{source}'. Use: landsat, modis, or era5_land.")

            map_id, tile_url = await self._tile_proxy(build_lst, vis, ee_geom)
            dataset_id = "LANDSAT/LC09/C02/T1_L2" if source == "landsat" else ("MODIS/061/MOD11A1" if source == "modis" else "ECMWF/ERA5_LAND/HOURLY")
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "source": source,
                "year": year,
                "unit": "Celsius (°C)",
                "temperature_range": {"min": min_temp, "max": max_temp},
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": (
                    f"Surface temperature layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else ".") +
                    f" Thermal scale: {min_temp}°C (blue) to {max_temp}°C (dark red). Useful for Urban Heat Island mapping."
                ),
            }

        except Exception as exc:
            return {"error": f"Surface temperature layer failed: {exc}", "code": "gee_error"}

    # ── 3. Climate & Water Balance ────────────────────────────────────────────

    async def _get_climate_layer(self, args: dict) -> dict:
        source = (args.get("source") or "terraclimate").strip().lower()
        variable = (args.get("variable") or "precipitation").strip().lower()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"Climate: {variable.replace('_', ' ').title()} ({source.title()} {year}) - {place_nm}" if place_nm else f"Climate: {variable.replace('_', ' ').title()} ({source.title()} {year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if source == "terraclimate":
                dataset_id = "IDAHO_EPSCOR/TERRACLIMATE"
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                if variable == "precipitation":
                    vis = {"min": 0, "max": 2000, "palette": ["ffffd9", "7fcdbb", "1d91c0", "081d58"]}
                    build_fn = lambda: coll.select("pr").sum().rename("annual_precipitation_mm")
                    unit = "mm/year"
                elif variable in ["max_temperature", "temperature"]:
                    vis = {"min": 0, "max": 45, "palette": ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000"]}
                    build_fn = lambda: coll.select("tmmx").mean().multiply(0.1).rename("max_temp_celsius")
                    unit = "°C"
                elif variable == "drought_pdsi":
                    vis = {"min": -6, "max": 6, "palette": ["d73027", "f46d43", "fdae61", "ffffbf", "abd9e9", "74add1", "4575b4"]}
                    build_fn = lambda: coll.select("pdsi").mean().multiply(0.01).rename("pdsi_drought_index")
                    unit = "PDSI index"
                elif variable == "soil_moisture":
                    vis = {"min": 0, "max": 250, "palette": ["f7fcb9", "addd8e", "41ab5d", "006837"]}
                    build_fn = lambda: coll.select("sm").mean().multiply(0.1).rename("soil_moisture_mm")
                    unit = "mm"
                else:
                    vis = {"min": 0, "max": 200, "palette": ["ffffd9", "41b6c4", "225ea8"]}
                    build_fn = lambda: coll.select("ro").sum().rename("runoff_mm")
                    unit = "mm"

            elif source == "chirps":
                dataset_id = "UCSB-CHG/CHIRPS/PENTAD"
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                vis = {"min": 0, "max": 2500, "palette": ["ffffd9", "7fcdbb", "1d91c0", "081d58"]}
                build_fn = lambda: coll.select("precipitation").sum().rename("annual_precipitation_mm")
                unit = "mm/year"

            elif source == "worldclim":
                dataset_id = "WORLDCLIM/V1/BIO"
                img = ee.Image(dataset_id)
                if variable == "precipitation":
                    vis = {"bands": ["bio12"], "min": 0, "max": 3000, "palette": ["ffffd9", "7fcdbb", "1d91c0", "081d58"]}
                    build_fn = lambda: img.select("bio12")
                    unit = "mm/year"
                else:
                    vis = {"bands": ["bio01"], "min": -100, "max": 350, "palette": ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000"]}
                    build_fn = lambda: img.select("bio01").multiply(0.1)
                    unit = "°C"
            else:
                dataset_id = "ECMWF/ERA5_LAND/HOURLY"
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                vis = {"min": 0, "max": 2000, "palette": ["ffffd9", "7fcdbb", "1d91c0", "081d58"]}
                build_fn = lambda: coll.select("total_precipitation").sum().multiply(1000).rename("precip_mm")
                unit = "mm"

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "source": source,
                "variable": variable,
                "year": year,
                "unit": unit,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Climate layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Climate layer failed: {exc}", "code": "gee_error"}

    # ── 4. Atmospheric Chemistry & Pollution ──────────────────────────────────

    async def _get_atmospheric_layer(self, args: dict) -> dict:
        pollutant = (args.get("pollutant") or "no2").strip().lower()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"Atmospheric: {pollutant.upper()} Concentration ({year}) - {place_nm}" if place_nm else f"Atmospheric: {pollutant.upper()} Concentration ({year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            pal = ["black", "blue", "purple", "cyan", "green", "yellow", "red"]

            if pollutant == "no2":
                dataset_id = "COPERNICUS/S5P/NRTI/L3_NO2"
                band = "tropospheric_NO2_column_number_density"
                vis = {"min": 0, "max": 0.0002, "palette": pal}
                unit = "mol/m²"
            elif pollutant == "co":
                dataset_id = "COPERNICUS/S5P/NRTI/L3_CO"
                band = "CO_column_number_density"
                vis = {"min": 0, "max": 0.05, "palette": pal}
                unit = "mol/m²"
            elif pollutant == "so2":
                dataset_id = "COPERNICUS/S5P/NRTI/L3_SO2"
                band = "SO2_column_number_density"
                vis = {"min": 0, "max": 0.0005, "palette": pal}
                unit = "mol/m²"
            elif pollutant == "o3":
                dataset_id = "COPERNICUS/S5P/NRTI/L3_O3"
                band = "O3_column_number_density"
                vis = {"min": 0.12, "max": 0.16, "palette": pal}
                unit = "mol/m²"
            elif pollutant == "aerosol_index":
                dataset_id = "COPERNICUS/S5P/NRTI/L3_AER_AI"
                band = "absorbing_aerosol_index"
                vis = {"min": -1, "max": 3, "palette": pal}
                unit = "AI index"
            elif pollutant == "formaldehyde":
                dataset_id = "COPERNICUS/S5P/NRTI/L3_HCHO"
                band = "tropospheric_HCHO_column_number_density"
                vis = {"min": 0, "max": 0.0003, "palette": pal}
                unit = "mol/m²"
            elif pollutant == "methane":
                dataset_id = "COPERNICUS/S5P/OFFL/L3_CH4"
                band = "CH4_column_volume_mixing_ratio_dry_air"
                vis = {"min": 1750, "max": 1950, "palette": pal}
                unit = "ppb"
            elif pollutant == "modis_aod":
                dataset_id = "MODIS/061/MCD19A2_GRANULES"
                band = "Optical_Depth_047"
                vis = {"min": 0, "max": 1000, "palette": ["blue", "cyan", "green", "yellow", "orange", "red"]}
                unit = "AOD (scaled 1e-3)"
            else:
                raise ValueError(f"Unknown pollutant '{pollutant}'. Use: no2, co, so2, o3, aerosol_index, formaldehyde, methane, modis_aod.")

            def build_atmos():
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                return coll.select(band).mean()

            map_id, tile_url = await self._tile_proxy(build_atmos, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "pollutant": pollutant,
                "year": year,
                "unit": unit,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Atmospheric pollution layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Atmospheric layer failed: {exc}", "code": "gee_error"}

    # ── 5. Gridded Weather ────────────────────────────────────────────────────

    async def _get_weather_layer(self, args: dict) -> dict:
        variable = (args.get("variable") or "temperature_2m").strip().lower()
        source = (args.get("source") or "era5_land").strip().lower()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"Weather: {variable.replace('_', ' ').title()} ({year}) - {place_nm}" if place_nm else f"Weather: {variable.replace('_', ' ').title()} ({year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            dataset_id = "ECMWF/ERA5_LAND/HOURLY"
            coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-06-01", f"{year}-08-31")
            if ee_geom is not None:
                try:
                    coll = coll.filterBounds(ee_geom)
                except Exception:
                    pass

            if variable == "temperature_2m":
                vis = {"min": 0, "max": 42, "palette": ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000"]}
                build_fn = lambda: coll.select("temperature_2m").mean().subtract(273.15).rename("temp_celsius")
                unit = "°C"
            elif variable == "precipitation":
                vis = {"min": 0, "max": 50, "palette": ["ffffff", "7fcdbb", "1d91c0", "081d58"]}
                build_fn = lambda: coll.select("total_precipitation").mean().multiply(1000).rename("precip_mm")
                unit = "mm/day"
            elif variable == "wind_speed":
                vis = {"min": 0, "max": 20, "palette": ["2c7bb6", "abd9e9", "ffffbf", "fdae61", "d7191c"]}
                def wind_fn():
                    u = coll.select("u_component_of_wind_10m").mean()
                    v = coll.select("v_component_of_wind_10m").mean()
                    return u.hypot(v).rename("wind_speed_ms")
                build_fn = wind_fn
                unit = "m/s"
            else:
                vis = {"min": 0, "max": 800, "palette": ["000000", "ffff80", "ffaa00", "ff4400", "ffffff"]}
                build_fn = lambda: coll.select("surface_solar_radiation_downwards_hourly").mean().divide(3600).rename("solar_wm2")
                unit = "W/m²"

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "variable": variable,
                "year": year,
                "unit": unit,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Weather layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Weather layer failed: {exc}", "code": "gee_error"}

    # ── 6. Multispectral Landsat ──────────────────────────────────────────────

    async def _get_landsat_layer(self, args: dict) -> dict:
        sat = (args.get("satellite") or "landsat_9").strip().lower()
        preset = (args.get("preset") or "true_color").strip().lower()
        year = int(args.get("year") or 2023)
        max_clouds = float(args.get("max_cloud_cover") or 15)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"{sat.replace('_', ' ').title()} — {preset.replace('_', ' ').title()} ({year}) - {place_nm}" if place_nm else f"{sat.replace('_', ' ').title()} — {preset.replace('_', ' ').title()} ({year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        sat_map = {
            "landsat_9": "LANDSAT/LC09/C02/T1_L2",
            "landsat_8": "LANDSAT/LC08/C02/T1_L2",
            "landsat_7": "LANDSAT/LE07/C02/T1_L2",
            "landsat_5": "LANDSAT/LT05/C02/T1_L2",
        }
        dataset_id = sat_map.get(sat, "LANDSAT/LC09/C02/T1_L2")

        try:
            import ee

            is_modern = sat in ["landsat_9", "landsat_8"]
            coll = (
                ee.ImageCollection(dataset_id)
                .filterDate(f"{year}-01-01", f"{year}-12-31")
                .filter(ee.Filter.lt("CLOUD_COVER", max_clouds))
            )
            if ee_geom is not None:
                try:
                    coll = coll.filterBounds(ee_geom)
                except Exception:
                    pass

            if preset == "true_color":
                bands = ["SR_B4", "SR_B3", "SR_B2"] if is_modern else ["SR_B3", "SR_B2", "SR_B1"]
                vis = {"bands": bands, "min": 7000, "max": 16000}
                build_fn = lambda: coll.median()
            elif preset == "false_color_nir":
                bands = ["SR_B5", "SR_B4", "SR_B3"] if is_modern else ["SR_B4", "SR_B3", "SR_B2"]
                vis = {"bands": bands, "min": 7000, "max": 18000}
                build_fn = lambda: coll.median()
            elif preset == "swir_geology":
                bands = ["SR_B7", "SR_B6", "SR_B4"] if is_modern else ["SR_B7", "SR_B5", "SR_B3"]
                vis = {"bands": bands, "min": 7000, "max": 18000}
                build_fn = lambda: coll.median()
            elif preset == "agriculture":
                bands = ["SR_B6", "SR_B5", "SR_B2"] if is_modern else ["SR_B5", "SR_B4", "SR_B1"]
                vis = {"bands": bands, "min": 7000, "max": 18000}
                build_fn = lambda: coll.median()
            elif preset == "thermal":
                vis = {"min": 15, "max": 45, "palette": ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000"]}
                build_fn = lambda: coll.median().select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15)
            else:
                vis = {"min": -0.1, "max": 0.8, "palette": ["8B4513", "FFFF00", "228B22", "006400"]}
                nir = "SR_B5" if is_modern else "SR_B4"
                red = "SR_B4" if is_modern else "SR_B3"
                build_fn = lambda: coll.median().normalizedDifference([nir, red]).rename("NDVI")

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "satellite": sat,
                "preset": preset,
                "year": year,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Landsat imagery layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Landsat layer failed: {exc}", "code": "gee_error"}

    # ── 7. Sentinel-1 SAR & Sentinel-2 Optical ────────────────────────────────

    async def _get_sentinel_layer(self, args: dict) -> dict:
        mission = (args.get("mission") or "sentinel_2").strip().lower()
        preset = (args.get("preset") or "true_color").strip().lower()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"{mission.replace('_', ' ').upper()} — {preset.replace('_', ' ').title()} ({year}) - {place_nm}" if place_nm else f"{mission.replace('_', ' ').upper()} — {preset.replace('_', ' ').title()} ({year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if mission == "sentinel_1_sar":
                dataset_id = "COPERNICUS/S1_GRD"
                coll = (
                    ee.ImageCollection(dataset_id)
                    .filter(ee.Filter.eq("instrumentMode", "IW"))
                    .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                )
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                if preset == "sar_vh":
                    vis = {"min": -30, "max": -5, "palette": ["000000", "ffffff"]}
                    build_fn = lambda: coll.select("VH").median()
                elif preset == "sar_dual":
                    vis = {"bands": ["VV", "VH", "VV"], "min": [-25, -30, -25], "max": [0, -5, 0]}
                    build_fn = lambda: coll.select(["VV", "VH"]).median()
                else:
                    vis = {"min": -25, "max": 0, "palette": ["000000", "ffffff"]}
                    build_fn = lambda: coll.select("VV").median()

            else:
                dataset_id = "COPERNICUS/S2_SR_HARMONIZED"
                coll = (
                    ee.ImageCollection(dataset_id)
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 15))
                )
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                if preset == "false_color_nir":
                    vis = {"bands": ["B8", "B4", "B3"], "min": 0, "max": 4000}
                    build_fn = lambda: coll.median()
                elif preset == "agriculture":
                    vis = {"bands": ["B11", "B8", "B2"], "min": 0, "max": 4000}
                    build_fn = lambda: coll.median()
                elif preset == "swir":
                    vis = {"bands": ["B12", "B8", "B4"], "min": 0, "max": 4000}
                    build_fn = lambda: coll.median()
                elif preset == "ndwi":
                    vis = {"min": -0.5, "max": 0.5, "palette": ["0000ff", "00ffff", "ffffff", "ffaa00", "885500"]}
                    build_fn = lambda: coll.median().normalizedDifference(["B3", "B8"]).rename("NDWI")
                elif preset == "ndvi":
                    vis = {"min": -0.1, "max": 0.85, "palette": ["8B4513", "D2691E", "FFFF00", "228B22", "006400"]}
                    build_fn = lambda: coll.median().normalizedDifference(["B8", "B4"]).rename("NDVI")
                else:
                    vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}
                    build_fn = lambda: coll.median()

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "mission": mission,
                "preset": preset,
                "year": year,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Sentinel layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Sentinel layer failed: {exc}", "code": "gee_error"}

    # ── 8. High-Resolution Aerial & Fine Satellite ────────────────────────────

    async def _get_high_resolution_imagery(self, args: dict) -> dict:
        source = (args.get("source") or "naip").strip().lower()
        preset = (args.get("preset") or "true_color").strip().lower()
        year = int(args.get("year") or 2022)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"High-Res Imagery ({source.upper()} {year}) - {place_nm}" if place_nm else f"High-Res Imagery ({source.upper()} {year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if source == "naip":
                dataset_id = "USDA/NAIP/DOQQ"
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year-1}-01-01", f"{year+1}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                if preset == "color_infrared":
                    vis = {"bands": ["N", "R", "G"], "min": 0, "max": 255}
                else:
                    vis = {"bands": ["R", "G", "B"], "min": 0, "max": 255}
                build_fn = lambda: coll.mosaic()
                desc = "0.6m - 1.0m USDA aerial orthoimagery"
            else:
                dataset_id = "COPERNICUS/S2_SR_HARMONIZED"
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31").filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 10))
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}
                build_fn = lambda: coll.median()
                desc = "10m European Space Agency Sentinel-2 optical"

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "source": source,
                "resolution": desc,
                "year": year,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"High resolution imagery '{layer_title}' ({desc}) added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"High-resolution imagery failed: {exc}", "code": "gee_error"}

    # ── 9. MODIS Planetary Suite ──────────────────────────────────────────────

    async def _get_modis_layer(self, args: dict) -> dict:
        product = (args.get("product") or "ndvi_evi").strip().lower()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"MODIS {product.replace('_', ' ').title()} ({year}) - {place_nm}" if place_nm else f"MODIS {product.replace('_', ' ').title()} ({year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if product == "reflectance":
                dataset_id = "MODIS/061/MOD09A1"
                vis = {"bands": ["sur_refl_b01", "sur_refl_b04", "sur_refl_b03"], "min": -100, "max": 8000}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.median()

            elif product == "surface_temperature":
                dataset_id = "MODIS/061/MOD11A1"
                vis = {"min": 10, "max": 48, "palette": ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("LST_Day_1km").mean().multiply(0.02).subtract(273.15)

            elif product == "active_fires":
                dataset_id = "FIRMS"
                vis = {"min": 0, "max": 1, "palette": ["ffff00", "ff0000"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("T21").max().gt(300)

            elif product == "snow_cover":
                dataset_id = "MODIS/061/MOD10A1"
                vis = {"bands": ["NDSI_Snow_Cover"], "min": 0, "max": 100, "palette": ["000000", "00ffff", "ffffff"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("NDSI_Snow_Cover").max()

            elif product == "burned_area":
                dataset_id = "MODIS/061/MCD64A1"
                vis = {"bands": ["BurnDate"], "min": 1, "max": 366, "palette": ["ffff00", "ff7700", "ff0000"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("BurnDate").max()

            elif product == "land_cover":
                dataset_id = "MODIS/061/MCD12Q1"
                vis = {"bands": ["LC_Type1"], "min": 1, "max": 17}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("LC_Type1").first()

            else:
                dataset_id = "MODIS/061/MOD13Q1"
                vis = {"min": 0.0, "max": 0.85, "palette": ["ffffff", "ce7e45", "df923d", "f1b555", "fcd163", "99b718", "74a901", "66a000", "529400", "3e8601", "207401", "056201", "004c00"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("NDVI").median().multiply(0.0001)

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "product": product,
                "year": year,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"MODIS layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"MODIS layer failed: {exc}", "code": "gee_error"}

    # ── 10. Digital Elevation Models & Terrain Derivatives ─────────────────────

    async def _get_dem_layer(self, args: dict) -> dict:
        source = (args.get("source") or "srtm").strip().lower()
        mode = (args.get("mode") or "").strip().lower()
        max_elev = float(args.get("max_elevation") or 3000)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"DEM ({source.upper()} {mode.title()}) - {place_nm}" if place_nm else f"DEM ({source.upper()} {mode.title()})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        _DEM_DATASETS = {
            "srtm": ("USGS/SRTMGL1_003", "elevation", False),
            "copernicus": ("COPERNICUS/DEM/GLO30", "DEM", False),
            "nasadem": ("NASA/NASADEM_HGT/001", "elevation", False),
            "alos": ("JAXA/ALOS/AW3D30/V3_2", "DSM", True),
        }

        if source not in _DEM_DATASETS:
            return {"error": f"Unknown source '{source}'. Use: srtm, copernicus, nasadem, alos."}

        dataset_id, band, is_coll = _DEM_DATASETS[source]

        if not mode:
            if "hillshade" in title.lower() or "relief" in title.lower():
                mode = "hillshade"
            elif "slope" in title.lower():
                mode = "slope"
            elif "aspect" in title.lower():
                mode = "aspect"
            else:
                mode = "elevation"

        if mode == "hillshade":
            vis = {"bands": ["hillshade"], "min": 0, "max": 255, "palette": ["000000", "777777", "ffffff"]}
        elif mode == "slope":
            vis = {"bands": ["slope"], "min": 0, "max": 45, "palette": ["2b83ba", "abdda4", "ffffbf", "fdae61", "d7191c"]}
        elif mode == "aspect":
            vis = {"bands": ["aspect"], "min": 0, "max": 360, "palette": ["red", "yellow", "green", "cyan", "blue", "magenta", "red"]}
        else:
            vis = {
                "bands": [band],
                "min": 0,
                "max": max_elev,
                "palette": ["0000ff", "00aaff", "00ff00", "ffff00", "ff7f00", "ff0000", "ffffff"],
            }

        try:
            import ee

            def build_terrain():
                raw = ee.ImageCollection(dataset_id).mosaic() if is_coll else ee.Image(dataset_id)
                dem_band = raw.select(band)
                if mode == "hillshade":
                    return ee.Terrain.hillshade(dem_band)
                if mode == "slope":
                    return ee.Terrain.slope(dem_band)
                if mode == "aspect":
                    return ee.Terrain.aspect(dem_band)
                return dem_band

            map_id, tile_url = await self._tile_proxy(build_terrain, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "source": source,
                "mode": mode,
                "dataset_id": dataset_id,
                "tile_url": tile_url,
                "map_id": map_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Terrain layer '{layer_title}' ({mode}) added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"DEM layer failed: {exc}", "code": "gee_error"}

    # ── 11. Multi-Class Land Cover (LULC) ─────────────────────────────────────

    async def _get_land_cover(self, args: dict) -> dict:
        source = (args.get("source") or "dynamic_world").strip().lower()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"Land Cover ({source.replace('_', ' ').title()} {year}) - {place_nm}" if place_nm else f"Land Cover ({source.replace('_', ' ').title()} {year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if source == "dynamic_world":
                dw_palette = ["419BDF", "397D49", "88B053", "7A87C6", "E49635", "DFC35A", "C4281B", "A59B8F", "B39FE1"]
                dw_classes = ["Water", "Trees", "Grass", "Flooded Vegetation", "Crops", "Shrub & Scrub", "Built Area", "Bare Ground", "Snow & Ice"]
                vis = {"min": 0, "max": 8, "palette": dw_palette, "palette_labels": dw_classes}
                dataset_id = "GOOGLE/DYNAMICWORLD/V1"
                def dw_fn():
                    coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    return coll.select("label").mode()
                build_fn = dw_fn

            elif source == "esa_worldcover":
                yr_map = {2020: "ESA/WorldCover/v100/2020", 2021: "ESA/WorldCover/v200/2021"}
                dataset_id = yr_map.get(year, "ESA/WorldCover/v200/2021")
                esa_palette = ["006400", "ffbb22", "ffff4c", "f096ff", "fa0000", "b4b4b4", "f0f0f0", "0064c8", "0096a0", "00cf75", "fae6a0"]
                esa_classes = ["Trees", "Shrubland", "Grassland", "Cropland", "Built-up", "Barren", "Snow & Ice", "Open Water", "Wetland", "Mangroves", "Moss & Lichen"]
                vis = {"bands": ["Map"], "min": 10, "max": 100, "palette": esa_palette, "palette_labels": esa_classes}
                build_fn = lambda: ee.Image(dataset_id)

            elif source == "modis_landcover":
                dataset_id = "MODIS/061/MCD12Q1"
                vis = {"bands": ["LC_Type1"], "min": 1, "max": 17}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("LC_Type1").first()

            else:
                dataset_id = "COPERNICUS/Landcover/100m/Proba-V-C3/Global"
                vis = {"bands": ["discrete_classification"], "min": 0, "max": 200}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("discrete_classification").first()

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "source": source,
                "year": year,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Land cover layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Land cover layer failed: {exc}", "code": "gee_error"}

    # ── 12. Agriculture & Crop Intelligence ───────────────────────────────────

    async def _get_agriculture_layer(self, args: dict) -> dict:
        indicator = (args.get("indicator") or "cropland_classes").strip().lower()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"Agriculture: {indicator.replace('_', ' ').title()} ({year}) - {place_nm}" if place_nm else f"Agriculture: {indicator.replace('_', ' ').title()} ({year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if indicator == "cropland_classes":
                dataset_id = "USDA/NASS/CDL"
                vis = {"bands": ["cropland"], "min": 1, "max": 254}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.first().select("cropland")
                desc = "USDA NASS Cropland Data Layer 30m detailed crop types"

            elif indicator == "soil_moisture":
                dataset_id = "NASA_USDA/HSL/SMAP10KM_soil_moisture"
                vis = {"min": 0, "max": 25, "palette": ["f7fcb9", "addd8e", "41ab5d", "006837", "081d58"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("ssm").mean()
                desc = "NASA-USDA SMAP 10km Surface Soil Moisture (mm)"

            elif indicator == "evapotranspiration":
                dataset_id = "MODIS/061/MOD16A2"
                vis = {"min": 0, "max": 250, "palette": ["ffffff", "a6bddb", "3690c0", "02818a"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("ET").mean().multiply(0.1)
                desc = "MODIS 500m 8-Day Evapotranspiration"

            elif indicator == "crop_health_ndre":
                dataset_id = "COPERNICUS/S2_SR_HARMONIZED"
                vis = {"min": 0, "max": 0.6, "palette": ["d73027", "fdae61", "ffffbf", "a6d96a", "1a9850"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31").filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 15))
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.median().normalizedDifference(["B8", "B5"]).rename("NDRE")
                desc = "Sentinel-2 Normalized Difference Red Edge (chlorophyll & nitrogen vigor)"

            elif indicator == "crop_water_stress":
                dataset_id = "COPERNICUS/S2_SR_HARMONIZED"
                vis = {"min": -0.3, "max": 0.5, "palette": ["a50026", "f46d43", "ffffbf", "74add1", "313695"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31").filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 15))
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.median().normalizedDifference(["B8", "B11"]).rename("NDWI")
                desc = "Sentinel-2 NDWI Canopy Water Stress"

            else:
                dataset_id = "COPERNICUS/S2_SR_HARMONIZED"
                vis = {"min": 0, "max": 1, "palette": ["ffffff", "ce7e45", "ffff00", "228B22", "006400"]}
                def evi_fn():
                    c = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31").filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 15))
                    if ee_geom is not None:
                        try:
                            c = c.filterBounds(ee_geom)
                        except Exception:
                            pass
                    s2 = c.median()
                    nir = s2.select("B8").multiply(0.0001)
                    red = s2.select("B4").multiply(0.0001)
                    blue = s2.select("B2").multiply(0.0001)
                    return nir.subtract(red).multiply(2.5).divide(nir.add(red.multiply(6.0)).subtract(blue.multiply(7.5)).add(1.0)).rename("EVI")
                build_fn = evi_fn
                desc = "Sentinel-2 Enhanced Vegetation Index (EVI)"

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "indicator": indicator,
                "description": desc,
                "year": year,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Agricultural layer '{layer_title}' ({desc}) added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Agriculture layer failed: {exc}", "code": "gee_error"}

    # ── 13. Other Geophysical & Planetary Data ────────────────────────────────

    async def _get_geophysical_layer(self, args: dict) -> dict:
        dataset_type = (args.get("dataset_type") or "surface_water").strip().lower()
        year = int(args.get("year") or 2021)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        layer_title = title or (f"Geophysical: {dataset_type.replace('_', ' ').title()} ({year}) - {place_nm}" if place_nm else f"Geophysical: {dataset_type.replace('_', ' ').title()} ({year})")
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if dataset_type == "water_seasonality":
                dataset_id = "JRC/GSW1_4/GlobalSurfaceWater"
                vis = {"bands": ["seasonality"], "min": 0, "max": 12, "palette": ["ffffff", "ffddaa", "a6bddb", "3690c0", "081d58"]}
                build_fn = lambda: ee.Image(dataset_id).select("seasonality")
                desc = "JRC Global Surface Water Seasonality (0-12 months)"

            elif dataset_type == "nighttime_lights":
                dataset_id = "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG"
                vis = {"bands": ["avg_rad"], "min": 0, "max": 60, "palette": ["000000", "111133", "224488", "ffff77", "ffffff"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("avg_rad").median()
                desc = "NOAA VIIRS Nighttime Lights DNB Radiance"

            elif dataset_type == "forest_canopy_cover":
                dataset_id = "UMD/hansen/global_forest_change_2024_v1_12"
                vis = {"bands": ["treecover2000"], "min": 0, "max": 100, "palette": ["ffffff", "d9f0a3", "78c679", "00441b"]}
                build_fn = lambda: ee.Image(dataset_id).select("treecover2000")
                desc = "Hansen Global Tree Canopy Cover (0-100%)"

            elif dataset_type == "forest_loss":
                dataset_id = "UMD/hansen/global_forest_change_2024_v1_12"
                vis = {"bands": ["loss"], "min": 0, "max": 1, "palette": ["000000", "ff0000"]}
                build_fn = lambda: ee.Image(dataset_id).select("loss")
                desc = "Hansen Global Forest Loss Year-by-Year"

            elif dataset_type == "active_fires":
                dataset_id = "FIRMS"
                vis = {"min": 0, "max": 1, "palette": ["ffff00", "ff0000"]}
                coll = ee.ImageCollection(dataset_id).filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("T21").max().gt(300)
                desc = "NASA FIRMS Active Thermal Fire Hotspots"

            else:
                dataset_id = "JRC/GSW1_4/GlobalSurfaceWater"
                vis = {"bands": ["occurrence"], "min": 0, "max": 100, "palette": ["ffffff", "ffddaa", "a6bddb", "3690c0", "081d58"]}
                build_fn = lambda: ee.Image(dataset_id).select("occurrence")
                desc = "JRC Global Surface Water Occurrence (0-100%)"

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "dataset_type": dataset_type,
                "description": desc,
                "year": year,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Geophysical layer '{layer_title}' ({desc}) added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Geophysical layer failed: {exc}", "code": "gee_error"}

    # ── 14. Search Earth Engine Catalog ───────────────────────────────────────

    async def _search_gee_datasets(self, args: dict) -> dict:
        query = (args.get("query") or "").strip().lower()
        category = (args.get("category") or "").strip().lower()

        _CATALOG = [
            # Surface Temp
            {"id": "LANDSAT/LC09/C02/T1_L2", "name": "Landsat 9 Collection 2 Level 2", "category": "surface_temperature", "bands": ["SR_B4", "SR_B3", "SR_B2", "ST_B10"], "res": "30m", "desc": "High-res optical surface reflectance and thermal surface temperature (ST_B10)."},
            {"id": "MODIS/061/MOD11A1", "name": "MODIS Terra Land Surface Temperature Daily", "category": "surface_temperature", "bands": ["LST_Day_1km", "LST_Night_1km"], "res": "1km", "desc": "Daily global land surface temperature in Kelvin (scale 0.02)."},
            # Climate & Weather
            {"id": "IDAHO_EPSCOR/TERRACLIMATE", "name": "TerraClimate Monthly Water Balance", "category": "climate", "bands": ["pr", "tmmx", "tmmn", "pdsi", "sm", "vpd", "ro"], "res": "4km", "desc": "Monthly climate water balance, Palmer Drought Severity Index, and runoff."},
            {"id": "ECMWF/ERA5_LAND/HOURLY", "name": "ERA5-Land Hourly Climate Reanalysis", "category": "weather", "bands": ["temperature_2m", "total_precipitation", "u_component_of_wind_10m", "v_component_of_wind_10m"], "res": "9km", "desc": "Hourly gridded atmospheric weather and land surface temperature."},
            {"id": "UCSB-CHG/CHIRPS/PENTAD", "name": "CHIRPS Precipitation Pentad", "category": "climate", "bands": ["precipitation"], "res": "5.5km", "desc": "Quasi-global high-resolution precipitation estimates."},
            # Atmospheric
            {"id": "COPERNICUS/S5P/NRTI/L3_NO2", "name": "Sentinel-5P TROPOMI NO2", "category": "atmospheric", "bands": ["tropospheric_NO2_column_number_density"], "res": "3.5km", "desc": "Tropospheric nitrogen dioxide air pollution monitoring."},
            {"id": "COPERNICUS/S5P/NRTI/L3_CO", "name": "Sentinel-5P TROPOMI Carbon Monoxide", "category": "atmospheric", "bands": ["CO_column_number_density"], "res": "5.5km", "desc": "Total carbon monoxide atmospheric column."},
            {"id": "COPERNICUS/S5P/NRTI/L3_SO2", "name": "Sentinel-5P TROPOMI Sulfur Dioxide", "category": "atmospheric", "bands": ["SO2_column_number_density"], "res": "3.5km", "desc": "Sulfur dioxide emissions from industry and volcanism."},
            {"id": "COPERNICUS/S5P/NRTI/L3_AER_AI", "name": "Sentinel-5P Absorbing Aerosol Index", "category": "atmospheric", "bands": ["absorbing_aerosol_index"], "res": "3.5km", "desc": "Atmospheric dust, smoke, smog, and particulate loading."},
            # Landsat & Sentinel
            {"id": "COPERNICUS/S2_SR_HARMONIZED", "name": "Sentinel-2 Surface Reflectance Harmonized", "category": "sentinel", "bands": ["B2", "B3", "B4", "B8", "B11", "B12"], "res": "10m-20m", "desc": "Harmonized 10m multispectral optical imagery for land and vegetation."},
            {"id": "COPERNICUS/S1_GRD", "name": "Sentinel-1 SAR C-Band Synthetic Aperture Radar", "category": "sentinel", "bands": ["VV", "VH"], "res": "10m", "desc": "All-weather day/night radar backscatter for flood mapping and terrain structure."},
            # High Resolution Aerial
            {"id": "USDA/NAIP/DOQQ", "name": "USDA National Agriculture Imagery Program (NAIP)", "category": "high_resolution", "bands": ["R", "G", "B", "N"], "res": "0.6m - 1m", "desc": "Sub-meter aerial digital ortho photography covering the US."},
            # MODIS
            {"id": "MODIS/061/MOD13Q1", "name": "MODIS Terra Vegetation Indices 16-Day", "category": "modis", "bands": ["NDVI", "EVI"], "res": "250m", "desc": "Global Normalized Difference Vegetation Index and Enhanced Vegetation Index."},
            {"id": "MODIS/061/MOD14A1", "name": "MODIS Thermal Anomalies & Fire Daily", "category": "modis", "bands": ["FireMask"], "res": "1km", "desc": "Daily active fire hotspots and thermal anomalies."},
            # Terrain
            {"id": "USGS/SRTMGL1_003", "name": "NASA Shuttle Radar Topography Mission (SRTM)", "category": "terrain", "bands": ["elevation"], "res": "30m", "desc": "Global digital elevation model between 60°N and 56°S."},
            {"id": "COPERNICUS/DEM/GLO30", "name": "Copernicus DEM Global 30m", "category": "terrain", "bands": ["DEM"], "res": "30m", "desc": "High-accuracy global 30m digital elevation model from WorldDEM."},
            # Land Cover
            {"id": "GOOGLE/DYNAMICWORLD/V1", "name": "Google Dynamic World Land Cover V1", "category": "landcover", "bands": ["label", "water", "trees", "built", "crops"], "res": "10m", "desc": "Near real-time 9-class global land cover from Sentinel-2."},
            {"id": "ESA/WorldCover/v200/2021", "name": "ESA WorldCover 10m 2021", "category": "landcover", "bands": ["Map"], "res": "10m", "desc": "Global 11-class land cover map produced by ESA."},
            # Agriculture
            {"id": "USDA/NASS/CDL", "name": "USDA NASS Cropland Data Layer", "category": "agriculture", "bands": ["cropland"], "res": "30m", "desc": "Crop-specific land cover classification across the US."},
            {"id": "NASA_USDA/HSL/SMAP10KM_soil_moisture", "name": "NASA-USDA SMAP Global Soil Moisture", "category": "agriculture", "bands": ["ssm", "susm"], "res": "10km", "desc": "Surface and subsurface soil moisture estimates."},
            # Geophysical
            {"id": "JRC/GSW1_4/GlobalSurfaceWater", "name": "JRC Global Surface Water Occurrence", "category": "geophysical", "bands": ["occurrence", "seasonality", "change_abs"], "res": "30m", "desc": "Decadal changes in global surface water occurrence and recurrence."},
            {"id": "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG", "name": "VIIRS Nighttime Day/Night Band", "category": "geophysical", "bands": ["avg_rad"], "res": "500m", "desc": "Monthly nighttime visible light luminosity from settlements."},
            {"id": "UMD/hansen/global_forest_change_2024_v1_12", "name": "Hansen Global Forest Change", "category": "geophysical", "bands": ["treecover2000", "loss", "gain"], "res": "30m", "desc": "Global forest extent, loss, and gain from 2000 to 2024."},
        ]

        matches = []
        for item in _CATALOG:
            if category and item["category"] != category:
                continue
            if query:
                haystack = f"{item['id']} {item['name']} {item['category']} {item['desc']}".lower()
                if query not in haystack:
                    continue
            matches.append(item)

        return {
            "status": "success",
            "query": query,
            "category": category or "all",
            "count": len(matches),
            "datasets": matches,
        }

    # ── 15. Generalized Zonal Statistics ──────────────────────────────────────

    async def _get_gee_zonal_stats(self, args: dict) -> dict:
        dataset = (args.get("dataset") or "").strip()
        band = (args.get("band") or "").strip()
        geojson_input = args.get("geojson")
        lat = args.get("lat")
        lng = args.get("lng")
        radius_km = float(args.get("radius_km") or 5.0)
        year = int(args.get("year") or 2023)
        workspace = args.get("_workspace")

        if not dataset:
            return {"error": "dataset parameter is required"}

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            default_vis, is_collection = _get_dataset_defaults(dataset)

            def run_stats():
                stats_geom = ee_geom
                if stats_geom is None:
                    if geojson_input:
                        stats_geom = ee.Geometry(geojson_input.get("geometry", geojson_input))
                    elif lat is not None and lng is not None:
                        stats_geom = ee.Geometry.Point([float(lng), float(lat)]).buffer(radius_km * 1000.0)
                    else:
                        stats_geom = ee.Geometry.Point([76.7794, 30.7333]).buffer(5000)

                if is_collection:
                    coll = ee.ImageCollection(dataset).filterDate(f"{year}-01-01", f"{year}-12-31")
                    if stats_geom is not None:
                        try:
                            coll = coll.filterBounds(stats_geom)
                        except Exception:
                            pass
                    img = coll.median()
                else:
                    img = ee.Image(dataset)

                target_img = img.select(band) if band else img

                stats = target_img.reduceRegion(
                    reducer=ee.Reducer.mean().combine(
                        ee.Reducer.minMax(), sharedInputs=True
                    ).combine(
                        ee.Reducer.stdDev(), sharedInputs=True
                    ),
                    geometry=stats_geom,
                    scale=100,
                    maxPixels=1e9,
                ).getInfo()

                return stats

            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, run_stats)

            return {
                "status": "success",
                "dataset": dataset,
                "band": band or "all",
                "year": year,
                "statistics": res,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": f"Zonal statistics for '{dataset}' calculated successfully" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Zonal stats failed: {exc}", "code": "gee_error"}

    # ── 16. Existing Tools Preserved ──────────────────────────────────────────

    @staticmethod
    def _infer_country_iso(args: dict, place_name: str, lat: float | None, lng: float | None) -> str:
        iso = (args.get("country_iso") or args.get("country_code") or "").upper().strip()
        if len(iso) == 3:
            return iso
        if len(iso) == 2:
            mapping = {
                "IN": "IND", "US": "USA", "GB": "GBR", "UK": "GBR", "CA": "CAN",
                "AU": "AUS", "DE": "DEU", "FR": "FRA", "JP": "JPN", "CN": "CHN",
                "BR": "BRA", "ZA": "ZAF", "IT": "ITA", "ES": "ESP", "MX": "MEX",
            }
            if iso in mapping:
                return mapping[iso]

        if lat is None or lng is None:
            map_ctx = args.get("_map_context")
            if isinstance(map_ctx, dict):
                center = map_ctx.get("center")
                if isinstance(center, (list, tuple)) and len(center) >= 2:
                    lng, lat = float(center[0]), float(center[1])

        if lat is not None and lng is not None:
            try:
                lat = float(lat)
                lng = float(lng)
                if 6.0 <= lat <= 38.0 and 68.0 <= lng <= 98.0:
                    return "IND"
                if 24.0 <= lat <= 50.0 and -125.0 <= lng <= -65.0:
                    return "USA"
                if 49.0 <= lat <= 61.0 and -8.0 <= lng <= 2.0:
                    return "GBR"
                if 42.0 <= lat <= 83.0 and -141.0 <= lng <= -52.0:
                    return "CAN"
                if -44.0 <= lat <= -10.0 and 112.0 <= lng <= 154.0:
                    return "AUS"
            except (ValueError, TypeError):
                pass

        p_lower = place_name.lower()
        if any(k in p_lower for k in ("india", "chandigarh", "delhi", "mumbai", "bengaluru", "bangalore", "punjab", "haryana", "kolkata", "chennai")):
            return "IND"
        if any(k in p_lower for k in ("usa", "united states", "new york", "california", "texas", "chicago", "los angeles")):
            return "USA"
        if any(k in p_lower for k in ("uk", "united kingdom", "london", "england", "scotland")):
            return "GBR"
        return ""

    async def _get_population_layer(self, args: dict) -> dict:
        source = args.get("source", "worldpop").strip().lower()
        year = int(args.get("year") or 2020)
        country_iso = (args.get("country_iso") or "").upper().strip()
        lat = args.get("lat")
        lng = args.get("lng")
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)

        if not country_iso:
            country_iso = self._infer_country_iso(args, place_nm or "", lat, lng)

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            vis = {
                "min": 1,
                "max": 100,
                "palette": ["fef0d9", "fdcc8a", "fc8d59", "e34a33", "b30000", "7a0177"],
                "palette_labels": ["1 (Rural)", "20", "40", "60", "80", "100+ (High Density)"],
            }

            def build_pop():
                palette = ["fef0d9", "fdcc8a", "fc8d59", "e34a33", "b30000", "7a0177"]
                if source == "worldpop":
                    yr = min(max(year, 2000), 2020)
                    coll = ee.ImageCollection("WorldPop/GP/100m/pop").filter(ee.Filter.eq("year", yr))
                    if country_iso:
                        coll = coll.filter(ee.Filter.eq("country", country_iso))
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    raw_img = coll.mosaic()
                    colored = raw_img.visualize(min=1, max=100, palette=palette)
                    # Mask out zeros / unpopulated agricultural lands so basemap shows through cleanly
                    return colored.updateMask(raw_img.gt(0.5))
                else:
                    valid_years = [2000, 2005, 2010, 2015, 2020]
                    yr = min(valid_years, key=lambda y: abs(y - year))
                    coll = ee.ImageCollection("CIESIN/GPWv411/GPW_Population_Density").filterDate(f"{yr}-01-01", f"{yr}-12-31")
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    raw_img = coll.first()
                    colored = raw_img.visualize(min=5, max=500, palette=palette)
                    return colored.updateMask(raw_img.gt(1.0))

            layer_title = title or (f"Population Density – {place_nm} ({year})" if place_nm else f"Population Density ({source.title()} {year})")
            if place_nm and place_nm.lower() not in layer_title.lower():
                layer_title = f"{layer_title} - {place_nm}"
            dataset_id = "WorldPop/GP/100m/pop" if source == "worldpop" else "CIESIN/GPWv411/GPW_Population_Density"
            map_id, tile_url = await self._tile_proxy(build_pop, {}, ee_geom)
            await self._send_layer(ws, tile_url, dataset_id, vis, layer_title)

            return {
                "status": "success",
                "source": source,
                "year": year,
                "country_iso": country_iso or "global",
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "message": f"Population density layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Population layer failed: {exc}", "code": "gee_error"}

    async def _analyze_lulc_change(self, args: dict) -> dict:
        year_start = int(args.get("year_start", 2018))
        year_end = int(args.get("year_end", 2023))
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        if year_start >= year_end:
            return {"error": "year_start must be less than year_end"}

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        if not title:
            title = f"LULC Change {year_start}→{year_end}" + (f" - {place_nm}" if place_nm else "")
        elif place_nm and place_nm.lower() not in title.lower():
            title = f"{title} - {place_nm}"

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
                c_start = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterDate(f"{year_start}-01-01", f"{year_start}-12-31")
                c_end = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterDate(f"{year_end}-01-01", f"{year_end}-12-31")
                if ee_geom is not None:
                    try:
                        c_start = c_start.filterBounds(ee_geom)
                        c_end = c_end.filterBounds(ee_geom)
                    except Exception:
                        pass
                lc_start = c_start.select("label").mode()
                lc_end = c_end.select("label").mode()
                return lc_start.neq(lc_end).rename("changed")

            def build_transition():
                c_start = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterDate(f"{year_start}-01-01", f"{year_start}-12-31")
                c_end = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterDate(f"{year_end}-01-01", f"{year_end}-12-31")
                if ee_geom is not None:
                    try:
                        c_start = c_start.filterBounds(ee_geom)
                        c_end = c_end.filterBounds(ee_geom)
                    except Exception:
                        pass
                lc_start = c_start.select("label").mode()
                lc_end = c_end.select("label").mode()
                changed = lc_start.neq(lc_end)
                return lc_start.multiply(10).add(lc_end).updateMask(changed)

            loop = asyncio.get_event_loop()
            _, changed_url = await loop.run_in_executor(None, _sync_get_map_id, build_changed, changed_vis, ee_geom)
            _, transition_url = await loop.run_in_executor(None, _sync_get_map_id, build_transition, transition_vis, ee_geom)

            changed_title = f"Changed Areas {year_start}→{year_end}" + (f" - {place_nm}" if place_nm else "")
            await self._send_layer(ws, changed_url, "GOOGLE/DYNAMICWORLD/V1", changed_vis, changed_title)
            await self._send_layer(ws, transition_url, "GOOGLE/DYNAMICWORLD/V1", transition_vis, title)

            return {
                "status": "success",
                "year_start": year_start,
                "year_end": year_end,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "layers_added": 2,
                "tile_url": transition_url,
                "message": f"LULC change layers added" + (f" for {place_nm}:" if place_nm else ":") + f" (1) changed mask, (2) class transition map {year_start}→{year_end}.",
            }

        except Exception as exc:
            return {"error": f"LULC change analysis failed: {exc}", "code": "gee_error"}

    async def _get_ndvi_layer(self, args: dict) -> dict:
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        if not title:
            title = f"NDVI {year}" + (f" - {place_nm}" if place_nm else "")
        elif place_nm and place_nm.lower() not in title.lower():
            title = f"{title} - {place_nm}"

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            ndvi_palette = ["8B4513", "D2691E", "F4A460", "FFFF00", "9ACD32", "228B22", "006400"]
            vis = {"min": -0.1, "max": 0.8, "palette": ndvi_palette}

            def build_ndvi():
                s2 = (
                    ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 10))
                )
                if ee_geom is not None:
                    try:
                        s2 = s2.filterBounds(ee_geom)
                    except Exception:
                        pass
                s2 = s2.select(["B8", "B4"]).median()
                return s2.normalizedDifference(["B8", "B4"]).rename("NDVI")

            map_id, tile_url = await self._tile_proxy(build_ndvi, vis, ee_geom)
            await self._send_layer(ws, tile_url, "COPERNICUS/S2_SR_HARMONIZED", vis, title)

            return {
                "status": "success",
                "year": year,
                "index": "NDVI",
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": "COPERNICUS/S2_SR_HARMONIZED",
                "vis": vis,
                "layer_title": title,
                "interpretation": {
                    "< 0.1": "Built-up / bare land / water",
                    "0.1 – 0.3": "Sparse vegetation / degraded land",
                    "0.3 – 0.5": "Moderate vegetation (agriculture, parks)",
                    "> 0.5": "Dense vegetation / forest",
                },
                "message": f"NDVI layer '{title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"NDVI computation failed: {exc}", "code": "gee_error"}

    async def _get_gee_layer(self, args: dict) -> dict:
        """Backward-compat: sample point values and return tile layer."""
        dataset = args.get("dataset", "").strip()
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        if not dataset:
            return {"error": "dataset is required"}

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            default_vis, is_collection = _get_dataset_defaults(dataset)

            def build_and_sample():
                if is_collection:
                    coll = ee.ImageCollection(dataset)
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    elif lat != 0 or lng != 0:
                        coll = coll.filterBounds(ee.Geometry.Point([lng, lat]))
                    img = coll.median()
                else:
                    img = ee.Image(dataset)

                map_id, tile_url = _sync_get_map_id(lambda: img, default_vis, ee_geom)

                sample = {}
                if lat != 0 or lng != 0:
                    point = ee.Geometry.Point([lng, lat])
                    try:
                        sample = img.sample(point, 30).first().toDictionary().getInfo()
                    except Exception:
                        sample = {}

                return map_id, tile_url, sample

            loop = asyncio.get_event_loop()
            map_id, tile_url, sample = await loop.run_in_executor(None, build_and_sample)

            title = f"{dataset.split('/')[-1]}" + (f" - {place_nm}" if place_nm else " — pixel sample")
            await self._send_layer(ws, tile_url, dataset, default_vis, title)

            return {
                "status": "success",
                "dataset": dataset,
                "pixel_values": sample,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "tile_url": tile_url,
                "map_id": map_id,
                "vis": default_vis,
                "layer_title": title,
                "message": f"Layer '{title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"GEE execution failed: {exc}", "code": "gee_error"}

    async def _analyze_land_use_zonal_stats(self, args: dict) -> dict:
        geojson_input = args.get("geojson")
        lat = args.get("lat")
        lng = args.get("lng")
        radius_km = float(args.get("radius_km") or 5.0)
        year = int(args.get("year") or 2023)
        workspace = args.get("_workspace")

        b_geojson, resolved_ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)

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
            return {
                "status": "partial_fallback",
                "message": f"GEE credentials not active ({err}). Displaying standard Dynamic World class schema for {year}.",
                "classes": {str(i): {"name": name, "color": color} for i, (name, color) in enumerate(zip(dw_classes, dw_colors))},
                "place_name": place_nm,
                "note": "Configure GEE credentials in workspace root (ee-service-account.json) for live pixel-reduction zonal stats."
            }

        try:
            import ee

            def run_zonal():
                ee_geom = resolved_ee_geom
                if ee_geom is None:
                    if geojson_input:
                        ee_geom = _geojson_to_ee_geometry(geojson_input)
                    elif lat is not None and lng is not None:
                        ee_geom = ee.Geometry.Point([float(lng), float(lat)]).buffer(radius_km * 1000.0)
                    else:
                        ee_geom = ee.Geometry.Point([76.7794, 30.7333]).buffer(5000)

                coll = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterDate(f"{year}-01-01", f"{year}-12-31")
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                img = coll.select("label").mode()

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
                "place_name": place_nm,
                "clipped_to_boundary": bool(resolved_ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "message": (
                    f"Zonal land-use analysis complete for {year}" + (f" ({place_nm})" if place_nm else "") + ". "
                    f"Total Area: {res['total_area_km2']} km². Dominant Land Use: {res['dominant_land_use']}."
                ),
            }

        except Exception as exc:
            return {"error": f"Zonal land use analysis failed: {exc}", "code": "gee_error"}

    async def _extract_land_use_polygons(self, args: dict) -> dict:
        target_input = str(args.get("target_class", "Built Area")).strip().lower()
        geojson_input = args.get("geojson")
        place_name = (
            args.get("place_name")
            or args.get("city")
            or args.get("location")
            or args.get("study_area")
            or args.get("boundary_name")
            or args.get("boundary")
            or args.get("place")
            or args.get("name")
            or ""
        ).strip()
        custom_color = args.get("color")
        lat = args.get("lat")
        lng = args.get("lng")
        radius_km = float(args.get("radius_km") or 5.0)
        year = int(args.get("year") or 2023)
        ws = args.get("_ws")
        workspace = args.get("_workspace")

        b_geojson, resolved_ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        if b_geojson and not geojson_input:
            geojson_input = b_geojson
        if place_nm and not place_name:
            place_name = place_nm

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

        target_idx = 6  # default Built Area
        if target_input.isdigit():
            target_idx = int(target_input)
        else:
            for i, name in enumerate(dw_classes):
                if target_input in name or name in target_input:
                    target_idx = i
                    break

        class_name = dw_display_names[target_idx] if 0 <= target_idx < len(dw_display_names) else "Built Area"

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

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": f"GEE credentials required to extract vector polygons: {err}", "code": "upstream_unavailable"}

        try:
            import ee

            def run_vectorize():
                ee_geom = resolved_ee_geom
                if ee_geom is None:
                    if geojson_input:
                        ee_geom = _geojson_to_ee_geometry(geojson_input)
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

                masked = img.eq(target_idx).selfMask()

                def extract_geom(g):
                    vectors = masked.reduceToVectors(
                        geometry=g,
                        scale=30,
                        maxPixels=1e9,
                        geometryType="polygon",
                        labelProperty="class_id",
                    )
                    return vectors.getInfo()

                try:
                    return extract_geom(ee_geom)
                except Exception as e:
                    err_str = str(e).lower()
                    if "5000" in err_str or "limit" in err_str or "aborted" in err_str or "memory" in err_str:
                        logger.info("Extraction exceeded limit. Splitting geometry into sub-quadrants...")

                        def split_and_extract(geom, depth=0):
                            if depth > 2:
                                raise Exception("Max recursion depth reached: region is too complex.")

                            bounds = geom.bounds().getInfo()["coordinates"][0]
                            lons = [pt[0] for pt in bounds]
                            lats = [pt[1] for pt in bounds]
                            w, e_lon = min(lons), max(lons)
                            s, n_lat = min(lats), max(lats)
                            mid_lon = (w + e_lon) / 2.0
                            mid_lat = (s + n_lat) / 2.0

                            quads = [
                                ee.Geometry.Rectangle([w, s, mid_lon, mid_lat]),
                                ee.Geometry.Rectangle([mid_lon, s, e_lon, mid_lat]),
                                ee.Geometry.Rectangle([w, mid_lat, mid_lon, n_lat]),
                                ee.Geometry.Rectangle([mid_lon, mid_lat, e_lon, n_lat]),
                            ]

                            feats = []
                            for q in quads:
                                inter = geom.intersection(q, 10)
                                if inter.area().getInfo() > 0:
                                    try:
                                        fc = extract_geom(inter)
                                        feats.extend(fc.get("features", []))
                                    except Exception as qe:
                                        err_msg = str(qe).lower()
                                        if "5000" in err_msg or "limit" in err_msg or "aborted" in err_msg or "memory" in err_msg:
                                            feats.extend(split_and_extract(inter, depth + 1))
                                        else:
                                            logger.warning(f"Quadrant extraction failed: {qe}")
                            return feats

                        all_features = split_and_extract(ee_geom)
                        if not all_features:
                            raise Exception("Vector extraction failed: Region is too large or too dense.")
                        return {"type": "FeatureCollection", "features": all_features}
                    else:
                        raise

            loop = asyncio.get_event_loop()
            fc_data = await loop.run_in_executor(None, run_vectorize)

            features = fc_data.get("features", [])

            if geom_data:
                try:
                    import shapely.geometry
                    b_shape = shapely.geometry.shape(geom_data)
                    clipped_features = []
                    for feat in features:
                        f_geom = feat.get("geometry")
                        if not f_geom:
                            continue
                        f_shape = shapely.geometry.shape(f_geom)
                        if b_shape.intersects(f_shape):
                            inter = b_shape.intersection(f_shape)
                            if not inter.is_empty:
                                feat["geometry"] = shapely.geometry.mapping(inter)
                                clipped_features.append(feat)
                    features = clipped_features
                except Exception as clip_err:
                    logger.warning(f"Spatial clipping of land cover polygons failed: {clip_err}")

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
                "geojson_file": str(out_path) if workspace else None,
                "layer_name": display_title,
                "message": (
                    f"Extracted {len(features)} {class_name} vector polygons for {place_name or year} in {class_color} and loaded on map."
                ),
            }

        except Exception as exc:
            return {"error": f"Vector polygon extraction failed: {exc}", "code": "gee_error"}
