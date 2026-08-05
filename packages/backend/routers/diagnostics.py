"""Endpoints for running startup self-checks and diagnostics."""
from __future__ import annotations

import os
import sys
import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel
from openai import AsyncOpenAI

router = APIRouter()

class DiagnosticResult(BaseModel):
    openai_api_key: dict[str, str]
    google_maps_api_key: dict[str, str]
    overpass_api: dict[str, str]
    nominatim_api: dict[str, str]
    osrm_api: dict[str, str]
    open_meteo: dict[str, str]
    libraries: dict[str, str]
    workspace: dict[str, str]

@router.get("")
async def run_diagnostics(workspace_path: str | None = Query(None)) -> DiagnosticResult:
    # 1. Check OpenAI API Key
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not openai_key:
        openai_status = {"status": "missing", "message": "OPENAI_API_KEY is not set."}
    else:
        try:
            client = AsyncOpenAI(api_key=openai_key, timeout=5.0)
            await client.models.list()
            openai_status = {"status": "valid", "message": "OpenAI API Key is valid."}
        except Exception as e:
            openai_status = {"status": "invalid", "message": f"OpenAI API check failed: {e}"}

    # 2. Check Google Maps API Key
    google_key = (
        os.environ.get("GOOGLE_MAPS_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()
    if not google_key:
        google_status = {"status": "missing", "message": "GOOGLE_MAPS_API_KEY is not set."}
    else:
        try:
            url = "https://maps.googleapis.com/maps/api/streetview/metadata"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, params={"location": "0,0", "key": google_key})
                if resp.status_code == 200:
                    google_status = {"status": "valid", "message": "Google Maps API Key is active."}
                else:
                    google_status = {"status": "invalid", "message": f"Google API returned HTTP {resp.status_code}."}
        except Exception as e:
            google_status = {"status": "configured", "message": f"Google Maps key set. Verify status: {e}"}

    # 3. Check Overpass API (OSM)
    try:
        headers = {"User-Agent": "Disha-Diagnostic/1.0"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://overpass-api.de/api/status", headers=headers)
            if resp.status_code == 200:
                overpass_status = {"status": "online", "message": "Overpass API is online and reachable."}
            else:
                overpass_status = {"status": "degraded", "message": f"Overpass API returned HTTP {resp.status_code}."}
    except Exception as e:
        overpass_status = {"status": "offline", "message": f"Cannot reach Overpass API: {e}"}

    # 4. Check Nominatim Geocoder
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {"User-Agent": "Urban-Planner-Diagnostic/1.0"}
            resp = await client.get("https://nominatim.openstreetmap.org/status.php?format=json", headers=headers)
            if resp.status_code == 200:
                nominatim_status = {"status": "online", "message": "Nominatim geocoding is active."}
            else:
                nominatim_status = {"status": "degraded", "message": f"Nominatim status endpoint returned HTTP {resp.status_code}."}
    except Exception as e:
        nominatim_status = {"status": "offline", "message": f"Nominatim API is unreachable: {e}"}

    # 5. Check OSRM Routing
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://router.project-osrm.org/route/v1/driving/0,0;0,0")
            if resp.status_code in (200, 400):
                osrm_status = {"status": "online", "message": "OSRM routing server is active."}
            else:
                osrm_status = {"status": "degraded", "message": f"OSRM returned HTTP {resp.status_code}."}
    except Exception as e:
        osrm_status = {"status": "offline", "message": f"OSRM routing is unreachable: {e}"}

    # 6. Check Open-Meteo Weather
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0&hourly=temperature_2m")
            if resp.status_code == 200:
                weather_status = {"status": "online", "message": "Open-Meteo weather service is online."}
            else:
                weather_status = {"status": "degraded", "message": f"Open-Meteo returned HTTP {resp.status_code}."}
    except Exception as e:
        weather_status = {"status": "offline", "message": f"Open-Meteo service is unreachable: {e}"}

    # 7. Check GIS Libraries
    missing_libs = []
    for lib in ["geopandas", "shapely", "fiona", "pyproj"]:
        try:
            __import__(lib)
        except ImportError:
            missing_libs.append(lib)

    if not missing_libs:
        lib_status = {"status": "valid", "message": "All required GIS libraries (geopandas, shapely, fiona, pyproj) are loaded."}
    else:
        lib_status = {"status": "invalid", "message": f"Missing GIS libraries: {', '.join(missing_libs)}"}

    # 8. Check Workspace Writable
    if not workspace_path:
        workspace_status = {"status": "missing", "message": "No active workspace path selected."}
    else:
        try:
            os.makedirs(workspace_path, exist_ok=True)
            test_file = os.path.join(workspace_path, ".diagnostic_write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            workspace_status = {"status": "valid", "message": "Active workspace is fully writable."}
        except Exception as e:
            workspace_status = {"status": "invalid", "message": f"Workspace directory is not writable: {e}"}

    return DiagnosticResult(
        openai_api_key=openai_status,
        google_maps_api_key=google_status,
        overpass_api=overpass_status,
        nominatim_api=nominatim_status,
        osrm_api=osrm_status,
        open_meteo=weather_status,
        libraries=lib_status,
        workspace=workspace_status,
    )
