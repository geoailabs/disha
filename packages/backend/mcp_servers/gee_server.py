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

_MODIS_IGBP_PALETTE = [
    "05450a", "086a10", "54a708", "78d203", "009900", "c6b044", "dcd159",
    "dade48", "fbff13", "b6ff05", "27ff87", "c24f44", "a5a5a5", "ff6d4c",
    "69fff8", "f9ffa4", "1c0dff",
]
_MODIS_IGBP_LABELS = [
    "Evergreen Needleleaf Forest", "Evergreen Broadleaf Forest", "Deciduous Needleleaf Forest",
    "Deciduous Broadleaf Forest", "Mixed Forests", "Closed Shrublands", "Open Shrublands",
    "Woody Savannas", "Savannas", "Grasslands", "Permanent Wetlands", "Croplands",
    "Urban and Built-up Lands", "Cropland/Natural Vegetation Mosaics", "Permanent Snow and Ice",
    "Barren", "Water Bodies",
]

class BoundaryUnresolved(ValueError):
    """A named place could not be resolved to an areal (polygon) boundary."""


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
    env = os.environ.get("GOOGLE_EARTH_ENGINE_CREDS") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if env and parse_gee_credentials_data(env):
        return env

    search_roots: list[Path] = []
    # 0. User home directory
    home_file = Path.home() / ".disha" / "ee-service-account.json"
    if home_file.exists() and parse_gee_credentials_data(home_file):
        return str(home_file)

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


def _simplify_geom_if_needed(geom: dict, max_coords: int = 20000) -> dict:
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
            simplified = s.simplify(0.0001, preserve_topology=True)
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
        global _EE_READY
        if not _EE_READY:
            creds = _find_gee_creds()
            if creds:
                _sync_init_gee(creds)

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
            if ee_geom is not None:
                try:
                    vis_img = vis_img.clip(ee_geom)
                except Exception:
                    pass
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
        return {
            "bands": ["LC_Type1"],
            "min": 1,
            "max": 17,
            "palette": _MODIS_IGBP_PALETTE,
            "palette_labels": _MODIS_IGBP_LABELS,
        }, True

    # 5. Population (ImageCollections: WorldPop, GHSL GHS-POP, GPWv4, LandScan)
    if "worldpop" in d or "landscan" in d or "gpw" in d or "ghs_pop" in d or "ghsl" in d:
        return {"min": 0, "max": 500, "palette": ["ffffe5", "f7fcb9", "addd8e", "31a354", "006837", "ff0000"]}, True

    # 6. MODIS collections (generic fallback for any MODIS asset ID)
    if "modis" in d or any(token in d for token in [
        "mod09a1", "mod10a1", "mod11a1", "myd11a1", "mcd12q1", "mod13q1", "mod14a1",
        "mcd64a1", "mod16a2", "mcd19a2", "mod15a2h", "mod17a2h", "mod21a2", "mod21a2d"
    ]):
        if "mod13q1" in d:
            return {"bands": ["NDVI"], "min": 0, "max": 8000, "palette": ["ffffff", "ce7e45", "df923d", "f1b555", "fcd163", "99b718", "74a901", "66a000", "529400", "3e8601", "207401", "056201", "004c00"]}, True
        if "mod14a1" in d:
            return {"bands": ["FireMask"], "min": 0, "max": 7, "palette": ["000000", "ffff00", "ff0000"]}, True
        if "mod09a1" in d:
            return {"bands": ["sur_refl_b01", "sur_refl_b04", "sur_refl_b03"], "min": -100, "max": 8000}, True
        if "mcd64a1" in d:
            return {"bands": ["BurnDate"], "min": 1, "max": 366, "palette": ["ffff00", "ff7700", "ff0000"]}, True
        if "mod16a2" in d:
            return {"bands": ["ET_500m"], "min": 0, "max": 400, "palette": ["f7fcf0", "bae4bc", "7bccc4", "2b8cbe", "084081"]}, True
        if "mcd19a2" in d:
            return {"bands": ["Optical_Depth_047"], "min": 0, "max": 1.0, "palette": ["000000", "00ff00", "ffff00", "ff0000"]}, True
        if "mod10a1" in d:
            return {"bands": ["NDSI_Snow_Cover"], "min": 0, "max": 100, "palette": ["000000", "00ffff", "ffffff"]}, True
        if "mcd12q1" in d:
            return {
                "bands": ["LC_Type1"],
                "min": 1,
                "max": 17,
                "palette": _MODIS_IGBP_PALETTE,
                "palette_labels": _MODIS_IGBP_LABELS,
            }, True
        return {"bands": ["NDVI"], "min": 0, "max": 8000, "palette": ["ffffff", "ce7e45", "df923d", "f1b555", "fcd163", "99b718", "74a901", "66a000", "529400", "3e8601", "207401", "056201", "004c00"]}, True

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


# ── Full Earth Engine Data Catalog (search + asset introspection) ────────────
#
# The public Earth Engine catalog has ~900+ datasets. Instead of hard-coding a
# handful, we load a machine-readable index of the whole catalog (cached on disk
# for a week) and fall back to the curated list below when offline. Any dataset
# ID found this way can be rendered by `add_gee_layer`, which introspects the
# asset type (Image / ImageCollection / FeatureCollection table) at runtime.

_GEE_CATALOG_URL = (
    "https://raw.githubusercontent.com/samapriya/Earth-Engine-Datasets-List/master/gee_catalog.json"
)
_GEE_CATALOG_TTL_S = 7 * 24 * 3600
_HYDRO_RIVERS_ID = "WWF/HydroSHEDS/v1/FreeFlowingRivers"
_MERIT_HYDRO_ID = "MERIT/Hydro/v1_0_1"
_GEE_CATALOG_CACHE: list[dict] | None = None
_ASSET_INFO_CACHE: dict[str, dict] = {}

# Curated, always-available entries (also used as an offline fallback).
_CURATED_CATALOG: list[dict] = [
    {"id": "LANDSAT/LC09/C02/T1_L2", "title": "Landsat 9 Collection 2 Level 2", "category": "surface_temperature", "type": "image_collection", "tags": "landsat, thermal, surface temperature, reflectance", "bands": ["SR_B4", "SR_B3", "SR_B2", "ST_B10"], "res": "30m", "desc": "High-res optical surface reflectance and thermal surface temperature (ST_B10)."},
    {"id": "MODIS/061/MOD11A1", "title": "MODIS Terra Land Surface Temperature Daily", "category": "surface_temperature", "type": "image_collection", "tags": "modis, lst, temperature", "bands": ["LST_Day_1km", "LST_Night_1km"], "res": "1km", "desc": "Daily global land surface temperature in Kelvin (scale 0.02)."},
    {"id": "IDAHO_EPSCOR/TERRACLIMATE", "title": "TerraClimate Monthly Water Balance", "category": "climate", "type": "image_collection", "tags": "climate, drought, precipitation, runoff", "bands": ["pr", "tmmx", "tmmn", "pdsi", "sm", "vpd", "ro"], "res": "4km", "desc": "Monthly climate water balance, Palmer Drought Severity Index, and runoff."},
    {"id": "ECMWF/ERA5_LAND/HOURLY", "title": "ERA5-Land Hourly Climate Reanalysis", "category": "weather", "type": "image_collection", "tags": "weather, temperature, wind, precipitation", "bands": ["temperature_2m", "total_precipitation", "u_component_of_wind_10m", "v_component_of_wind_10m"], "res": "9km", "desc": "Hourly gridded atmospheric weather and land surface temperature."},
    {"id": "UCSB-CHG/CHIRPS/PENTAD", "title": "CHIRPS Precipitation Pentad", "category": "climate", "type": "image_collection", "tags": "rainfall, precipitation", "bands": ["precipitation"], "res": "5.5km", "desc": "Quasi-global high-resolution precipitation estimates."},
    {"id": "COPERNICUS/S5P/NRTI/L3_NO2", "title": "Sentinel-5P TROPOMI NO2", "category": "atmospheric", "type": "image_collection", "tags": "air quality, pollution, no2", "bands": ["tropospheric_NO2_column_number_density"], "res": "3.5km", "desc": "Tropospheric nitrogen dioxide air pollution monitoring."},
    {"id": "COPERNICUS/S5P/NRTI/L3_CO", "title": "Sentinel-5P TROPOMI Carbon Monoxide", "category": "atmospheric", "type": "image_collection", "tags": "air quality, pollution, co", "bands": ["CO_column_number_density"], "res": "5.5km", "desc": "Total carbon monoxide atmospheric column."},
    {"id": "COPERNICUS/S5P/NRTI/L3_SO2", "title": "Sentinel-5P TROPOMI Sulfur Dioxide", "category": "atmospheric", "type": "image_collection", "tags": "air quality, pollution, so2", "bands": ["SO2_column_number_density"], "res": "3.5km", "desc": "Sulfur dioxide emissions from industry and volcanism."},
    {"id": "COPERNICUS/S5P/NRTI/L3_AER_AI", "title": "Sentinel-5P Absorbing Aerosol Index", "category": "atmospheric", "type": "image_collection", "tags": "aerosol, dust, smoke", "bands": ["absorbing_aerosol_index"], "res": "3.5km", "desc": "Atmospheric dust, smoke, smog, and particulate loading."},
    {"id": "COPERNICUS/S2_SR_HARMONIZED", "title": "Sentinel-2 Surface Reflectance Harmonized", "category": "sentinel", "type": "image_collection", "tags": "sentinel, optical, multispectral", "bands": ["B2", "B3", "B4", "B8", "B11", "B12"], "res": "10m-20m", "desc": "Harmonized 10m multispectral optical imagery for land and vegetation."},
    {"id": "COPERNICUS/S1_GRD", "title": "Sentinel-1 SAR C-Band Synthetic Aperture Radar", "category": "sentinel", "type": "image_collection", "tags": "radar, sar, flood", "bands": ["VV", "VH"], "res": "10m", "desc": "All-weather day/night radar backscatter for flood mapping and terrain structure."},
    {"id": "USDA/NAIP/DOQQ", "title": "USDA National Agriculture Imagery Program (NAIP)", "category": "high_resolution", "type": "image_collection", "tags": "aerial, orthophoto", "bands": ["R", "G", "B", "N"], "res": "0.6m - 1m", "desc": "Sub-meter aerial digital ortho photography covering the US."},
    {"id": "MODIS/061/MOD09A1", "title": "MODIS Surface Reflectance 8-Day", "category": "modis", "type": "image_collection", "tags": "modis, reflectance", "bands": ["sur_refl_b01", "sur_refl_b04", "sur_refl_b03"], "res": "500m", "desc": "Surface reflectance imagery suitable for vegetation, burn scars, and land surface monitoring."},
    {"id": "MODIS/061/MOD10A1", "title": "MODIS Snow Cover Daily", "category": "modis", "type": "image_collection", "tags": "modis, snow", "bands": ["NDSI_Snow_Cover"], "res": "500m", "desc": "Daily snow extent and snow cover fraction."},
    {"id": "MODIS/061/MCD12Q1", "title": "MODIS Land Cover Type Yearly", "category": "modis", "type": "image_collection", "tags": "modis, landcover", "bands": ["LC_Type1"], "res": "500m", "desc": "Annual IGBP land cover classes globally."},
    {"id": "MODIS/061/MOD13Q1", "title": "MODIS Terra Vegetation Indices 16-Day", "category": "modis", "type": "image_collection", "tags": "modis, ndvi, evi, vegetation", "bands": ["NDVI", "EVI"], "res": "250m", "desc": "Global Normalized Difference Vegetation Index and Enhanced Vegetation Index."},
    {"id": "MODIS/061/MOD14A1", "title": "MODIS Thermal Anomalies & Fire Daily", "category": "modis", "type": "image_collection", "tags": "modis, fire", "bands": ["FireMask"], "res": "1km", "desc": "Daily active fire hotspots and thermal anomalies."},
    {"id": "MODIS/061/MCD64A1", "title": "MODIS Burned Area Monthly", "category": "modis", "type": "image_collection", "tags": "modis, fire, burn", "bands": ["BurnDate"], "res": "500m", "desc": "Monthly burned-area detection and burn date."},
    {"id": "MODIS/061/MOD16A2", "title": "MODIS Evapotranspiration 8-Day", "category": "modis", "type": "image_collection", "tags": "modis, evapotranspiration", "bands": ["ET_500m"], "res": "500m", "desc": "Evapotranspiration and water use estimates."},
    {"id": "USGS/SRTMGL1_003", "title": "NASA Shuttle Radar Topography Mission (SRTM)", "category": "terrain", "type": "image", "tags": "dem, elevation, topography", "bands": ["elevation"], "res": "30m", "desc": "Global digital elevation model between 60°N and 56°S."},
    {"id": "COPERNICUS/DEM/GLO30", "title": "Copernicus DEM Global 30m", "category": "terrain", "type": "image_collection", "tags": "dem, elevation", "bands": ["DEM"], "res": "30m", "desc": "High-accuracy global 30m digital elevation model from WorldDEM."},
    {"id": "GOOGLE/DYNAMICWORLD/V1", "title": "Google Dynamic World Land Cover V1", "category": "landcover", "type": "image_collection", "tags": "landcover, lulc, built, water, trees", "bands": ["label", "water", "trees", "built", "crops"], "res": "10m", "desc": "Near real-time 9-class global land cover from Sentinel-2."},
    {"id": "ESA/WorldCover/v200", "title": "ESA WorldCover 10m v200", "category": "landcover", "type": "image_collection", "tags": "landcover, lulc", "bands": ["Map"], "res": "10m", "desc": "Global 11-class land cover map produced by ESA."},
    {"id": "USDA/NASS/CDL", "title": "USDA NASS Cropland Data Layer", "category": "agriculture", "type": "image_collection", "tags": "crop, agriculture", "bands": ["cropland"], "res": "30m", "desc": "Crop-specific land cover classification across the US."},
    {"id": "NASA_USDA/HSL/SMAP10KM_soil_moisture", "title": "NASA-USDA SMAP Global Soil Moisture", "category": "agriculture", "type": "image_collection", "tags": "soil moisture", "bands": ["ssm", "susm"], "res": "10km", "desc": "Surface and subsurface soil moisture estimates."},
    {"id": "JRC/GSW1_4/GlobalSurfaceWater", "title": "JRC Global Surface Water Occurrence", "category": "geophysical", "type": "image", "tags": "water, surface water, lakes, rivers", "bands": ["occurrence", "seasonality", "change_abs"], "res": "30m", "desc": "Decadal changes in global surface water occurrence and recurrence."},
    {"id": "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG", "title": "VIIRS Nighttime Day/Night Band", "category": "geophysical", "type": "image_collection", "tags": "nighttime lights", "bands": ["avg_rad"], "res": "500m", "desc": "Monthly nighttime visible light luminosity from settlements."},
    {"id": "UMD/hansen/global_forest_change_2024_v1_12", "title": "Hansen Global Forest Change", "category": "geophysical", "type": "image", "tags": "forest, deforestation", "bands": ["treecover2000", "loss", "gain"], "res": "30m", "desc": "Global forest extent, loss, and gain from 2000 to 2024."},
    # Hydrography / drainage
    {"id": "WWF/HydroSHEDS/v1/FreeFlowingRivers", "title": "WWF HydroSHEDS Free Flowing Rivers Network", "category": "hydrology", "type": "table", "tags": "hydrology, river, stream, drainage, waterway, network, vector", "bands": [], "res": "15 arc-sec (~500m)", "desc": "Global vector river/stream network (line reaches) with river order, upstream area and discharge. Use extract_water_streams."},
    {"id": "MERIT/Hydro/v1_0_1", "title": "MERIT Hydro Global Hydrography", "category": "hydrology", "type": "image", "tags": "hydrology, river, stream, drainage, flow accumulation, river width, hand", "bands": ["elv", "dir", "wth", "wat", "upa", "upg", "hnd", "viswth"], "res": "90m", "desc": "Flow direction, upstream drainage area (upa), river width and HAND. Fine drainage channels via upa thresholds."},
    {"id": "WWF/HydroSHEDS/15ACC", "title": "WWF HydroSHEDS Flow Accumulation 15 arc-sec", "category": "hydrology", "type": "image", "tags": "hydrology, flow accumulation, drainage", "bands": ["b1"], "res": "500m", "desc": "Flow accumulation (number of upstream cells)."},
    {"id": "WWF/HydroSHEDS/v1/Basins/hybas_8", "title": "WWF HydroBASINS Level 8", "category": "hydrology", "type": "table", "tags": "hydrology, watershed, catchment, basin, vector", "bands": [], "res": "vector", "desc": "Nested watershed / sub-basin polygons."},
]

# Query synonyms so natural phrasing ("water streams") finds catalog entries.
_SEARCH_SYNONYMS: dict[str, list[str]] = {
    "stream": ["river", "drainage", "hydro", "waterway"],
    "streams": ["river", "drainage", "hydro", "waterway"],
    "river": ["stream", "hydro", "drainage"],
    "rivers": ["river", "stream", "hydro"],
    "drainage": ["river", "flow accumulation", "hydro"],
    "watershed": ["basin", "catchment", "hydro"],
    "catchment": ["basin", "watershed"],
    "rain": ["precipitation", "rainfall"],
    "rainfall": ["precipitation"],
    "elevation": ["dem", "topography", "terrain"],
    "terrain": ["dem", "elevation"],
    "lulc": ["landcover", "land cover"],
    "pollution": ["air quality", "no2", "aerosol"],
    "built": ["urban", "settlement", "building"],
    "urban": ["built", "settlement"],
    "buildings": ["building", "footprint"],
    "forest": ["tree", "canopy"],
    "lights": ["nighttime", "viirs"],
    "heat": ["temperature", "lst"],
    "flood": ["water", "inundation", "sar"],
    "soil": ["soil moisture", "soilgrids"],
    "population": ["worldpop", "gpw", "demography"],
}

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "surface_temperature": ["temperature", "lst", "thermal"],
    "climate": ["climate", "precipitation", "drought"],
    "atmospheric": ["air quality", "s5p", "pollution", "aerosol", "atmosphere"],
    "weather": ["weather", "era5", "wind"],
    "landsat": ["landsat"],
    "sentinel": ["sentinel", "copernicus"],
    "high_resolution": ["naip", "aerial", "high resolution"],
    "modis": ["modis"],
    "terrain": ["dem", "elevation", "topography", "terrain"],
    "landcover": ["landcover", "land cover", "lulc"],
    "agriculture": ["agriculture", "crop", "soil"],
    "geophysical": ["water", "nighttime", "forest", "fire"],
    "hydrology": ["hydrology", "river", "stream", "drainage", "watershed", "basin", "flow"],
}


def _catalog_cache_path() -> Path:
    return Path.home() / ".disha" / "gee_catalog_cache.json"


def _normalise_catalog_entry(raw: dict) -> dict | None:
    ds_id = (raw.get("id") or "").strip()
    if not ds_id:
        return None
    ds_type = (raw.get("type") or "").lower()
    if ds_type in ("folder", "bigquery_table"):
        return None
    return {
        "id": ds_id,
        "title": raw.get("title") or raw.get("name") or ds_id,
        "type": ds_type or "unknown",
        "tags": raw.get("tags") or "",
        "provider": raw.get("provider") or "",
        "start_date": raw.get("start_date") or "",
        "end_date": raw.get("end_date") or "",
        "catalog_url": raw.get("asset_url") or "",
        "category": raw.get("category") or "",
        "bands": raw.get("bands") or [],
        "res": raw.get("res") or "",
        "desc": raw.get("desc") or "",
    }


def _load_full_catalog() -> list[dict]:
    """Return the full Earth Engine catalog index (network → disk cache → curated)."""
    global _GEE_CATALOG_CACHE
    if _GEE_CATALOG_CACHE is not None:
        return _GEE_CATALOG_CACHE

    import time

    cache_file = _catalog_cache_path()
    raw_entries: list[dict] | None = None
    stale_entries: list[dict] | None = None

    try:
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, list) and cached:
                if time.time() - cache_file.stat().st_mtime < _GEE_CATALOG_TTL_S:
                    raw_entries = cached
                else:
                    stale_entries = cached
    except Exception as exc:
        logger.debug(f"GEE catalog cache unreadable: {exc}")

    if raw_entries is None and os.environ.get("DISHA_GEE_CATALOG_OFFLINE") != "1":
        try:
            import httpx
            resp = httpx.get(_GEE_CATALOG_URL, timeout=8.0, follow_redirects=True)
            resp.raise_for_status()
            fetched = resp.json()
            if isinstance(fetched, list) and fetched:
                raw_entries = fetched
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(fetched), encoding="utf-8")
                except Exception as exc:
                    logger.debug(f"Could not write GEE catalog cache: {exc}")
        except Exception as exc:
            logger.info(f"Full GEE catalog fetch failed, using cached/curated catalog: {exc}")

    if raw_entries is None:
        raw_entries = stale_entries or []

    merged: dict[str, dict] = {}
    for raw in raw_entries:
        entry = _normalise_catalog_entry(raw) if isinstance(raw, dict) else None
        if entry:
            merged[entry["id"]] = entry
    # Curated entries win: they carry band hints and planner-friendly descriptions.
    for raw in _CURATED_CATALOG:
        entry = _normalise_catalog_entry(raw)
        if entry:
            merged[entry["id"]] = {**merged.get(entry["id"], {}), **{k: v for k, v in entry.items() if v}}

    _GEE_CATALOG_CACHE = list(merged.values())
    return _GEE_CATALOG_CACHE


def _expand_query_terms(query: str) -> list[str]:
    import re
    terms = [t for t in re.split(r"[^a-z0-9_]+", query.lower()) if len(t) > 1]
    stop = {"the", "of", "in", "for", "and", "all", "map", "show", "plot", "data", "dataset", "layer", "on", "a", "an"}
    expanded: list[str] = []
    for t in terms:
        if t in stop:
            continue
        expanded.append(t)
        if t.endswith("s") and len(t) > 3:
            expanded.append(t[:-1])
        expanded.extend(_SEARCH_SYNONYMS.get(t, []))
    seen: set[str] = set()
    return [t for t in expanded if not (t in seen or seen.add(t))]


def _score_catalog_entry(entry: dict, query: str, terms: list[str]) -> float:
    title = entry.get("title", "").lower()
    tags = entry.get("tags", "").lower()
    ds_id = entry.get("id", "").lower()
    rest = f"{entry.get('desc', '')} {entry.get('provider', '')} {entry.get('category', '')}".lower()
    score = 0.0
    if query and (query in title or query in tags or query in ds_id):
        score += 10
    for t in terms:
        if t in tags:
            score += 3
        if t in title:
            score += 3
        if t in ds_id:
            score += 2
        if t in rest:
            score += 1
    # Prefer curated / non-deprecated entries
    if entry.get("desc"):
        score += 0.5
    if "deprecated" in title:
        score -= 5
    return score


def _layer_kind(ds_type: str) -> str:
    return "vector" if ds_type == "table" else "raster"


def _sync_get_asset_info(dataset: str) -> dict:
    """Return {'type': IMAGE|IMAGE_COLLECTION|TABLE, 'properties': {...}} for any EE asset."""
    if dataset in _ASSET_INFO_CACHE:
        return _ASSET_INFO_CACHE[dataset]
    import ee
    info: dict = {"type": None, "properties": {}}
    try:
        asset = ee.data.getAsset(dataset)
        info["type"] = (asset.get("type") or "").upper() or None
        info["properties"] = asset.get("properties") or {}
    except Exception as exc:
        logger.debug(f"ee.data.getAsset failed for {dataset}: {exc}")
        # Fall back to probing the object types directly
        for kind, probe in (
            ("IMAGE_COLLECTION", lambda: ee.ImageCollection(dataset).limit(1).size().getInfo()),
            ("IMAGE", lambda: ee.Image(dataset).bandNames().getInfo()),
            ("TABLE", lambda: ee.FeatureCollection(dataset).limit(1).size().getInfo()),
        ):
            try:
                probe()
                info["type"] = kind
                break
            except Exception:
                continue
    if info["type"] == "FEATURE_COLLECTION":
        info["type"] = "TABLE"
    if info["type"]:
        _ASSET_INFO_CACHE[dataset] = info
    return info


def _catalog_vis_from_properties(props: dict) -> dict:
    """Use the official catalog visualization embedded in asset properties (visualization_0_*)."""
    if not props or "visualization_0_bands" not in props:
        return {}
    vis: dict = {}
    bands = [b.strip() for b in str(props.get("visualization_0_bands", "")).split(",") if b.strip()]
    if bands:
        vis["bands"] = bands
    for key in ("min", "max", "gamma"):
        raw = props.get(f"visualization_0_{key}")
        if raw is None:
            continue
        vals = [float(v) for v in str(raw).split(",") if v.strip()]
        if vals:
            vis[key] = vals[0] if len(vals) == 1 else vals
    palette = props.get("visualization_0_palette")
    if palette:
        vis["palette"] = [p.strip().lstrip("#") for p in str(palette).split(",") if p.strip()]
    return vis


def _vis_is_complete(vis: dict) -> bool:
    if not vis:
        return False
    if vis.get("palette"):
        return True
    if "min" in vis and "max" in vis:
        return True
    return len(vis.get("bands") or []) == 3 and "min" in vis


_SEQUENTIAL_PALETTE = ["440154", "3b528b", "21918c", "5ec962", "fde725"]


def _sync_auto_visualize(img: Any, sample_img: Any, region: Any) -> tuple[Any, dict, list[dict] | None]:
    """Derive visualization for an arbitrary image.

    Returns (image_to_render, vis_params, legend_classes_or_None). Categorical
    bands with catalog class metadata (<band>_class_values / _class_palette /
    _class_names) are remapped to contiguous indices so the palette is exact.
    """
    import ee

    band_names = sample_img.bandNames().getInfo() or []
    if not band_names:
        raise ValueError("The dataset has no image bands to visualize in this area/date range.")
    lower = [b.lower() for b in band_names]

    # 1) Categorical band with embedded class palette (e.g. ESA WorldCover 'Map').
    try:
        prop_names = set(sample_img.propertyNames().getInfo() or [])
    except Exception:
        prop_names = set()
    for band in band_names:
        if f"{band}_class_values" in prop_names and f"{band}_class_palette" in prop_names:
            meta = ee.Dictionary({
                "values": sample_img.get(f"{band}_class_values"),
                "palette": sample_img.get(f"{band}_class_palette"),
                "names": sample_img.get(f"{band}_class_names") if f"{band}_class_names" in prop_names else [],
            }).getInfo()
            values = [int(v) for v in meta.get("values") or []]
            palette = [str(p).lstrip("#") for p in meta.get("palette") or []]
            names = meta.get("names") or []
            if values and len(palette) >= len(values):
                remapped = img.select(band).remap(values, list(range(len(values)))).rename(band)
                legend = [
                    {"value": v, "name": names[i] if i < len(names) else str(v), "color": f"#{palette[i]}"}
                    for i, v in enumerate(values)
                ]
                return remapped, {"min": 0, "max": len(values) - 1, "palette": palette[: len(values)]}, legend

    # 2) RGB composite when the dataset exposes red/green/blue bands.
    rgb = None
    for trio in (("b4", "b3", "b2"), ("sr_b4", "sr_b3", "sr_b2"), ("red", "green", "blue"), ("r", "g", "b")):
        if all(t in lower for t in trio):
            rgb = [band_names[lower.index(t)] for t in trio]
            break
    bands = rgb or [band_names[0]]

    # 3) Stretch to 2nd–98th percentile over the area of interest.
    vis: dict = {"bands": bands}
    stats = None
    if region is not None:
        try:
            area_m2 = region.bounds(100).area(100).getInfo() or 1e8
            scale = max(10.0, min(5000.0, (area_m2 ** 0.5) / 400.0))
            stats = img.select(bands).reduceRegion(
                reducer=ee.Reducer.percentile([2, 98]),
                geometry=region,
                scale=scale,
                bestEffort=True,
                maxPixels=int(1e8),
                tileScale=4,
            ).getInfo()
        except Exception as exc:
            logger.debug(f"Auto-stretch statistics failed: {exc}")
    lows, highs = [], []
    for b in bands:
        lo = (stats or {}).get(f"{b}_p2")
        hi = (stats or {}).get(f"{b}_p98")
        if lo is not None and hi is not None and hi > lo:
            lows.append(float(lo))
            highs.append(float(hi))
    if len(lows) == len(bands):
        vis["min"] = min(lows)
        vis["max"] = max(highs)
    else:
        vis["min"], vis["max"] = 0, 1 if not rgb else 3000
    if len(bands) == 1:
        vis["palette"] = _SEQUENTIAL_PALETTE
    return img, vis, None


def _boundary_shape(boundary_geojson: Any):
    """Return a shapely geometry for a GeoJSON Feature/FeatureCollection/geometry, or None."""
    if not boundary_geojson:
        return None
    from shapely.geometry import shape
    from shapely.ops import unary_union
    if isinstance(boundary_geojson, str):
        boundary_geojson = json.loads(boundary_geojson)
    btype = boundary_geojson.get("type")
    if btype == "FeatureCollection":
        shapes = [shape(f["geometry"]) for f in boundary_geojson.get("features", []) if f.get("geometry")]
        geom = unary_union(shapes) if shapes else None
    elif btype == "Feature":
        geom = shape(boundary_geojson["geometry"]) if boundary_geojson.get("geometry") else None
    else:
        geom = shape(boundary_geojson)
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = geom.buffer(0)
    # Points/lines can't contain features; only clip to areal boundaries.
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    return geom


def _clip_features_to_boundary(features: list[dict], boundary_geojson: Any) -> list[dict]:
    """Clip any-geometry-type features to an areal boundary, preserving geometry dimension."""
    b_shape = _boundary_shape(boundary_geojson)
    if b_shape is None:
        return features
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union, linemerge

    dim_of = {"Point": 0, "MultiPoint": 0, "LineString": 1, "MultiLineString": 1, "LinearRing": 1, "Polygon": 2, "MultiPolygon": 2}
    out: list[dict] = []
    for feat in features:
        g = feat.get("geometry")
        if not g:
            continue
        try:
            s = shape(g)
            if not s.is_valid and s.geom_type in ("Polygon", "MultiPolygon"):
                s = s.buffer(0)
            if not b_shape.intersects(s):
                continue
            if b_shape.contains(s):
                out.append(feat)
                continue
            target_dim = dim_of.get(s.geom_type, 2)
            inter = b_shape.intersection(s)
            parts, pending = [], [inter]
            while pending:
                part = pending.pop()
                if hasattr(part, "geoms"):
                    pending.extend(part.geoms)
                elif not part.is_empty and dim_of.get(part.geom_type) == target_dim:
                    parts.append(part)
            if not parts:
                continue
            merged = unary_union(parts)
            if target_dim == 1 and merged.geom_type == "MultiLineString":
                merged = linemerge(merged)
            new_feat = dict(feat)
            new_feat["geometry"] = mapping(merged)
            out.append(new_feat)
        except Exception as exc:
            logger.debug(f"Feature clip failed: {exc}")
    return out


def _geodesic_length_km(geom: dict) -> float:
    """WGS84 ellipsoidal length of a (Multi)LineString GeoJSON geometry in km."""
    try:
        from pyproj import Geod
        from shapely.geometry import shape
        return abs(Geod(ellps="WGS84").geometry_length(shape(geom))) / 1000.0
    except Exception:
        return 0.0


def _safe_slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:60] or "layer"


# ── Land cover: per-year dataset selection, availability & harmonised classes ──
#
# No single land-cover product spans every year: MODIS MCD12Q1 (500 m) covers
# 2001→~last year, Google Dynamic World (10 m) covers mid-2015→today, ESA
# WorldCover only 2020/2021 and Copernicus 100 m only 2015–2019. Every land-cover
# tool goes through these helpers so a requested year is never silently
# replaced by another year's data.

_DW_ID = "GOOGLE/DYNAMICWORLD/V1"
_MODIS_LC_ID = "MODIS/061/MCD12Q1"
_DW_FIRST_FULL_YEAR = 2016  # Dynamic World starts 2015-06-27 (2015 is partial)
_ESA_WORLDCOVER_YEARS = {2020: "ESA/WorldCover/v100/2020", 2021: "ESA/WorldCover/v200/2021"}
_COPERNICUS_LC_YEARS = range(2015, 2020)
_MODIS_LC_LATEST: int | None = None

# Harmonised groups so different products can be compared on one chart.
LC_GROUPS = ["Built-up", "Trees", "Cropland", "Grass/Shrub", "Water", "Wetland", "Bare", "Snow/Ice"]
LC_GROUP_COLORS = ["#C4281B", "#397D49", "#E49635", "#88B053", "#419BDF", "#7A87C6", "#A59B8F", "#B39FE1"]
# source → (class values, harmonised group index per value)
_LC_GROUP_REMAP: dict[str, tuple[list[int], list[int]]] = {
    "dynamic_world": ([0, 1, 2, 3, 4, 5, 6, 7, 8], [4, 1, 3, 5, 2, 3, 0, 6, 7]),
    "modis_landcover": (
        list(range(1, 18)),
        [1, 1, 1, 1, 1, 3, 3, 1, 3, 3, 5, 2, 0, 2, 7, 6, 4],
    ),
    "esa_worldcover": ([10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100], [1, 3, 3, 2, 0, 6, 7, 4, 5, 1, 3]),
}
_LC_SOURCE_LABELS = {
    "dynamic_world": "Google Dynamic World V1 (10 m, Sentinel-2)",
    "modis_landcover": "MODIS MCD12Q1 IGBP (500 m)",
    "esa_worldcover": "ESA WorldCover (10 m)",
    "copernicus_landcover": "Copernicus Global Land Cover (100 m)",
}
_LC_NATIVE_SCALE = {"dynamic_world": 10, "modis_landcover": 500, "esa_worldcover": 10, "copernicus_landcover": 100}


def _modis_lc_latest_year() -> int:
    """Latest MCD12Q1 year published in Earth Engine (cached; needs ee initialised)."""
    global _MODIS_LC_LATEST
    if _MODIS_LC_LATEST is None:
        try:
            import ee
            ts = ee.ImageCollection(_MODIS_LC_ID).aggregate_max("system:time_start").getInfo()
            from datetime import datetime, timezone
            _MODIS_LC_LATEST = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).year
        except Exception:
            from datetime import date
            return date.today().year - 2
    return _MODIS_LC_LATEST


def _lc_available_years(source: str) -> list[int]:
    from datetime import date
    current = date.today().year
    if source == "dynamic_world":
        return list(range(2015, current + 1))
    if source == "modis_landcover":
        return list(range(2001, _modis_lc_latest_year() + 1))
    if source == "esa_worldcover":
        return sorted(_ESA_WORLDCOVER_YEARS)
    if source == "copernicus_landcover":
        return list(_COPERNICUS_LC_YEARS)
    return []


def _lc_resolve_source(source: str | None, year: int | None) -> str:
    """'auto' → Dynamic World for 2016+, MODIS for earlier years."""
    src = (source or "auto").strip().lower()
    if src in ("", "auto"):
        if year is not None and year < _DW_FIRST_FULL_YEAR:
            return "modis_landcover"
        return "dynamic_world"
    return src


def _lc_year_error(source: str, year: int) -> str | None:
    years = _lc_available_years(source)
    if year in years:
        return None
    span = f"{years[0]}–{years[-1]}" if len(years) > 2 else ", ".join(map(str, years))
    hint = (
        " Use source='modis_landcover' for years before 2016."
        if source in ("dynamic_world", "esa_worldcover", "copernicus_landcover") and year < 2016
        else (" Use source='dynamic_world' for recent years." if year > years[-1] else "")
    )
    return f"{_LC_SOURCE_LABELS.get(source, source)} has no data for {year} (available: {span}).{hint}"


def _lc_year_notes(source: str, year: int) -> str | None:
    from datetime import date
    if source == "dynamic_world" and year == 2015:
        return "2015 is partial (Dynamic World starts 27 June 2015)."
    if source == "dynamic_world" and year == date.today().year:
        return f"{year} is year-to-date."
    return None


def _lc_class_image(source: str, year: int, geom: Any = None) -> Any:
    """Native single-band land-cover class image ('lc') for exactly the given year."""
    import ee
    if source == "dynamic_world":
        coll = ee.ImageCollection(_DW_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        if geom is not None:
            coll = coll.filterBounds(geom)
        return coll.select("label").mode().rename("lc")
    if source == "modis_landcover":
        return (ee.ImageCollection(_MODIS_LC_ID)
                .filter(ee.Filter.calendarRange(year, year, "year"))
                .first().select("LC_Type1").rename("lc"))
    if source == "esa_worldcover":
        return ee.Image(_ESA_WORLDCOVER_YEARS[year]).select("Map").rename("lc")
    if source == "copernicus_landcover":
        return (ee.ImageCollection("COPERNICUS/Landcover/100m/Proba-V-C3/Global")
                .filter(ee.Filter.calendarRange(year, year, "year"))
                .first().select("discrete_classification").rename("lc"))
    raise ValueError(f"Unknown land cover source '{source}'.")


def _lc_group_image(source: str, year: int, geom: Any = None) -> Any:
    values, groups = _LC_GROUP_REMAP[source]
    return _lc_class_image(source, year, geom).remap(values, groups).rename("group")


def _lc_reduce_scale(source: str, area_km2: float | None) -> int:
    native = _LC_NATIVE_SCALE.get(source, 30)
    if native >= 100 or not area_km2:
        return native
    # Keep 10 m sampling for city-scale areas; coarsen for very large regions.
    if area_km2 <= 3000:
        return native
    if area_km2 <= 30000:
        return 30
    return 100


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
        "compare_modis_fire_history",
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
        "extract_water_streams",
        "analyze_land_cover_timeseries",
        "analyze_population_timeseries",
        "analyze_building_growth",
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
                    "Add ANY dataset from the Google Earth Engine public data catalog to the map. "
                    "The asset type is detected automatically: Images and ImageCollections are rendered as clipped "
                    "raster tiles (auto-styled from the catalog's own visualization / class palette, or a percentile "
                    "stretch); FeatureCollection tables (rivers, basins, roads, protected areas, building footprints, "
                    "admin units, etc.) are extracted as clipped vector GeoJSON features on the canvas. "
                    "Use search_gee_datasets first when you don't know the dataset ID. "
                    "When place_name or geojson is provided, the layer is strictly clipped to that boundary."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string", "description": "Earth Engine dataset/asset ID (e.g. 'COPERNICUS/S2_SR_HARMONIZED', 'USGS/SRTMGL1_003', 'WWF/HydroSHEDS/v1/FreeFlowingRivers', 'WCMC/WDPA/current/polygons')."},
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "vis_params": {"type": "object", "description": "Optional GEE visualization params (e.g. {\"min\":0,\"max\":3000,\"bands\":[\"B4\",\"B3\",\"B2\"]}). Omit to auto-style."},
                        "band": {"type": "string", "description": "Optional single band to display (raster datasets)."},
                        "date": {"type": "string", "description": "Year (e.g. '2023') or start date (YYYY-MM-DD) for collection filtering. Omit to use the latest year of data."},
                        "end_date": {"type": "string", "description": "Optional end date (YYYY-MM-DD) for collection filtering."},
                        "color": {"type": "string", "description": "Colour for vector (table) datasets."},
                        "max_features": {"type": "integer", "description": "Max vector features to extract for table datasets (default 5000)."},
                        "title": {"type": "string", "description": "Title label for the map layer panel."},
                        "url": {"type": "string", "description": "Optional pre-built XYZ tile URL; when given the layer is added directly without Earth Engine processing."},
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
                        "year": {"type": "integer", "description": "The exact year the user asked for. Only that calendar year is fetched (year-to-date for the current year). Omit when no year was mentioned → current year."},
                        "title": {"type": "string", "description": "Layer title."},
                    },
                },
            ),
            ToolDeclaration(
                name="compare_modis_fire_history",
                description=(
                    "Compare MODIS burned area and FIRMS active-fire history for one or more places/villages. "
                    "Years compared = the year the user asked for + the present year (no year mentioned: current year only). "
                    "Call this ONCE with ALL requested places; a single comparison report artifact is saved automatically. "
                    "Pass village_names, villages as [{name, geojson}], or a GeoJSON FeatureCollection."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "villages": {
                            "type": "array",
                            "description": "Village names or geometries; objects may contain name and geojson Feature/geometry.",
                            "items": {"oneOf": [{"type": "string"}, {"type": "object"}]},
                        },
                        "village_names": {
                            "type": "array",
                            "description": "Any village/place names. Official boundaries are resolved automatically before analysis.",
                            "items": {"type": "string"},
                        },
                        "geojson": {"type": "object", "description": "FeatureCollection whose features are villages; NAME/name is used as the village name."},
                        "year": {"type": "integer", "description": "The year the user asked about. It is compared against the present (current) year. Omit when no year was mentioned (current year only)."},
                        "years": {"type": "array", "items": {"type": "integer"}, "description": "Several specific years the user asked about (each compared with the present year)."},
                        "start_year": {"type": "integer", "description": "Only for an explicit range request ('from 2019 to 2023'): first year, inclusive."},
                        "end_year": {"type": "integer", "description": "Only for an explicit range request: last year, inclusive (defaults to the current year)."},
                    },
                    "required": [],
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
                            "enum": ["auto", "dynamic_world", "esa_worldcover", "modis_landcover", "copernicus_landcover"],
                            "description": (
                                "Land cover dataset. Default 'auto' = Dynamic World (10 m) for 2016+, MODIS (500 m) for 2001–2015. "
                                "ESA WorldCover exists ONLY for 2020 and 2021; Copernicus 100 m only 2015–2019."
                            ),
                        },
                        "year": {"type": "integer", "description": "The exact year asked for; that year's data is shown or an explicit no-data error is returned. Omit when no year is mentioned (latest available)."},
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
                    "Search the FULL Google Earth Engine public data catalog (900+ datasets: imagery, climate, "
                    "hydrology, soils, population, infrastructure, vector tables, etc.). Returns ranked dataset IDs "
                    "with title, type (image / image_collection / table), date range, provider and the tool to use. "
                    "Pass the returned ID to add_gee_layer to put it on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Free-text search (e.g. 'rivers', 'soil organic carbon', 'flood', 'building footprints', 'protected areas')."},
                        "category": {
                            "type": "string",
                            "enum": ["surface_temperature", "climate", "atmospheric", "weather", "landsat", "sentinel", "high_resolution", "modis", "terrain", "landcover", "agriculture", "geophysical", "hydrology"],
                            "description": "Optional category filter.",
                        },
                        "limit": {"type": "integer", "description": "Max results (default 25)."},
                    },
                },
            ),
            ToolDeclaration(
                name="extract_water_streams",
                description=(
                    "Plot the river / stream / drainage network of a place on the map as clipped vector LINE features "
                    "(WWF HydroSHEDS river reaches with river order, upstream area and discharge), plus an optional fine "
                    "drainage-channel raster from MERIT Hydro flow accumulation for small streams. ALWAYS use this for "
                    "'water streams', 'streams', 'rivers', 'drainage network', 'nallahs', 'channels' or 'waterways' requests. "
                    "Returns reach count, total length (km) and length by river order (discharge class)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "lat": {"type": "number", "description": "Latitude for a circular study area (when no place/boundary)."},
                        "lng": {"type": "number", "description": "Longitude for a circular study area."},
                        "radius_km": {"type": "number", "description": "Radius in km for the circular study area (default 10)."},
                        "min_upstream_area_km2": {"type": "number", "description": "Only keep reaches draining at least this area (default 0 = all mapped reaches)."},
                        "include_drainage_raster": {"type": "boolean", "description": "Also add a MERIT Hydro fine drainage-channel raster layer (default true)."},
                        "drainage_threshold_km2": {"type": "number", "description": "Upstream area threshold (km²) defining a channel in the drainage raster (default 1)."},
                        "color": {"type": "string", "description": "Line colour (default blue)."},
                        "title": {"type": "string", "description": "Layer title."},
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
                    "Add a high-resolution population density raster layer to the map from WorldPop (100m grid, 2000-2020), "
                    "JRC GHSL (GHS-POP 100m grid, 1975-2030 epochs including 2025), or CIESIN GPWv4 / LandScan. ALWAYS use this for 'population raster', 'population density map', 'WorldPop', "
                    "'ghsl population', or urban density visualization requests across historical, current, and future years."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "geojson": geojson_param,
                        "source": {"type": "string", "enum": ["worldpop", "ghsl", "landscan", "gpw"], "description": "Dataset source: 'worldpop' (2000-2020 annual), 'ghsl' (JRC GHS-POP 1975-2030, recommended for post-2020/2025), or 'gpw' (default 'worldpop'; auto-routes to 'ghsl' if year > 2020)."},
                        "year": {"type": "integer", "description": "Year of population data (e.g. 2000-2030, default 2020)."},
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
                        "year": {"type": "integer", "description": "The exact year asked for (omit → latest available)."},
                        "source": {
                            "type": "string",
                            "enum": ["auto", "dynamic_world", "modis_landcover", "esa_worldcover"],
                            "description": "Default 'auto' = Dynamic World for 2016+, MODIS for 2001–2015. ESA WorldCover only 2020/2021.",
                        },
                    },
                },
            ),
            ToolDeclaration(
                name="analyze_land_cover_timeseries",
                description=(
                    "Land use / land cover CHANGE OVER MULTIPLE YEARS for a place, with an automatic multi-line chart "
                    "(one line per land cover class) saved as an image artifact. ALWAYS use this — in ONE call — for "
                    "'land use/land cover from <year> to <year>', 'trend', 'change over time', or any request to graph "
                    "land cover across years. Uses MODIS (500 m, 2001–latest) for long ranges and Dynamic World (10 m, "
                    "2016–present) for recent years; years with no data are reported, never filled. Do NOT call "
                    "create_plot yourself for this — the chart is generated from the computed values."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "place_names": {"type": "array", "items": {"type": "string"}, "description": "Several places merged into ONE study area (e.g. the cities of a tri-city region)."},
                        "region_name": {"type": "string", "description": "Label for the merged region."},
                        "boundary_layer_name": {"type": "string", "description": "Polygon layer already on the map to use as the boundary."},
                        "geojson": geojson_param,
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "radius_km": {"type": "number"},
                        "start_year": {"type": "integer", "description": "First year asked for (inclusive)."},
                        "end_year": {"type": "integer", "description": "Last year asked for (inclusive; default current year)."},
                        "source": {
                            "type": "string",
                            "enum": ["auto", "dynamic_world", "modis_landcover", "esa_worldcover"],
                            "description": "Default 'auto' (recommended).",
                        },
                        "metric": {"type": "string", "enum": ["percent", "area_km2"], "description": "Y axis: share of area (default) or km²."},
                        "create_chart": {"type": "boolean", "description": "Save the line chart artifact (default true)."},
                    },
                    "required": ["start_year"],
                },
            ),
            ToolDeclaration(
                name="analyze_population_timeseries",
                description=(
                    "Population growth inside a place's exact boundary over a range of years (backend calculation + automatic "
                    "line chart artifact; nothing is added to the map except the boundary outline). Sums WorldPop (annual "
                    "2000–2020, 100 m) and GHSL GHS-POP (5-yearly; 2025/2030 are projections) inside the polygon; returns "
                    "totals per year, change, CAGR and density. Use for 'population growth of <place> from <year> to <year>'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "place_names": {"type": "array", "items": {"type": "string"}, "description": "Several places merged into ONE study area (e.g. the cities of a tri-city region)."},
                        "region_name": {"type": "string", "description": "Label for the merged region."},
                        "boundary_layer_name": {"type": "string", "description": "Polygon layer already on the map to use as the boundary."},
                        "start_year": {"type": "integer"},
                        "end_year": {"type": "integer"},
                        "create_chart": {"type": "boolean"},
                    },
                    "required": ["start_year"],
                },
            ),
            ToolDeclaration(
                name="analyze_building_growth",
                description=(
                    "Building-level growth inside a place's exact boundary — HORIZONTAL (built-up footprint area, building count) "
                    "and VERTICAL (average/median building height, built volume) — over a range of years, with an automatic "
                    "multi-panel chart artifact. Google Open Buildings Temporal (2016–2023, ~0.5 m effective) plus GHSL built "
                    "surface/volume (5-yearly 1975–2030, 100 m; 2025/2030 projected). Backend calculation only."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": place_param,
                        "place_names": {"type": "array", "items": {"type": "string"}, "description": "Several places merged into ONE study area (e.g. the cities of a tri-city region)."},
                        "region_name": {"type": "string", "description": "Label for the merged region."},
                        "boundary_layer_name": {"type": "string", "description": "Polygon layer already on the map to use as the boundary."},
                        "start_year": {"type": "integer"},
                        "end_year": {"type": "integer"},
                        "create_chart": {"type": "boolean"},
                    },
                    "required": ["start_year"],
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

        try:
            return await self._route(tool_name, args)
        except BoundaryUnresolved as exc:
            return {"error": str(exc), "code": "boundary_unresolved"}

    async def _route(self, tool_name: str, args: dict) -> dict:
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
        if tool_name == "compare_modis_fire_history":
            return await self._compare_modis_fire_history(args)
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
        if tool_name == "extract_water_streams":
            return await self._extract_water_streams(args)
        if tool_name == "analyze_land_cover_timeseries":
            return await self._analyze_land_cover_timeseries(args)
        if tool_name == "analyze_population_timeseries":
            return await self._analyze_population_timeseries(args)
        if tool_name == "analyze_building_growth":
            return await self._analyze_building_growth(args)

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

    async def _send_layer(self, ws, tile_url: str, dataset: str, vis_params: dict, title: str, bbox: dict | None = None, centroid: dict | None = None) -> None:
        """Send add_gee_layer action over WebSocket if connected."""
        payload = {
            "url": tile_url,
            "dataset": dataset,
            "vis_params": vis_params,
            "title": title,
        }
        if bbox:
            payload["bbox"] = bbox
            payload["bounds"] = [bbox.get("west"), bbox.get("south"), bbox.get("east"), bbox.get("north")]
        if centroid:
            payload["centroid"] = centroid
            payload["center"] = [centroid.get("lng") or centroid.get("x"), centroid.get("lat") or centroid.get("y")]
        await self._send_action(ws, "add_gee_layer", payload)

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
        workspace = args.get("_workspace")
        map_context = args.get("_map_context") or {}

        # 0. Always ensure Earth Engine is initialized so ee.Geometry conversions succeed!
        try:
            await _ensure_gee(workspace)
        except Exception as _init_err:
            logger.debug(f"Initial _ensure_gee in _resolve_place_boundary: {_init_err}")

        # Multi-place regions (e.g. a tri-city) and named map layers use the shared resolver,
        # which unions the official polygons and outlines the result on the map.
        if args.get("place_names") or args.get("boundary_layer_name"):
            from tools.boundary import BoundaryError, resolve_study_boundary
            try:
                sb = await resolve_study_boundary({**args, "_map_context": map_context, "_ws": ws, "_workspace": workspace})
            except BoundaryError as exc:
                raise BoundaryUnresolved(str(exc)) from exc
            ee_geom = _geojson_to_ee_geometry(sb.geojson)
            if ee_geom is None:
                raise BoundaryUnresolved(f"The boundary of '{sb.name}' could not be converted for Earth Engine.")
            return sb.geojson, ee_geom, sb.name, sb.bbox

        # If place_name not explicitly set, check title for a place indicator (e.g. 'NDVI - Paris')
        explicit_place = bool(place_name)
        if not place_name and not geojson_input:
            title = (args.get("title") or "").strip()
            if " - " in title:
                candidate = title.split(" - ")[-1].strip()
                if candidate and len(candidate) > 2 and not candidate.isdigit():
                    place_name = candidate
            elif " – " in title:
                candidate = title.split(" – ")[-1].strip()
                if candidate and len(candidate) > 2 and not candidate.isdigit():
                    place_name = candidate
            elif " for " in title.lower():
                candidate = title.lower().split(" for ")[-1].strip()
                if candidate and len(candidate) > 2 and not candidate.isdigit():
                    place_name = candidate

        # If place_name is empty or generic ("that place", "here", "the boundary", "study area"):
        generic_terms = {"", "that place", "this place", "the place", "here", "the boundary", "boundary", "study area", "study region"}
        selected_features = map_context.get("selected_features") or []
        selected_feature_geojson = []
        selected_names = []
        for selected in selected_features:
            selected_geom = selected.get("geojson")
            if not isinstance(selected_geom, dict):
                continue
            if selected_geom.get("type") == "Feature":
                geometry = selected_geom.get("geometry")
            else:
                geometry = selected_geom
            if geometry and geometry.get("type") in ("Polygon", "MultiPolygon"):
                selected_feature_geojson.append({
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": selected_geom.get("properties", selected.get("properties", {}))
                    if selected_geom.get("type") == "Feature" else selected.get("properties", {}),
                })
                selected_names.append(str(selected.get("layerName") or "").strip())
        selection_matches = (
            not place_name
            or place_name.lower().strip() in generic_terms
            or any(
                place_name.casefold() in selected_name.casefold()
                or selected_name.casefold() in place_name.casefold()
                for selected_name in selected_names
                if selected_name
            )
        )
        if not geojson_input and selected_feature_geojson and selection_matches:
            geojson_input = (
                selected_feature_geojson[0]
                if len(selected_feature_geojson) == 1
                else {"type": "FeatureCollection", "features": selected_feature_geojson}
            )
            if not place_name and selected_names:
                place_name = selected_names[0]

        if not geojson_input and (not place_name or place_name.lower().strip() in generic_terms):
            try:
                from tools.spatial_registry import spatial_registry
                active_polys = spatial_registry.list_polygons()
                study_polys = [p for p in active_polys if p.get("source") in ("osm_boundary", "ai_draw", "user_draw")]
                if study_polys:
                    latest = study_polys[-1]
                    geojson_input = latest.get("geometry")
                    place_name = latest.get("name")
                elif active_polys:
                    geojson_input = active_polys[-1].get("geometry")
                    place_name = active_polys[-1].get("name")
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
                from shapely.ops import unary_union
                if geojson_input.get("type") == "FeatureCollection":
                    geometries = [
                        shape(feature["geometry"])
                        for feature in geojson_input.get("features", [])
                        if feature.get("geometry")
                    ]
                    if not geometries:
                        raise ValueError("GeoJSON FeatureCollection contains no geometry")
                    s = unary_union(geometries)
                elif geojson_input.get("type") == "Feature":
                    s = shape(geojson_input["geometry"])
                else:
                    s = shape(geojson_input)
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

            # Check active map layers (matching against spatial registry or file on disk)
            if not geojson_input and map_context.get("layers"):
                p_lower = place_name.lower().strip()
                for layer in map_context["layers"]:
                    lname = (layer.get("name") or "").lower().strip()
                    if p_lower in lname or lname in p_lower:
                        # Priority 1: spatial registry (already has the exact polygon geometry)
                        try:
                            from tools.spatial_registry import spatial_registry
                            p = spatial_registry.get_polygon(layer.get("name") or "")
                            if p and p.geometry:
                                geojson_input = p.geometry
                                matched_name = p.name
                                bbox = p.bbox
                                centroid = p.centroid
                                break
                        except Exception:
                            pass
                        # Priority 2: load actual GeoJSON from the layer's file on disk.
                        # This ensures we use the EXACT polygon shape, not just its bounding
                        # box, when the user selects a drawn or uploaded boundary layer.
                        file_path = layer.get("filePath") or layer.get("file_path")
                        if file_path and not geojson_input:
                            try:
                                import json as _json
                                from pathlib import Path as _Path
                                fp = _Path(file_path)
                                if not fp.is_absolute() and workspace:
                                    fp = _Path(workspace) / file_path
                                if fp.exists() and fp.suffix.lower() in (".geojson", ".json"):
                                    file_data = _json.loads(fp.read_text(encoding="utf-8"))
                                    gtype = file_data.get("type", "") if isinstance(file_data, dict) else ""
                                    if gtype in ("FeatureCollection", "Feature", "Polygon", "MultiPolygon", "GeometryCollection"):
                                        geojson_input = file_data
                                        matched_name = layer.get("name")
                                        break
                            except Exception as _fp_err:
                                logger.debug(f"Failed to load layer geometry from file: {_fp_err}")
                        # Priority 3: inline geometry_data or data field from map context
                        ldata = layer.get("data") or layer.get("geometry_data")
                        if isinstance(ldata, dict) and (ldata.get("features") or ldata.get("type")):
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

                except Exception as b_err:
                    logger.warning(f"Could not auto-fetch boundary for '{place_name}': {b_err}")

        if isinstance(geojson_input, str):
            try:
                geojson_input = json.loads(geojson_input)
            except Exception:
                geojson_input = None

        # Calculations must use the place's real polygon. A point (unmapped
        # village centroid) or line would turn into a single pixel / square.
        boundary_shape = _boundary_shape(geojson_input) if geojson_input else None
        place_requested = (
            explicit_place and bool(place_name and place_name.lower().strip() not in generic_terms)
        ) or bool(args.get("geojson"))
        if geojson_input and boundary_shape is None:
            if place_requested:
                raise BoundaryUnresolved(
                    f"No polygon boundary is mapped for '{place_name or 'the supplied geometry'}' (only a point or line was found). "
                    "Nothing was calculated. Draw or upload the area's boundary polygon, or name the enclosing administrative area."
                )
            geojson_input = None
        if place_requested and boundary_shape is None and not geojson_input:
            raise BoundaryUnresolved(
                f"Could not resolve an official boundary polygon for '{place_name}'. Nothing was calculated for another area."
            )

        # Compute bbox and centroid from the full boundary (all parts)
        if boundary_shape is not None and not bbox:
            minx, miny, maxx, maxy = boundary_shape.bounds
            bbox = {"west": round(minx, 6), "south": round(miny, 6), "east": round(maxx, 6), "north": round(maxy, 6)}
            if not centroid:
                c = boundary_shape.representative_point() if not boundary_shape.centroid.within(boundary_shape) else boundary_shape.centroid
                centroid = {"lat": round(c.y, 6), "lng": round(c.x, 6)}

        # Mark the place's boundary on the map (outline only) when it was resolved
        # from a place name and is not already a layer on the canvas.
        if ws and boundary_shape is not None and matched_name and not args.get("geojson") and not args.get("_skip_boundary_layer"):
            layer_names = {str(l.get("name") or "").strip().lower() for l in (map_context.get("layers") or [])}
            boundary_layer = f"{matched_name} boundary"
            if boundary_layer.lower() not in layer_names and str(matched_name).lower() not in layer_names:
                from shapely.geometry import mapping as _mapping
                await self._send_action(ws, "add_geojson", {
                    "geojson": {
                        "type": "FeatureCollection",
                        "features": [{"type": "Feature", "geometry": _mapping(boundary_shape), "properties": {"name": matched_name}}],
                    },
                    "name": boundary_layer,
                    "color": "#f8fafc",
                    "lineColor": "#f8fafc",
                    "fillColor": "#f8fafc",
                    "fillOpacity": 0,
                    "lineWidth": 2.5,
                })

        # Frame camera on the boundary
        if ws and bbox:
            try:
                await self._send_action(ws, "fit_bounds", {
                    "west": bbox["west"],
                    "south": bbox["south"],
                    "east": bbox["east"],
                    "north": bbox["north"],
                    "bounds": [bbox["west"], bbox["south"], bbox["east"], bbox["north"]],
                })
            except Exception:
                pass

        # Convert to Earth Engine geometry (the real polygon, never its bbox)
        ee_geom = None
        if geojson_input:
            ee_geom = _geojson_to_ee_geometry(geojson_input)
            if ee_geom is None and place_requested:
                raise BoundaryUnresolved(f"The boundary of '{place_name}' could not be converted for Earth Engine.")

        return geojson_input, ee_geom, matched_name, bbox

    # ── 1. Universal GEE Layer ────────────────────────────────────────────────

    async def _add_gee_layer(self, args: dict) -> dict:
        dataset = str(args.get("dataset") or "").strip()
        vis_params = dict(args.get("vis_params") or {})
        band = str(args.get("band") or "").strip()
        date_str = str(args.get("date") or "").strip()
        end_date = str(args.get("end_date") or "").strip()
        title = str(args.get("title") or "").strip()
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

        loop = asyncio.get_event_loop()
        try:
            import ee

            info = await loop.run_in_executor(None, _sync_get_asset_info, dataset)
            asset_type = info.get("type")
            if not asset_type:
                return {
                    "error": (
                        f"Earth Engine asset '{dataset}' was not found or is not accessible. "
                        "Call search_gee_datasets to find the exact dataset ID."
                    ),
                    "code": "gee_error",
                }

            # Region used for scene filtering / auto-stretch statistics (not clipping):
            # the study boundary when one exists, otherwise the current viewport.
            region = ee_geom
            if region is None:
                vp = self._viewport_bounds(args)
                if vp:
                    region = ee.Geometry.Rectangle(vp, None, False)

            if asset_type == "TABLE":
                return await self._add_gee_table_layer(
                    args, dataset, title, b_geojson, ee_geom, region, place_nm, bbox
                )

            default_vis, _ = _get_dataset_defaults(dataset)
            catalog_vis = _catalog_vis_from_properties(info.get("properties") or {})
            legend_holder: dict = {}

            def prepare_image():
                d_lower = dataset.lower()
                if asset_type == "IMAGE_COLLECTION":
                    coll = ee.ImageCollection(dataset)
                    if region is not None:
                        coll = coll.filterBounds(region)
                    if date_str:
                        start = f"{date_str}-01-01" if len(date_str) == 4 else date_str
                        if end_date:
                            end = f"{end_date}-12-31" if len(end_date) == 4 else end_date
                        else:
                            end = f"{date_str.split('-')[0]}-12-31"
                        coll = coll.filterDate(start, end)
                    else:
                        # No date given: use the most recent year of available data.
                        latest = coll.aggregate_max("system:time_start").getInfo()
                        if latest:
                            end_d = ee.Date(latest).advance(1, "day")
                            coll = coll.filterDate(end_d.advance(-1, "year"), end_d)
                    if "copernicus/s2" in d_lower:
                        coll = coll.filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 15))
                    elif "landsat" in d_lower and "c02" in d_lower:
                        coll = coll.filter(ee.Filter.lt("CLOUD_COVER", 20))
                    if coll.size().getInfo() == 0:
                        raise ValueError(
                            "No images found for this dataset in the requested area/date range."
                        )
                    sample = coll.first()
                    try:
                        sample_props = sample.propertyNames().getInfo() or []
                    except Exception:
                        sample_props = []
                    categorical = any(str(p).endswith("_class_values") for p in sample_props)
                    img = coll.mode() if categorical else coll.median()
                else:
                    img = ee.Image(dataset)
                    sample = img

                if band:
                    img = img.select([band])
                    sample = sample.select([band])

                if _vis_is_complete(vis_params):
                    return img, vis_params
                if not band and _vis_is_complete(default_vis):
                    return img, {**default_vis, **vis_params}
                if not band and _vis_is_complete(catalog_vis):
                    return img, {**catalog_vis, **vis_params}
                out_img, auto_vis, legend = _sync_auto_visualize(img, sample, region)
                if legend:
                    legend_holder["legend"] = legend
                return out_img, {**auto_vis, **vis_params}

            image, final_vis = await loop.run_in_executor(None, prepare_image)
            map_id, tile_url = await self._tile_proxy(lambda: image, final_vis, ee_geom)

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }
            result = {
                "status": "success",
                "message": f"GEE layer '{title}' added to map" + (f" for {place_nm}." if place_nm else "."),
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset,
                "asset_type": asset_type.lower(),
                "vis": final_vis,
                "layer_title": title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
            }
            if legend_holder.get("legend"):
                result["legend"] = legend_holder["legend"]
                result["vis"] = {**final_vis, "palette_labels": [c["name"] for c in legend_holder["legend"]]}
            return result

        except Exception as exc:
            return {"error": f"GEE layer failed: {exc}", "code": "gee_error"}

    @staticmethod
    def _viewport_bounds(args: dict) -> list[float] | None:
        """Current map viewport as [west, south, east, north] from the map context, if any."""
        b = (args.get("_map_context") or {}).get("bounds")
        try:
            if isinstance(b, dict):
                vals = [float(b["west"]), float(b["south"]), float(b["east"]), float(b["north"])]
            elif isinstance(b, (list, tuple)) and len(b) == 4:
                vals = [float(v) for v in b]
            elif isinstance(b, str) and b.count(",") == 3:
                vals = [float(v) for v in b.split(",")]
            else:
                return None
        except (KeyError, TypeError, ValueError):
            return None
        if vals[2] <= vals[0] or vals[3] <= vals[1]:
            return None
        return vals

    def _write_vector_output(self, workspace: str | None, filename: str, geojson: dict) -> str | None:
        if not workspace:
            return None
        out_path = Path(workspace) / filename
        out_path.write_text(json.dumps(geojson), encoding="utf-8")
        return str(out_path)

    @staticmethod
    def _with_workspace(tile_url: str, workspace: str | None) -> str:
        if workspace and "workspace=" not in tile_url:
            from urllib.parse import quote
            sep = "&" if "?" in tile_url else "?"
            return f"{tile_url}{sep}workspace={quote(str(workspace))}"
        return tile_url

    async def _add_gee_table_layer(
        self,
        args: dict,
        dataset: str,
        title: str,
        b_geojson: Any,
        ee_geom: Any,
        region: Any,
        place_nm: str | None,
        bbox: dict | None,
    ) -> dict:
        """Render an Earth Engine FeatureCollection (table) as vector GeoJSON, or tiles when huge."""
        import ee

        workspace = args.get("_workspace")
        max_features = int(args.get("max_features") or 5000)
        color = str(args.get("color") or "#2563EB")
        if not color.startswith("#") and len(color) in (3, 6):
            color = f"#{color}"

        def fetch():
            fc = ee.FeatureCollection(dataset)
            if region is not None:
                fc = fc.filterBounds(region)
            total = fc.size().getInfo()
            if total == 0:
                return 0, None
            if region is None or total > max_features:
                return total, None
            try:
                simplified = fc.map(lambda f: f.simplify(maxError=5))
                return total, simplified.getInfo()
            except Exception as exc:
                logger.info(f"Vector download for {dataset} failed ({exc}); falling back to tiles.")
                return total, None

        loop = asyncio.get_event_loop()
        total, data = await loop.run_in_executor(None, fetch)

        centroid = None
        if bbox:
            centroid = {
                "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
            }

        if total == 0:
            return {
                "status": "success",
                "dataset_id": dataset,
                "asset_type": "table",
                "feature_count": 0,
                "place_name": place_nm,
                "layer_title": title,
                "message": f"No features from '{dataset}' intersect " + (f"{place_nm}." if place_nm else "the current view."),
            }

        if data is None:
            # Too many features (or no bounded region) → server-side styled raster tiles.
            style_img = lambda: ee.FeatureCollection(dataset).style(  # noqa: E731
                color=color.lstrip("#"), width=1.5, fillColor=f"{color.lstrip('#')}55", pointSize=3
            )
            map_id, tile_url = await self._tile_proxy(style_img, {}, ee_geom)
            return {
                "status": "success",
                "dataset_id": dataset,
                "asset_type": "table",
                "rendered_as": "styled_tiles",
                "feature_count": total,
                "tile_url": tile_url,
                "map_id": map_id,
                "vis": {"color": color},
                "layer_title": title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
                "message": (
                    f"'{title}' has {total} features in this area — rendered as styled tiles. "
                    "Provide a smaller boundary to extract them as vector features."
                ),
            }

        features = data.get("features", [])
        if b_geojson:
            features = _clip_features_to_boundary(features, b_geojson)

        total_len_km = 0.0
        total_area_km2 = 0.0
        geom_types: dict[str, int] = {}
        try:
            from pyproj import Geod
            from shapely.geometry import shape
            geod = Geod(ellps="WGS84")
        except Exception:
            geod = None
        for feat in features:
            props = feat.setdefault("properties", {}) or {}
            feat["properties"] = props
            g = feat.get("geometry") or {}
            gtype = g.get("type", "Unknown")
            geom_types[gtype] = geom_types.get(gtype, 0) + 1
            if geod is not None and g:
                try:
                    s = shape(g)
                    if gtype in ("LineString", "MultiLineString"):
                        total_len_km += abs(geod.geometry_length(s)) / 1000.0
                    elif gtype in ("Polygon", "MultiPolygon"):
                        total_area_km2 += abs(geod.geometry_area_perimeter(s)[0]) / 1e6
                except Exception:
                    pass
            props["layer_name"] = title
            props["source_dataset"] = dataset
            props["source_tool"] = "add_gee_layer"
            props.setdefault("fillColor", color)
            props.setdefault("strokeColor", color)

        output = {"type": "FeatureCollection", "features": features}
        place_slug = f"_{_safe_slug(place_nm)}" if place_nm else ""
        geojson_file = self._write_vector_output(workspace, f"gee_{_safe_slug(dataset)}{place_slug}.geojson", output)

        result = {
            "status": "success",
            "dataset_id": dataset,
            "asset_type": "table",
            "rendered_as": "vector",
            "feature_count": len(features),
            "geometry_types": geom_types,
            "layer_title": title,
            "layer_name": title,
            "color": color,
            "place_name": place_nm,
            "clipped_to_boundary": bool(b_geojson),
            "geojson": output,
            "geojson_file": geojson_file,
            "bbox": bbox,
            "centroid": centroid,
            "message": f"Loaded {len(features)} vector features from '{dataset}'" + (f" clipped to {place_nm}." if place_nm else "."),
        }
        if total_len_km:
            result["total_length_km"] = round(total_len_km, 3)
        if total_area_km2:
            result["total_area_km2"] = round(total_area_km2, 4)
            result["area_hectares"] = round(total_area_km2 * 100, 2)
        return result

    # ── Hydrography: rivers / streams / drainage network ──────────────────────

    async def _extract_water_streams(self, args: dict) -> dict:
        workspace = args.get("_workspace")
        ws = args.get("_ws")
        color = str(args.get("color") or "#1E88E5")
        if not color.startswith("#") and len(color) in (3, 6):
            color = f"#{color}"
        min_upa = float(args.get("min_upstream_area_km2") or 0)
        include_raster = args.get("include_drainage_raster")
        include_raster = True if include_raster is None else bool(include_raster)
        threshold = float(args.get("drainage_threshold_km2") or 1.0)
        lat, lng = args.get("lat"), args.get("lng")
        radius_km = float(args.get("radius_km") or 10.0)

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        loop = asyncio.get_event_loop()

        try:
            import ee

            if ee_geom is None and lat is not None and lng is not None:
                ee_geom = ee.Geometry.Point([float(lng), float(lat)]).buffer(radius_km * 1000.0)
                b_geojson = await loop.run_in_executor(None, ee_geom.getInfo)
                place_nm = place_nm or f"{radius_km:g} km around ({float(lat):.4f}, {float(lng):.4f})"
                ring = b_geojson["coordinates"][0]
                xs, ys = [p[0] for p in ring], [p[1] for p in ring]
                bbox = {"west": round(min(xs), 6), "south": round(min(ys), 6), "east": round(max(xs), 6), "north": round(max(ys), 6)}
            if ee_geom is None:
                return {
                    "error": (
                        "A study area is required to plot streams. Provide place_name, a boundary GeoJSON, "
                        "select a polygon on the map, or pass lat/lng with radius_km."
                    ),
                    "code": "invalid_input",
                }

            cap = 5000
            props = ["RIV_ORD", "UPLAND_SKM", "DIS_AV_CMS", "LENGTH_KM", "REACH_ID"]

            def fetch_rivers():
                fc = ee.FeatureCollection(_HYDRO_RIVERS_ID).filterBounds(ee_geom)
                if min_upa > 0:
                    fc = fc.filter(ee.Filter.gte("UPLAND_SKM", min_upa))
                total = fc.size().getInfo()
                if total == 0:
                    return 0, False, []
                truncated = total > cap
                if truncated:
                    fc = fc.sort("UPLAND_SKM", False).limit(cap)
                data = fc.select(props).getInfo()
                return total, truncated, data.get("features", [])

            total, truncated, features = await loop.run_in_executor(None, fetch_rivers)
            features = _clip_features_to_boundary(features, b_geojson) if b_geojson else features

            display_title = str(args.get("title") or "").strip() or (
                f"Water Streams - {place_nm}" if place_nm else "Water Streams"
            )

            length_by_order: dict[str, float] = {}
            total_len = 0.0
            max_upa = 0.0
            max_dis = 0.0
            for feat in features:
                p = feat.get("properties") or {}
                seg_len = _geodesic_length_km(feat.get("geometry") or {})
                total_len += seg_len
                order = p.get("RIV_ORD")
                key = f"class_{int(order)}" if order is not None else "class_unknown"
                length_by_order[key] = round(length_by_order.get(key, 0.0) + seg_len, 3)
                upa = float(p.get("UPLAND_SKM") or 0)
                dis = float(p.get("DIS_AV_CMS") or 0)
                max_upa = max(max_upa, upa)
                max_dis = max(max_dis, dis)
                feat["properties"] = {
                    "river_order": order,
                    "upstream_area_km2": round(upa, 2),
                    "mean_discharge_m3s": round(dis, 3),
                    "reach_id": p.get("REACH_ID"),
                    "length_km": round(seg_len, 3),
                    "layer_name": display_title,
                    "source_tool": "extract_water_streams",
                    "source_dataset": _HYDRO_RIVERS_ID,
                    "strokeColor": color,
                    "fillColor": color,
                }

            output = {"type": "FeatureCollection", "features": features}
            place_slug = f"_{_safe_slug(place_nm)}" if place_nm else ""
            geojson_file = self._write_vector_output(workspace, f"water_streams{place_slug}.geojson", output)

            drainage = None
            if include_raster:
                import math

                def build_channels():
                    upa = ee.Image(_MERIT_HYDRO_ID).select("upa")
                    return upa.updateMask(upa.gte(threshold)).log10().rename("log_upa")

                d_vis = {
                    "min": round(math.log10(max(threshold, 0.01)), 3),
                    "max": 4,
                    "palette": ["c6dbef", "6baed6", "2171b5", "08306b"],
                }
                try:
                    _, d_url = await self._tile_proxy(build_channels, d_vis, ee_geom)
                    d_url = self._with_workspace(d_url, workspace)
                    d_title = f"Drainage Channels (MERIT Hydro ≥{threshold:g} km²)" + (f" - {place_nm}" if place_nm else "")
                    await self._send_layer(ws, d_url, _MERIT_HYDRO_ID, d_vis, d_title, bbox=bbox)
                    drainage = {"tile_url": d_url, "title": d_title, "threshold_km2": threshold}
                except Exception as exc:
                    logger.warning(f"MERIT Hydro drainage raster failed: {exc}")

            if not features and not drainage:
                msg = f"No mapped river reaches found in {place_nm or 'the study area'}."
            else:
                msg = (
                    f"Plotted {len(features)} stream/river reaches ({round(total_len, 2)} km) "
                    + (f"in {place_nm}" if place_nm else "")
                    + (" plus a fine drainage-channel raster." if drainage else ".")
                )
                if truncated:
                    msg += f" Showing the {cap} largest of {total} reaches."

            return {
                "status": "success",
                "dataset_id": _HYDRO_RIVERS_ID,
                "target_class": "Water Streams",
                "place_name": place_nm,
                "layer_name": display_title,
                "layer_title": display_title,
                "color": color,
                "stream_reaches": len(features),
                "reaches_in_area_total": total,
                "truncated": truncated,
                "total_stream_length_km": round(total_len, 3),
                "length_by_river_order_km": dict(sorted(length_by_order.items())),
                "river_order_note": "HydroRIVERS discharge-based river order: 1 = largest rivers, 10 = smallest streams.",
                "max_upstream_area_km2": round(max_upa, 2),
                "max_mean_discharge_m3s": round(max_dis, 3),
                "drainage_raster": drainage,
                "geojson": output,
                "geojson_file": geojson_file,
                "bbox": bbox,
                "clipped_to_boundary": bool(b_geojson),
                "message": msg,
            }
        except Exception as exc:
            return {"error": f"Stream network extraction failed: {exc}", "code": "gee_error"}

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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
                "message": f"High resolution imagery '{layer_title}' ({desc}) added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"High-resolution imagery failed: {exc}", "code": "gee_error"}

    # ── 9. MODIS Planetary Suite ──────────────────────────────────────────────

    async def _get_modis_layer(self, args: dict) -> dict:
        from datetime import date, timedelta

        product = (args.get("product") or "ndvi_evi").strip().lower()
        today = date.today()
        try:
            year = int(str(args.get("year") or today.year)[:4])
        except ValueError:
            return {"error": f"Invalid year '{args.get('year')}'.", "code": "invalid_input"}
        if year < 2000 or year > today.year:
            return {"error": f"MODIS data is available from 2000 to {today.year}; got {year}.", "code": "invalid_input"}
        # Only the requested calendar year (year-to-date for the current year).
        y_start = f"{year}-01-01"
        y_end = (today + timedelta(days=1)).isoformat() if year == today.year else f"{year + 1}-01-01"
        title = (args.get("title") or "").strip()
        ws = args.get("_ws")
        workspace = args.get("_workspace")
        requested_place = any(
            str(args.get(k) or "").strip()
            for k in ("place_name", "city", "location", "study_area", "boundary_name", "place")
        ) or bool(args.get("geojson"))

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        if requested_place and ee_geom is None:
            return {
                "error": (
                    f"Could not resolve the boundary for '{args.get('place_name') or 'the requested area'}'. "
                    "Refusing to fetch MODIS data outside the requested place."
                ),
                "code": "boundary_unresolved",
            }
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
                coll = ee.ImageCollection(dataset_id).filterDate(y_start, y_end)
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.median()

            elif product == "surface_temperature":
                dataset_id = "MODIS/061/MOD11A1"
                vis = {"min": 10, "max": 48, "palette": ["0000ff", "00ffff", "ffff00", "ff7700", "ff0000"]}
                coll = ee.ImageCollection(dataset_id).filterDate(y_start, y_end)
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("LST_Day_1km").mean().multiply(0.02).subtract(273.15)

            elif product == "active_fires":
                dataset_id = "FIRMS"
                vis = {"min": 0, "max": 1, "palette": ["ffff00", "ff0000"]}
                coll = ee.ImageCollection(dataset_id).filterDate(y_start, y_end)
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("T21").max().gt(300)

            elif product == "snow_cover":
                dataset_id = "MODIS/061/MOD10A1"
                vis = {"bands": ["NDSI_Snow_Cover"], "min": 0, "max": 100, "palette": ["000000", "00ffff", "ffffff"]}
                coll = ee.ImageCollection(dataset_id).filterDate(y_start, y_end)
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("NDSI_Snow_Cover").max()

            elif product == "burned_area":
                dataset_id = "MODIS/061/MCD64A1"
                vis = {"bands": ["BurnDate"], "min": 1, "max": 366, "palette": ["ffff00", "ff7700", "ff0000"]}
                coll = ee.ImageCollection(dataset_id).filterDate(y_start, y_end)
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("BurnDate").max()

            elif product == "land_cover":
                dataset_id = "MODIS/061/MCD12Q1"
                vis = {
                    "bands": ["LC_Type1"],
                    "min": 1,
                    "max": 17,
                    "palette": _MODIS_IGBP_PALETTE,
                    "palette_labels": _MODIS_IGBP_LABELS,
                }
                coll = ee.ImageCollection(dataset_id).filterDate(y_start, y_end)
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("LC_Type1").first().toFloat()

            else:
                dataset_id = "MODIS/061/MOD13Q1"
                vis = {"min": 0.0, "max": 0.85, "palette": ["ffffff", "ce7e45", "df923d", "f1b555", "fcd163", "99b718", "74a901", "66a000", "529400", "3e8601", "207401", "056201", "004c00"]}
                coll = ee.ImageCollection(dataset_id).filterDate(y_start, y_end)
                if ee_geom is not None:
                    try:
                        coll = coll.filterBounds(ee_geom)
                    except Exception:
                        pass
                build_fn = lambda: coll.select("NDVI").median().multiply(0.0001)

            loop = asyncio.get_event_loop()
            image_count = await loop.run_in_executor(None, lambda: coll.size().getInfo())
            if not image_count:
                return {
                    "error": (
                        f"No MODIS {product.replace('_', ' ')} data has been published for {year}"
                        + (f" over {place_nm}" if place_nm else "")
                        + " yet. Try an earlier year."
                    ),
                    "code": "no_data",
                }
            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

            return {
                "status": "success",
                "product": product,
                "year": year,
                "date_range": [y_start, y_end],
                "year_to_date": year == today.year,
                "image_count": image_count,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
                "message": f"MODIS layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"MODIS layer failed: {exc}", "code": "gee_error"}

    async def _compare_modis_fire_history(self, args: dict) -> dict:
        """Calculate comparable annual MODIS fire/burned-area metrics per village."""
        from datetime import date, timedelta

        raw_villages = args.get("villages") or []
        raw_villages = [({"name": v} if isinstance(v, str) else v) for v in raw_villages]
        raw_villages.extend({"name": v} for v in (args.get("village_names") or []))
        if not raw_villages:
            gj = args.get("geojson") or {}
            if gj.get("type") == "FeatureCollection":
                raw_villages = gj.get("features", [])
            elif gj:
                raw_villages = [gj]
        if not raw_villages:
            return {"error": "Provide village geometries in villages or a GeoJSON FeatureCollection."}

        # Years = the year(s) asked for + the present year; no year asked ->
        # the current year only (year-to-date). See tools/fire_report.py.
        from tools.fire_report import resolve_years, compute_differences
        years, year_err = resolve_years(args)
        if year_err:
            return {"error": year_err, "code": "invalid_input"}
        start_year, end_year = years[0], years[-1]
        today = date.today()
        current_year = today.year
        workspace = args.get("_workspace")
        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            unresolved = []

            async def resolve_named(item):
                if not isinstance(item, dict):
                    return None, None
                has_geometry = bool(item.get("geojson") or item.get("geometry") or item.get("type"))
                if has_geometry or not item.get("name"):
                    return item, None
                try:
                    boundary, _ee_geom, matched_name, _bbox = await self._resolve_place_boundary({
                        "place_name": str(item["name"]),
                        "_workspace": workspace,
                        "_map_context": {},
                        "_ws": args.get("_ws"),
                    })
                except BoundaryUnresolved:
                    return None, str(item["name"])
                if boundary:
                    return {"name": matched_name or item["name"], "geojson": boundary}, None
                return None, str(item["name"])

            resolved_pairs = await asyncio.gather(*(resolve_named(item) for item in raw_villages))
            resolved_villages = []
            for item, missing in resolved_pairs:
                if item:
                    resolved_villages.append(item)
                if missing:
                    unresolved.append(missing)

            def feature_geometry(item):
                props = item.get("properties", {}) if isinstance(item, dict) else {}
                name = (item.get("name") if isinstance(item, dict) else None) or props.get("NAME") or props.get("name") or props.get("Name") or "Village"
                geom = item.get("geojson") if isinstance(item, dict) else None
                if not geom and isinstance(item, dict):
                    geom = item.get("geometry") or item
                if isinstance(geom, dict) and geom.get("type") == "Feature":
                    geom = geom.get("geometry")
                return str(name), _geojson_to_ee_geometry(geom)

            village_geoms = [feature_geometry(v) for v in resolved_villages]
            if not village_geoms:
                return {"error": "No village boundaries could be resolved.", "unresolved_villages": unresolved}

            def compute():
                # Batch all village geometries into one FeatureCollection and
                # use reduceRegions once per dataset/year. The previous
                # village-by-village loop made 42 blocking getInfo() calls for
                # seven villages over three years and often appeared hung.
                village_fc = ee.FeatureCollection([
                    ee.Feature(geom, {"village": name}) for name, geom in village_geoms
                ])
                annual_by_village = {name: {} for name, _ in village_geoms}
                partial = None
                for year in years:
                    y_end = (
                        (today + timedelta(days=1)).isoformat()
                        if year == current_year else f"{year + 1}-01-01"
                    )
                    burned_coll = ee.ImageCollection("MODIS/061/MCD64A1").filterDate(f"{year}-01-01", y_end)
                    fire_coll = ee.ImageCollection("FIRMS").filterDate(f"{year}-01-01", y_end)
                    if year == current_year:
                        def latest(coll):
                            ts = coll.aggregate_max("system:time_start").getInfo()
                            return ee.Date(ts).format("YYYY-MM-dd").getInfo() if ts else None
                        partial = {
                            "year": year,
                            "as_of": today.isoformat(),
                            "burned_area_data_through": latest(burned_coll),
                            "active_fire_data_through": latest(fire_coll),
                        }
                    burned = burned_coll.select("BurnDate").max().gt(0).selfMask()
                    burned_regions = ee.Image.pixelArea().updateMask(burned).reduceRegions(
                        collection=village_fc,
                        reducer=ee.Reducer.sum(),
                        scale=500,
                        tileScale=4,
                    ).getInfo().get("features", [])

                    fires = (fire_coll
                             .select("T21")
                             .map(lambda image: image.gt(300).rename("fire"))
                             .sum())
                    fire_regions = fires.reduceRegions(
                        collection=village_fc,
                        reducer=ee.Reducer.sum(),
                        scale=1000,
                        tileScale=4,
                    ).getInfo().get("features", [])

                    burned_values = {
                        str(f.get("properties", {}).get("village")): f.get("properties", {}).get("sum", 0)
                        for f in burned_regions
                    }
                    fire_values = {
                        str(f.get("properties", {}).get("village")): f.get("properties", {}).get("sum", 0)
                        for f in fire_regions
                    }
                    for name, _ in village_geoms:
                        annual_by_village[name][str(year)] = {
                            "burned_area_hectares": round(float(burned_values.get(name, 0) or 0) / 10000.0, 3),
                            "active_fire_pixel_days": round(float(fire_values.get(name, 0) or 0), 3),
                        }

                rows = []
                for name, _ in village_geoms:
                    annual = annual_by_village[name]
                    rows.append({"village": name, "annual": annual, "differences": compute_differences(annual, years)})
                return rows, partial

            rows, partial = await asyncio.get_event_loop().run_in_executor(None, compute)
            year_text = " vs ".join(map(str, years))
            return {
                "status": "success",
                "source": "NASA MODIS MCD64A1 burned area + FIRMS active fires via Google Earth Engine",
                "years": years,
                "start_year": start_year,
                "end_year": end_year,
                "partial_year": partial,
                "villages_count": len(rows),
                "unresolved_villages": unresolved,
                "results": rows,
                "message": (
                    f"Compared MODIS fire history for {len(rows)} area(s): {year_text}"
                    + (f" ({current_year} is year-to-date)." if partial else ".")
                ),
            }
        except Exception as exc:
            return {"error": f"MODIS fire comparison failed: {exc}", "code": "gee_error"}

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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
                "message": f"Terrain layer '{layer_title}' ({mode}) added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"DEM layer failed: {exc}", "code": "gee_error"}

    # ── 11. Multi-Class Land Cover (LULC) ─────────────────────────────────────

    # ── Land cover helpers (instance) ─────────────────────────────────────────

    @staticmethod
    def _parse_year(value: Any) -> tuple[int | None, str | None]:
        if value in (None, ""):
            return None, None
        try:
            return int(str(value).strip()[:4]), None
        except ValueError:
            return None, f"Invalid year '{value}'."

    @staticmethod
    def _place_was_requested(args: dict) -> bool:
        return any(
            str(args.get(k) or "").strip()
            for k in ("place_name", "city", "location", "study_area", "boundary_name", "place")
        ) or bool(args.get("geojson"))

    @staticmethod
    def _boundary_area_km2(boundary_geojson: Any) -> float | None:
        try:
            from pyproj import Geod
            shp = _boundary_shape(boundary_geojson)
            if shp is None:
                return None
            return abs(Geod(ellps="WGS84").geometry_area_perimeter(shp)[0]) / 1e6
        except Exception:
            return None

    async def _resolve_study_area(self, args: dict, default_radius_km: float = 5.0):
        """Boundary (or lat/lng circle) for land-cover analysis. Never a hard-coded default place."""
        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        if ee_geom is None and self._place_was_requested(args):
            raise ValueError(
                f"Could not resolve the boundary for '{args.get('place_name') or 'the requested area'}'. "
                "Refusing to compute land cover for a different area."
            )
        if ee_geom is None and args.get("lat") is not None and args.get("lng") is not None:
            import ee
            radius = float(args.get("radius_km") or default_radius_km)
            ee_geom = ee.Geometry.Point([float(args["lng"]), float(args["lat"])]).buffer(radius * 1000.0)
            loop = asyncio.get_event_loop()
            b_geojson = await loop.run_in_executor(None, ee_geom.getInfo)
            place_nm = place_nm or f"{radius:g} km around ({float(args['lat']):.4f}, {float(args['lng']):.4f})"
        if ee_geom is None:
            raise ValueError(
                "A study area is required: pass place_name, a boundary GeoJSON, select a polygon on the map, "
                "or pass lat/lng with radius_km."
            )
        return b_geojson, ee_geom, place_nm, bbox

    # ── 11. Land Cover layer ──────────────────────────────────────────────────

    async def _get_land_cover(self, args: dict) -> dict:
        from datetime import date

        requested_source = (args.get("source") or "auto").strip().lower()
        year, year_err = self._parse_year(args.get("year"))
        if year_err:
            return {"error": year_err, "code": "invalid_input"}
        title = (args.get("title") or "").strip()
        workspace = args.get("_workspace")

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        b_geojson, ee_geom, place_nm, bbox = await self._resolve_place_boundary(args)
        if self._place_was_requested(args) and ee_geom is None:
            return {
                "error": f"Could not resolve the boundary for '{args.get('place_name') or 'the requested area'}'. "
                         "Refusing to fetch land cover outside the requested place.",
                "code": "boundary_unresolved",
            }

        loop = asyncio.get_event_loop()
        source = _lc_resolve_source(requested_source, year)
        if source not in _LC_SOURCE_LABELS:
            return {"error": f"Unknown land cover source '{source}'.", "code": "invalid_input"}
        if year is None:
            # No year mentioned → latest year the chosen product has.
            available = await loop.run_in_executor(None, _lc_available_years, source)
            year = date.today().year if source == "dynamic_world" else available[-1]
        year_error = await loop.run_in_executor(None, _lc_year_error, source, year)
        if year_error:
            return {"error": year_error, "code": "no_data", "source": source, "year": year}

        label = source.replace("_", " ").title()
        layer_title = title or (f"Land Cover ({label} {year})" + (f" - {place_nm}" if place_nm else ""))
        if place_nm and place_nm.lower() not in layer_title.lower():
            layer_title = f"{layer_title} - {place_nm}"

        try:
            import ee

            if source == "dynamic_world":
                dw_palette = ["419BDF", "397D49", "88B053", "7A87C6", "E49635", "DFC35A", "C4281B", "A59B8F", "B39FE1"]
                dw_classes = ["Water", "Trees", "Grass", "Flooded Vegetation", "Crops", "Shrub & Scrub", "Built Area", "Bare Ground", "Snow & Ice"]
                vis = {"min": 0, "max": 8, "palette": dw_palette, "palette_labels": dw_classes}
                dataset_id = _DW_ID

                def count_images():
                    c = ee.ImageCollection(_DW_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01")
                    if ee_geom is not None:
                        c = c.filterBounds(ee_geom)
                    return c.size().getInfo()

                if not await loop.run_in_executor(None, count_images):
                    return {
                        "error": f"No Dynamic World scenes for {year}" + (f" over {place_nm}" if place_nm else "") + ".",
                        "code": "no_data",
                    }
                build_fn = lambda: _lc_class_image("dynamic_world", year, ee_geom)  # noqa: E731

            elif source == "esa_worldcover":
                dataset_id = _ESA_WORLDCOVER_YEARS[year]
                esa_values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
                esa_palette = ["006400", "ffbb22", "ffff4c", "f096ff", "fa0000", "b4b4b4", "f0f0f0", "0064c8", "0096a0", "00cf75", "fae6a0"]
                esa_classes = ["Trees", "Shrubland", "Grassland", "Cropland", "Built-up", "Barren", "Snow & Ice", "Open Water", "Wetland", "Mangroves", "Moss & Lichen"]
                # Remap the non-contiguous class codes so each class gets its exact colour.
                vis = {"min": 0, "max": 10, "palette": esa_palette, "palette_labels": esa_classes}
                build_fn = lambda: _lc_class_image("esa_worldcover", year).remap(esa_values, list(range(11)))  # noqa: E731

            elif source == "modis_landcover":
                dataset_id = _MODIS_LC_ID
                vis = {
                    "bands": ["LC_Type1"],
                    "min": 1,
                    "max": 17,
                    "palette": _MODIS_IGBP_PALETTE,
                    "palette_labels": _MODIS_IGBP_LABELS,
                }
                build_fn = lambda: (  # noqa: E731
                    ee.ImageCollection(_MODIS_LC_ID)
                    .filter(ee.Filter.calendarRange(year, year, "year"))
                    .select("LC_Type1").first().toFloat()
                )

            else:  # copernicus_landcover
                dataset_id = "COPERNICUS/Landcover/100m/Proba-V-C3/Global"
                vis = {"bands": ["discrete_classification"], "min": 0, "max": 200}
                build_fn = lambda: (  # noqa: E731
                    ee.ImageCollection(dataset_id)
                    .filter(ee.Filter.calendarRange(year, year, "year"))
                    .select("discrete_classification").first()
                )

            map_id, tile_url = await self._tile_proxy(build_fn, vis, ee_geom)

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }
            note = _lc_year_notes(source, year)
            return {
                "status": "success",
                "source": source,
                "source_label": _LC_SOURCE_LABELS[source],
                "year": year,
                "year_note": note,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
                "message": f"Land cover layer '{layer_title}' added to map" + (f" for {place_nm}." if place_nm else ".")
                + (f" Note: {note}" if note else ""),
            }

        except Exception as exc:
            return {"error": f"Land cover layer failed: {exc}", "code": "gee_error"}

    # ── Land cover zonal statistics (single year) ─────────────────────────────

    async def _analyze_land_use_zonal_stats(self, args: dict) -> dict:
        from datetime import date

        year, year_err = self._parse_year(args.get("year"))
        if year_err:
            return {"error": year_err, "code": "invalid_input"}
        workspace = args.get("_workspace")
        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            b_geojson, ee_geom, place_nm, _bbox = await self._resolve_study_area(args)
        except ValueError as exc:
            return {"error": str(exc), "code": "boundary_unresolved"}

        loop = asyncio.get_event_loop()
        source = _lc_resolve_source(args.get("source"), year)
        if source not in _LC_GROUP_REMAP:
            return {"error": f"Zonal statistics support dynamic_world, modis_landcover or esa_worldcover (got '{source}').", "code": "invalid_input"}
        if year is None:
            available = await loop.run_in_executor(None, _lc_available_years, source)
            year = date.today().year if source == "dynamic_world" else available[-1]
        year_error = await loop.run_in_executor(None, _lc_year_error, source, year)
        if year_error:
            return {"error": year_error, "code": "no_data", "source": source, "year": year}

        class_names = {
            "dynamic_world": {i: n for i, n in enumerate(["Water", "Trees", "Grass", "Flooded Vegetation", "Crops", "Shrub & Scrub", "Built Area", "Bare Ground", "Snow & Ice"])},
            "modis_landcover": {i + 1: n for i, n in enumerate(_MODIS_IGBP_LABELS)},
            "esa_worldcover": dict(zip([10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100], ["Trees", "Shrubland", "Grassland", "Cropland", "Built-up", "Barren", "Snow & Ice", "Open Water", "Wetland", "Mangroves", "Moss & Lichen"])),
        }[source]
        values, groups = _LC_GROUP_REMAP[source]
        value_to_group = dict(zip(values, groups))
        scale = _lc_reduce_scale(source, self._boundary_area_km2(b_geojson))

        try:
            import ee

            def run_zonal():
                if source == "dynamic_world":
                    n = ee.ImageCollection(_DW_ID).filterDate(f"{year}-01-01", f"{year + 1}-01-01").filterBounds(ee_geom).size().getInfo()
                    if not n:
                        raise ValueError(f"No Dynamic World scenes for {year} over this area.")
                lc = _lc_class_image(source, year, ee_geom)
                stats = ee.Image.pixelArea().addBands(lc).reduceRegion(
                    reducer=ee.Reducer.sum().group(groupField=1, groupName="class_id"),
                    geometry=ee_geom,
                    scale=scale,
                    maxPixels=int(1e10),
                    tileScale=4,
                ).getInfo()
                return stats.get("groups", [])

            groups_out = await loop.run_in_executor(None, run_zonal)
            total_m2 = sum(float(g.get("sum", 0)) for g in groups_out) or 1.0
            breakdown = []
            harmonised = {g: 0.0 for g in LC_GROUPS}
            for g in groups_out:
                cid = int(g.get("class_id", 0))
                area_m2 = float(g.get("sum", 0))
                gi = value_to_group.get(cid)
                if gi is not None:
                    harmonised[LC_GROUPS[gi]] += area_m2
                breakdown.append({
                    "class_id": cid,
                    "class_name": class_names.get(cid, f"Class {cid}"),
                    "area_km2": round(area_m2 / 1e6, 4),
                    "area_hectares": round(area_m2 / 1e4, 2),
                    "percentage": round(area_m2 / total_m2 * 100, 2),
                })
            breakdown.sort(key=lambda r: r["area_km2"], reverse=True)
            harmonised_rows = [
                {"group": k, "area_km2": round(v / 1e6, 4), "percentage": round(v / total_m2 * 100, 2)}
                for k, v in harmonised.items() if v > 0
            ]
            dominant = breakdown[0]["class_name"] if breakdown else "Unknown"
            note = _lc_year_notes(source, year)
            return {
                "status": "success",
                "year": year,
                "year_note": note,
                "source": _LC_SOURCE_LABELS[source],
                "source_id": source,
                "scale_m": scale,
                "zonal_analysis": {
                    "total_area_km2": round(total_m2 / 1e6, 4),
                    "dominant_land_use": dominant,
                    "breakdown": breakdown,
                    "harmonised_breakdown": harmonised_rows,
                },
                "place_name": place_nm,
                "clipped_to_boundary": True,
                "boundary_geojson": b_geojson if place_nm else None,
                "message": (
                    f"Zonal land-use analysis for {year}" + (f" ({place_nm})" if place_nm else "")
                    + f" from {_LC_SOURCE_LABELS[source]}. Total area {round(total_m2 / 1e6, 2)} km²; dominant: {dominant}."
                    + (f" Note: {note}" if note else "")
                ),
            }
        except Exception as exc:
            return {"error": f"Zonal land use analysis failed: {exc}", "code": "gee_error"}

    # ── Land cover time series (multi-year trend + line chart) ────────────────

    async def _analyze_land_cover_timeseries(self, args: dict) -> dict:
        from concurrent.futures import ThreadPoolExecutor
        from datetime import date

        current = date.today().year
        start, s_err = self._parse_year(args.get("start_year") or args.get("year_start"))
        end, e_err = self._parse_year(args.get("end_year") or args.get("year_end"))
        if s_err or e_err:
            return {"error": s_err or e_err, "code": "invalid_input"}
        end = end or current
        start = start or (end - 10)
        if start > end:
            start, end = end, start
        if start < 2001 or end > current:
            return {"error": f"Land cover time series are available for 2001–{current}.", "code": "invalid_input"}
        if end - start > 30:
            return {"error": "At most 31 years per time series.", "code": "invalid_input"}
        metric = (args.get("metric") or "percent").strip().lower()
        if metric not in ("percent", "area_km2"):
            metric = "percent"
        requested_source = (args.get("source") or "auto").strip().lower()
        make_chart = args.get("create_chart", True) is not False
        workspace = args.get("_workspace")

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}
        try:
            b_geojson, ee_geom, place_nm, bbox = await self._resolve_study_area(args)
        except ValueError as exc:
            return {"error": str(exc), "code": "boundary_unresolved"}

        loop = asyncio.get_event_loop()
        modis_latest = await loop.run_in_executor(None, _modis_lc_latest_year)
        requested_years = list(range(start, end + 1))

        # Plan which product computes which years. Never mix products within one line.
        plan: list[tuple[str, list[int]]] = []
        if requested_source in ("", "auto"):
            if start < _DW_FIRST_FULL_YEAR:
                modis_years = [y for y in requested_years if y <= modis_latest]
                if modis_years:
                    plan.append(("modis_landcover", modis_years))
                if end > modis_latest or end >= _DW_FIRST_FULL_YEAR:
                    dw_years = [y for y in requested_years if y >= _DW_FIRST_FULL_YEAR]
                    if dw_years and end > modis_latest:
                        plan.append(("dynamic_world", dw_years))
            else:
                plan.append(("dynamic_world", requested_years))
        else:
            if requested_source not in _LC_GROUP_REMAP:
                return {"error": f"Time series support auto, dynamic_world, modis_landcover or esa_worldcover (got '{requested_source}').", "code": "invalid_input"}
            avail = set(await loop.run_in_executor(None, _lc_available_years, requested_source))
            plan.append((requested_source, [y for y in requested_years if y in avail]))
        plan = [(s, ys) for s, ys in plan if ys]
        if not plan:
            return {"error": f"No land cover product has data for {start}–{end}.", "code": "no_data"}

        area_km2 = self._boundary_area_km2(b_geojson)

        try:
            import ee

            def compute_source(source: str, years: list[int]) -> dict[int, dict[str, float]]:
                scale = _lc_reduce_scale(source, area_km2)
                if source == "dynamic_world":
                    sizes = ee.Dictionary({
                        str(y): ee.ImageCollection(_DW_ID).filterDate(f"{y}-01-01", f"{y + 1}-01-01").filterBounds(ee_geom).size()
                        for y in years
                    }).getInfo()
                    years = [y for y in years if sizes.get(str(y))]

                def one_year(y: int) -> tuple[int, dict[str, float]]:
                    stats = ee.Image.pixelArea().addBands(_lc_group_image(source, y, ee_geom)).reduceRegion(
                        reducer=ee.Reducer.sum().group(groupField=1, groupName="g"),
                        geometry=ee_geom,
                        scale=scale,
                        maxPixels=int(1e10),
                        tileScale=4,
                    ).getInfo()
                    out = {g: 0.0 for g in LC_GROUPS}
                    for row in stats.get("groups", []):
                        gi = int(row.get("g", -1))
                        if 0 <= gi < len(LC_GROUPS):
                            out[LC_GROUPS[gi]] += float(row.get("sum", 0)) / 1e6
                    return y, out

                with ThreadPoolExecutor(max_workers=6) as pool:
                    return dict(pool.map(one_year, years))

            results: dict[str, dict[int, dict[str, float]]] = {}
            for source, years in plan:
                results[source] = await loop.run_in_executor(None, compute_source, source, years)

            covered = {y for per_year in results.values() for y in per_year}
            missing_years = [y for y in requested_years if y not in covered]

            series_out: list[dict] = []
            panels: list[dict] = []
            for source, per_year in results.items():
                if not per_year:
                    continue
                yrs = sorted(per_year)
                table = {}
                for y in yrs:
                    total = sum(per_year[y].values()) or 1.0
                    table[str(y)] = {
                        g: {"area_km2": round(v, 4), "percent": round(v / total * 100, 2)}
                        for g, v in per_year[y].items() if v > 0
                    }
                # Classes that are present (≥0.1 % in any year) get a line.
                present = [
                    g for g in LC_GROUPS
                    if any(table[str(y)].get(g, {}).get("percent", 0) >= 0.1 for y in yrs)
                ]
                x_all = [y for y in requested_years if (yrs[0] <= y <= yrs[-1])]
                lines = {
                    g: [
                        (table[str(y)][g][metric] if g in table.get(str(y), {}) else (0.0 if str(y) in table else None))
                        for y in x_all
                    ]
                    for g in present
                }
                first, last = str(yrs[0]), str(yrs[-1])
                change = {
                    g: {
                        "from_year": yrs[0], "to_year": yrs[-1],
                        "percent_points": round(table[last].get(g, {}).get("percent", 0) - table[first].get(g, {}).get("percent", 0), 2),
                        "area_km2": round(table[last].get(g, {}).get("area_km2", 0) - table[first].get(g, {}).get("area_km2", 0), 4),
                    }
                    for g in present
                }
                notes = [n for n in (_lc_year_notes(source, y) for y in yrs) if n]
                series_out.append({
                    "source": source,
                    "source_label": _LC_SOURCE_LABELS[source],
                    "years": yrs,
                    "table": table,
                    "change_first_to_last": change,
                    "notes": notes,
                })
                panels.append({
                    "subtitle": f"{_LC_SOURCE_LABELS[source]} · {yrs[0]}–{yrs[-1]}" + (" (latest year YTD)" if yrs[-1] == current and source == "dynamic_world" else ""),
                    "x": x_all,
                    "series": lines,
                    "colors": {g: LC_GROUP_COLORS[LC_GROUPS.index(g)] for g in present},
                })

            place_label = place_nm or "Study area"
            title = f"Land Cover Change — {place_label} ({start}–{end})"
            chart = None
            if make_chart and panels:
                from tools.charts import normalise_spec, save_chart
                footnote = (
                    "Different products use different sensors and resolutions; compare trends within a panel, not absolute "
                    "values across panels." if len(panels) > 1 else ""
                )
                if missing_years:
                    footnote = (footnote + " " if footnote else "") + f"No data: {', '.join(map(str, missing_years))}."
                footnote = (footnote + " " if footnote else "") + f"Computed inside the {place_label} boundary ({round(area_km2, 2) if area_km2 else '?'} km²)."
                spec = normalise_spec({
                    "plot_type": "line", "title": title, "panels": panels, "x_label": "Year",
                    "y_label": "Share of area (%)" if metric == "percent" else "Area (km²)",
                    "y_suffix": "%" if metric == "percent" else "", "footnote": footnote,
                })
                chart = await loop.run_in_executor(None, lambda: save_chart(spec, workspace, overwrite=True))

            return {
                "status": "success",
                "place_name": place_nm,
                "start_year": start,
                "end_year": end,
                "metric": metric,
                "total_area_km2": round(area_km2, 4) if area_km2 else None,
                "series": series_out,
                "missing_years": missing_years,
                "chart": chart,
                "chart_artifact_id": chart["artifact_id"] if chart else None,
                "clipped_to_boundary": True,
                "message": (
                    f"Land cover trend for {place_label} {start}–{end} computed from "
                    + " and ".join(f"{_LC_SOURCE_LABELS[s['source']]} ({s['years'][0]}–{s['years'][-1]})" for s in series_out)
                    + (f"; no data for {', '.join(map(str, missing_years))}" if missing_years else "")
                    + (f". Line chart saved as artifact {chart['artifact_id']}." if chart else ".")
                ),
            }
        except Exception as exc:
            return {"error": f"Land cover time series failed: {exc}", "code": "gee_error"}


    # ── Population & building growth (backend analysis + chart, boundary-only) ──

    async def _timeseries_setup(self, args: dict, default_span: int = 10):
        """Common year-range / boundary / EE setup for growth analyses."""
        from datetime import date
        current = date.today().year
        start, s_err = self._parse_year(args.get("start_year") or args.get("year_start"))
        end, e_err = self._parse_year(args.get("end_year") or args.get("year_end"))
        if s_err or e_err:
            raise ValueError(s_err or e_err)
        end = end or current
        start = start or (end - default_span)
        if start > end:
            start, end = end, start
        ok, err = await _ensure_gee(args.get("_workspace"))
        if not ok:
            raise RuntimeError(err)
        b_geojson, ee_geom, place_nm, _bbox = await self._resolve_study_area(args)
        return start, end, current, b_geojson, ee_geom, place_nm, self._boundary_area_km2(b_geojson)

    @staticmethod
    def _parallel_years(fn, years: list[int]) -> dict[int, Any]:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            return dict(zip(years, pool.map(fn, years)))

    async def _analyze_population_timeseries(self, args: dict) -> dict:
        try:
            start, end, current, b_geojson, ee_geom, place_nm, area_km2 = await self._timeseries_setup(args, 15)
        except BoundaryUnresolved as exc:
            return {"error": str(exc), "code": "boundary_unresolved"}
        except ValueError as exc:
            return {"error": str(exc), "code": "boundary_unresolved" if "boundary" in str(exc).lower() else "invalid_input"}
        except RuntimeError as exc:
            return {"error": str(exc), "code": "upstream_unavailable"}
        loop = asyncio.get_event_loop()
        years = list(range(start, end + 1))
        wp_years = [y for y in years if 2000 <= y <= 2020]
        ghs_years = [y for y in years if y % 5 == 0 and 1975 <= y <= 2030]
        if end > 2020 and start <= 2025:
            # Requested years after the last census-based epoch: include GHSL 2025 (projected).
            ghs_years.append(2025)
        ghs_years = sorted(set(ghs_years))

        try:
            import ee

            def wp(y):
                img = ee.ImageCollection("WorldPop/GP/100m/pop").filterBounds(ee_geom).filter(ee.Filter.eq("year", y)).mosaic()
                v = img.select("population").reduceRegion(ee.Reducer.sum(), ee_geom, 100, maxPixels=int(1e10), tileScale=4).getInfo()
                return v.get("population")

            def ghs(y):
                img = ee.ImageCollection("JRC/GHSL/P2023A/GHS_POP").filter(ee.Filter.calendarRange(y, y, "year")).first()
                v = img.select("population_count").reduceRegion(ee.Reducer.sum(), ee_geom, 100, maxPixels=int(1e10), tileScale=4).getInfo()
                return v.get("population_count")

            wp_vals = await loop.run_in_executor(None, self._parallel_years, wp, wp_years) if wp_years else {}
            ghs_vals = await loop.run_in_executor(None, self._parallel_years, ghs, ghs_years) if ghs_years else {}
        except Exception as exc:
            return {"error": f"Population time series failed: {exc}", "code": "gee_error"}

        def rnd(v):
            return None if v is None else int(round(float(v)))

        x = sorted(set(years) | set(ghs_years))
        series = {}
        if wp_vals:
            series["WorldPop (annual, 100 m)"] = [rnd(wp_vals.get(y)) if y in wp_vals else None for y in x]
        if ghs_vals:
            series["GHS-POP (5-yearly; 2025/2030 projected)"] = [rnd(ghs_vals.get(y)) if y in ghs_vals else None for y in x]
        missing = [y for y in years if y not in wp_vals and y not in ghs_vals]
        place_label = place_nm or "Study area"
        chart = None
        if args.get("create_chart", True) is not False and series:
            from tools.charts import normalise_spec, save_chart
            spec = normalise_spec({
                "plot_type": "line", "title": f"Population Growth — {place_label} ({start}–{end})",
                "x_data": x, "series": series, "x_label": "Year", "y_label": "Population",
                "connect": ["GHS-POP (5-yearly; 2025/2030 projected)"],
                "footnote": (
                    f"Sum of gridded population inside the {place_label} boundary ({round(area_km2 or 0, 2)} km²). "
                    "Years without a data release are left blank"
                    + (f" ({', '.join(map(str, missing))})" if missing else "") + ". GHS-POP 2025/2030 are model projections."
                ),
            })
            chart = await loop.run_in_executor(None, lambda: save_chart(spec, args.get("_workspace"), overwrite=True))

        def growth(vals: dict):
            ks = sorted(k for k, v in vals.items() if v)
            if len(ks) < 2:
                return None
            a, b = vals[ks[0]], vals[ks[-1]]
            yrs = ks[-1] - ks[0]
            return {"from_year": ks[0], "to_year": ks[-1], "change": rnd(b - a), "percent": round((b - a) / a * 100, 2),
                    "cagr_percent": round(((b / a) ** (1 / yrs) - 1) * 100, 3) if yrs else None}

        return {
            "status": "success",
            "place_name": place_nm,
            "area_km2": round(area_km2, 3) if area_km2 else None,
            "worldpop_annual": {str(k): rnd(v) for k, v in sorted(wp_vals.items())},
            "ghs_pop_5yearly": {str(k): rnd(v) for k, v in sorted(ghs_vals.items())},
            "ghs_projected_years": [y for y in ghs_vals if y > 2020],
            "growth_worldpop": growth(wp_vals),
            "growth_ghs_pop": growth(ghs_vals),
            "years_without_data": missing,
            "density_per_km2_latest": (
                round(float(ghs_vals.get(max(k for k in ghs_vals if k <= current)) or 0) / area_km2, 1)
                if ghs_vals and area_km2 and any(k <= current for k in ghs_vals) else None
            ),
            "chart": chart,
            "chart_artifact_id": chart["artifact_id"] if chart else None,
            "clipped_to_boundary": True,
            "message": f"Population inside the {place_label} boundary computed for {start}–{end}" + (f"; chart saved as artifact {chart['artifact_id']}." if chart else "."),
        }

    async def _analyze_building_growth(self, args: dict) -> dict:
        try:
            start, end, current, b_geojson, ee_geom, place_nm, area_km2 = await self._timeseries_setup(args, 10)
        except BoundaryUnresolved as exc:
            return {"error": str(exc), "code": "boundary_unresolved"}
        except ValueError as exc:
            return {"error": str(exc), "code": "boundary_unresolved" if "boundary" in str(exc).lower() else "invalid_input"}
        except RuntimeError as exc:
            return {"error": str(exc), "code": "upstream_unavailable"}
        loop = asyncio.get_event_loop()
        years = list(range(start, end + 1))
        ob_years = [y for y in years if 2016 <= y <= 2023]
        ghs_years = sorted({y for y in years if y % 5 == 0 and 1975 <= y <= 2030} | ({2025} if end >= 2021 and start <= 2025 else set()))
        # Open Buildings is ~0.5 m effective resolution delivered on a 4 m grid.
        ob_scale = 4 if (area_km2 or 0) <= 400 else (10 if (area_km2 or 0) <= 3000 else 30)

        try:
            import ee

            def ob(y):
                coll = (ee.ImageCollection("GOOGLE/Research/open-buildings-temporal/v1")
                        .filterBounds(ee_geom).filter(ee.Filter.calendarRange(y, y, "year")))
                # Native grid is 0.5 m (UTM). Sample on that grid at ob_scale so the
                # sample is regular/unbiased; per-pixel COUNTS must then be scaled by
                # (ob_scale / 0.5)² — areas use pixelArea and need no correction.
                native_crs = coll.first().select("building_presence").projection().crs()
                img = coll.mosaic()
                presence = img.select("building_presence").gte(0.5)
                height = img.select("building_height").updateMask(presence)
                px = ee.Image.pixelArea()
                stack = (px.updateMask(presence).rename("footprint_m2")
                         .addBands(height.multiply(px).rename("volume_m3"))
                         .addBands(img.select("building_fractional_count").rename("count")))
                sums = stack.reduceRegion(ee.Reducer.sum(), ee_geom, ob_scale, crs=native_crs,
                                          maxPixels=int(1e11), tileScale=16).getInfo()
                sums["count"] = float(sums.get("count") or 0) * (ob_scale / 0.5) ** 2
                med = height.reduceRegion(ee.Reducer.median(), ee_geom, max(ob_scale, 10), crs=native_crs,
                                          maxPixels=int(1e11), tileScale=16).getInfo()
                return {**sums, "median_height": med.get("building_height")}

            def ghs(y):
                s_img = ee.ImageCollection("JRC/GHSL/P2023A/GHS_BUILT_S").filter(ee.Filter.calendarRange(y, y, "year")).first()
                v_img = ee.ImageCollection("JRC/GHSL/P2023A/GHS_BUILT_V").filter(ee.Filter.calendarRange(y, y, "year")).first()
                stack = s_img.select(["built_surface", "built_surface_nres"]).addBands(v_img.select(["built_volume_total", "built_volume_nres"]))
                return stack.reduceRegion(ee.Reducer.sum(), ee_geom, 100, maxPixels=int(1e10), tileScale=4).getInfo()

            ob_vals = await loop.run_in_executor(None, self._parallel_years, ob, ob_years) if ob_years else {}
            ghs_vals = await loop.run_in_executor(None, self._parallel_years, ghs, ghs_years) if ghs_years else {}
        except Exception as exc:
            return {"error": f"Building growth analysis failed: {exc}", "code": "gee_error"}

        ob_table = {}
        for y, v in sorted(ob_vals.items()):
            fp = float(v.get("footprint_m2") or 0)
            vol = float(v.get("volume_m3") or 0)
            ob_table[str(y)] = {
                "footprint_km2": round(fp / 1e6, 4),
                "footprint_share_percent": round(fp / 1e6 / area_km2 * 100, 3) if area_km2 else None,
                "building_count": int(round(float(v.get("count") or 0))),
                "mean_height_m": round(vol / fp, 2) if fp else None,
                "median_height_m": round(float(v["median_height"]), 2) if v.get("median_height") is not None else None,
                "built_volume_million_m3": round(vol / 1e6, 3),
            }
        ghs_table = {}
        for y, v in sorted(ghs_vals.items()):
            surf = float(v.get("built_surface") or 0)
            vol = float(v.get("built_volume_total") or 0)
            ghs_table[str(y)] = {
                "built_surface_km2": round(surf / 1e6, 4),
                "non_residential_surface_km2": round(float(v.get("built_surface_nres") or 0) / 1e6, 4),
                "built_volume_million_m3": round(vol / 1e6, 3),
                "avg_height_m": round(vol / surf, 2) if surf else None,
                "projected": y > 2020,
            }

        x = sorted(set(years) | {int(k) for k in ghs_table})
        def col(table, key):
            return [table.get(str(y), {}).get(key) for y in x]
        OB, GH = "Open Buildings Temporal (yearly)", "GHSL (5-yearly; 2025/2030 projected)"
        colors = {OB: "#2563eb", GH: "#f97316"}
        panels = [
            {"subtitle": "Horizontal growth — built-up footprint (km²)", "x": x, "colors": colors, "connect": [GH], "series": {
                **({OB: col(ob_table, "footprint_km2")} if ob_table else {}),
                **({GH: col(ghs_table, "built_surface_km2")} if ghs_table else {}),
            }},
            {"subtitle": "Vertical growth — average building height (m)", "x": x, "colors": colors, "connect": [GH], "series": {
                **({OB: col(ob_table, "mean_height_m")} if ob_table else {}),
                **({GH: col(ghs_table, "avg_height_m")} if ghs_table else {}),
            }},
            {"subtitle": "Built volume (million m³)", "x": x, "colors": colors, "connect": [GH], "series": {
                **({OB: col(ob_table, "built_volume_million_m3")} if ob_table else {}),
                **({GH: col(ghs_table, "built_volume_million_m3")} if ghs_table else {}),
            }},
        ]
        panels = [p for p in panels if p["series"]]
        place_label = place_nm or "Study area"
        missing = [y for y in years if str(y) not in ob_table and str(y) not in ghs_table]
        chart = None
        if args.get("create_chart", True) is not False and panels:
            from tools.charts import normalise_spec, save_chart
            spec = normalise_spec({
                "plot_type": "line", "title": f"Building Growth — {place_label} ({start}–{end})", "panels": panels,
                "x_label": "Year",
                "footnote": (
                    f"Computed inside the {place_label} boundary ({round(area_km2 or 0, 2)} km²). Open Buildings Temporal covers 2016–2023 "
                    f"(sampled at {ob_scale} m); GHSL is 5-yearly at 100 m. Years without data are blank"
                    + (f" ({', '.join(map(str, missing))})" if missing else "") + "."
                ),
            })
            chart = await loop.run_in_executor(None, lambda: save_chart(spec, args.get("_workspace"), overwrite=True))

        def change(table, key):
            ks = [k for k in table if table[k].get(key) is not None]
            if len(ks) < 2:
                return None
            a, b = table[ks[0]][key], table[ks[-1]][key]
            return {"from_year": int(ks[0]), "to_year": int(ks[-1]), "change": round(b - a, 4),
                    "percent": round((b - a) / a * 100, 2) if a else None}

        return {
            "status": "success",
            "place_name": place_nm,
            "area_km2": round(area_km2, 3) if area_km2 else None,
            "open_buildings": ob_table,
            "ghsl": ghs_table,
            "horizontal_change": {"open_buildings_footprint_km2": change(ob_table, "footprint_km2"), "ghsl_built_surface_km2": change(ghs_table, "built_surface_km2")},
            "vertical_change": {"open_buildings_mean_height_m": change(ob_table, "mean_height_m"), "ghsl_avg_height_m": change(ghs_table, "avg_height_m")},
            "building_count_change": change(ob_table, "building_count"),
            "years_without_data": missing,
            "chart": chart,
            "chart_artifact_id": chart["artifact_id"] if chart else None,
            "clipped_to_boundary": True,
            "message": f"Building growth inside the {place_label} boundary computed for {start}–{end}" + (f"; chart saved as artifact {chart['artifact_id']}." if chart else "."),
        }

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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
                "message": f"Geophysical layer '{layer_title}' ({desc}) added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"Geophysical layer failed: {exc}", "code": "gee_error"}

    # ── 14. Search Earth Engine Catalog ───────────────────────────────────────

    async def _search_gee_datasets(self, args: dict) -> dict:
        query = (args.get("query") or "").strip().lower()
        category = (args.get("category") or "").strip().lower()
        limit = int(args.get("limit") or 25)

        loop = asyncio.get_event_loop()
        catalog = await loop.run_in_executor(None, _load_full_catalog)
        terms = _expand_query_terms(query) if query else []
        cat_words = _CATEGORY_KEYWORDS.get(category, [category]) if category else []

        scored: list[tuple[float, dict]] = []
        for entry in catalog:
            if category:
                hay = f"{entry.get('category', '')} {entry.get('tags', '')} {entry.get('title', '')} {entry.get('id', '')}".lower()
                if entry.get("category") != category and not any(w in hay for w in cat_words):
                    continue
            score = _score_catalog_entry(entry, query, terms) if query else (1.0 if entry.get("desc") else 0.5)
            if query and score <= 0.5:
                continue
            scored.append((score, entry))
        scored.sort(key=lambda t: (-t[0], t[1].get("title", "")))

        datasets = []
        for _, entry in scored[:limit]:
            ds_type = entry.get("type") or "unknown"
            item = {
                "id": entry["id"],
                "name": entry.get("title"),
                "type": ds_type,
                "layer_kind": _layer_kind(ds_type),
                "category": entry.get("category") or "",
                "provider": entry.get("provider") or "",
                "date_range": f"{entry.get('start_date', '')} – {entry.get('end_date', '')}".strip(" –"),
                "tags": entry.get("tags") or "",
                "recommended_tool": (
                    "extract_water_streams" if entry["id"] == _HYDRO_RIVERS_ID else "add_gee_layer"
                ),
            }
            if entry.get("bands"):
                item["bands"] = entry["bands"]
            if entry.get("res"):
                item["res"] = entry["res"]
            if entry.get("desc"):
                item["desc"] = entry["desc"]
            datasets.append(item)

        return {
            "status": "success",
            "query": query,
            "category": category or "all",
            "catalog_size": len(catalog),
            "count": len(datasets),
            "datasets": datasets,
            "hint": "Pass a dataset 'id' to add_gee_layer(dataset=..., place_name=...) to render it (raster or vector).",
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
                        raise ValueError("A target location (place_name, geojson, or lat/lng) is required to calculate zonal statistics.")

                if is_collection:
                    d_lower = dataset.lower()
                    if "worldpop" in d_lower:
                        coll = ee.ImageCollection(dataset).filter(ee.Filter.eq("year", min(max(year, 2000), 2020)))
                    else:
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

                reducer = ee.Reducer.mean().combine(
                    ee.Reducer.minMax(), sharedInputs=True
                ).combine(
                    ee.Reducer.stdDev(), sharedInputs=True
                )
                if hasattr(ee.Reducer, "sum"):
                    try:
                        reducer = reducer.combine(ee.Reducer.sum(), sharedInputs=True)
                    except Exception:
                        pass

                stats = target_img.reduceRegion(
                    reducer=reducer,
                    geometry=stats_geom,
                    scale=100,
                    maxPixels=1_000_000_000,
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
        if any(k in p_lower for k in (
            "india", "chandigarh", "delhi", "mumbai", "bengaluru", "bangalore", "punjab", "haryana",
            "kolkata", "chennai", "karnataka", "maharashtra", "tamil nadu", "gujarat", "rajasthan",
            "kerala", "hyderabad", "pune", "ahmedabad", "jaipur", "lucknow", "kanpur", "nagpur",
            "indore", "bhopal", "patna", "vadodara", "ghaziabad", "ludhiana", "agra", "nashik",
            "faridabad", "meerut", "rajkot", "varanasi", "srinagar", "amritsar", "mohali", "panchkula"
        )):
            return "IND"
        if any(k in p_lower for k in ("usa", "united states", "new york", "california", "texas", "chicago", "los angeles", "florida", "washington")):
            return "USA"
        if any(k in p_lower for k in ("uk", "united kingdom", "london", "england", "scotland", "wales")):
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
            if (lat is None or lng is None) and bbox:
                lat = (bbox["south"] + bbox["north"]) / 2
                lng = (bbox["west"] + bbox["east"]) / 2
            country_iso = self._infer_country_iso(args, place_nm or "", lat, lng)

        ok, err = await _ensure_gee(workspace)
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            vis = {
                "min": 1,
                "max": 150,
                "palette": ["fef0d9", "fdcc8a", "fc8d59", "e34a33", "b30000", "7a0177"],
                "palette_labels": ["<25 pph (Rural)", "25-75 (Suburban)", "75-150 (Urban)", "150+ pph (High-Density Core)"],
                "density_unit": "persons_per_hectare",
            }
            if args.get("vis_params"):
                vis.update(args["vis_params"])

            resolved_yr = year
            active_dataset_id = "WorldPop/GP/100m/pop"

            def build_pop():
                nonlocal resolved_yr, active_dataset_id
                palette = ["fef0d9", "fdcc8a", "fc8d59", "e34a33", "b30000", "7a0177"]

                if source in ("ghsl", "ghs") or (source == "worldpop" and year > 2020):
                    # JRC GHSL GHS-POP multitemporal 100m grid (1975-2030 epochs)
                    valid_years = [1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025, 2030]
                    resolved_yr = min(valid_years, key=lambda y: abs(y - year))
                    active_dataset_id = "JRC/GHSL/P2023A/GHS_POP"
                    coll = ee.ImageCollection(active_dataset_id).filterDate(f"{resolved_yr}-01-01", f"{resolved_yr}-12-31")
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    raw_img = coll.first()
                    if ee_geom is not None:
                        try:
                            raw_img = raw_img.clip(ee_geom)
                        except Exception:
                            pass
                    colored = raw_img.visualize(min=1, max=100, palette=palette)
                    res = colored.updateMask(raw_img.gt(0.5))
                    if ee_geom is not None:
                        try:
                            res = res.clip(ee_geom)
                        except Exception:
                            pass
                    return res
                elif source == "worldpop":
                    resolved_yr = min(max(year, 2000), 2020)
                    active_dataset_id = "WorldPop/GP/100m/pop"
                    coll = ee.ImageCollection(active_dataset_id).filter(ee.Filter.eq("year", resolved_yr))
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    elif country_iso:
                        coll = coll.filter(ee.Filter.eq("country", country_iso))
                    raw_img = coll.mosaic()
                    if ee_geom is not None:
                        try:
                            raw_img = raw_img.clip(ee_geom)
                        except Exception:
                            pass
                    colored = raw_img.visualize(min=1, max=100, palette=palette)
                    # Mask out zeros / unpopulated agricultural lands so basemap shows through cleanly
                    res = colored.updateMask(raw_img.gt(0.5))
                    if ee_geom is not None:
                        try:
                            res = res.clip(ee_geom)
                        except Exception:
                            pass
                    return res
                else:
                    valid_years = [2000, 2005, 2010, 2015, 2020]
                    resolved_yr = min(valid_years, key=lambda y: abs(y - year))
                    active_dataset_id = "CIESIN/GPWv411/GPW_Population_Density"
                    coll = ee.ImageCollection(active_dataset_id).filterDate(f"{resolved_yr}-01-01", f"{resolved_yr}-12-31")
                    if ee_geom is not None:
                        try:
                            coll = coll.filterBounds(ee_geom)
                        except Exception:
                            pass
                    raw_img = coll.first()
                    if ee_geom is not None:
                        try:
                            raw_img = raw_img.clip(ee_geom)
                        except Exception:
                            pass
                    colored = raw_img.visualize(min=5, max=500, palette=palette)
                    res = colored.updateMask(raw_img.gt(1.0))
                    if ee_geom is not None:
                        try:
                            res = res.clip(ee_geom)
                        except Exception:
                            pass
                    return res

            layer_title = title or (f"Population Density – {place_nm} ({year})" if place_nm else f"Population Density ({source.title()} {year})")
            if place_nm and place_nm.lower() not in layer_title.lower():
                layer_title = f"{layer_title} - {place_nm}"
            map_id, tile_url = await self._tile_proxy(build_pop, {}, ee_geom)
            dataset_id = active_dataset_id

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

            return {
                "status": "success",
                "source": source,
                "year": year,
                "resolved_year": resolved_yr,
                "country_iso": country_iso or "global",
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "tile_url": tile_url,
                "map_id": map_id,
                "dataset_id": dataset_id,
                "vis": vis,
                "layer_title": layer_title,
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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
        for _yr in (year_start, year_end):
            _dw_err = _lc_year_error("dynamic_world", _yr)
            if _dw_err:
                return {"error": _dw_err + " analyze_lulc_change uses Dynamic World; for earlier years use analyze_land_cover_timeseries.", "code": "no_data"}

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
            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }
            await self._send_layer(ws, changed_url, "GOOGLE/DYNAMICWORLD/V1", changed_vis, changed_title, bbox=bbox, centroid=centroid)
            await self._send_layer(ws, transition_url, "GOOGLE/DYNAMICWORLD/V1", transition_vis, title, bbox=bbox, centroid=centroid)

            return {
                "status": "success",
                "year_start": year_start,
                "year_end": year_end,
                "place_name": place_nm,
                "clipped_to_boundary": bool(ee_geom),
                "boundary_geojson": b_geojson if place_nm else None,
                "layers_added": 2,
                "tile_url": transition_url,
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
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

            centroid = None
            if bbox:
                centroid = {
                    "lat": round((bbox["south"] + bbox["north"]) / 2, 6),
                    "lng": round((bbox["west"] + bbox["east"]) / 2, 6),
                }

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
                "bbox": bbox,
                "bounds": bbox,
                "centroid": centroid,
                "center": centroid,
                "message": f"Layer '{title}' added to map" + (f" for {place_nm}." if place_nm else "."),
            }

        except Exception as exc:
            return {"error": f"GEE execution failed: {exc}", "code": "gee_error"}

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

        dw_year_error = _lc_year_error("dynamic_world", year)
        if dw_year_error:
            return {"error": dw_year_error, "code": "no_data"}

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
                        raise ValueError(
                            "A study boundary is required. Select a polygon layer, provide GeoJSON, "
                            "or provide a place name or coordinates; no default location is used."
                        )

                if ee_geom is None:
                    raise ValueError(
                        "Could not create a bounded Earth Engine geometry from the supplied boundary. "
                        "Provide valid GeoJSON, a place name with a resolvable boundary, or lat/lng coordinates."
                    )

                img = (
                    ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .filterBounds(ee_geom)
                    .select("label")
                    .mode()
                )

                # CRITICAL: clip the image to the exact boundary geometry BEFORE vectorizing.
                # Without .clip(), reduceToVectors produces polygons whose edges bleed outside
                # the boundary because GEE vectorizes at pixel/tile boundaries, not the supplied
                # geometry boundary. filterBounds alone only filters scenes, not pixels.
                masked = img.eq(target_idx).selfMask().clip(ee_geom)

                def extract_geom(g):
                    if g is None:
                        raise ValueError("A bounded geometry is required to extract land-use polygons.")
                    vectors = masked.reduceToVectors(
                        geometry=g,
                        scale=30,
                        maxPixels=1e9,
                        geometryType="polygon",
                        labelProperty="class_id",
                        bestEffort=True,
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

            boundary_geometry = geojson_input
            if isinstance(boundary_geometry, str):
                boundary_geometry = json.loads(boundary_geometry)

            if boundary_geometry:
                try:
                    import shapely.geometry
                    from shapely.ops import unary_union
                    boundary_type = boundary_geometry.get("type")
                    if boundary_type == "Feature":
                        b_shape = shapely.geometry.shape(boundary_geometry["geometry"])
                    elif boundary_type == "FeatureCollection":
                        boundary_shapes = [
                            shapely.geometry.shape(feature["geometry"])
                            for feature in boundary_geometry.get("features", [])
                            if feature.get("geometry")
                        ]
                        b_shape = unary_union(boundary_shapes)
                    else:
                        b_shape = shapely.geometry.shape(boundary_geometry)
                    if b_shape.is_empty:
                        raise ValueError("The study boundary is empty.")
                    clipped_features = []
                    for feat in features:
                        f_geom = feat.get("geometry")
                        if not f_geom:
                            continue
                        f_shape = shapely.geometry.shape(f_geom)
                        if b_shape.intersects(f_shape):
                            inter = b_shape.intersection(f_shape)
                            polygons = []
                            pending = [inter]
                            while pending:
                                part = pending.pop()
                                if part.geom_type == "Polygon":
                                    if part.area > 0:
                                        polygons.append(part)
                                elif hasattr(part, "geoms"):
                                    pending.extend(part.geoms)
                            if polygons:
                                clipped_shape = unary_union(polygons)
                                feat["geometry"] = shapely.geometry.mapping(clipped_shape)
                                clipped_features.append(feat)
                    features = clipped_features
                except Exception as clip_err:
                    raise ValueError(
                        f"Could not clip extracted polygons to the requested study boundary: {clip_err}"
                    ) from clip_err
            else:
                raise ValueError(
                    "A study boundary is required to clip extracted polygons; refusing to return unbounded results."
                )

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
