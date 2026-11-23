"""Shared study-boundary resolution for place-bounded tools (POIs, streets, …).

Given a place name (or several, e.g. a tri-city region), a boundary layer on the
map, an explicit GeoJSON polygon or the user's selected polygon, return the
exact areal boundary used to clip and calculate. Rules:

* Only real polygons count — a point/line fallback or a bounding box is never
  used as a study area (BoundaryError instead).
* The boundary is outlined on the map as "<name> boundary" (unless that layer
  is already present) so the user sees exactly what was used.
* Geometry never goes back to the LLM — only name, area and bbox.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BoundaryError(ValueError):
    """The requested study area could not be resolved to a polygon."""


@dataclass
class StudyBoundary:
    name: str
    shape: Any  # shapely (Multi)Polygon, valid
    geojson: dict
    bbox: dict
    area_km2: float
    parts: list[str] = field(default_factory=list)

    @property
    def overpass_bbox(self) -> str:
        b = self.bbox
        return f"({b['south']},{b['west']},{b['north']},{b['east']})"

    def summary(self) -> dict:
        return {"name": self.name, "area_km2": round(self.area_km2, 3), "bbox": self.bbox, "parts": self.parts or [self.name]}


def _areal(geom_like: Any):
    """GeoJSON (FeatureCollection/Feature/geometry) → valid shapely areal geometry or None."""
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    if not geom_like:
        return None
    if isinstance(geom_like, str):
        try:
            geom_like = json.loads(geom_like)
        except Exception:
            return None
    t = geom_like.get("type") if isinstance(geom_like, dict) else None
    shapes = []
    if t == "FeatureCollection":
        for f in geom_like.get("features", []):
            if f.get("geometry"):
                shapes.append(shape(f["geometry"]))
    elif t == "Feature":
        if geom_like.get("geometry"):
            shapes.append(shape(geom_like["geometry"]))
    elif t:
        shapes.append(shape(geom_like))
    polys = []
    for s in shapes:
        if not s.is_valid:
            s = make_valid(s)
        parts = [s]
        while parts:
            p = parts.pop()
            if hasattr(p, "geoms"):
                parts.extend(p.geoms)
            elif p.geom_type in ("Polygon", "MultiPolygon") and not p.is_empty and p.area > 0:
                polys.append(p)
    if not polys:
        return None
    merged = unary_union(polys)
    if not merged.is_valid:
        merged = make_valid(merged)
    return merged if merged.geom_type in ("Polygon", "MultiPolygon") else None


def geodesic_area_km2(shp) -> float:
    from pyproj import Geod
    return abs(Geod(ellps="WGS84").geometry_area_perimeter(shp)[0]) / 1e6


def _layer_geometry(layer: dict, workspace: str | None):
    fp = layer.get("filePath") or layer.get("file_path")
    if fp:
        p = Path(fp)
        if not p.is_absolute() and workspace:
            p = Path(workspace) / fp
        if p.exists() and p.suffix.lower() in (".geojson", ".json"):
            try:
                return _areal(json.loads(p.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.debug(f"Could not read boundary layer file {p}: {exc}")
    for key in ("data", "geometry_data"):
        g = layer.get(key)
        if isinstance(g, list):
            g = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": x, "properties": {}} for x in g if isinstance(x, dict)]}
        s = _areal(g)
        if s is not None:
            return s
    return None


async def _resolve_one(name: str, country_code: str, map_context: dict, workspace: str | None):
    """Resolve one place name → (shapely polygon, matched name)."""
    lname = name.lower().strip()
    # 1. A polygon layer already on the map with this name
    for layer in map_context.get("layers") or []:
        ln = str(layer.get("name") or "").lower().strip()
        if ln and (ln == lname or ln == f"{lname} boundary"):
            s = _layer_geometry(layer, workspace)
            if s is not None:
                return s, layer.get("name").replace(" boundary", "")
    # 2. Central spatial registry
    try:
        from tools.spatial_registry import spatial_registry
        poly = spatial_registry.get_polygon(name)
        if poly and poly.geometry:
            s = _areal(poly.geometry)
            if s is not None:
                return s, poly.name
    except Exception as exc:
        logger.debug(f"Registry lookup failed for {name}: {exc}")
    # 3. Official boundary from OSM / geoBoundaries / DataMeet
    from mcp_servers.osm_server import OSMServer
    res = await OSMServer()._fetch_boundary({"name": name, "country_code": country_code, "_map_context": map_context})
    if isinstance(res, dict) and res.get("geojson"):
        s = _areal(res["geojson"])
        if s is not None:
            matched = res.get("name") or name
            try:
                from tools.spatial_registry import spatial_registry
                spatial_registry.register_or_get(name=matched, geometry=res["geojson"], source="osm_boundary")
            except Exception:
                pass
            return s, matched
        raise BoundaryError(
            f"Only a point location (no polygon boundary) is mapped for '{name}'. Nothing was calculated — "
            "draw or upload the area's boundary, or name the enclosing administrative area."
        )
    raise BoundaryError(f"Could not find an official boundary polygon for '{name}'. Nothing was calculated for another area.")


async def resolve_study_boundary(args: dict, *, draw: bool = True, required: bool = True) -> StudyBoundary | None:
    """Resolve the study boundary from tool args (+ `_map_context`, `_ws`, `_workspace`)."""
    from shapely.geometry import mapping
    from shapely.ops import unary_union

    map_context = args.get("_map_context") or {}
    workspace = args.get("_workspace") or map_context.get("workspace")
    ws = args.get("_ws")
    country_code = str(args.get("country_code") or "").strip()

    names: list[str] = []
    for key in ("place_names", "places"):
        v = args.get(key)
        if isinstance(v, list):
            names.extend(str(x.get("name") if isinstance(x, dict) else x).strip() for x in v if x)
    single = str(args.get("place_name") or args.get("boundary_name") or args.get("city") or "").strip()
    if single and not names:
        names = [single]
    names = [n for n in names if n]
    layer_name = str(args.get("boundary_layer_name") or "").strip()

    shp = None
    label = ""
    parts: list[str] = []
    drawn_already = False

    if args.get("geojson"):
        shp = _areal(args["geojson"])
        if shp is None:
            raise BoundaryError("The supplied GeoJSON contains no polygon to use as a boundary.")
        label = single or "Selected area"
        drawn_already = True
    elif layer_name:
        for layer in map_context.get("layers") or []:
            if str(layer.get("name") or "").lower().strip() == layer_name.lower():
                shp = _layer_geometry(layer, workspace)
                break
        if shp is None:
            raise BoundaryError(f"No polygon layer named '{layer_name}' was found on the map.")
        label = layer_name.replace(" boundary", "")
        drawn_already = True
    elif names:
        shapes = []
        for n in names:
            s, matched = await _resolve_one(n, country_code, map_context, workspace)
            shapes.append(s)
            parts.append(matched)
        shp = unary_union(shapes) if len(shapes) > 1 else shapes[0]
        label = str(args.get("region_name") or "").strip() or " + ".join(parts)
    else:
        selected = []
        for sel in map_context.get("selected_features") or []:
            s = _areal(sel.get("geojson"))
            if s is not None:
                selected.append(s)
                parts.append(str(sel.get("layerName") or "Selected area"))
        if selected:
            shp = unary_union(selected)
            label = parts[0] if len(parts) == 1 else "Selected areas"
            drawn_already = True

    if shp is None:
        if required:
            raise BoundaryError(
                "A study area is required: pass place_name (or place_names for a multi-city region), "
                "boundary_layer_name, or select a polygon on the map."
            )
        return None

    minx, miny, maxx, maxy = shp.bounds
    bbox = {"west": round(minx, 6), "south": round(miny, 6), "east": round(maxx, 6), "north": round(maxy, 6)}
    geo = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(shp), "properties": {"name": label}}]}
    boundary = StudyBoundary(name=label, shape=shp, geojson=geo, bbox=bbox, area_km2=geodesic_area_km2(shp), parts=parts)

    if ws and draw:
        layer_names = {str(l.get("name") or "").strip().lower() for l in (map_context.get("layers") or [])}
        layer = f"{label} boundary"
        try:
            if not drawn_already and layer.lower() not in layer_names and label.lower() not in layer_names:
                await ws.send_text(json.dumps({"type": "action", "action": "add_geojson", "payload": {
                    "geojson": geo, "name": layer, "color": "#f8fafc", "lineColor": "#f8fafc",
                    "fillColor": "#f8fafc", "fillOpacity": 0, "lineWidth": 2.5,
                }}))
            await ws.send_text(json.dumps({"type": "action", "action": "fit_bounds", "payload": {
                **bbox, "bounds": [bbox["west"], bbox["south"], bbox["east"], bbox["north"]],
            }}))
        except Exception as exc:
            logger.debug(f"Could not draw boundary: {exc}")
    return boundary


def boundary_args_present(args: dict) -> bool:
    return any(args.get(k) for k in ("place_name", "place_names", "places", "boundary_layer_name", "geojson", "boundary_name"))


# Declaration snippets shared by place-bounded tools
BOUNDARY_PARAMS = {
    "place_name": {"type": "string", "description": "Place whose official boundary polygon limits the search and all calculations (e.g. a city, district, sector)."},
    "place_names": {"type": "array", "items": {"type": "string"}, "description": "Several places merged into ONE study area (e.g. the three cities of a tri-city region)."},
    "region_name": {"type": "string", "description": "Optional label for a merged multi-place region (e.g. 'Tricity')."},
    "boundary_layer_name": {"type": "string", "description": "Name of a polygon layer already on the map to use as the boundary."},
    "country_code": {"type": "string", "description": "ISO alpha-2 code to disambiguate the place, e.g. 'IN'."},
}
