"""Google Maps Platform shared client.

Thin wrapper over :mod:`tools.http` that injects ``GOOGLE_MAPS_API_KEY`` and
maps Google's error envelopes onto :class:`GoogleUnavailable` so callers can
fall back cleanly to OSM/Overture/Open-Meteo upstreams.

Two auth styles are in play:
  - **v1 APIs** (Places, Air Quality, Solar, Area Insights) — key goes in the
    ``X-Goog-Api-Key`` header. ``FieldMask`` is set per-call by the caller.
  - **Legacy APIs** (Elevation, classic Geocoding) — key goes in the query
    string as ``?key=...``.

The key is read from the environment lazily on each call rather than at
import time, so a backend started without the key still imports cleanly and
each tool can announce itself unavailable at execute-time.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

from tools import http as http_client

# Context-local variable for request-specific Google Maps API Key passed from the frontend
google_maps_key_var: ContextVar[str] = ContextVar("google_maps_key", default="")


class GoogleUnavailable(RuntimeError):
    """Raised when a Google API call cannot succeed.

    Mirrors :class:`tools.worldpop.WorldPopUnavailable` — callers catch this
    and fall back to a free upstream rather than surfacing the failure.
    """


def _api_key() -> str | None:
    """Read the API key fresh every call. Returns ``None`` if unset/blank."""
    key = google_maps_key_var.get().strip()
    if not key:
        key = (
            os.environ.get("GOOGLE_MAPS_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or ""
        ).strip()
    return key or None


def _require_key() -> str:
    key = _api_key()
    if not key:
        raise GoogleUnavailable("GOOGLE_MAPS_API_KEY is not set")
    return key


def _check_error_envelope(payload: Any) -> None:
    """Google v1 error shape: ``{"error": {"status": "...", "message": "..."}}``.

    Raises :class:`GoogleUnavailable` if the payload looks like an error
    response. ``status`` is preserved in the message for telemetry.
    """
    if not isinstance(payload, dict):
        return
    err = payload.get("error")
    if not err:
        return
    if isinstance(err, dict):
        status = err.get("status") or err.get("code") or "ERROR"
        msg = err.get("message") or "Google API returned error"
        raise GoogleUnavailable(f"{status}: {msg}")
    raise GoogleUnavailable(str(err))


async def call_v1(
    url: str,
    *,
    namespace: str,
    method: str = "POST",
    params: dict | None = None,
    json_body: Any = None,
    field_mask: str | None = None,
) -> dict:
    """Call a Google Maps v1 endpoint (Places / Air Quality / Solar / Insights).

    Auth via ``X-Goog-Api-Key``. ``field_mask`` becomes ``X-Goog-FieldMask``.
    Raises :class:`GoogleUnavailable` on missing key, transport failure, or
    Google error envelope.
    """
    key = _require_key()
    headers = {"X-Goog-Api-Key": key, "Content-Type": "application/json"}
    if field_mask:
        headers["X-Goog-FieldMask"] = field_mask

    try:
        payload = await http_client.fetch_json(
            url,
            namespace=namespace,
            method=method,
            params=params,
            json_body=json_body,
            headers=headers,
        )
    except http_client.HTTPError as e:
        raise GoogleUnavailable(f"{namespace}: {e}") from e

    _check_error_envelope(payload)
    return payload if isinstance(payload, dict) else {}


async def call_legacy(
    url: str,
    *,
    namespace: str,
    method: str = "GET",
    params: dict | None = None,
) -> dict:
    """Call a legacy Google Maps endpoint (Elevation, classic Geocoding).

    Auth via ``?key=...`` query param. Legacy responses use ``status`` as the
    primary success/failure flag — anything other than ``OK`` or ``ZERO_RESULTS``
    becomes :class:`GoogleUnavailable`.
    """
    key = _require_key()
    merged_params = dict(params or {})
    merged_params["key"] = key

    try:
        payload = await http_client.fetch_json(
            url,
            namespace=namespace,
            method=method,
            params=merged_params,
        )
    except http_client.HTTPError as e:
        raise GoogleUnavailable(f"{namespace}: {e}") from e

    if not isinstance(payload, dict):
        raise GoogleUnavailable(f"{namespace}: unexpected response shape")

    status = payload.get("status")
    if status and status not in {"OK", "ZERO_RESULTS"}:
        msg = payload.get("error_message") or status
        raise GoogleUnavailable(f"{namespace}: {status} ({msg})")

    return payload


def has_key() -> bool:
    """Cheap probe used by orchestration to skip Google attempts entirely."""
    return _api_key() is not None


_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


async def geocode_query(query: str, *, limit: int = 5) -> list[dict]:
    """Forward-geocode `query` via Google's legacy Geocoding API.

    Returns a list of ``{display_name, lat, lon, type, class, importance}``
    shaped to match :mod:`routers.geocode` and :mod:`tools.utility._geocode`.
    Raises :class:`GoogleUnavailable` on missing key, transport failure, or
    non-OK status. Empty result (``ZERO_RESULTS``) returns ``[]``.
    """
    payload = await call_legacy(
        _GEOCODE_URL,
        namespace="google_geocoding",
        params={"address": query},
    )
    out: list[dict] = []
    for r in (payload.get("results") or [])[:limit]:
        loc = (r.get("geometry") or {}).get("location") or {}
        lat = loc.get("lat")
        lng = loc.get("lng")
        if lat is None or lng is None:
            continue
        types = r.get("types") or []
        out.append({
            "display_name": r.get("formatted_address", ""),
            "lat": float(lat),
            "lon": float(lng),
            "type": types[0] if types else None,
            "class": "google",
            # Google has no "importance" field; surface location_type instead so
            # the UI ranker can still tier results.
            "importance": (r.get("geometry") or {}).get("location_type"),
        })
    return out
