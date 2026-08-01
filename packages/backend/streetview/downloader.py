"""Google Maps Street View lookup and image download functions."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
import httpx

from .cache import read_cached_image, write_cached_image
from .metadata import StreetViewMetadata

def get_google_key() -> str:
    """Return the configured Google Maps API key."""
    return (
        os.environ.get("GOOGLE_MAPS_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()


def lookup_metadata(lat: float, lng: float, radius: int = 50) -> StreetViewMetadata:
    """Return metadata for the nearest Google Street View panorama."""
    key = get_google_key()
    if not key:
        return StreetViewMetadata(found=False, error="GOOGLE_MAPS_API_KEY is not set")

    try:
        url = "https://maps.googleapis.com/maps/api/streetview/metadata"
        params = {
            "location": f"{lat},{lng}",
            "radius": radius,
            "key": key
        }
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK":
                    loc = data.get("location") or {}
                    return StreetViewMetadata(
                        found=True,
                        pano_id=data.get("pano_id"),
                        lat=loc.get("lat", lat),
                        lon=loc.get("lng", lng),
                        date=data.get("date"),
                        address=f"Street View image near {lat:.5f}, {lng:.5f}",
                        is_pano=True
                    )
    except Exception as e:
        return StreetViewMetadata(found=False, error=str(e))

    return StreetViewMetadata(found=False)


def panorama_jpeg(lat: float, lng: float, radius: int = 50, zoom: int = 3) -> tuple[StreetViewMetadata, bytes | None, bool]:
    """Return nearest Google Street View panorama JPEG bytes with metadata and cache-hit flag."""
    meta = lookup_metadata(lat, lng, radius)
    if not meta.found or not meta.pano_id:
        return meta, None, False

    cached = read_cached_image(meta.pano_id, zoom)
    if cached:
        return meta, cached, True

    key = get_google_key()
    if not key:
        return meta, None, False

    try:
        url = "https://maps.googleapis.com/maps/api/streetview"
        params = {
            "size": "1024x768",
            "location": f"{meta.lat},{meta.lon}",
            "key": key
        }
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.content
                write_cached_image(meta.pano_id, zoom, data)
                return meta, data, False
    except Exception:
        pass

    return meta, None, False


def artifact_metadata(meta: StreetViewMetadata, notes: str | None = None) -> dict[str, Any]:
    """Return normalized artifact metadata for a Google Street View image."""
    return {
        "source": "google",
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
