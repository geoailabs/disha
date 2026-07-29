"""Mapillary lookup and image download functions for street-level imagery."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from .cache import read_cached_image, write_cached_image
from .metadata import StreetViewMetadata, metadata_from_mapillary_feature

_GRAPH_API = "https://graph.mapillary.com"
_FIELDS = ",".join(
    [
        "id",
        "computed_geometry",
        "geometry",
        "captured_at",
        "compass_angle",
        "computed_compass_angle",
        "is_pano",
        "thumb_2048_url",
        "thumb_original_url",
    ]
)


def get_mapillary_token() -> str:
    """Return the configured Mapillary client access token."""
    return (
        os.environ.get("MAPILLARY_ACCESS_TOKEN")
        or os.environ.get("MAPILLARY_CLIENT_TOKEN")
        or ""
    ).strip()


def _require_token() -> str:
    token = get_mapillary_token()
    if not token:
        raise RuntimeError("MAPILLARY_ACCESS_TOKEN is not set")
    return token


import math

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_earth = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return r_earth * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


def _download_bytes(url: str) -> bytes:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def find_panorama(lat: float, lng: float, radius: int = 50) -> dict[str, Any] | None:
    """Find the nearest Mapillary image to a coordinate, expanding search via bbox if needed."""
    token = _require_token()
    r_50 = min(max(1, radius), 50)

    # 1. Direct point radius search (up to 50m limit enforced by Mapillary API)
    for img_type in ["pano", None]:
        params: dict[str, Any] = {
            "access_token": token,
            "fields": _FIELDS,
            "lat": lat,
            "lng": lng,
            "radius": r_50,
            "limit": 1,
        }
        if img_type:
            params["image_type"] = img_type

        data = _get_json(f"{_GRAPH_API}/images", params)
        if data:
            images = data.get("data") or data.get("features") or []
            if images:
                return images[0]

    # 2. Expanding bbox search when no image is found within 50m
    search_radii = [150, 400, 1000, 2500, 5000, 10000]
    max_search = max(radius, 5000)
    cos_lat = max(0.01, math.cos(math.radians(lat)))

    for rad_m in search_radii:
        if rad_m > max_search * 2:
            break

        dlat = rad_m / 111000.0
        dlng = rad_m / (111000.0 * cos_lat)

        bbox_str = f"{lng - dlng:.6f},{lat - dlat:.6f},{lng + dlng:.6f},{lat + dlat:.6f}"
        params = {
            "access_token": token,
            "fields": _FIELDS,
            "bbox": bbox_str,
            "limit": 50,
        }

        data = _get_json(f"{_GRAPH_API}/images", params)
        if data:
            images = data.get("data") or data.get("features") or []
            if images:
                # 1st pass: Prefer closest 360-degree panorama (is_pano: True)
                best_img = None
                best_dist = float("inf")
                for img in images:
                    if img.get("is_pano") is True:
                        geom = img.get("geometry") or img.get("computed_geometry") or {}
                        coords = geom.get("coordinates")
                        if coords and len(coords) >= 2:
                            dist = _haversine_m(lat, lng, coords[1], coords[0])
                            if dist < best_dist:
                                best_dist = dist
                                best_img = img
                if best_img:
                    return best_img

                # 2nd pass: Fall back to closest flat perspective capture
                best_dist = float("inf")
                for img in images:
                    geom = img.get("geometry") or img.get("computed_geometry") or {}
                    coords = geom.get("coordinates")
                    if coords and len(coords) >= 2:
                        dist = _haversine_m(lat, lng, coords[1], coords[0])
                        if dist < best_dist:
                            best_dist = dist
                            best_img = img
                if best_img:
                    return best_img

    return None


def lookup_metadata(lat: float, lng: float, radius: int = 50) -> StreetViewMetadata:
    """Return metadata for the nearest Mapillary image."""
    return metadata_from_mapillary_feature(find_panorama(lat, lng, radius))


def panorama_jpeg(lat: float, lng: float, radius: int = 50, zoom: int = 3) -> tuple[StreetViewMetadata, bytes | None, bool]:
    """Return nearest Mapillary image metadata, JPEG bytes, and cache-hit flag."""
    image = find_panorama(lat, lng, radius)
    meta = metadata_from_mapillary_feature(image)
    if not image or not meta.pano_id:
        return meta, None, False

    cached = read_cached_image(meta.pano_id, zoom)
    if cached:
        return meta, cached, True

    image_url = image.get("thumb_original_url") or image.get("thumb_2048_url")
    if not image_url:
        details = _get_json(
            f"{_GRAPH_API}/{meta.pano_id}",
            {
                "access_token": _require_token(),
                "fields": "thumb_original_url,thumb_2048_url",
            },
        )
        image_url = details.get("thumb_original_url") or details.get("thumb_2048_url")
    if not image_url:
        return meta, None, False

    data = _download_bytes(image_url)
    write_cached_image(meta.pano_id, zoom, data)
    return meta, data, False


def artifact_metadata(meta: StreetViewMetadata, notes: str | None = None) -> dict[str, Any]:
    """Return normalized artifact metadata for a Mapillary street-level image."""
    return {
        "source": "mapillary",
        "image_id": meta.pano_id,
        "pano_id": meta.pano_id,
        "lat": meta.lat,
        "lng": meta.lon,
        "address": meta.address,
        "capture_date": meta.date,
        "heading": meta.heading,
        "planner_notes": notes or "",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
