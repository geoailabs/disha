"""
Central Spatial & Polygon Registry for Disha.

Single source of truth for all study areas, boundaries, zoning parcels, and
user/AI-drawn polygons. Enforces spatial deduplication (IoU >= 90% and normalized
name matching) to prevent overdrawing and duplicate layer generation.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from tools.geo import _to_geom, area_breakdown, geodesic_area_m2

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    """Normalize a place or layer name for robust comparison."""
    if not name:
        return ""
    # Strip common suffixes/prefixes, lowercase, remove non-alphanumerics
    cleaned = name.lower().strip()
    cleaned = re.sub(r"\b(boundary|layer|polygon|shape|area|zone)\b", "", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass
class PolygonEntry:
    id: str
    name: str
    source: str  # 'user_draw' | 'ai_draw' | 'osm_boundary' | 'datameet' | 'zoning' | 'digitize'
    geometry: dict
    properties: dict = field(default_factory=dict)
    area_km2: float = 0.0
    area_hectares: float = 0.0
    area_m2: float = 0.0
    perimeter_m: float = 0.0
    centroid: dict = field(default_factory=lambda: {"lat": 0.0, "lng": 0.0})
    bbox: dict = field(default_factory=lambda: {"south": 0.0, "west": 0.0, "north": 0.0, "east": 0.0})
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_geojson_feature(self) -> dict[str, Any]:
        props = {
            **self.properties,
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "area_km2": self.area_km2,
            "area_hectares": self.area_hectares,
        }
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": self.geometry,
            "properties": props,
        }


class SpatialRegistry:
    """Manages spatial polygons, boundaries, and study areas across all domains."""

    def __init__(self) -> None:
        self._polygons: dict[str, PolygonEntry] = {}

    def compute_iou(self, geom1: Any, geom2: Any) -> float:
        """Compute Intersection over Union (IoU) between two geometries."""
        try:
            s1 = _to_geom(geom1)
            s2 = _to_geom(geom2)
            if s1.is_empty or s2.is_empty or not s1.is_valid or not s2.is_valid:
                return 0.0
            inter = s1.intersection(s2)
            if inter.is_empty:
                return 0.0
            inter_area = inter.area
            union_area = s1.union(s2).area
            if union_area <= 0:
                return 0.0
            return float(inter_area / union_area)
        except Exception as exc:
            logger.debug(f"compute_iou error: {exc}")
            return 0.0

    def find_duplicate(
        self,
        name: str,
        geometry: dict | None = None,
        iou_threshold: float = 0.90,
    ) -> tuple[PolygonEntry | None, str, float]:
        """Check if a polygon is a duplicate by normalized name or spatial IoU >= iou_threshold.
        Returns: (matching_entry, match_reason, iou_score)
        """
        norm_name = _normalize_name(name)

        # 1. Check spatial IoU first if geometry is provided
        if geometry:
            for entry in self._polygons.values():
                score = self.compute_iou(geometry, entry.geometry)
                if score >= iou_threshold:
                    return entry, f"spatial_overlap ({round(score * 100, 1)}% IoU)", score

        # 2. Check normalized name match
        if norm_name:
            for entry in self._polygons.values():
                entry_norm = _normalize_name(entry.name)
                if entry_norm and (norm_name == entry_norm or norm_name in entry_norm or entry_norm in norm_name):
                    iou = self.compute_iou(geometry, entry.geometry) if geometry else 0.0
                    return entry, "name_match", iou

        return None, "none", 0.0

    def register_or_get(
        self,
        name: str,
        geometry: dict,
        source: str = "ai_draw",
        properties: dict | None = None,
        iou_threshold: float = 0.90,
    ) -> dict[str, Any]:
        """Register a new polygon or return the existing one if duplicate/overlapping."""
        properties = properties or {}
        existing, reason, score = self.find_duplicate(name, geometry, iou_threshold=iou_threshold)

        if existing is not None:
            logger.info(
                f"[SpatialRegistry] Reusing existing polygon '{existing.name}' ({existing.id}) "
                f"for requested '{name}' via {reason} (score={score:.2f})"
            )
            return {
                "status": "existing",
                "is_duplicate": True,
                "match_reason": reason,
                "iou": round(score, 4),
                "layer_name": existing.name,
                "polygon": existing.to_dict(),
            }

        # Calculate accurate geodesic and spatial bounds
        breakdown = area_breakdown(geometry)
        geom_shape = _to_geom(geometry)
        minx, miny, maxx, maxy = geom_shape.bounds
        c = geom_shape.centroid

        entry_id = properties.get("id") or f"poly-{uuid.uuid4().hex[:8]}"
        entry = PolygonEntry(
            id=entry_id,
            name=name,
            source=source,
            geometry=mapping(geom_shape) if hasattr(geom_shape, "__geo_interface__") else geometry,
            properties=properties,
            area_m2=breakdown["area_m2"],
            area_hectares=breakdown["area_hectares"],
            area_km2=breakdown["area_km2"],
            perimeter_m=breakdown["perimeter_m"],
            centroid={"lat": round(c.y, 6), "lng": round(c.x, 6)},
            bbox={"south": round(miny, 6), "west": round(minx, 6), "north": round(maxy, 6), "east": round(maxx, 6)},
        )

        self._polygons[entry.id] = entry
        logger.info(f"[SpatialRegistry] Registered new polygon '{entry.name}' ({entry.id}, {entry.area_hectares} ha)")

        return {
            "status": "created",
            "is_duplicate": False,
            "match_reason": "none",
            "iou": 0.0,
            "layer_name": entry.name,
            "polygon": entry.to_dict(),
        }

    def get_polygon(self, name_or_id: str) -> PolygonEntry | None:
        """Find a polygon by ID or name (case-insensitive)."""
        if not name_or_id:
            return None
        if name_or_id in self._polygons:
            return self._polygons[name_or_id]

        target = name_or_id.lower().strip()
        norm_target = _normalize_name(name_or_id)

        for p in self._polygons.values():
            if p.name.lower().strip() == target:
                return p
        for p in self._polygons.values():
            if _normalize_name(p.name) == norm_target:
                return p
        return None

    def list_polygons(self, source: str | None = None) -> list[dict[str, Any]]:
        """List all active registered polygons."""
        polys = self._polygons.values()
        if source:
            polys = [p for p in polys if p.source == source]
        return [p.to_dict() for p in polys]

    def check_overlap(self, geometry: dict, min_iou: float = 0.05) -> list[dict[str, Any]]:
        """Find all registered polygons that intersect or overlap with the given geometry."""
        overlaps = []
        try:
            target_shape = _to_geom(geometry)
            if target_shape.is_empty:
                return []

            for entry in self._polygons.values():
                entry_shape = _to_geom(entry.geometry)
                if not target_shape.intersects(entry_shape):
                    continue

                inter = target_shape.intersection(entry_shape)
                if inter.is_empty:
                    continue

                iou = self.compute_iou(geometry, entry.geometry)
                inter_area_m2 = geodesic_area_m2(mapping(inter))
                overlaps.append({
                    "id": entry.id,
                    "name": entry.name,
                    "source": entry.source,
                    "iou": round(iou, 4),
                    "overlap_pct": round(iou * 100, 1),
                    "intersection_hectares": round(inter_area_m2 / 10000, 2),
                    "intersection_area_km2": round(inter_area_m2 / 1e6, 4),
                })
        except Exception as exc:
            logger.error(f"[SpatialRegistry] check_overlap failed: {exc}")

        return sorted(overlaps, key=lambda x: x["iou"], reverse=True)

    def calculate_land_budget(self) -> dict[str, Any]:
        """Compute total land budget across registered polygons grouped by zone or source."""
        total_area_m2 = 0.0
        total_ha = 0.0
        breakdown: dict[str, dict[str, Any]] = {}

        for entry in self._polygons.values():
            total_area_m2 += entry.area_m2
            total_ha += entry.area_hectares
            group_key = (
                entry.properties.get("zone_code")
                or entry.properties.get("land_use")
                or entry.properties.get("category")
                or entry.source
            )
            if group_key not in breakdown:
                breakdown[group_key] = {"count": 0, "area_m2": 0.0, "area_hectares": 0.0}
            breakdown[group_key]["count"] += 1
            breakdown[group_key]["area_m2"] += entry.area_m2
            breakdown[group_key]["area_hectares"] += entry.area_hectares

        # Compute percentage shares
        for k, v in breakdown.items():
            pct = (v["area_hectares"] / total_ha * 100) if total_ha > 0 else 0.0
            v["share_pct"] = round(pct, 2)
            v["area_hectares"] = round(v["area_hectares"], 2)

        return {
            "total_polygons": len(self._polygons),
            "total_area_hectares": round(total_ha, 2),
            "total_area_km2": round(total_ha / 100, 4),
            "breakdown": breakdown,
        }

    def sync_from_map_layers(self, layers: list[dict] | None) -> None:
        """Synchronize in-memory registry with active Polygon/MultiPolygon layers on the map."""
        if not layers:
            return

        for layer in layers:
            name = layer.get("name") or "Layer"
            source = layer.get("source") or "map_layer"
            features = layer.get("features_data") or layer.get("features") or []

            # Check if geometry is in geometry_data or features
            if not features and "geometry_data" in layer:
                geom_data = layer["geometry_data"]
                if isinstance(geom_data, list):
                    for idx, g in enumerate(geom_data):
                        g_type = g.get("type")
                        coords = g.get("coordinates")
                        if g_type in ("Polygon", "MultiPolygon") and coords:
                            geom = {"type": g_type, "coordinates": coords}
                            layer_feat_name = f"{name} #{idx + 1}" if len(geom_data) > 1 else name
                            self.register_or_get(
                                name=layer_feat_name,
                                geometry=geom,
                                source=source,
                                properties={"layer_id": layer.get("id"), "layer_name": name},
                            )

            for idx, feat in enumerate(features):
                geom = feat.get("geometry") if isinstance(feat, dict) else None
                if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
                    continue
                props = feat.get("properties") or {}
                feat_name = props.get("name") or props.get("label") or f"{name} #{idx + 1}"
                self.register_or_get(
                    name=feat_name,
                    geometry=geom,
                    source=props.get("source") or source,
                    properties={**props, "layer_id": layer.get("id"), "layer_name": name},
                )

    def delete_polygon(self, name_or_id: str) -> bool:
        """Delete a polygon from the registry."""
        entry = self.get_polygon(name_or_id)
        if entry and entry.id in self._polygons:
            del self._polygons[entry.id]
            logger.info(f"[SpatialRegistry] Removed polygon '{entry.name}' ({entry.id})")
            return True
        return False

    def clear(self) -> None:
        """Reset the registry."""
        self._polygons.clear()


# Global Singleton instance
spatial_registry = SpatialRegistry()
