"""Small geometry helpers shared by boundary-clipping tools."""

from __future__ import annotations

from typing import Any

_DIM = {"Point": 0, "MultiPoint": 0, "LineString": 1, "MultiLineString": 1, "LinearRing": 1, "Polygon": 2, "MultiPolygon": 2}


def dimension_parts(clipped: Any, original: Any):
    """Keep only the parts of `clipped` with the same dimension as `original`.

    shapely intersections can return GeometryCollections mixing points/lines/
    polygons (e.g. a road touching the boundary at one point); for drawing and
    measuring we keep only same-dimension parts, merged.
    """
    from shapely.ops import linemerge, unary_union

    target = _DIM.get(original.geom_type, 2)
    parts, pending = [], [clipped]
    while pending:
        g = pending.pop()
        if g is None or g.is_empty:
            continue
        if hasattr(g, "geoms") and g.geom_type not in ("Polygon",):
            pending.extend(g.geoms)
        elif _DIM.get(g.geom_type) == target:
            parts.append(g)
    if not parts:
        return None
    merged = unary_union(parts)
    if target == 1 and merged.geom_type == "MultiLineString":
        merged = linemerge(merged)
    return merged
