"""Metadata helpers for street-level imagery."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class StreetViewMetadata:
    """Serializable description of a resolved street-level image."""

    found: bool
    pano_id: str | None = None
    lat: float | None = None
    lon: float | None = None
    date: str | None = None
    heading: float | None = None
    address: str | None = None
    error: str | None = None
    is_pano: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return metadata in the API shape already used by the renderer."""
        return asdict(self)


def _parse_mapillary_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return str(value)
    # Mapillary API returns milliseconds since epoch.
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()


def metadata_from_mapillary_feature(feature: dict[str, Any] | None) -> StreetViewMetadata:
    """Convert a Mapillary API image feature into the existing API shape."""
    if not feature:
        return StreetViewMetadata(found=False)

    props = feature.get("properties") or feature
    geometry = (
        props.get("computed_geometry")
        or props.get("geometry")
        or feature.get("geometry")
        or {}
    )
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
    lon = coords[0] if isinstance(coords, list) and len(coords) >= 2 else None
    lat = coords[1] if isinstance(coords, list) and len(coords) >= 2 else None

    image_id = props.get("id") or feature.get("id")
    heading = props.get("computed_compass_angle")
    if heading is None:
        heading = props.get("compass_angle")

    is_pano = bool(props.get("is_pano") or feature.get("is_pano") or False)

    return StreetViewMetadata(
        found=bool(image_id),
        pano_id=str(image_id) if image_id is not None else None,
        lat=lat,
        lon=lon,
        date=_parse_mapillary_date(props.get("captured_at")),
        heading=heading,
        address=f"Mapillary image {image_id}" if image_id is not None else None,
        is_pano=is_pano,
    )
