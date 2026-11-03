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
