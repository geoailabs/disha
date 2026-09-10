"""
Domain Hub Architecture Protocol for Disha.

Defines the standard ToolResult contract and BaseDomainHub interface used across
all 7+1 domain hubs (Spatial, Mobility, Environment, Planning, Demographics,
Places, Scenarios, Utility).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Standardized result returned by any domain hub tool execution."""
    status: str = "success"  # "success" | "error" | "cancelled"
    data: dict[str, Any] = field(default_factory=dict)
    map_action: dict[str, Any] | None = None  # e.g. {"action": "add_geojson", "payload": {...}}
    artifact: dict[str, Any] | None = None  # e.g. {"title": "...", "content": "...", "artifact_type": "report", "format": "markdown"}
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        res = dict(self.data)
        # Strip raw GeoJSON FeatureCollections or massive coordinate arrays from LLM data
        # to prevent context length overflow while map_action preserves full geometry for the map.
        if "geojson" in res:
            gj = res["geojson"]
            if isinstance(gj, dict) and "features" in gj:
                res.setdefault("feature_count", len(gj.get("features", [])))
            del res["geojson"]
        if "geometry" in res:
            geom = res["geometry"]
            if isinstance(geom, dict) and "coordinates" in geom:
                coords = geom.get("coordinates")
                if isinstance(coords, list) and (len(coords) > 10 or any(isinstance(c, list) and len(c) > 10 for c in coords)):
                    del res["geometry"]
        if self.status != "success":
            res["status"] = self.status
        if self.error:
            res["error"] = self.error
        return res

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class BaseDomainHub(ABC):
    """Abstract base class for a cohesive domain subsystem."""

    name: str
    description: str
    tool_names: set[str]

    @abstractmethod
    def get_declarations(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible tool declaration dictionaries."""
        ...

    @abstractmethod
    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a tool within this domain and return a standardized ToolResult."""
        ...
