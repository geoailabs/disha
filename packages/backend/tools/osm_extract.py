"""Exact, boundary-clipped OpenStreetMap extraction (POIs and line/area features).

The Overpass query uses the boundary's bounding box only to fetch candidates;
every result is then tested against the real boundary polygon:

* point mode    — facility kept only if its location (node, or centre of the
                  mapped building/campus) lies inside the polygon; duplicates
                  (same named place mapped as node + building) counted once.
* geometry mode — lines/polygons are intersected with the polygon so only the
                  part inside the boundary is drawn and measured.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from tools.boundary import StudyBoundary
from tools.osm_categories import GEOMETRY_KEYS, OSM_CATEGORIES, overpass_filters

logger = logging.getLogger(__name__)

POINT_KEEP_TAGS = (
    "name", "name:en", "amenity", "healthcare", "shop", "office", "tourism", "leisure", "building",
    "operator", "operator:type", "beds", "isced:level", "addr:street", "addr:city", "website",
    "public_transport", "railway", "station", "highway", "bus", "brand", "opening_hours",
)


def _norm_name(n: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (n or "").lower()).strip()


async def fetch_overpass(query: str, timeout: float = 120.0) -> dict:
    from mcp_servers.osm_server import _overpass_post
    return await _overpass_post(query, timeout=timeout)


def _matches_category(tags: dict, cat: dict) -> bool:
    for k, v in cat["tags"]:
        if k not in tags:
            continue
        if v is None or str(tags[k]) in v.split("|"):
            req = (cat.get("require") or {}).get(k)
            if req and not any(
                (kk != k and kk in tags and (vv is None or str(tags[kk]) in vv.split("|")))
                for kk, vv in cat["tags"]
            ):
                rk, rv = req
                if str(tags.get(rk)) != rv:
                    continue
            return True
    return False


def _element_shape(el: dict):
    """Shapely geometry for an Overpass element returned with `out geom`."""
    from shapely.geometry import LineString, Point, Polygon
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    if el["type"] == "way" and el.get("geometry"):
        coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
        if len(coords) >= 4 and coords[0] == coords[-1]:
            poly = Polygon(coords)
            return poly if poly.is_valid else poly.buffer(0)
        return LineString(coords) if len(coords) >= 2 else None
    if el["type"] == "relation":
        return _relation_polygons(el)
    return None


async def extract_points_multi(
    boundary: StudyBoundary, jobs: list[tuple[str, list[tuple[str, str | None]], dict | None]]
) -> dict[str, tuple[list[dict], int, int]]:
    """Facilities inside the boundary for several categories in ONE Overpass query.

    Returns {key: (features, candidates_in_bbox, merged_into_campus)}. A facility is:
      * counted once (node + building of the same named place merged),
      * merged into its campus when it lies inside a larger mapped area of the same
        category (e.g. departments tagged as hospitals inside a hospital campus),
      * kept only if its location lies inside the boundary polygon.
    """
    from pyproj import Geod
    from shapely.geometry import Point
    from shapely.prepared import prep
    from shapely.strtree import STRtree

    all_filters: list[str] = []
    for _key, tags, _cat in jobs:
        for f in overpass_filters(tags):
            if f not in all_filters:
                all_filters.append(f)
    body = "".join(f"nwr{f}{boundary.overpass_bbox};" for f in all_filters)
    data = await fetch_overpass(f"[out:json][timeout:180][maxsize:1073741824];({body});out geom tags;", timeout=200.0)
    elements = data.get("elements", [])
    poly = prep(boundary.shape)
    geod = Geod(ellps="WGS84")
    results: dict[str, tuple[list[dict], int, int]] = {}

    for key, tags, cat in jobs:
        cat_def = cat or {"tags": tags}
        items = []
        for el in elements:
            t = el.get("tags") or {}
            if not t or not _matches_category(t, cat_def):
                continue
            try:
                shp = _element_shape(el)
            except Exception:
                shp = None
            if shp is None or shp.is_empty:
                continue
            pt = shp if shp.geom_type == "Point" else (shp.centroid if shp.centroid.within(shp) else shp.representative_point())
            area = shp.area if shp.geom_type in ("Polygon", "MultiPolygon") else 0.0
            items.append({"el": el, "tags": t, "shape": shp, "pt": pt, "area": area})
        candidates = len(items)

        # Campus merge: drop facilities located inside a LARGER mapped area of the same category.
        areas = [it for it in items if it["area"] > 0]
        merged = 0
        if areas:
            tree = STRtree([a["shape"] for a in areas])
            for it in items:
                for idx in tree.query(it["pt"]):
                    parent = areas[int(idx)]
                    if parent is not it and parent["area"] > it["area"] and parent["shape"].contains(it["pt"]):
                        it["parent"] = parent
                        parent["children"] = parent.get("children", 0) + 1
                        merged += 1
                        break
        items = [it for it in items if "parent" not in it]

        # Inside the study boundary only
        items = [it for it in items if poly.contains(it["pt"])]

        # Same named facility mapped twice (node + outline) within 200 m → once
        items.sort(key=lambda it: -it["area"])
        feats: list[dict] = []
        seen: dict[str, list[tuple[float, float]]] = {}
        for it in items:
            lon, lat = it["pt"].x, it["pt"].y
            nm = _norm_name(it["tags"].get("name"))
            if nm and any(abs(geod.inv(lon, lat, ox, oy)[2]) < 200 for ox, oy in seen.get(nm, [])):
                merged += 1
                continue
            if nm:
                seen.setdefault(nm, []).append((lon, lat))
            props = {k: it["tags"][k] for k in POINT_KEEP_TAGS if k in it["tags"]}
            props["osm_id"] = f"{it['el']['type']}/{it['el']['id']}"
            if it.get("children"):
                props["merged_sub_facilities"] = it["children"]
            if it["area"]:
                props["site_area_ha"] = round(abs(geod.geometry_area_perimeter(it["shape"])[0]) / 1e4, 2)
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}, "properties": props})
        results[key] = (feats, candidates, merged)
    return results


async def extract_points(boundary: StudyBoundary, tags: list[tuple[str, str | None]], cat: dict | None = None) -> tuple[list[dict], int]:
    res = await extract_points_multi(boundary, [("_", tags, cat)])
    feats, candidates, _merged = res["_"]
    return feats, candidates


def _relation_polygons(el: dict):
    from shapely.geometry import LineString, Polygon
    from shapely.ops import linemerge, polygonize, unary_union

    outers, inners = [], []
    for m in el.get("members", []):
        if m.get("type") != "way" or not m.get("geometry"):
            continue
        coords = [(p["lon"], p["lat"]) for p in m["geometry"]]
        if len(coords) < 2:
            continue
        (inners if m.get("role") == "inner" else outers).append(LineString(coords))
    if not outers:
        return None
    outer = unary_union(list(polygonize(linemerge(outers))))
    if inners:
        hole = unary_union(list(polygonize(linemerge(inners))))
        outer = outer.difference(hole)
    return None if outer.is_empty else outer


async def extract_geometries(boundary: StudyBoundary, tags: list[tuple[str, str | None]], keep_tags: tuple[str, ...] = ()) -> list[dict]:
    """Lines/polygons clipped to the boundary (only the part inside is kept)."""
    from shapely.geometry import LineString, Polygon, mapping
    from shapely.prepared import prep
    from tools.geometry_ops import dimension_parts

    filters = overpass_filters(tags)
    body = "".join(f"way{f}{boundary.overpass_bbox};relation{f}{boundary.overpass_bbox};" for f in filters)
    data = await fetch_overpass(f"[out:json][timeout:180][maxsize:1073741824];({body});out geom;")
    shp = boundary.shape
    pshp = prep(shp)
    out: list[dict] = []
    from mcp_servers.osm_server import _is_area_way
    for el in data.get("elements", []):
        t = el.get("tags") or {}
        geom = None
        try:
            if el["type"] == "way" and el.get("geometry"):
                coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
                if len(coords) < 2:
                    continue
                closed = len(coords) >= 4 and coords[0] == coords[-1]
                geom = Polygon(coords) if closed and _is_area_way(t) else LineString(coords)
            elif el["type"] == "relation" and t.get("type") in ("multipolygon", "boundary"):
                geom = _relation_polygons(el)
            if geom is None or geom.is_empty:
                continue
            if not geom.is_valid:
                geom = geom.buffer(0) if geom.geom_type in ("Polygon", "MultiPolygon") else geom
            if not pshp.intersects(geom):
                continue
            clipped = geom if pshp.contains(geom) else dimension_parts(shp.intersection(geom), geom)
            if clipped is None or clipped.is_empty:
                continue
        except Exception as exc:
            logger.debug(f"Skipping OSM element {el.get('id')}: {exc}")
            continue
        props = {k: t[k] for k in (keep_tags or tuple(t.keys())) if k in t}
        props["osm_id"] = f"{el['type']}/{el['id']}"
        out.append({"type": "Feature", "geometry": mapping(clipped), "properties": props})
    return out


def category_mode(category: str | None, feature_type: str | None) -> str:
    if category and category in OSM_CATEGORIES:
        return OSM_CATEGORIES[category]["mode"]
    return "geometry" if (feature_type or "") in GEOMETRY_KEYS else "point"


def measure(features: list[dict]) -> dict:
    """Geodesic totals for clipped features: count, length (km) and area (km²)."""
    from pyproj import Geod
    from shapely.geometry import shape
    geod = Geod(ellps="WGS84")
    length = area = 0.0
    for f in features:
        try:
            s = shape(f["geometry"])
            if s.geom_type in ("LineString", "MultiLineString"):
                length += abs(geod.geometry_length(s))
            elif s.geom_type in ("Polygon", "MultiPolygon"):
                area += abs(geod.geometry_area_perimeter(s)[0])
        except Exception:
            pass
    out: dict[str, Any] = {"count": len(features)}
    if length:
        out["total_length_km"] = round(length / 1000, 3)
    if area:
        out["total_area_km2"] = round(area / 1e6, 4)
    return out
