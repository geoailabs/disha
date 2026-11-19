"""
Demographics & Employment — population and jobs near a point.

WorldPop (wpgppop, 100m grid, ML-modeled) is the primary source for population.
Employment is estimated via a Multi-Source Proxy Model or custom dataset.
"""

from __future__ import annotations

import math
import os
import json
from pathlib import Path
from llm.base import ToolDeclaration
from tools import cache, http as http_client, worldpop
from tools.geo import geodesic_buffer, geodesic_area_m2

try:
    import shapely.geometry as sg
    from shapely.geometry import shape, Point
    from shapely.ops import unary_union
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False
    sg = None
    shape = None
    Point = None
    unary_union = None


_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _resolve_workspace(workspace_arg: str) -> str:
    if not workspace_arg:
        return ""
    arg = workspace_arg.strip()
    if not arg or arg == "/workspace" or arg == ".":
        return ""
    return str(Path(arg).resolve())


class DemographicsServer:
    description = "Population & Employment demographics around coordinates and projections forecasting"
    tool_names = {"get_demographics", "project_population", "get_employment_density", "project_employment"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="get_demographics",
                description=(
                    "Estimate total population and population density for a boundary or around coordinates. "
                    "Multi-tier sources: WorldPop 100m grid, JRC GHSL multitemporal, and OSM tagged populations. "
                    "Returns total population, population density in persons/ha and persons/km², urban density classification, "
                    "and study area size. Supports place_name, polygon GeoJSON, or lat/lng with search radius across years 2000-2030."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_name": {
                            "type": "string",
                            "description": "Place name or city to query (e.g. 'Austin, Texas', 'Oxford'). Resolves administrative boundary.",
                        },
                        "geojson": {
                            "type": "object",
                            "description": "Optional GeoJSON Feature, FeatureCollection, or Polygon to aggregate population within.",
                        },
                        "lat": {"type": "number", "description": "Center latitude (if querying point radius)."},
                        "lng": {"type": "number", "description": "Center longitude (if querying point radius)."},
                        "radius_meters": {
                            "type": "number",
                            "description": "Search radius in meters when using lat/lng (default 8000, max 25000).",
                        },
                        "year": {
                            "type": "integer",
                            "description": "Year of population data (2000-2030, default 2020).",
                        },
                    },
                    "required": [],
                },
            ),
            ToolDeclaration(
                name="project_population",
                description=(
                    "Forecast future population growth for a study area. Can automatically retrieve the baseline "
                    "population at a coordinate for a specific year, or accept an explicit baseline population value. Supports linear, "
                    "exponential, and logistic models with annual growth rate, baseline year, target years, and carrying capacity constraints."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "base_population": {
                            "type": "integer",
                            "description": "Baseline population. If not specified, lat and lng must be provided to fetch gridded population."
                        },
                        "base_year": {
                            "type": "integer",
                            "description": "Baseline year corresponding to base_population (default 2020 for gridded data, or current planning year like 2026)."
                        },
                        "growth_rate": {
                            "type": "number",
                            "description": "Annual population growth rate as a decimal (e.g. 0.025 for 2.5% growth). Default: 0.02"
                        },
                        "target_years": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of future years to calculate projections for (e.g. [2030, 2040, 2050]). Default: [2030, 2035, 2040, 2045, 2050]"
                        },
                        "model_type": {
                            "type": "string",
                            "enum": ["exponential", "linear", "logistic"],
                            "description": "Growth model formulation. Default: exponential"
                        },
                        "carrying_capacity": {
                            "type": "integer",
                            "description": "Upper population ceiling constraint for the logistic model. Required if model_type is 'logistic'."
                        },
                        "lat": {
                            "type": "number",
                            "description": "Latitude to fetch base population (optional if base_population is provided)."
                        },
                        "lng": {
                            "type": "number",
                            "description": "Longitude to fetch base population (optional if base_population is provided)."
                        },
                        "radius_meters": {
                            "type": "number",
                            "description": "Demographic search radius in meters (default 5000)."
                        }
                    },
                    "required": []
                }
            ),
            ToolDeclaration(
                name="get_employment_density",
                description=(
                    "Estimate employment density (job counts) around a coordinate. "
                    "Checks for a custom 'employment_grid.geojson' or 'employment.geojson' "
                    "in the workspace first to sample actual data. "
                    "If absent, calculates a multi-source proxy: builds a local model using "
                    "building footprints (Overture/OSM), point POIs, and zoning layer areas. "
                    "Job density coefficients automatically adapt to the municipality (e.g. Chandigarh, Mohali) "
                    "and scale based on whether the area is high-density urban core vs. suburban, "
                    "plus additional density increases in Transit-Oriented Development (TOD) corridors."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Center latitude coordinate."},
                        "lng": {"type": "number", "description": "Center longitude coordinate."},
                        "radius_meters": {
                            "type": "number",
                            "description": "Search radius in meters (default 2000, max 10000).",
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder.",
                        },
                        "coefficient_overrides": {
                            "type": "object",
                            "description": "Optional dictionary of custom sqm_per_job or flat jobs values to override defaults.",
                        }
                    },
                    "required": ["lat", "lng", "workspace"]
                }
            ),
            ToolDeclaration(
                name="project_employment",
                description=(
                    "Forecast future employment (job growth) for a study area. "
                    "Can automatically calculate baseline jobs at a coordinate or accept a custom baseline. "
                    "Supports linear, exponential, and logistic growth models. "
                    "Calculates the future commercial and industrial land demand (hectares) "
                    "required to support the projected jobs based on employment space standards."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "base_jobs": {
                            "type": "integer",
                            "description": "Baseline job count. If not specified, lat, lng, and workspace must be provided to estimate current baseline jobs."
                        },
                        "base_year": {
                            "type": "integer",
                            "description": "Baseline year corresponding to base_jobs (default current year, e.g. 2026)."
                        },
                        "growth_rate": {
                            "type": "number",
                            "description": "Annual employment growth rate as a decimal (e.g. 0.03 for 3% growth). Default: 0.025"
                        },
                        "target_years": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of future years to calculate projections for (e.g. [2030, 2040, 2050]). Default: [2030, 2035, 2040, 2045, 2050]"
                        },
                        "model_type": {
                            "type": "string",
                            "enum": ["exponential", "linear", "logistic"],
                            "description": "Growth model formulation. Default: exponential"
                        },
                        "carrying_capacity": {
                            "type": "integer",
                            "description": "Upper limit job constraint for the logistic model. Required if model_type is 'logistic'."
                        },
                        "lat": {
                            "type": "number",
                            "description": "Latitude to estimate baseline jobs."
                        },
                        "lng": {
                            "type": "number",
                            "description": "Longitude to estimate baseline jobs."
                        },
                        "radius_meters": {
                            "type": "number",
                            "description": "Search radius in meters (default 2000)."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder. Required if lat/lng are used."
                        },
                        "space_standard_sqm": {
                            "type": "number",
                            "description": "Average floor space standard per worker in sqm (default 20.0). Used to calculate commercial/industrial land requirements."
                        },
                        "average_far": {
                            "type": "number",
                            "description": "Average Floor Area Ratio / FSI for new developments (default 2.0). Used to estimate raw land requirements."
                        }
                    },
                    "required": []
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "get_demographics":
            return await self._get_demographics(args)
        if tool_name == "project_population":
            return await self._project_population(args)
        if tool_name == "get_employment_density":
            return await self._get_employment_density(args)
        if tool_name == "project_employment":
            return await self._project_employment(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _get_demographics(self, args: dict) -> dict:
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        radius = min(int(args.get("radius_meters", 8000)), 25000)
        req_year = args.get("year")
        year = int(req_year) if req_year is not None else 2020
        valid_year = min(max(year, 2000), 2020)
        place_name = (args.get("place_name") or "").strip()
        geojson_input = args.get("geojson")

        polygon = None
        resolved_place = place_name

        # 1. Resolve geometry from GeoJSON, place name, or point radius
        if geojson_input:
            if isinstance(geojson_input, dict):
                gtype = geojson_input.get("type")
                if gtype in ("Polygon", "MultiPolygon"):
                    polygon = geojson_input
                elif gtype == "Feature":
                    polygon = geojson_input.get("geometry")
                elif gtype == "FeatureCollection":
                    feats = geojson_input.get("features", [])
                    if feats:
                        polygon = feats[0].get("geometry")

        if polygon is None and place_name:
            try:
                nom_res = await http_client.fetch_json(
                    "https://nominatim.openstreetmap.org/search",
                    namespace="nominatim",
                    params={
                        "q": place_name,
                        "format": "json",
                        "polygon_geojson": 1,
                        "limit": 1,
                    },
                )
                if nom_res and isinstance(nom_res, list) and len(nom_res) > 0:
                    entry = nom_res[0]
                    resolved_place = entry.get("display_name", place_name)
                    if lat == 0 and lng == 0:
                        lat = float(entry.get("lat", 0))
                        lng = float(entry.get("lon", 0))
                    g = entry.get("geojson")
                    if g and g.get("type") in ("Polygon", "MultiPolygon"):
                        polygon = g
            except Exception:
                pass

        if polygon is None:
            point_geom = {"type": "Point", "coordinates": [lng, lat]}
            polygon = geodesic_buffer(point_geom, radius)

        # 2. Compute study area metrics
        area_m2 = geodesic_area_m2(polygon)
        area_ha = round(area_m2 / 10000.0, 2)
        area_km2 = round(area_m2 / 1000000.0, 3)

        out: dict = {
            "status": "success",
            "input": {"lat": lat, "lng": lng, "radius_meters": radius, "year": year, "place_name": place_name or None},
            "place_name": resolved_place or None,
            "population": None,
            "population_source": None,
            "population_year": valid_year,
            "area_ha": area_ha,
            "area_km2": area_km2,
            "population_density_ha": None,
            "population_density_sqkm": None,
            "density_classification": None,
            "places_with_population": [],
            "reverse_geocode_summary": None,
            "notes": (
                f"Multi-tier demographics: WorldPop (100m grid, 2000-2020), JRC GHSL (1975-2030), "
                "and OSM tagged populations. Density benchmark: <25 pph (Rural), 25-75 (Suburban), 75-150 (Urban), 150+ (High Density Core)."
            ),
        }

        # 3. Multi-tier population calculation
        # Tier 1: WorldPop API (for years <= 2020)
        wp_pop = None
        if year <= 2020:
            try:
                wp_pop = await worldpop.population_in_polygon(polygon, year=valid_year)
            except Exception as e:
                out["worldpop_error"] = str(e)

        if wp_pop is not None:
            out["population"] = round(wp_pop)
            out["population_source"] = f"WorldPop 100m grid ({valid_year})"
            out["population_year"] = valid_year
        else:
            # Tier 2: Fall back to GEE if available (for fast cloud execution or year > 2020 via GHSL)
            try:
                from mcp_servers.gee_server import _ensure_gee
                ok, _ = await _ensure_gee()
                if ok:
                    import ee
                    if year > 2020:
                        ghsl_years = [1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025, 2030]
                        closest_yr = min(ghsl_years, key=lambda y: abs(y - year))
                        coll = ee.ImageCollection("JRC/GHSL/P2023A/GHS_POP").filterDate(f"{closest_yr}-01-01", f"{closest_yr}-12-31")
                        pop_img = coll.first()
                        gee_source = f"JRC GHSL ({closest_yr})"
                        resolved_gee_yr = closest_yr
                    else:
                        coll = ee.ImageCollection("WorldPop/GP/100m/pop").filter(ee.Filter.eq("year", valid_year))
                        pop_img = coll.mosaic()
                        gee_source = f"WorldPop GEE ({valid_year})"
                        resolved_gee_yr = valid_year

                    ee_geom = ee.Geometry(polygon)
                    stats = pop_img.reduceRegion(
                        reducer=ee.Reducer.sum(),
                        geometry=ee_geom,
                        scale=100,
                        maxPixels=1_000_000_000,
                    ).getInfo()
                    if stats:
                        val = next(iter(stats.values()), None)
                        if val is not None and val > 0:
                            out["population"] = round(float(val))
                            out["population_source"] = gee_source
                            out["population_year"] = resolved_gee_yr
            except Exception as gee_err:
                out["gee_error"] = str(gee_err)

        if lat != 0 and lng != 0:
            out["reverse_geocode_summary"] = await self._reverse_summary(lat, lng)
            out["places_with_population"] = await self._osm_population_tags(lat, lng, radius)

        # Tier 3: OSM tagged values fallback
        if out["population"] is None and out["places_with_population"]:
            tagged = [_to_int(p["population"]) for p in out["places_with_population"]]
            tagged = [t for t in tagged if t is not None]
            if tagged:
                out["population"] = max(tagged)
                out["population_source"] = "OSM tagged values"

        # 4. Standardized population density calculations
        if out["population"] is not None and area_ha > 0:
            dens_ha = round(out["population"] / area_ha, 2)
            dens_km2 = round(out["population"] / area_km2, 1) if area_km2 > 0 else 0.0

            if dens_ha < 25.0:
                dens_class = "Rural (<25 pph)"
            elif dens_ha < 75.0:
                dens_class = "Suburban (25-75 pph)"
            elif dens_ha < 150.0:
                dens_class = "Urban (75-150 pph)"
            else:
                dens_class = "High-Density Core (150+ pph)"

            out["population_density_ha"] = dens_ha
            out["population_density_sqkm"] = dens_km2
            out["density_classification"] = dens_class

        return out

    @staticmethod
    async def _reverse_summary(lat: float, lng: float) -> dict | None:
        cache_key = {"lat": round(lat, 4), "lng": round(lng, 4), "zoom": 10}

        async def _fetch() -> dict:
            return await http_client.fetch_json(
                "https://nominatim.openstreetmap.org/reverse",
                namespace="nominatim",
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "addressdetails": 1,
                    "zoom": 10,
                },
            )

        try:
            data = await cache.get_or_fetch(
                namespace="nominatim",
                key=cache_key,
                ttl_seconds=86_400 * 7,
                fetch_fn=_fetch,
            )
        except Exception:
            return None
        return {
            "display_name": data.get("display_name", ""),
            "type": data.get("type", ""),
            "address": data.get("address", {}),
        }

    @staticmethod
    async def _osm_population_tags(lat: float, lng: float, radius: int) -> list[dict]:
        query = (
            f"[out:json][timeout:25];"
            f"("
            f'node["population"](around:{radius},{lat},{lng});'
            f'way["population"](around:{radius},{lat},{lng});'
            f");"
            f"out center tags 25;"
        )
        cache_key = {"q": query}

        async def _fetch() -> dict:
            return await http_client.fetch_json(
                _OVERPASS_URL,
                namespace="overpass",
                params={"data": query},
            )

        try:
            data = await cache.get_or_fetch(
                namespace="overpass",
                key=cache_key,
                ttl_seconds=86_400,
                fetch_fn=_fetch,
            )
        except Exception:
            return []

        seen: set = set()
        out: list[dict] = []
        for el in (data or {}).get("elements", [])[:25]:
            tags = el.get("tags", {})
            pop = tags.get("population")
            name = tags.get("name", "")
            if not pop:
                continue
            key = (name, pop)
            if key in seen:
                continue
            seen.add(key)
            center = el.get("center", {})
            plat = center.get("lat") or el.get("lat")
            plon = center.get("lon") or el.get("lon")
            out.append({
                "name": name,
                "population": pop,
                "place": tags.get("place", ""),
                "admin_level": tags.get("admin_level", ""),
                "lat": plat,
                "lon": plon,
            })
        return out

    async def _project_population(self, args: dict) -> dict:
        import math
        base_pop_arg = args.get("base_population")
        growth_rate = float(args.get("growth_rate", 0.02))
        target_years = args.get("target_years") or [2030, 2035, 2040, 2045, 2050]
        model_type = args.get("model_type", "exponential").strip().lower()
        carrying_capacity = args.get("carrying_capacity")
        lat_arg = args.get("lat")
        lng_arg = args.get("lng")
        radius = int(args.get("radius_meters", 5000))
        user_base_year = args.get("base_year")

        # 1. Resolve base population
        base_population = None
        base_year = None
        source_summary = ""

        if base_pop_arg is not None:
            try:
                base_population = int(base_pop_arg)
                base_year = int(user_base_year) if user_base_year is not None else 2026
                source_summary = f"User-supplied explicit baseline value for year {base_year}"
            except (ValueError, TypeError):
                return {"error": "Invalid base_population value. Must be an integer."}

        elif lat_arg is not None and lng_arg is not None:
            # Query WorldPop/OSM demographics at these coordinates
            req_year = int(user_base_year) if user_base_year is not None else 2020
            demog_args = {"lat": float(lat_arg), "lng": float(lng_arg), "radius_meters": radius, "year": req_year}
            demog_res = await self._get_demographics(demog_args)
            if demog_res.get("population") is not None:
                base_population = demog_res["population"]
                base_year = int(user_base_year) if user_base_year is not None else demog_res.get("population_year", 2020)
                # Extract a human-readable place name from the reverse geocode summary
                rev = demog_res.get("reverse_geocode_summary") or {}
                addr = rev.get("address", {})
                place_name_raw = (
                    addr.get("city")
                    or addr.get("town")
                    or addr.get("district")
                    or addr.get("county")
                    or addr.get("state")
                    or ""
                )
                source_summary = (
                    f"Geolocated baseline ({base_year}) near {place_name_raw} ({lat_arg}, {lng_arg}) "
                    f"using {demog_res['population_source']} source."
                    if place_name_raw
                    else f"Geolocated baseline ({base_year}) around coordinates ({lat_arg}, {lng_arg}) using {demog_res['population_source']} source."
                )
            else:
                return {"error": f"Could not determine baseline population at coordinates ({lat_arg}, {lng_arg}). Please specify base_population explicitly."}
        else:
            return {"error": "Either base_population or geocoding lat/lng coordinates must be provided."}

        if base_population <= 0:
            return {"error": f"Base population must be greater than zero. Received: {base_population}"}

        if model_type == "logistic":
            if carrying_capacity is None:
                return {"error": "carrying_capacity limit is required when model_type is set to 'logistic'."}
            try:
                carrying_capacity = int(carrying_capacity)
            except (ValueError, TypeError):
                return {"error": "Invalid carrying_capacity value. Must be an integer."}
            if carrying_capacity <= base_population:
                return {"error": f"Carrying capacity ceiling ({carrying_capacity}) must be greater than the base population ({base_population})."}

        # 2. Run projection
        if base_year is None:
            base_year = int(user_base_year) if user_base_year is not None else 2020
        results = []

        # Sort years to be chronological
        sorted_years = sorted(list(set([int(y) for y in target_years if int(y) > base_year])))
        if not sorted_years:
            return {"error": f"All target years must be greater than the baseline year {base_year}."}

        for yr in sorted_years:
            dt = yr - base_year
            if model_type == "linear":
                proj = base_population * (1.0 + growth_rate * dt)
            elif model_type == "logistic":
                try:
                    exp_factor = math.exp(growth_rate * dt)
                    numerator = carrying_capacity * base_population * exp_factor
                    denominator = carrying_capacity + base_population * (exp_factor - 1.0)
                    proj = numerator / denominator
                except OverflowError:
                    proj = carrying_capacity
            else:  # exponential (default)
                try:
                    proj = base_population * math.exp(growth_rate * dt)
                except OverflowError:
                    proj = float("inf")

            results.append({
                "year": yr,
                "projected_population": round(proj),
                "growth_increment": round(proj - base_population)
            })

        # 3. Create a Markdown report comparison table
        md = []
        md.append(f"# Population Projection Report")
        md.append(f"**Baseline Year:** {base_year}")
        md.append(f"**Baseline Population:** {base_population:,}")
        md.append(f"**Annual Growth Rate:** {growth_rate * 100:.2f}%")
        md.append(f"**Projection Model Type:** {model_type.upper()}")
        md.append(f"**Source Context:** {source_summary}")
        if model_type == "logistic":
            md.append(f"**Carrying Capacity Limit:** {carrying_capacity:,}")
        md.append("")
        md.append("| Target Year | Elapsed Years | Projected Population | Total Growth |")
        md.append("| :--- | :--- | :--- | :--- |")
        for r in results:
            dt = r["year"] - base_year
            md.append(f"| {r['year']} | +{dt} | {r['projected_population']:,} | +{r['growth_increment']:,} |")
        md.append("")

        # Calculate land density requirements (150 people per hectare)
        final_proj = results[-1]["projected_population"]
        total_increment = final_proj - base_population
        required_ha = round(total_increment / 150.0, 1)

        md.append("## Planning Implications & Space Demands")
        md.append(f"Based on a standard density benchmark of 150 persons/hectare, supporting the projected increase of **{total_increment:,}** additional residents by the year **{results[-1]['year']}** will require approximately:")
        md.append(f"* **{required_ha:,} hectares** of newly zoned residential land, OR")
        md.append(f"* A proportional increase in Floor Area Ratio (FAR) within existing built-up sectors to accommodate the influx without expanding the municipal boundary.")

        markdown_report = "\n".join(md)

        # Extract place name for the calling side-effect (chat.py artifact title)
        place_name_for_title = ""
        if source_summary:
            # Pattern: "Geolocated baseline near <CITY> ("
            import re
            m = re.search(r"near ([^(]+)\(", source_summary)
            if m:
                place_name_for_title = m.group(1).strip().rstrip(",")

        return {
            "status": "success",
            "baseline": {
                "year": base_year,
                "population": base_population,
                "source": source_summary
            },
            "growth_rate": growth_rate,
            "model_type": model_type,
            "projections": results,
            "land_demand_hectares": required_ha,
            "place_name": place_name_for_title,
            "report": markdown_report
        }

    async def _get_employment_density(self, args: dict) -> dict:
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        radius = min(int(args.get("radius_meters", 2000)), 10000)
        workspace = _resolve_workspace(args.get("workspace", ""))
        overrides = args.get("coefficient_overrides") or {}

        # 1. Check for Custom Dataset Override in Workspace
        custom_jobs = None
        custom_source = ""
        if workspace:
            ws_path = Path(workspace)
            custom_file = None
            for fname in ("employment_grid.geojson", "employment.geojson"):
                p = ws_path / fname
                if p.exists():
                    custom_file = p
                    break

            if custom_file:
                try:
                    with open(custom_file) as f:
                        grid_data = json.load(f)

                    if HAS_SHAPELY:
                        point_geom = {"type": "Point", "coordinates": [lng, lat]}
                        buffer_dict = geodesic_buffer(point_geom, radius)
                        buffer_shape = shape(buffer_dict)

                        features = grid_data.get("features", [])
                        total_jobs = 0.0
                        matched_count = 0

                        for feat in features:
                            f_geom_dict = feat.get("geometry")
                            if not f_geom_dict:
                                continue
                            f_shape = shape(f_geom_dict)
                            if buffer_shape.intersects(f_shape):
                                if f_shape.geom_type in ("Polygon", "MultiPolygon") and buffer_shape.geom_type in ("Polygon", "MultiPolygon"):
                                    try:
                                        inter = buffer_shape.intersection(f_shape)
                                        ratio = inter.area / f_shape.area if f_shape.area > 0 else 0.0
                                    except Exception:
                                        ratio = 1.0 if buffer_shape.contains(f_shape.centroid) else 0.0
                                else:
                                    ratio = 1.0 if buffer_shape.contains(f_shape.centroid or f_shape) else 0.0

                                # Extract job values
                                props = feat.get("properties") or {}
                                job_val = None
                                for col in ("jobs", "employment", "emp", "work_trips", "total_jobs", "job_count", "workers"):
                                    for k, v in props.items():
                                        if k.lower() == col:
                                            job_val = v
                                            break
                                    if job_val is not None:
                                        break
                                if job_val is not None:
                                    try:
                                        total_jobs += float(job_val) * ratio
                                        matched_count += 1
                                    except (ValueError, TypeError):
                                        pass

                        custom_jobs = round(total_jobs)
                        custom_source = f"Custom grid '{custom_file.name}' in workspace ({matched_count} cells matched)"
                except Exception:
                    pass

        if custom_jobs is not None:
            report_md = (
                f"# Employment Density Report\n\n"
                f"* **Location:** {lat:.5f}, {lng:.5f}\n"
                f"* **Search Buffer:** {radius:,} meters\n"
                f"* **Data Source:** {custom_source}\n\n"
                f"| Category | Estimated Jobs |\n"
                f"| :--- | :--- |\n"
                f"| **Total Jobs (User Grid)** | **{custom_jobs:,}** |\n\n"
                f"Methodology: Area-weighted spatial overlay intersection of custom TAZ grid and query buffer."
            )
            return {
                "status": "success",
                "lat": lat,
                "lng": lng,
                "radius_meters": radius,
                "total_jobs": custom_jobs,
                "source": "custom_dataset",
                "dataset_name": custom_source,
                "report": report_md
            }

        # 2. Heuristic: Reverse Geocoding for City Bylaws
        city_name = "generic"
        rev_info = await self._reverse_summary(lat, lng)
        place_label = "Study Area"
        if rev_info:
            addr = rev_info.get("address") or {}
            display = str(rev_info.get("display_name", "")).lower()
            place_label = addr.get("city") or addr.get("town") or addr.get("suburb") or place_label

            if "chandigarh" in display or any("chandigarh" in str(addr.get(k)).lower() for k in addr):
                city_name = "chandigarh"
            elif "mohali" in display or "sahibzada ajit singh nagar" in display or any("mohali" in str(addr.get(k)).lower() for k in addr):
                city_name = "mohali"
            elif "panchkula" in display or any("panchkula" in str(addr.get(k)).lower() for k in addr):
                city_name = "panchkula"
            elif "zirakpur" in display:
                city_name = "zirakpur"
            elif "kharar" in display:
                city_name = "kharar"

        CITY_DEFAULTS = {
            "chandigarh": {
                "office_sqm_per_job": 16.0,
                "retail_sqm_per_job": 30.0,
                "industrial_sqm_per_job": 60.0,
                "commercial_levels": 3.0,
                "industrial_levels": 1.0,
                "school_jobs": 60,
                "hospital_jobs": 200,
                "bank_jobs": 20,
            },
            "mohali": {
                "office_sqm_per_job": 14.0,
                "retail_sqm_per_job": 25.0,
                "industrial_sqm_per_job": 50.0,
                "commercial_levels": 5.0,
                "industrial_levels": 2.0,
                "school_jobs": 70,
                "hospital_jobs": 250,
                "bank_jobs": 25,
            },
            "panchkula": {
                "office_sqm_per_job": 15.0,
                "retail_sqm_per_job": 28.0,
                "industrial_sqm_per_job": 55.0,
                "commercial_levels": 4.0,
                "industrial_levels": 1.5,
                "school_jobs": 65,
                "hospital_jobs": 220,
                "bank_jobs": 22,
            },
            "zirakpur": {
                "office_sqm_per_job": 18.0,
                "retail_sqm_per_job": 35.0,
                "industrial_sqm_per_job": 70.0,
                "commercial_levels": 3.0,
                "industrial_levels": 1.0,
                "school_jobs": 40,
                "hospital_jobs": 150,
                "bank_jobs": 15,
            },
            "kharar": {
                "office_sqm_per_job": 18.0,
                "retail_sqm_per_job": 35.0,
                "industrial_sqm_per_job": 70.0,
                "commercial_levels": 3.0,
                "industrial_levels": 1.0,
                "school_jobs": 40,
                "hospital_jobs": 150,
                "bank_jobs": 15,
            },
            "generic": {
                "office_sqm_per_job": 18.0,
                "retail_sqm_per_job": 35.0,
                "industrial_sqm_per_job": 60.0,
                "commercial_levels": 3.0,
                "industrial_levels": 1.0,
                "school_jobs": 50,
                "hospital_jobs": 150,
                "bank_jobs": 15,
            }
        }

        # 3. Dynamic Scaling 1: Population Density Adjustments
        pop_density_ha = 0.0
        pop_count = 0
        try:
            density_radius = 1000
            demog_args = {"lat": lat, "lng": lng, "radius_meters": density_radius}
            demog_res = await self._get_demographics(demog_args)
            pop_count = demog_res.get("population") or 0
            buffer_ha = (math.pi * (density_radius ** 2)) / 10000.0
            pop_density_ha = pop_count / buffer_ha if buffer_ha > 0 else 0.0
        except Exception:
            pass

        density_category = "medium"
        if pop_density_ha > 150.0:
            density_category = "high"
        elif pop_density_ha < 50.0:
            density_category = "low"

        # 4. Dynamic Scaling 2: TOD Station Check
        is_tod = False
        transit_count = 0
        transit_query = (
            f"[out:json][timeout:15];"
            f"("
            f'  node["public_transport"~"stop_position|platform|station"](around:500,{lat},{lng});'
            f'  node["railway"~"station|halt|tram_stop"](around:500,{lat},{lng});'
            f");"
            f"out count;"
        )

        async def _fetch_transit() -> dict:
            return await http_client.fetch_json(
                _OVERPASS_URL,
                namespace="overpass",
                params={"data": transit_query},
            )

        try:
            transit_data = await cache.get_or_fetch(
                namespace="overpass",
                key={"q": transit_query},
                ttl_seconds=86_400,
                fetch_fn=_fetch_transit,
            )
            count_tags = (transit_data.get("elements") or [{}])[0].get("tags") or {}
            transit_count = int(count_tags.get("total", 0))
            if transit_count > 0:
                is_tod = True
        except Exception:
            pass

        # 5. Apply Multipliers
        base_coefs = CITY_DEFAULTS.get(city_name, CITY_DEFAULTS["generic"])
        density_mult = 1.0
        level_mult = 1.0
        poi_mult = 1.0

        if density_category == "high":
            density_mult = 0.8  # denser space utilization
            level_mult = 1.3
            poi_mult = 1.2
        elif density_category == "low":
            density_mult = 1.3  # sparser space utilization
            level_mult = 0.8
            poi_mult = 0.7

        if is_tod:
            density_mult *= 0.85
            level_mult *= 1.4
            poi_mult *= 1.15

        office_sqm_per_job = overrides.get("office_sqm_per_job", base_coefs["office_sqm_per_job"] * density_mult)
        retail_sqm_per_job = overrides.get("retail_sqm_per_job", base_coefs["retail_sqm_per_job"] * density_mult)
        industrial_sqm_per_job = overrides.get("industrial_sqm_per_job", base_coefs["industrial_sqm_per_job"] * density_mult)
        commercial_levels = max(1.0, overrides.get("commercial_levels", base_coefs["commercial_levels"] * level_mult))
        industrial_levels = max(1.0, overrides.get("industrial_levels", base_coefs["industrial_levels"] * level_mult))

        school_jobs = overrides.get("school_jobs", base_coefs["school_jobs"] * poi_mult)
        hospital_jobs = overrides.get("hospital_jobs", base_coefs["hospital_jobs"] * poi_mult)
        bank_jobs = overrides.get("bank_jobs", base_coefs["bank_jobs"] * poi_mult)

        # 6. Fetch OSM elements
        osm_query = (
            f"[out:json][timeout:30];"
            f"("
            f'  node["building"](around:{radius},{lat},{lng});'
            f'  way["building"](around:{radius},{lat},{lng});'
            f'  relation["building"](around:{radius},{lat},{lng});'
            f'  node["amenity"](around:{radius},{lat},{lng});'
            f'  node["shop"](around:{radius},{lat},{lng});'
            f'  node["office"](around:{radius},{lat},{lng});'
            f'  node["craft"](around:{radius},{lat},{lng});'
            f'  node["industrial"](around:{radius},{lat},{lng});'
            f'  way["amenity"](around:{radius},{lat},{lng});'
            f'  way["shop"](around:{radius},{lat},{lng});'
            f'  way["office"](around:{radius},{lat},{lng});'
            f");"
            f"out geom;"
        )

        async def _fetch_osm() -> dict:
            return await http_client.fetch_json(
                _OVERPASS_URL,
                namespace="overpass",
                params={"data": osm_query},
            )

        try:
            osm_data = await cache.get_or_fetch(
                namespace="overpass",
                key={"q": osm_query},
                ttl_seconds=86_400,
                fetch_fn=_fetch_osm,
            )
        except Exception as e:
            return {"error": f"Failed to fetch OSM features: {str(e)}"}

        elements = (osm_data or {}).get("elements", [])

        # Process Buildings & POIs
        buildings = []
        pois = []
        for el in elements:
            tags = el.get("tags") or {}
            is_building = "building" in tags and tags["building"] != "no"
            if is_building and el.get("type") in ("way", "relation"):
                buildings.append(el)
            else:
                pois.append(el)

        parsed_buildings = []
        building_jobs_total = 0.0
        building_gfa_total = 0.0
        jobs_by_cat = {"office": 0.0, "retail": 0.0, "industrial": 0.0, "education": 0.0, "healthcare": 0.0, "other": 0.0}

        for b in buildings:
            tags = b.get("tags") or {}
            geom_pts = b.get("geometry") or []
            if len(geom_pts) < 3:
                continue

            try:
                coords = [(pt["lon"], pt["lat"]) for pt in geom_pts]
                poly = sg.Polygon(coords) if HAS_SHAPELY else None
                if poly and not poly.is_valid:
                    poly = poly.buffer(0)
                if poly and poly.is_empty:
                    continue

                area_m2 = geodesic_area_m2({"type": "Polygon", "coordinates": [[c[0], c[1]] for c in coords]})
                levels = None
                if "building:levels" in tags:
                    try:
                        levels = float(tags["building:levels"])
                    except (ValueError, TypeError):
                        pass
                if levels is None and "height" in tags:
                    try:
                        levels = max(1.0, float(str(tags["height"]).replace("m", "").strip()) / 3.5)
                    except (ValueError, TypeError):
                        pass

                b_type = str(tags.get("building", "")).lower()
                if levels is None:
                    if any(x in b_type for x in ("office", "commercial", "retail", "supermarket", "school", "university", "hospital", "hotel", "public")):
                        levels = commercial_levels
                    elif any(x in b_type for x in ("industrial", "warehouse", "manufacture", "factory")):
                        levels = industrial_levels
                    elif b_type in ("apartments", "terrace", "residential"):
                        levels = 2.0
                    else:
                        levels = 1.0

                gfa = area_m2 * levels
                sqm_per_job = None
                cat = "other"

                if any(x in b_type for x in ("office", "commercial", "hotel", "public")):
                    sqm_per_job = office_sqm_per_job
                    cat = "office"
                elif any(x in b_type for x in ("retail", "supermarket", "shop")):
                    sqm_per_job = retail_sqm_per_job
                    cat = "retail"
                elif any(x in b_type for x in ("industrial", "warehouse", "manufacture", "factory")):
                    sqm_per_job = industrial_sqm_per_job
                    cat = "industrial"
                elif any(x in b_type for x in ("school", "university", "college", "kindergarten")):
                    sqm_per_job = office_sqm_per_job * 1.5
                    cat = "education"
                elif any(x in b_type for x in ("hospital", "clinic", "doctors")):
                    sqm_per_job = office_sqm_per_job * 2.0
                    cat = "healthcare"
                elif b_type in ("apartments", "terrace", "residential", "house", "detached"):
                    sqm_per_job = 0.0

                jobs = (gfa / sqm_per_job) if sqm_per_job and sqm_per_job > 0 else 0.0
                building_jobs_total += jobs
                building_gfa_total += gfa
                if cat in jobs_by_cat:
                    jobs_by_cat[cat] += jobs

                parsed_buildings.append({
                    "shape": poly,
                    "jobs": jobs,
                    "gfa": gfa
                })
            except Exception:
                continue

        # Process POIs with deduplication
        poi_jobs_total = 0.0
        building_union = None
        if HAS_SHAPELY and parsed_buildings:
            try:
                building_union = unary_union([pb["shape"] for pb in parsed_buildings if pb["shape"]])
            except Exception:
                pass

        for p in pois:
            tags = p.get("tags") or {}
            plat = p.get("lat")
            plon = p.get("lon")
            if plat is None or plon is None:
                geom_pts = p.get("geometry") or []
                if geom_pts:
                    plat = geom_pts[0]["lat"]
                    plon = geom_pts[0]["lon"]

            if plat is None or plon is None:
                continue

            # Deduplication
            if HAS_SHAPELY and building_union is not None:
                try:
                    if building_union.contains(Point(plon, plat)):
                        continue
                except Exception:
                    pass

            jobs = 0.0
            cat = "other"
            amenity = str(tags.get("amenity", "")).lower()
            shop = str(tags.get("shop", "")).lower()
            office = str(tags.get("office", "")).lower()

            if any(x in amenity for x in ("school", "university", "college", "kindergarten")):
                jobs = school_jobs
                cat = "education"
            elif any(x in amenity for x in ("hospital", "clinic", "doctors")):
                jobs = hospital_jobs
                cat = "healthcare"
            elif amenity in ("bank", "post_office"):
                jobs = bank_jobs
                cat = "office"
            elif any(x in amenity for x in ("restaurant", "cafe", "fast_food", "bar", "pub")):
                jobs = 8.0
                cat = "retail"
            elif shop and shop != "no":
                jobs = 4.0
                cat = "retail"
            elif office and office != "no":
                jobs = 8.0
                cat = "office"
            elif amenity and amenity != "no":
                jobs = 12.0
                cat = "other"
            else:
                jobs = 3.0
                cat = "other"

            poi_jobs_total += jobs
            if cat in jobs_by_cat:
                jobs_by_cat[cat] += jobs

        # 7. Fallback to Zoning polygons from map context
        zoning_jobs_total = 0.0
        zoning_source = ""
        total_heuristic = building_jobs_total + poi_jobs_total
        map_context = args.get("_map_context") or {}
        layers = map_context.get("layers") or []

        if total_heuristic < 10.0 and layers and HAS_SHAPELY:
            zoning_layer = None
            for layer in layers:
                name = str(layer.get("name", "")).lower()
                if "zone" in name or "landuse" in name or "land_use" in name:
                    zoning_layer = layer
                    break

            if zoning_layer:
                point_geom = {"type": "Point", "coordinates": [lng, lat]}
                buffer_dict = geodesic_buffer(point_geom, radius)
                buffer_shape = shape(buffer_dict)
                features = zoning_layer.get("features_data", []) or zoning_layer.get("features", [])

                for f in features:
                    f_geom = f.get("geometry")
                    if not f_geom:
                        continue
                    try:
                        f_shape = shape(f_geom)
                        if buffer_shape.intersects(f_shape):
                            inter = buffer_shape.intersection(f_shape)
                            inter_area_ha = geodesic_area_m2(sg.mapping(inter)) / 10000.0
                            props = f.get("properties") or {}
                            z_code = str(props.get("zone_code") or props.get("land_use") or "").lower()

                            jobs_per_ha = 0.0
                            cat = "other"
                            if "c" in z_code or "commercial" in z_code or "office" in z_code:
                                jobs_per_ha = 120.0
                                cat = "office"
                            elif "i" in z_code or "industrial" in z_code or "manufact" in z_code:
                                jobs_per_ha = 80.0
                                cat = "industrial"
                            elif "mx" in z_code or "mixed" in z_code:
                                jobs_per_ha = 60.0
                                cat = "retail"
                            elif "inst" in z_code or "public" in z_code:
                                jobs_per_ha = 40.0
                                cat = "office"

                            if jobs_per_ha > 0:
                                jobs = inter_area_ha * jobs_per_ha
                                zoning_jobs_total += jobs
                                if cat in jobs_by_cat:
                                    jobs_by_cat[cat] += jobs
                    except Exception:
                        continue
                if zoning_jobs_total > 0:
                    zoning_source = f"Zoning layer '{zoning_layer.get('name')}'"

        final_jobs = round(building_jobs_total + poi_jobs_total + zoning_jobs_total)
        source_str = "OSM Heuristic Proxy Model"
        if zoning_jobs_total > 0:
            source_str = f"Hybrid OSM + {zoning_source} Fallback"

        # Construct markdown report
        md = []
        md.append(f"# Employment Density Report — {place_label}")
        md.append(f"* **Municipality Matched:** {city_name.upper()}")
        md.append(f"* **Population Density:** {pop_density_ha:.1f} persons/ha (Density Class: {density_category.upper()})")
        md.append(f"* **Transit Access:** {'Yes (TOD Zone scaling active)' if is_tod else 'No (Standard scaling)'}")
        md.append(f"* **Search Radius:** {radius:,} meters")
        md.append(f"* **Total Estimated Jobs:** **{final_jobs:,}**")
        md.append("")
        md.append("## Heuristic Estimation Parameters")
        md.append("| Bylaw Parameter | Value / Multiplier |")
        md.append("| :--- | :--- |")
        md.append(f"| Office Floor Area per Job | {office_sqm_per_job:.1f} sqm |")
        md.append(f"| Retail Floor Area per Job | {retail_sqm_per_job:.1f} sqm |")
        md.append(f"| Industrial Floor Area per Job | {industrial_sqm_per_job:.1f} sqm |")
        md.append(f"| Default Commercial Levels | {commercial_levels:.1f} |")
        md.append(f"| Default Industrial Levels | {industrial_levels:.1f} |")
        md.append(f"| Flat School/Univ Jobs | {school_jobs:.1f} |")
        md.append(f"| Flat Hospital/Clinic Jobs | {hospital_jobs:.1f} |")
        md.append("")
        md.append("## Employment Breakdown by Planning Category")
        md.append("| Category | Estimated Jobs | Percentage |")
        md.append("| :--- | :--- | :--- |")
        for k, v in jobs_by_cat.items():
            pct = (v / final_jobs * 100.0) if final_jobs > 0 else 0.0
            md.append(f"| {k.title()} | {round(v):,} | {pct:.1f}% |")
        md.append("")
        md.append("## Methodology Note")
        md.append("Estimated by filtering building polygons and POIs within the search radius from OpenStreetMap. Building heights/levels are translated into Gross Floor Area (GFA) and divided by workspace-adjusted sqm-per-job ratios. POIs outside buildings are added as flat job markers. Double-counting is prevented by polygon containment checks.")
        markdown_report = "\n".join(md)

        return {
            "status": "success",
            "lat": lat,
            "lng": lng,
            "radius_meters": radius,
            "municipality": city_name,
            "population_density_ha": pop_density_ha,
            "is_tod": is_tod,
            "total_jobs": final_jobs,
            "breakdown": {k: round(v) for k, v in jobs_by_cat.items()},
            "source": source_str,
            "report": markdown_report
        }

    async def _project_employment(self, args: dict) -> dict:
        base_jobs_arg = args.get("base_jobs")
        growth_rate = float(args.get("growth_rate", 0.025))
        target_years = args.get("target_years") or [2030, 2035, 2040, 2045, 2050]
        model_type = args.get("model_type", "exponential").strip().lower()
        carrying_capacity = args.get("carrying_capacity")
        lat_arg = args.get("lat")
        lng_arg = args.get("lng")
        radius = int(args.get("radius_meters", 2000))
        workspace = args.get("workspace")
        space_standard = float(args.get("space_standard_sqm", 20.0))
        average_far = float(args.get("average_far", 2.0))

        base_jobs = None
        source_summary = ""

        if base_jobs_arg is not None:
            try:
                base_jobs = int(base_jobs_arg)
                source_summary = "User-supplied explicit baseline value"
            except (ValueError, TypeError):
                return {"error": "Invalid base_jobs value. Must be an integer."}
        elif lat_arg is not None and lng_arg is not None and workspace is not None:
            demog_args = {
                "lat": float(lat_arg),
                "lng": float(lng_arg),
                "radius_meters": radius,
                "workspace": workspace
            }
            res = await self._get_employment_density(demog_args)
            if res.get("total_jobs") is not None:
                base_jobs = res["total_jobs"]
                source_summary = f"Geolocated baseline around coordinates ({lat_arg}, {lng_arg}) using {res['source']} source."
            else:
                return {"error": "Could not determine baseline jobs at coordinates. Please specify base_jobs explicitly."}
        else:
            return {"error": "Either base_jobs or geocoding coordinates (lat, lng, radius_meters, workspace) must be provided."}

        if base_jobs <= 0:
            return {"error": f"Base jobs must be greater than zero. Received: {base_jobs}"}

        if model_type == "logistic":
            if carrying_capacity is None:
                return {"error": "carrying_capacity limit is required when model_type is set to 'logistic'."}
            try:
                carrying_capacity = int(carrying_capacity)
            except (ValueError, TypeError):
                return {"error": "Invalid carrying_capacity value. Must be an integer."}
            if carrying_capacity <= base_jobs:
                return {"error": f"Carrying capacity ceiling ({carrying_capacity}) must be greater than baseline jobs ({base_jobs})."}

        user_base_year = args.get("base_year")
        base_year = int(user_base_year) if user_base_year is not None else 2026
        results = []

        sorted_years = sorted(list(set([int(y) for y in target_years if int(y) > base_year])))
        if not sorted_years:
            return {"error": f"All target years must be greater than baseline year {base_year}."}

        for yr in sorted_years:
            dt = yr - base_year
            if model_type == "linear":
                proj = base_jobs * (1.0 + growth_rate * dt)
            elif model_type == "logistic":
                try:
                    exp_factor = math.exp(growth_rate * dt)
                    numerator = carrying_capacity * base_jobs * exp_factor
                    denominator = carrying_capacity + base_jobs * (exp_factor - 1.0)
                    proj = numerator / denominator
                except OverflowError:
                    proj = carrying_capacity
            else:
                try:
                    proj = base_jobs * math.exp(growth_rate * dt)
                except OverflowError:
                    proj = float("inf")

            projected_val = round(proj)
            increment = projected_val - base_jobs
            # Land requirement calculation
            required_gfa = increment * space_standard
            required_land_sqm = required_gfa / average_far
            required_land_ha = round(required_land_sqm / 10000.0, 2)

            results.append({
                "year": yr,
                "projected_jobs": projected_val,
                "growth_increment": increment,
                "gfa_required_sqm": round(required_gfa),
                "land_required_hectares": required_land_ha
            })

        # Generate report
        md = []
        md.append(f"# Employment & Land Demand Projection")
        md.append(f"**Baseline Year:** {base_year}")
        md.append(f"**Baseline Jobs:** {base_jobs:,}")
        md.append(f"**Annual Growth Rate:** {growth_rate * 100:.2f}%")
        md.append(f"**Projection Model Type:** {model_type.upper()}")
        md.append(f"**Average FAR/FSI Target:** {average_far:.2f}")
        md.append(f"**Space Standard per Worker:** {space_standard:.1f} sqm")
        md.append(f"**Baseline Source:** {source_summary}")
        if model_type == "logistic":
            md.append(f"**Carrying Capacity Limit:** {carrying_capacity:,} jobs")
        md.append("")
        md.append("| Target Year | Projected Jobs | Job Increase | Floor Area Required (sqm) | Raw Land Required (Hectares) |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")
        for r in results:
            md.append(f"| {r['year']} | {r['projected_jobs']:,} | +{r['growth_increment']:,} | {r['gfa_required_sqm']:,} sqm | {r['land_required_hectares']:,} ha |")
        md.append("")
        md.append("## Planning Implications")
        final_ha = results[-1]["land_required_hectares"]
        final_inc = results[-1]["growth_increment"]
        md.append(f"To support the projected increase of **{final_inc:,}** jobs by the year **{results[-1]['year']}**, the municipality must zone and provide infrastructure for approximately **{final_ha:,} hectares** of commercial and industrial land.")
        md.append("Increasing the average FAR/FSI target above the specified baseline can reduce the total raw land footprint required by allowing taller development envelopes inside existing urban cores.")
        markdown_report = "\n".join(md)

        return {
            "status": "success",
            "baseline": {
                "year": base_year,
                "jobs": base_jobs,
                "source": source_summary
            },
            "growth_rate": growth_rate,
            "model_type": model_type,
            "projections": results,
            "report": markdown_report
        }


def _to_int(value) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        return None

