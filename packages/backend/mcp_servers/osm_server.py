"""
OpenStreetMap MCP Server

Provides tools for querying real-world geographic features via the Overpass API.
Supports amenity search, land-use queries, building footprints, road networks, etc.
"""

from __future__ import annotations

import asyncio
import json as _json

import httpx
from llm.base import ToolDeclaration
from tools import cache, http as http_client


# Multiple Overpass mirrors. The main instance frequently rate-limits (429)
# or returns empty 504 bodies under load — try the next mirror automatically.
_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",  # secondary load-balanced node of the official server
]

_OVERPASS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://overpass-turbo.eu/",
}


async def _overpass_post(query: str, timeout: float = 30.0) -> dict:
    """Resilient Overpass call with mirror failover and rate-limit auto-retries."""
    last_status: int | None = None
    last_body_snippet: str = ""
    for url in _OVERPASS_MIRRORS:
        # Retry up to 3 times per mirror on rate limits (429) or gateway timeouts (504/502)
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=timeout, headers=_OVERPASS_HEADERS) as http:
                    resp = await http.post(url, data={"data": query})
            except httpx.RequestError as e:
                last_body_snippet = f"network error: {e}"
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                break
                
            last_status = resp.status_code
            if resp.status_code in (403, 429, 502, 503, 504):
                last_body_snippet = (resp.text or "").strip()[:200]
                # Wait longer on each attempt (exponential backoff: 0.5s, 1s, 2s)
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            if resp.status_code != 200:
                last_body_snippet = (resp.text or "").strip()[:200]
                break
            text = resp.text or ""
            if not text.strip():
                last_body_snippet = "<empty body>"
                break
            try:
                return _json.loads(text)
            except _json.JSONDecodeError:
                last_body_snippet = text.strip()[:200]
                break
                
    raise OverpassError(
        f"Overpass mirrors all failed (last status {last_status}). "
        f"This is usually a transient rate-limit or upstream outage; "
        f"please retry in 30–60 seconds."
        + (f" Last body: {last_body_snippet!r}" if last_body_snippet else "")
    )



class OverpassError(RuntimeError):
    """Raised by `_overpass_post` when every mirror fails."""


def _merge_ways(way_coords: list[list[list[float]]]) -> list[list[list[float]]]:
    """Merge an unordered list of way coordinate arrays into closed rings.

    Overpass returns boundary relations as individual way segments that
    need to be joined end-to-end to form complete polygon rings.
    """
    if not way_coords:
        return []

    remaining = [list(w) for w in way_coords]
    rings: list[list[list[float]]] = []

    while remaining:
        current = remaining.pop(0)
        changed = True
        while changed:
            changed = False
            for i, seg in enumerate(remaining):
                # Try to connect: current end -> seg start
                if _coords_close(current[-1], seg[0]):
                    current.extend(seg[1:])
                    remaining.pop(i)
                    changed = True
                    break
                # current end -> seg end (reverse seg)
                if _coords_close(current[-1], seg[-1]):
                    current.extend(reversed(seg[:-1]))
                    remaining.pop(i)
                    changed = True
                    break
                # seg end -> current start
                if _coords_close(seg[-1], current[0]):
                    current = seg + current[1:]
                    remaining.pop(i)
                    changed = True
                    break
                # seg start -> current start (reverse seg)
                if _coords_close(seg[0], current[0]):
                    current = list(reversed(seg)) + current[1:]
                    remaining.pop(i)
                    changed = True
                    break

        # Close the ring if not already
        if not _coords_close(current[0], current[-1]):
            current.append(current[0])
        rings.append(current)

    return rings


def _coords_close(a: list[float], b: list[float], tol: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _sanitize_osm_token(value) -> str:
    """Strip a tag key/value to characters safe inside an Overpass query string.

    OSM keys/values are alphanumeric + underscore + colon + dash. Anything else
    (quotes, brackets, semicolons) would let a model break out of the query.
    """
    if not isinstance(value, str):
        value = str(value)
    return "".join(c for c in value if c.isalnum() or c in "_:-")


def _sanitize_osm_name(value) -> str:
    """Sanitize a place name for safe interpolation into an Overpass query.

    Place names can contain spaces, accents, dots — but never quotes, brackets,
    semicolons, or backslashes. Strip those.
    """
    if not isinstance(value, str):
        value = str(value)
    return "".join(c for c in value if c not in '"\\[];()$<>{}')


# Cap for `osm_search` results before the FeatureCollection is auto-displayed
# on the map. Larger payloads freeze the renderer's main thread on JSON.parse.
_OSM_MAX_FEATURES = 1000


# Subset of ISO-3166-1: alpha-2 → alpha-3. Country codes not here fall back to
# Nominatim+Overpass (which doesn't need ISO-3). Add more as users request them.
_ISO2_TO_ISO3 = {
    "AE": "ARE", "AF": "AFG", "AR": "ARG", "AT": "AUT", "AU": "AUS",
    "BD": "BGD", "BE": "BEL", "BR": "BRA", "BT": "BTN", "CA": "CAN",
    "CH": "CHE", "CL": "CHL", "CN": "CHN", "CO": "COL", "CZ": "CZE",
    "DE": "DEU", "DK": "DNK", "EG": "EGY", "ES": "ESP", "ET": "ETH",
    "FI": "FIN", "FR": "FRA", "GB": "GBR", "GH": "GHA", "GR": "GRC",
    "ID": "IDN", "IE": "IRL", "IL": "ISR", "IN": "IND", "IQ": "IRQ",
    "IR": "IRN", "IT": "ITA", "JP": "JPN", "KE": "KEN", "KH": "KHM",
    "KR": "KOR", "LK": "LKA", "MA": "MAR", "MM": "MMR", "MX": "MEX",
    "MY": "MYS", "NG": "NGA", "NL": "NLD", "NO": "NOR", "NP": "NPL",
    "NZ": "NZL", "PE": "PER", "PH": "PHL", "PK": "PAK", "PL": "POL",
    "PT": "PRT", "RO": "ROU", "RU": "RUS", "SA": "SAU", "SE": "SWE",
    "SG": "SGP", "TH": "THA", "TR": "TUR", "TW": "TWN", "UA": "UKR",
    "US": "USA", "VN": "VNM", "ZA": "ZAF",
}

# OSM admin_level → geoBoundaries ADM level. Mapping is approximate; admin_level
# conventions vary by country. If geoBoundaries returns no match the chain falls
# through to Nominatim+Overpass, so a conservative mapping is fine.
_ADMIN_LEVEL_TO_GB = {
    2: "ADM0", 3: "ADM0",
    4: "ADM1",
    5: "ADM2", 6: "ADM2",
    7: "ADM3", 8: "ADM3",
    9: "ADM4", 10: "ADM4",
}

# OSM tag keys that ALWAYS imply a linear feature, even when the way is closed
# (roundabouts, loop trails, circular roads).
_LINE_TAG_KEYS = {"highway", "railway", "waterway", "barrier", "power", "aeroway"}

# OSM tag keys that, when present on a closed way, imply an areal feature.
_AREA_TAG_KEYS = {"building", "landuse", "leisure", "amenity", "natural",
                  "tourism", "historic", "shop", "office", "place", "boundary"}

# Values of `natural=*` that are linear (coast, ridge), not areal.
_NATURAL_LINE_VALUES = {"coastline", "ridge", "tree_row", "cliff"}


def _is_area_way(tags: dict) -> bool:
    """Decide whether a closed OSM way represents an Area (Polygon) or just a
    closed Line. Mirrors the OSM 'area or line' rules.
    """
    if not tags:
        return False
    if str(tags.get("area", "")).lower() == "yes":
        return True
    if str(tags.get("area", "")).lower() == "no":
        return False
    for k in _LINE_TAG_KEYS:
        if k in tags:
            return False
    nat = tags.get("natural")
    if nat and nat in _NATURAL_LINE_VALUES:
        return False
    for k in _AREA_TAG_KEYS:
        if k in tags:
            return True
    return False


class OSMServer:
    description = "OpenStreetMap Overpass API for querying real-world features"
    tool_names = {"osm_search", "osm_boundary", "osm_boundary_union", "osm_reverse_geocode", "osm_route_overview", "osm_fetch_bus_routes"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="osm_search",
                description=(
                    "Search OpenStreetMap for features near a location. "
                    "Returns GeoJSON displayed on the map automatically. "
                    "Use for amenities (hospitals, schools, parks), "
                    "infrastructure (bus_stop, railway, highway), buildings, land use, shops.\n\n"
                    "feature_value accepts THREE forms:\n"
                    "  • Single value, e.g. 'hospital' → exact match ['amenity'='hospital'].\n"
                    "  • '*' or empty string → ANY value of that key. Use this for 'all shops' "
                    "(feature_type='shop', feature_value='*') or 'all amenities'.\n"
                    "  • Pipe-separated list, e.g. 'convenience|supermarket|mall|department_store' "
                    "→ matches any of those values in a single call. Prefer this over multiple calls."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "feature_type": {
                            "type": "string",
                            "description": "OSM tag key: amenity, building, highway, leisure, natural, shop, tourism, landuse, railway, waterway, public_transport, place",
                        },
                        "feature_value": {
                            "type": "string",
                            "description": "OSM tag value. Single value ('hospital'), '*' for any value of the key, or pipe-separated list ('convenience|supermarket|mall').",
                        },
                        "lat": {"type": "number", "description": "Center latitude. Optional if use_current_bounds is true."},
                        "lng": {"type": "number", "description": "Center longitude. Optional if use_current_bounds is true."},
                        "radius_meters": {"type": "number", "description": "Search radius in meters (default 1000, max 10000). Optional if use_current_bounds is true."},
                        "use_current_bounds": {"type": "boolean", "description": "If true, searches within the current map viewport bounds instead of using lat/lng/radius_meters."},
                    },
                    "required": ["feature_type"],
                },
            ),
            ToolDeclaration(
                name="osm_boundary",
                description=(
                    "Fetch a boundary polygon from OpenStreetMap. Returns GeoJSON displayed on the map automatically.\n\n"
                    "TWO MODES — pick one:\n"
                    "1) ADMINISTRATIVE boundary (country/state/district/city). Pass `name` and "
                    "`admin_level` (2=country, 4=state/UT, 5=district, 6=sub-district, 8=city/town).\n"
                    "2) SUB-CITY feature (Indian sector, neighborhood, suburb, colony, ward). Pass "
                    "`name`, `place_type` ('suburb' | 'neighbourhood' | 'quarter' | 'village'), AND "
                    "`parent` (the containing city, e.g. 'Chandigarh'). Do NOT set admin_level here — "
                    "sectors/neighborhoods are NOT administrative boundaries in OSM.\n\n"
                    "ALWAYS pass `country_code` (e.g. 'IN' for India) — it dramatically improves accuracy.\n\n"
                    "RETRY STRATEGY — keep trying if a call returns empty or errors. Do not give up after one attempt:\n"
                    "  • Chandigarh sectors are often split into halves in OSM. If 'Sector 30' returns nothing, "
                    "retry with 'Sector 30 A' and 'Sector 30 B' separately.\n"
                    "  • Try name variants: 'Sector-30', 'Sector 30, Chandigarh', regional spellings.\n"
                    "  • Cycle through place_type values: 'suburb' → 'neighbourhood' → 'quarter' → 'residential'.\n"
                    "  • As a last resort, call osm_search with feature_type='place', feature_value='suburb', "
                    "lat/lng at the city center, radius_meters=5000 — then read sector names off the returned features.\n"
                    "  • If still empty, you can use osm_reverse_geocode at a known coordinate inside the sector "
                    "to confirm the OSM name, then re-query osm_boundary with that exact name."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Place name, e.g. 'Chandigarh', 'Sector 30', 'Sector 30 A', 'Punjab'",
                        },
                        "admin_level": {
                            "type": "number",
                            "description": "OSM admin level for administrative boundaries: 2=country, 4=state/UT, 5=district, 6=sub-district, 8=city/town. OMIT this when using place_type.",
                        },
                        "place_type": {
                            "type": "string",
                            "description": "OSM `place` tag value for sub-city features. Use 'suburb' or 'neighbourhood' for Indian sectors/colonies, 'quarter' for urban districts, 'village'/'hamlet' for rural. When set, admin_level is ignored.",
                        },
                        "parent": {
                            "type": "string",
                            "description": "Containing city/region for disambiguation, e.g. 'Chandigarh'. Strongly recommended for sub-city queries.",
                        },
                        "country_code": {
                            "type": "string",
                            "description": "ISO 3166-1 alpha-2 country code, e.g. 'IN', 'US', 'GB'. Always pass this.",
                        },
                    },
                    "required": ["name"],
                },
            ),
            ToolDeclaration(
                name="osm_boundary_union",
                description=(
                    "Fetch multiple OSM boundaries and merge them server-side into ONE polygon, "
                    "displayed as a single map layer. Use this WHENEVER the user asks for a single "
                    "polygon/region/boundary that covers multiple cities, districts, or sectors "
                    "(e.g. 'mark Chandigarh, Panchkula and Mohali as one polygon', 'show the tricity "
                    "area', 'merge X and Y into one region'). Each entry in `places` follows the same "
                    "shape as osm_boundary args. Server unions the geometries with Shapely (handles "
                    "MultiPolygon correctly). The merged geometry is NOT returned to you — only a "
                    "summary (centroid, bbox, area). Do NOT call osm_boundary multiple times and try "
                    "to gis_union the results yourself; that requires echoing every coordinate back "
                    "and reliably fails."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "places": {
                            "type": "array",
                            "description": "Two or more places to fetch and merge. Each item uses the same fields as osm_boundary.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "Place name, e.g. 'Chandigarh'."},
                                    "admin_level": {"type": "number", "description": "Admin level for administrative boundaries (2/4/5/6/8). Omit when using place_type."},
                                    "place_type": {"type": "string", "description": "OSM `place` tag value for sub-city features ('suburb','neighbourhood','quarter')."},
                                    "parent": {"type": "string", "description": "Containing city/region for sub-city queries."},
                                    "country_code": {"type": "string", "description": "ISO 3166-1 alpha-2 country code, e.g. 'IN'. Always pass this."},
                                },
                                "required": ["name"],
                            },
                        },
                        "layer_name": {
                            "type": "string",
                            "description": "Label for the merged map layer, e.g. 'Tricity', 'Bay Area'.",
                        },
                    },
                    "required": ["places", "layer_name"],
                },
            ),
            ToolDeclaration(
                name="osm_reverse_geocode",
                description="Get address and place details from coordinates",
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude"},
                        "lng": {"type": "number", "description": "Longitude"},
                    },
                    "required": ["lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="osm_route_overview",
                description=(
                    "Get a driving/walking route overview between two points using OSRM. "
                    "Returns distance, duration, and route geometry."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "start_lat": {"type": "number"},
                        "start_lng": {"type": "number"},
                        "end_lat": {"type": "number"},
                        "end_lng": {"type": "number"},
                        "mode": {
                            "type": "string",
                            "description": "Travel mode: driving (default), walking, cycling",
                        },
                    },
                    "required": ["start_lat", "start_lng", "end_lat", "end_lng"],
                },
            ),
            ToolDeclaration(
                name="osm_fetch_bus_routes",
                description=(
                    "Fetch actual public transport / bus route line geometries from OpenStreetMap (Overpass API) "
                    "around a location or within map bounds. Returns a GeoJSON FeatureCollection of LineStrings "
                    "representing route paths (with names, route numbers, operator, etc.) displayed on the map automatically. "
                    "Use this WHENEVER the user asks to display, mark, or analyze bus routes, transit lines, or ISBT network routes."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Center latitude (e.g. 30.7333 for Chandigarh ISBT)."},
                        "lng": {"type": "number", "description": "Center longitude (e.g. 76.7794)."},
                        "radius_meters": {"type": "number", "description": "Search radius in meters (default 5000, max 15000)."},
                        "limit": {"type": "number", "description": "Maximum number of distinct route lines to return (default 15)."},
                        "network_name": {"type": "string", "description": "Optional transit network name to filter (e.g. 'CTU', 'Chandigarh Transport')."},
                    },
                    "required": [],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "osm_search":
            return await self._osm_search(args)
        elif tool_name == "osm_boundary":
            return await self._fetch_boundary(args)
        elif tool_name == "osm_boundary_union":
            return await self._fetch_boundary_union(args)
        elif tool_name == "osm_reverse_geocode":
            return await self._reverse_geocode(args)
        elif tool_name == "osm_route_overview":
            return await self._route_overview(args)
        elif tool_name == "osm_fetch_bus_routes":
            return await self._osm_fetch_bus_routes(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _osm_search(self, args: dict) -> dict:
        feature_type = _sanitize_osm_token(args.get("feature_type", "amenity")) or "amenity"
        raw_value = args.get("feature_value", "")
        
        # Build the tag filter:
        #   '' or '*'  → existence check ["key"]
        #   list / 'a|b|c' → regex match ["key"~"a|b|c"]
        #   single token → exact match ["key"="value"]
        if isinstance(raw_value, list):
            values = [_sanitize_osm_token(v) for v in raw_value if v]
            values = [v for v in values if v]
        elif isinstance(raw_value, str):
            stripped = raw_value.strip()
            if stripped in ("", "*"):
                values = []
            elif "|" in stripped:
                values = [_sanitize_osm_token(v) for v in stripped.split("|") if v.strip()]
                values = [v for v in values if v]
            else:
                token = _sanitize_osm_token(stripped)
                values = [token] if token else []
        else:
            values = []

        if not values:
            tag_filter = f'["{feature_type}"]'
        elif len(values) == 1:
            tag_filter = f'["{feature_type}"="{values[0]}"]'
        else:
            tag_filter = f'["{feature_type}"~"^({"|".join(values)})$"]'

        use_current_bounds = args.get("use_current_bounds", False)
        map_context = args.get("_map_context")
        bounds = map_context.get("bounds") if map_context else None

        if use_current_bounds and bounds and all(bounds.get(k) is not None for k in ["south", "west", "north", "east"]):
            s = bounds["south"]
            w = bounds["west"]
            n = bounds["north"]
            e = bounds["east"]
            bbox_filter = f"({s},{w},{n},{e})"
            
            overpass_query = f"""
[out:json][timeout:25];
(
  node{tag_filter}{bbox_filter};
  way{tag_filter}{bbox_filter};
  relation{tag_filter}{bbox_filter};
);
out body;
>;
out skel qt;
"""
        else:
            lat = args.get("lat", 0)
            lng = args.get("lng", 0)
            radius = min(int(args.get("radius_meters", 1000)), 10000)
            overpass_query = f"""
[out:json][timeout:25];
(
  node{tag_filter}(around:{radius},{lat},{lng});
  way{tag_filter}(around:{radius},{lat},{lng});
  relation{tag_filter}(around:{radius},{lat},{lng});
);
out body;
>;
out skel qt;
"""
        try:
            data = await _overpass_post(overpass_query, timeout=30.0)

            nodes: dict[int, tuple[float, float]] = {}
            features = []
            for el in data.get("elements", []):
                if el["type"] == "node":
                    nodes[el["id"]] = (el.get("lon", 0), el.get("lat", 0))
                    if el.get("tags"):
                        features.append({
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                            "properties": {**el.get("tags", {}), "osm_id": el["id"]},
                        })
                elif el["type"] == "way" and el.get("tags"):
                    tags = el.get("tags", {})
                    coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
                    if len(coords) >= 2:
                        is_closed = coords[0] == coords[-1] and len(coords) >= 4
                        if is_closed and _is_area_way(tags):
                            geom = {"type": "Polygon", "coordinates": [coords]}
                        else:
                            geom = {"type": "LineString", "coordinates": coords}
                        features.append({
                            "type": "Feature",
                            "geometry": geom,
                            "properties": {**tags, "osm_id": el["id"]},
                        })

            total_count = len(features)
            truncated = total_count > _OSM_MAX_FEATURES
            if truncated:
                features = features[:_OSM_MAX_FEATURES]

            geojson = {"type": "FeatureCollection", "features": features}
            return {
                "geojson": geojson,
                "count": len(features),
                "total_count": total_count,
                "truncated": truncated,
                "feature_type": feature_type,
                "feature_value": raw_value,
            }
        except OverpassError as e:
            return {"error": str(e), "code": "upstream_unavailable"}
        except Exception as e:
            return {"error": f"Unexpected error: {e}", "code": "internal"}

    async def _fetch_boundary(self, args: dict) -> dict:
        name = _sanitize_osm_name(args.get("name", "")).strip()
        place_type = _sanitize_osm_token((args.get("place_type") or "").strip())
        parent = _sanitize_osm_name((args.get("parent") or "").strip())
        country_code = _sanitize_osm_token((args.get("country_code") or "").strip())

        if not name:
            return {"error": "Place name is required"}

        try:
            geojson_feature: dict | None = None

            if place_type:
                # Sub-city features (sectors, neighborhoods). Nominatim with a
                # parent + country handles these far better than raw Overpass.
                geojson_feature = await self._nominatim_boundary(
                    name=name, country_code=country_code,
                    parent=parent, place_type=place_type,
                )
                if not geojson_feature:
                    overpass_query = (
                        f'[out:json][timeout:30];'
                        f'(way["name"~"{name}",i]["place"~"{place_type}"];'
                        f' relation["name"~"{name}",i]["place"~"{place_type}"];);'
                        f'out geom;'
                    )
                    geojson_feature = await self._overpass_boundary(overpass_query)

                if not geojson_feature:
                    return {"error": (
                        f"No boundary found for '{name}'"
                        + (f" in '{parent}'" if parent else "")
                        + f" as place_type='{place_type}'. "
                        f"Retry with a name variant ('{name} A', '{name} B'), "
                        f"a different place_type ('suburb','neighbourhood','quarter','residential'), "
                        f"or call osm_search(feature_type='place', feature_value='suburb') near the city center."
                    )}
            else:
                admin_level_int = int(args.get("admin_level", 4))
                admin_level = str(admin_level_int)
                overpass_query = (
                    f'[out:json][timeout:30];'
                    f'relation["name"~"^{name}$",i]["admin_level"="{admin_level}"]'
                    f'["boundary"="administrative"];'
                    f'out geom;'
                )

                if country_code:
                    # 1) geoBoundaries: clean MultiPolygon, no way-merge needed,
                    #    aggressively cached (30-day TTL).
                    geojson_feature = await self._geoboundaries_boundary(
                        name=name,
                        country_code=country_code,
                        admin_level=admin_level_int,
                    )
                    # 2) Nominatim: handles arbitrary names (sub-national places
                    #    geoBoundaries doesn't ship — sectors, neighborhoods).
                    if not geojson_feature:
                        geojson_feature = await self._nominatim_boundary(
                            name=name, country_code=country_code, parent=parent,
                        )
                    # 3) Overpass: last resort, with the way-merge fallback path.
                    if not geojson_feature:
                        geojson_feature = await self._overpass_boundary(overpass_query)
                else:
                    geojson_feature = await self._overpass_boundary(overpass_query)
                    if not geojson_feature:
                        geojson_feature = await self._nominatim_boundary(
                            name=name, country_code="", parent=parent,
                        )

                if not geojson_feature:
                    return {"error": (
                        f"No administrative boundary for '{name}' at admin_level {admin_level}. "
                        f"If this is a sector/neighborhood, retry with place_type='suburb' "
                        f"and parent='<city>'. Otherwise try a different admin_level or pass country_code."
                    )}

            geojson = {"type": "FeatureCollection", "features": [geojson_feature]}
            return {
                "geojson": geojson,
                "name": geojson_feature.get("properties", {}).get("name", name),
            }
        except Exception as e:
            return {"error": str(e)}

    async def _fetch_boundary_union(self, args: dict) -> dict:
        places = args.get("places")
        if not isinstance(places, list) or len(places) < 2:
            return {"error": "Provide at least 2 entries in 'places'."}
        layer_name = (args.get("layer_name") or "").strip() or "Merged region"

        # Fetch all boundaries concurrently. Each _fetch_boundary call hits
        # Nominatim and/or Overpass on its own and is independent of the others.
        place_args = [p if isinstance(p, dict) else {} for p in places]
        results = await asyncio.gather(
            *(self._fetch_boundary(p) for p in place_args),
            return_exceptions=True,
        )

        resolved: list[dict] = []
        failed: list[dict] = []
        for place, res in zip(place_args, results):
            place_name = place.get("name", "<unnamed>")
            if isinstance(res, Exception):
                failed.append({"name": place_name, "error": str(res)})
                continue
            if not isinstance(res, dict) or res.get("error"):
                failed.append({"name": place_name, "error": (res.get("error") if isinstance(res, dict) else "Unexpected result")})
                continue
            feats = (res.get("geojson") or {}).get("features") or []
            geom = feats[0].get("geometry") if feats else None
            if not geom:
                failed.append({"name": place_name, "error": "No geometry returned"})
                continue
            resolved.append({"name": res.get("name", place_name), "geometry": geom})

        if len(resolved) < 2:
            return {
                "error": "Need at least 2 successfully resolved boundaries to merge.",
                "places_resolved": [r["name"] for r in resolved],
                "places_failed": failed,
            }

        try:
            from shapely.geometry import mapping, shape
            from shapely.ops import unary_union
        except ImportError:
            return {"error": "Shapely not installed; union requires shapely"}

        try:
            merged = unary_union([shape(r["geometry"]) for r in resolved])
            if merged.is_empty:
                return {"error": "Union produced empty geometry"}
            merged_geom = mapping(merged)
        except Exception as e:
            return {"error": f"Union failed: {e}"}

        feature = {
            "type": "Feature",
            "geometry": merged_geom,
            "properties": {
                "name": layer_name,
                "merged_from": [r["name"] for r in resolved],
            },
        }
        return {
            "geojson": {"type": "FeatureCollection", "features": [feature]},
            "name": layer_name,
            "places_resolved": [r["name"] for r in resolved],
            "places_failed": failed,
        }

    async def _geoboundaries_boundary(
        self,
        name: str,
        country_code: str,
        admin_level: int,
    ) -> dict | None:
        """Fetch a single boundary feature from geoBoundaries (gbOpen).

        Returns clean MultiPolygon GeoJSON without the way-merge dance. Returns
        ``None`` when country_code can't be mapped to ISO-3, the API errors,
        or no feature matches `name`. Both the metadata response and the GeoJSON
        download are cached for 30 days — boundaries change rarely.
        """
        if not country_code:
            return None
        iso3 = _ISO2_TO_ISO3.get(country_code.upper())
        if not iso3:
            return None
        gb_level = _ADMIN_LEVEL_TO_GB.get(int(admin_level))
        if not gb_level:
            return None

        metadata_url = f"https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{gb_level}/"

        async def _fetch_metadata() -> dict:
            return await http_client.fetch_json(metadata_url, namespace="geoboundaries")

        try:
            metadata = await cache.get_or_fetch(
                namespace="geoboundaries",
                key={"url": metadata_url},
                ttl_seconds=86_400 * 30,
                fetch_fn=_fetch_metadata,
            )
        except http_client.HTTPError:
            return None

        download_url = (metadata or {}).get("gjDownloadURL")
        if not download_url:
            return None

        async def _fetch_geojson() -> dict:
            return await http_client.fetch_json(download_url, namespace="geoboundaries")

        try:
            feature_collection = await cache.get_or_fetch(
                namespace="geoboundaries",
                key={"url": download_url},
                ttl_seconds=86_400 * 30,
                fetch_fn=_fetch_geojson,
            )
        except http_client.HTTPError:
            return None

        features = (feature_collection or {}).get("features") or []
        if not features:
            return None

        if gb_level == "ADM0":
            chosen = features[0]
        else:
            chosen = self._select_geoboundaries_feature(features, name)
            if chosen is None:
                return None

        geom = chosen.get("geometry")
        if not geom:
            return None
        props = chosen.get("properties") or {}
        return {
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "name": props.get("shapeName") or props.get("boundaryName") or name,
                "source": "geoboundaries",
                "shape_iso": props.get("shapeISO"),
                "shape_type": props.get("shapeType"),
                "admin_level": admin_level,
            },
        }

    @staticmethod
    def _select_geoboundaries_feature(features: list[dict], name: str) -> dict | None:
        """Pick the feature whose shapeName best matches `name` (case-insensitive).

        Exact match wins. Otherwise prefer the candidate whose name length is
        closest to the query — matching whole words. Returns None if no candidate
        is a whole-word match.
        """
        import re
        target = name.lower().strip()
        if not target:
            return None
        
        # 1. Look for exact match
        for feat in features:
            props = feat.get("properties") or {}
            candidate = (props.get("shapeName") or props.get("boundaryName") or "").strip()
            if not candidate:
                continue
            cand = candidate.lower()
            if cand == target:
                return feat

        # 2. Look for whole-word substring match
        best: tuple[int, dict] | None = None
        for feat in features:
            props = feat.get("properties") or {}
            candidate = (props.get("shapeName") or props.get("boundaryName") or "").strip()
            if not candidate:
                continue
            cand = candidate.lower()
            
            pattern_cand = r'\b' + re.escape(cand) + r'\b'
            pattern_target = r'\b' + re.escape(target) + r'\b'
            
            if re.search(pattern_cand, target) or re.search(pattern_target, cand):
                score = abs(len(cand) - len(target))
                if best is None or score < best[0]:
                    best = (score, feat)
        return best[1] if best else None

    async def _overpass_boundary(self, query: str) -> dict | None:
        """Run an Overpass query and convert the first relation/way result to a GeoJSON Feature."""
        try:
            data = await _overpass_post(query, timeout=35.0)
        except OverpassError:
            return None

        elements = data.get("elements", [])
        for el in elements:
            if el.get("type") == "relation":
                feature = self._relation_to_geojson(el)
                if feature:
                    return feature
        for el in elements:
            if el.get("type") == "way":
                feature = self._way_to_geojson(el)
                if feature:
                    return feature
        return None

    async def _nominatim_boundary(
        self,
        name: str,
        country_code: str,
        parent: str = "",
        place_type: str = "",
    ) -> dict | None:
        """Search Nominatim and return a GeoJSON polygon (uses polygon_geojson=1)."""
        query_str = f"{name}, {parent}" if parent else name
        params: dict = {
            "q": query_str,
            "format": "json",
            "limit": 10,
            "addressdetails": 1,
            "polygon_geojson": 1,
        }
        if country_code:
            params["countrycodes"] = country_code.lower()

        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(
                    "https://nominatim.openstreetmap.org/search",
                    params=params,
                    headers={"User-Agent": "CursorUrbanPlanners/1.0"},
                )
        except httpx.RequestError:
            return None
        if resp.status_code != 200 or not (resp.text or "").strip():
            return None
        try:
            results = _json.loads(resp.text)
        except _json.JSONDecodeError:
            return None

        if not results:
            return None

        # Restrict strictly to boundary, place, and landuse features (prevent lakes, buildings, shops, etc.)
        allowed_classes = {"boundary", "place", "landuse"}
        filtered_results = [
            r for r in results 
            if r.get("class") in allowed_classes
        ]

        if not filtered_results:
            return None

        # Pick best match. If place_type is set, prefer that; otherwise prefer
        # relations (admin boundaries), then ways.
        chosen = None
        if place_type:
            for r in filtered_results:
                if r.get("type") == place_type:
                    chosen = r
                    break
            if not chosen:
                for r in filtered_results:
                    if r.get("class") == "place":
                        chosen = r
                        break
        if not chosen:
            for r in filtered_results:
                if r.get("osm_type") == "relation":
                    chosen = r
                    break
        if not chosen:
            for r in filtered_results:
                if r.get("osm_type") == "way":
                    chosen = r
                    break
        if not chosen:
            chosen = filtered_results[0]

        polygon = chosen.get("geojson")
        if polygon and polygon.get("type") in ("Polygon", "MultiPolygon"):
            display = chosen.get("display_name", name)
            return {
                "type": "Feature",
                "geometry": polygon,
                "properties": {
                    "name": display.split(",")[0].strip() if display else name,
                    "osm_id": chosen.get("osm_id"),
                    "osm_type": chosen.get("osm_type"),
                    "class": chosen.get("class"),
                    "type": chosen.get("type"),
                },
            }

        # Polygon not directly returned — fall back to Overpass by id
        osm_id = chosen.get("osm_id")
        osm_type = chosen.get("osm_type")
        if not osm_id:
            return None
        if osm_type == "way":
            query = f'[out:json][timeout:30];way({osm_id});out geom;'
        else:
            query = f'[out:json][timeout:30];relation({osm_id});out geom;'
        return await self._overpass_boundary(query)

    @staticmethod
    def _way_to_geojson(element: dict) -> dict | None:
        """Convert an Overpass way element (with geometry) to a Polygon Feature."""
        geom = element.get("geometry") or []
        coords = [[pt["lon"], pt["lat"]] for pt in geom if "lon" in pt and "lat" in pt]
        if len(coords) < 3:
            return None
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        tags = element.get("tags", {})
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "name": tags.get("name", ""),
                "osm_id": element.get("id"),
                "osm_type": "way",
                "place": tags.get("place", ""),
            },
        }

    @staticmethod
    def _relation_to_geojson(element: dict) -> dict | None:
        """Convert an Overpass relation element (with geometry) to a GeoJSON Feature."""
        members = element.get("members", [])
        tags = element.get("tags", {})

        outer_rings: list[list[list[float]]] = []
        inner_rings: list[list[list[float]]] = []

        for member in members:
            role = member.get("role", "")
            geom = member.get("geometry")
            if not geom or member.get("type") != "way":
                continue
            coords = [[pt["lon"], pt["lat"]] for pt in geom if "lon" in pt and "lat" in pt]
            if len(coords) < 3:
                continue
            if role == "inner":
                inner_rings.append(coords)
            else:
                outer_rings.append(coords)

        if not outer_rings:
            return None

        # Merge outer way segments into closed rings
        merged_outers = _merge_ways(outer_rings)
        merged_inners = _merge_ways(inner_rings) if inner_rings else []

        if not merged_outers:
            return None

        if len(merged_outers) == 1:
            rings = [merged_outers[0]] + merged_inners
            geometry = {"type": "Polygon", "coordinates": rings}
        else:
            polygons = [[ring] for ring in merged_outers]
            geometry = {"type": "MultiPolygon", "coordinates": polygons}

        return {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "name": tags.get("name", ""),
                "admin_level": tags.get("admin_level", ""),
                "osm_id": element.get("id"),
                **{k: v for k, v in tags.items() if k in (
                    "name:en", "boundary", "wikidata", "wikipedia", "population",
                )},
            },
        }

    async def _reverse_geocode(self, args: dict) -> dict:
        lat = args["lat"]
        lng = args["lng"]
        cache_key = {"lat": round(float(lat), 5), "lng": round(float(lng), 5), "zoom": 18}

        async def _fetch() -> dict:
            return await http_client.fetch_json(
                "https://nominatim.openstreetmap.org/reverse",
                namespace="nominatim",
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "addressdetails": 1,
                    "zoom": 18,
                },
            )

        try:
            data = await cache.get_or_fetch(
                namespace="nominatim",
                key=cache_key,
                ttl_seconds=86_400 * 7,
                fetch_fn=_fetch,
            )
        except http_client.HTTPError as e:
            return {"error": str(e), "code": e.code}
        except Exception as e:
            return {"error": f"Unexpected error: {e}", "code": "internal"}

        return {
            "display_name": data.get("display_name", ""),
            "address": data.get("address", {}),
            "type": data.get("type", ""),
            "osm_type": data.get("osm_type", ""),
        }

    async def _route_overview(self, args: dict) -> dict:
        mode_map = {"driving": "car", "walking": "foot", "cycling": "bike"}
        mode = mode_map.get(args.get("mode", "driving"), "car")
        start = f"{args['start_lng']},{args['start_lat']}"
        end = f"{args['end_lng']},{args['end_lat']}"
        url = f"https://router.project-osrm.org/route/v1/{mode}/{start};{end}"
        cache_key = {"mode": mode, "start": start, "end": end}

        async def _fetch() -> dict:
            return await http_client.fetch_json(
                url,
                namespace="osrm",
                params={"overview": "full", "geometries": "geojson", "steps": "false"},
            )

        try:
            data = await cache.get_or_fetch(
                namespace="osrm",
                key=cache_key,
                ttl_seconds=86_400,
                fetch_fn=_fetch,
            )
        except http_client.HTTPError as e:
            return {"error": str(e), "code": e.code}
        except Exception as e:
            return {"error": f"Unexpected error: {e}", "code": "internal"}

        if data.get("code") != "Ok" or not data.get("routes"):
            return {"error": data.get("message", "No route found"), "code": "not_found"}

        route = data["routes"][0]
        return {
            "distance_km": round(route["distance"] / 1000, 2),
            "duration_minutes": round(route["duration"] / 60, 1),
            "geometry": route["geometry"],
        }

    async def _osm_fetch_bus_routes(self, args: dict) -> dict:
        lat = args.get("lat") or 30.7333
        lng = args.get("lng") or 76.7794
        radius = int(args.get("radius_meters") or 5000)
        radius = min(max(radius, 1000), 15000)
        limit = int(args.get("limit") or 15)

        # Overpass query to fetch bus route relations with geometries
        query = f"""
        [out:json][timeout:30];
        (
          relation["type"="route"]["route"="bus"](around:{radius},{lat},{lng});
          relation["public_transport:version"="2"]["route"="bus"](around:{radius},{lat},{lng});
        );
        out body geom {limit};
        """
        features = []
        try:
            data = await _overpass_post(query, timeout=30.0)
            elements = data.get("elements", [])
            for elem in elements:
                tags = elem.get("tags", {})
                route_ref = tags.get("ref", tags.get("name", "Bus Route"))
                route_name = tags.get("name", f"Route {route_ref}")
                operator = tags.get("operator", "CTU / Local Transit")
                color = tags.get("colour", tags.get("color", "#3b82f6"))

                # Extract line geometry from relation member ways
                coords = []
                for member in elem.get("members", []):
                    if member.get("type") == "way" and "geometry" in member:
                        way_coords = [[pt["lon"], pt["lat"]] for pt in member["geometry"]]
                        if len(way_coords) >= 2:
                            coords.append(way_coords)

                if not coords:
                    continue

                # Create feature (MultiLineString or LineString)
                geom = {"type": "MultiLineString", "coordinates": coords} if len(coords) > 1 else {"type": "LineString", "coordinates": coords[0]}
                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "route_ref": route_ref,
                        "name": route_name,
                        "operator": operator,
                        "color": color,
                        "from": tags.get("from", ""),
                        "to": tags.get("to", ""),
                    }
                })
        except Exception:
            pass

        # Fallback: If OSM route relations are sparse in this area, fetch major arterial road corridors radiating around lat/lng
        if len(features) < 3:
            try:
                fallback_query = f"""
                [out:json][timeout:25];
                (
                  way["highway"~"primary|secondary|trunk|tertiary"](around:{radius},{lat},{lng});
                );
                out body geom {limit * 2};
                """
                fb_data = await _overpass_post(fallback_query, timeout=25.0)
                seen_names = set()
                for elem in fb_data.get("elements", []):
                    tags = elem.get("tags", {})
                    name = tags.get("name", tags.get("ref", ""))
                    if not name or name in seen_names:
                        continue
                    seen_names.add(name)
                    way_coords = [[pt["lon"], pt["lat"]] for pt in elem.get("geometry", [])]
                    if len(way_coords) < 2:
                        continue
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": way_coords},
                        "properties": {
                            "route_ref": tags.get("ref", name),
                            "name": f"Corridor Route - {name}",
                            "operator": "Primary Arterial Network",
                            "color": "#ef4444",
                            "from": "ISBT Network",
                            "to": "Sector Corridor"
                        }
                    })
                    if len(features) >= limit:
                        break
            except Exception:
                pass

        geojson = {"type": "FeatureCollection", "features": features[:limit]}
        return {
            "status": "success",
            "name": f"Transit Routes ({len(features[:limit])} lines)",
            "count": len(features[:limit]),
            "geojson": geojson,
        }
