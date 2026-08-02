"""HTTP endpoints for the integrated street-level imagery workspace."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, Response

from streetview.viewer import StreetViewService

router = APIRouter()
service = StreetViewService()


class StreetViewImageRequest(BaseModel):
    lat: float
    lng: float
    radius: int = Field(50, ge=1, le=500)
    zoom: int = Field(3, ge=0, le=5)
    title: str | None = None
    notes: str | None = None
    workspace: str | None = None


class RoadInspectionRequest(BaseModel):
    geometry: dict[str, Any]
    interval_m: float = Field(30.0, ge=5.0, le=500.0)


class StreetViewReportRequest(BaseModel):
    title: str = "Street View Report"
    images: list[dict[str, Any]]
    workspace: str | None = None


@router.get("/meta")
async def streetview_meta(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(50, ge=1, le=500),
):
    try:
        return await run_in_threadpool(service.metadata, lat, lng, radius)
    except Exception as e:  # network / upstream change
        return JSONResponse(
            status_code=502,
            content={"found": False, "error": f"Street View lookup failed: {e}"},
        )


@router.get("/token")
async def streetview_token():
    """Return the configured Google Maps key for the Street View embed."""
    import os

    google_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    return {
        "configured": bool(google_key),
        "google_key": google_key,
    }


@router.get("/pano")
async def streetview_pano(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(50, ge=1, le=500),
    zoom: int = Query(3, ge=0, le=5),
):
    """Download the nearest Google Street View panorama as a JPEG."""
    try:
        meta, image, _cache_hit = await run_in_threadpool(
            service.image_bytes, lat, lng, radius, zoom
        )
        if not meta.get("found") or image is None:
            return JSONResponse(
                status_code=404, content={"error": "Panorama not found."}
            )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Panorama download failed: {e}"},
        )

    return Response(content=image, media_type="image/jpeg")


@router.post("/image")
async def streetview_image(req: StreetViewImageRequest):
    """Download a Street View image and save it as a project artifact."""
    try:
        return await run_in_threadpool(
            service.image_artifact,
            req.lat,
            req.lng,
            radius=req.radius,
            zoom=req.zoom,
            title=req.title,
            notes=req.notes,
            workspace=req.workspace,
        )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"found": False, "error": f"Street View image failed: {e}"},
        )


@router.post("/road-inspection")
async def road_inspection(req: RoadInspectionRequest):
    """Sample points along a road/polyline for asynchronous gallery downloads."""
    try:
        return await run_in_threadpool(service.road_points, req.geometry, req.interval_m)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"error": f"Could not sample road geometry: {e}"},
        )


@router.post("/report")
async def streetview_report(req: StreetViewReportRequest):
    """Create an editable report artifact from Street View images."""
    try:
        return await run_in_threadpool(service.report, req.title, req.images, workspace=req.workspace)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"error": f"Could not create Street View report: {e}"},
        )


@router.get("/coverage")
async def streetview_coverage(
    s: float = Query(...),
    w: float = Query(...),
    n: float = Query(...),
    e: float = Query(...),
):
    import math
    from tools import cache

    # Quantize coordinates to 3 decimal places (approx. 100 meters) to maximize cache hits
    s_q = math.floor(s * 1000) / 1000.0
    w_q = math.floor(w * 1000) / 1000.0
    n_q = math.ceil(n * 1000) / 1000.0
    e_q = math.ceil(e * 1000) / 1000.0

    query = f"""
    [out:json][timeout:15];
    (
      way["highway"~"^(motorway|primary|secondary|tertiary|unclassified|residential|living_street|service)$"]({s_q},{w_q},{n_q},{e_q});
    );
    out body;
    >;
    out skel qt;
    """
    try:
        from mcp_servers.osm_server import _overpass_post
        
        async def fetch_osm():
            return await _overpass_post(query, timeout=20.0)

        data = await cache.get_or_fetch(
            namespace="streetview_coverage",
            key={"s": s_q, "w": w_q, "n": n_q, "e": e_q},
            ttl_seconds=86400 * 7,
            fetch_fn=fetch_osm
        )
        
        nodes = {}
        ways = []
        for el in data.get("elements", []):
            if el["type"] == "node":
                nodes[el["id"]] = (el.get("lon"), el.get("lat"))
            elif el["type"] == "way":
                ways.append(el)
                
        features = []
        for el in ways:
            tags = el.get("tags", {})
            coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
            if len(coords) >= 2:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": {
                        "osm_id": el["id"],
                        "highway": tags.get("highway", ""),
                        "name": tags.get("name", "unnamed")
                    }
                })
        return {"type": "FeatureCollection", "features": features}
    except Exception as err:
        print(f"Error in streetview_coverage Overpass fetch: {err}")
        return {"type": "FeatureCollection", "features": []}
