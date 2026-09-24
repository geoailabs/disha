"""
Centralized Provenance Engine — Tracks data sources, analytical basis,
calculation formulas, and regulatory norms across Disha artifacts.

Supports:
1. Tool-to-source telemetry mapping (capturing provider, query scope, timestamp, basis).
2. Markdown parsing of '## Data Sources & Methodology' sections into structured metadata.
3. Automatic synthesis & auto-enrichment of the sources section if omitted or incomplete.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict


class SourceEntry(TypedDict, total=False):
    name: str
    category: str
    provider: str
    query_scope: str
    timestamp: str
    basis_or_assumptions: str
    url: str


DEFAULT_SOURCE_URLS: dict[str, str] = {
    "air quality": "https://open-meteo.com/en/docs/air-quality-api",
    "cams": "https://open-meteo.com/en/docs/air-quality-api",
    "pm2.5": "https://open-meteo.com/en/docs/air-quality-api",
    "pm10": "https://open-meteo.com/en/docs/air-quality-api",
    "aqi": "https://open-meteo.com/en/docs/air-quality-api",
    "weather": "https://open-meteo.com/en/docs",
    "climate": "https://open-meteo.com/en/docs",
    "forecast": "https://open-meteo.com/en/docs",
    "worldpop": "https://hub.worldpop.org",
    "population": "https://hub.worldpop.org",
    "demographic": "https://hub.worldpop.org",
    "openstreetmap": "https://www.openstreetmap.org",
    "osm": "https://www.openstreetmap.org",
    "overpass": "https://wiki.openstreetmap.org/wiki/Overpass_API",
    "photon": "https://photon.komoot.io",
    "dynamic world": "https://dynamicworld.app",
    "sentinel": "https://earthengine.google.com",
    "earth engine": "https://earthengine.google.com",
    "gee": "https://earthengine.google.com",
    "places": "https://developers.google.com/maps/documentation/places/web-service",
    "google maps": "https://developers.google.com/maps",
    "overture": "https://overturemaps.org",
    "osrm": "https://project-osrm.org",
    "route": "https://project-osrm.org",
    "routing": "https://project-osrm.org",
    "isochrone": "https://project-osrm.org",
    "datameet": "http://projects.datameet.org/maps",
    "solar": "https://developers.google.com/maps/documentation/solar",
    "geodesic": "https://proj.org/operations/geodesic.html",
    "wgs84": "https://proj.org/operations/geodesic.html",
    "pyproj": "https://proj.org/operations/geodesic.html",
    "shapely": "https://shapely.readthedocs.io",
    "zoning": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
    "master plan": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
    "urdpfi": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
    "land budget": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
    "emissions": "https://www.eea.europa.eu/publications/emep-eea-guidebook-2019",
    "gtfs": "https://gtfs.org",
    "mcda": "https://en.wikipedia.org/wiki/Analytic_hierarchy_process",
    "ahp": "https://en.wikipedia.org/wiki/Analytic_hierarchy_process",
}


def resolve_source_url(name: str = "", provider: str = "", category: str = "", current_url: str = "") -> str:
    """Resolve an authoritative documentation or portal URL for a data source."""
    if current_url and current_url.startswith("http"):
        return current_url
    search_target = f"{name} {provider} {category}".lower()
    for kw, target_url in DEFAULT_SOURCE_URLS.items():
        if kw in search_target:
            return target_url
    return ""


# Mapping of analytical / spatial tools to canonical provenance definitions
TOOL_SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "osm_boundary": {
        "name": "OpenStreetMap Administrative Boundary",
        "category": "Geospatial Vector",
        "provider": "OpenStreetMap (Nominatim / Overpass)",
        "url": "https://www.openstreetmap.org",
        "default_basis": "Administrative polygon boundaries fetched from OpenStreetMap with boundary hierarchy resolution.",
    },
    "osm_boundary_union": {
        "name": "OpenStreetMap Boundary Union",
        "category": "Geospatial Vector",
        "provider": "OpenStreetMap (Overpass API)",
        "url": "https://www.openstreetmap.org",
        "default_basis": "Spatial union of multiple administrative boundaries into a consolidated study area polygon.",
    },
    "osm_query": {
        "name": "OpenStreetMap Vector Features",
        "category": "Geospatial Vector",
        "provider": "OpenStreetMap (Overpass API)",
        "url": "https://wiki.openstreetmap.org/wiki/Overpass_API",
        "default_basis": "Vector features retrieved via Overpass QL tag filtering and constrained to study area boundary.",
    },
    "osm_search": {
        "name": "OpenStreetMap Amenities & Points of Interest",
        "category": "Places & Amenities",
        "provider": "OpenStreetMap / Photon Geocoder",
        "url": "https://www.openstreetmap.org",
        "default_basis": "Point of interest inventory filtered spatially within study boundary.",
    },
    "nearby_places": {
        "name": "Local Amenities & Points of Interest",
        "category": "Places & Amenities",
        "provider": "OpenStreetMap / Photon Geocoder",
        "url": "https://www.openstreetmap.org",
        "default_basis": "Radial proximity search for urban amenities around target coordinates.",
    },
    "datameet_boundary": {
        "name": "DataMeet India Administrative Boundaries",
        "category": "Geospatial Vector",
        "provider": "DataMeet India Open Data Community",
        "url": "http://projects.datameet.org/maps",
        "default_basis": "Official Census/Survey of India boundary shapefiles sourced from DataMeet.",
    },
    "worldpop_population": {
        "name": "WorldPop 100m Population Count",
        "category": "Raster Demographics",
        "provider": "WorldPop (hub.worldpop.org)",
        "url": "https://hub.worldpop.org",
        "default_basis": "100m resolution building-constrained raster population grid (UN-adjusted) aggregated within study boundary.",
    },
    "worldpop_density": {
        "name": "WorldPop Population Density",
        "category": "Raster Demographics",
        "provider": "WorldPop (hub.worldpop.org)",
        "url": "https://hub.worldpop.org",
        "default_basis": "Population density per square kilometer derived from 100m constrained raster grid.",
    },
    "cohort_projection": {
        "name": "Demographic Cohort Projection",
        "category": "Demographic Modeling",
        "provider": "Cohort-Component Demographic Engine",
        "url": "https://www.un.org/development/desa/pd",
        "default_basis": "Age-sex cohort-component model applying baseline fertility, mortality rates, and net migration projections.",
    },
    "employment_density": {
        "name": "Employment & Job Density Projections",
        "category": "Economic Planning",
        "provider": "Urban Employment Density Model",
        "url": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
        "default_basis": "Land use-based employment density factors and commercial Floor Area Ratio (FAR) norms.",
    },
    "open_meteo_weather": {
        "name": "Open-Meteo Weather Forecast & Historical Climate",
        "category": "Meteorological & Climate",
        "provider": "Open-Meteo Weather API",
        "url": "https://open-meteo.com/en/docs",
        "default_basis": "High-resolution numerical weather prediction models (ECMWF, GFS, ICON).",
    },
    "open_meteo_air_quality": {
        "name": "Open-Meteo Air Quality Index",
        "category": "Environmental & Air Quality",
        "provider": "Copernicus CAMS / Open-Meteo API",
        "url": "https://open-meteo.com/en/docs/air-quality-api",
        "default_basis": "Atmospheric dispersion reanalysis providing PM2.5, PM10, NO2, and composite AQI values.",
    },
    "gee_analysis": {
        "name": "Google Earth Engine Multi-Spectral Analysis",
        "category": "Earth Observation & Remote Sensing",
        "provider": "Google Earth Engine (Sentinel-2 / Landsat)",
        "url": "https://earthengine.google.com",
        "default_basis": "Satellite spectral indices (e.g. NDVI, NDWI, NDBI) computed over selected timeframes.",
    },
    "gee_stats": {
        "name": "Google Earth Engine Regional Statistics",
        "category": "Earth Observation & Remote Sensing",
        "provider": "Google Earth Engine",
        "url": "https://earthengine.google.com",
        "default_basis": "Zonal raster reduction (mean, median, min, max) within study boundary.",
    },
    "gee_timeseries": {
        "name": "Google Earth Engine Temporal Series",
        "category": "Earth Observation & Remote Sensing",
        "provider": "Google Earth Engine",
        "url": "https://earthengine.google.com",
        "default_basis": "Multi-year temporal change analysis from cloud-masked satellite composites.",
    },
    "extract_land_use_polygons": {
        "name": "Satellite Land Use & Land Cover (LULC)",
        "category": "Earth Observation & Remote Sensing",
        "provider": "Dynamic World / Sentinel-2 LULC (10m)",
        "url": "https://dynamicworld.app",
        "default_basis": "10-meter deep learning near-real-time land cover classification vectorized into analytical polygons.",
    },
    "get_land_cover": {
        "name": "Multi-Class Land Cover Classification",
        "category": "Earth Observation & Remote Sensing",
        "provider": "Dynamic World / Sentinel-2 LULC (10m)",
        "url": "https://dynamicworld.app",
        "default_basis": "Categorical breakdown of built-up, tree canopy, water, crop, and bare ground cover.",
    },
    "google_solar": {
        "name": "Google Solar Building Irradiance",
        "category": "Renewable Energy",
        "provider": "Google Maps Platform Solar API",
        "url": "https://developers.google.com/maps/documentation/solar",
        "default_basis": "High-resolution 3D rooftop geometry and annual solar flux modeling.",
    },
    "fleet_emissions": {
        "name": "Vehicle Fleet Emissions Model",
        "category": "Environmental & Mobility",
        "provider": "Fleet Emissions Modeling Engine",
        "url": "https://www.eea.europa.eu/publications/emep-eea-guidebook-2019",
        "default_basis": "Tier-2 emissions methodology calculating CO2, NOx, and PM factors per vehicle-kilometer traveled.",
    },
    "route": {
        "name": "OSRM Multimodal Network Routing",
        "category": "Mobility & Transportation",
        "provider": "OSRM (Open Source Routing Machine)",
        "url": "https://project-osrm.org",
        "default_basis": "Dijkstra shortest/fastest path algorithm calculated on OpenStreetMap topological road network.",
    },
    "osm_route_overview": {
        "name": "OSRM Road Corridor Overview",
        "category": "Mobility & Transportation",
        "provider": "OSRM / OpenStreetMap",
        "url": "https://project-osrm.org",
        "default_basis": "Corridor path geometry, turn guidance, and driving distance computation.",
    },
    "freight_route": {
        "name": "Freight Logistics & Heavy Vehicle Routing",
        "category": "Freight & Logistics",
        "provider": "Freight Corridor Engine",
        "url": "https://project-osrm.org",
        "default_basis": "Road classification filtering, axle-weight constraints, and arterial corridor prioritization.",
    },
    "catchment_isochrone": {
        "name": "Walkshed & Travel-Time Isochrone Shed",
        "category": "Public Transit & Accessibility",
        "provider": "Isochrone Routing Service",
        "url": "https://project-osrm.org",
        "default_basis": "Pedestrian walkshed modeled at 400m (5-min) and 800m (10-min) walking thresholds at 4.5 km/h.",
    },
    "gtfs_isochrone": {
        "name": "GTFS Transit Travel-Time Catchment",
        "category": "Public Transit & Accessibility",
        "provider": "GTFS Transit Schedule & Isochrone Engine",
        "url": "https://gtfs.org",
        "default_basis": "Scheduled transit timetable arrival times combined with walking access buffers.",
    },
    "optimize_signals": {
        "name": "Traffic Signal Timing Optimization",
        "category": "Traffic Engineering",
        "provider": "Webster's ITS Signal Engine",
        "url": "https://ops.fhwa.dot.gov",
        "default_basis": "Webster's minimum delay cycle length formula and volume-to-capacity split optimization.",
    },
    "parking_demand": {
        "name": "Urban Parking Demand Estimation",
        "category": "Mobility & Parking",
        "provider": "Urban Parking Demand Calculator",
        "url": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
        "default_basis": "Equivalent Car Space (ECS) standards per 100 sqm Gross Floor Area by land use category.",
    },
    "gravity_model": {
        "name": "Spatial Interaction Gravity Model",
        "category": "Mobility & Transportation",
        "provider": "Gravity Mobility Engine",
        "url": "https://en.wikipedia.org/wiki/Gravity_model_of_migration",
        "default_basis": "Doubly-constrained spatial interaction model scaled by power-law distance decay.",
    },
    "places_search": {
        "name": "Google Places Commercial Directory",
        "category": "Places & Commerce",
        "provider": "Google Maps Platform Places API",
        "url": "https://developers.google.com/maps/documentation/places/web-service",
        "default_basis": "Commercial establishment inventory and category search from Google Places Platform.",
    },
    "places_details": {
        "name": "Google Places Entity Verification",
        "category": "Places & Commerce",
        "provider": "Google Maps Platform Places API",
        "url": "https://developers.google.com/maps/documentation/places/web-service",
        "default_basis": "Verified business operational status, ratings, and operating hours.",
    },
    "places_nearby": {
        "name": "Google Places Proximity Density",
        "category": "Places & Commerce",
        "provider": "Google Maps Platform Places API",
        "url": "https://developers.google.com/maps/documentation/places/web-service",
        "default_basis": "Radial amenity distribution and competitive density within study buffer.",
    },
    "overture_buildings": {
        "name": "Overture Maps 3D Building Footprints",
        "category": "Built Environment",
        "provider": "Overture Maps Foundation",
        "url": "https://overturemaps.org",
        "default_basis": "Open vector building footprint geometry and roof height / floor estimates.",
    },
    "overture_pois": {
        "name": "Overture Places of Interest",
        "category": "Places & Commerce",
        "provider": "Overture Maps Foundation",
        "url": "https://overturemaps.org",
        "default_basis": "Open points-of-interest database with standardized taxonomies.",
    },
    "zoning_lookup": {
        "name": "Master Plan Zoning & Land Use Codes",
        "category": "Urban Planning & Regulations",
        "provider": "Municipal Master Plan / Zoning Regulations",
        "url": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
        "default_basis": "Statutory Floor Area Ratio (FAR), maximum ground coverage, and permitted use matrices.",
    },
    "zoning_compliance": {
        "name": "Zoning Regulatory Compliance Audit",
        "category": "Urban Planning & Regulations",
        "provider": "Municipal Development Code Checker",
        "url": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
        "default_basis": "Evaluation of proposed density and FAR against permissible development controls.",
    },
    "calculate_land_budget": {
        "name": "Urban Land Budget & Allocation Norms",
        "category": "Urban Planning & Regulations",
        "provider": "Planning Norms & Land Budget Engine",
        "url": "https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
        "default_basis": "URDPFI / Planning Authority percentage allocations for residential, commercial, and open space.",
    },
    "mcda_evaluate": {
        "name": "Multi-Criteria Decision Analysis (MCDA)",
        "category": "Decision Support & Scenarios",
        "provider": "Analytical Hierarchy Process (AHP) / MCDA",
        "url": "https://en.wikipedia.org/wiki/Analytic_hierarchy_process",
        "default_basis": "Normalized pairwise comparison matrix evaluating spatial suitability scores across weighted criteria.",
    },
    "compare_scenarios": {
        "name": "Planning Scenario Comparative Evaluation",
        "category": "Decision Support & Scenarios",
        "provider": "Scenario Comparison Engine",
        "url": "https://en.wikipedia.org/wiki/Scenario_planning",
        "default_basis": "Cross-scenario delta computation evaluating land budget, traffic impact, and environmental metrics.",
    },
    "gis_buffer": {
        "name": "Geodesic GIS Buffer",
        "category": "Geodesic GIS",
        "provider": "Central Spatial Registry / Shapely",
        "url": "https://proj.org/operations/geodesic.html",
        "default_basis": "Geodesic distance buffer computed in metric projection to prevent high-latitude planar distortion.",
    },
    "gis_area": {
        "name": "Geodesic Land Area Measurement",
        "category": "Geodesic GIS",
        "provider": "pyproj.Geod (WGS84 Ellipsoid)",
        "url": "https://proj.org/operations/geodesic.html",
        "default_basis": "True geodesic surface area calculated on the WGS84 ellipsoid; planar distortion avoided.",
    },
    "gis_centroid": {
        "name": "Geometric Centroid Resolution",
        "category": "Geodesic GIS",
        "provider": "Central Spatial Registry / Shapely",
        "url": "https://shapely.readthedocs.io",
        "default_basis": "Spatial centroid of polygon geometry computed in EPSG:4326.",
    },
    "gis_intersection": {
        "name": "Spatial Feature Intersection",
        "category": "Geodesic GIS",
        "provider": "Central Spatial Registry / Shapely",
        "url": "https://shapely.readthedocs.io",
        "default_basis": "Exact geometric intersection between study area boundary and thematic vector layer.",
    },
    "gis_clip": {
        "name": "Spatial Layer Clipping",
        "category": "Geodesic GIS",
        "provider": "Central Spatial Registry / Shapely",
        "url": "https://shapely.readthedocs.io",
        "default_basis": "Vector clipping constraining thematic geometries strictly to study area perimeter.",
    },
    "web_search": {
        "name": "Live Web Research & External Reports",
        "category": "Web Research",
        "provider": "Web Search / Authoritative Portals",
        "url": "https://duckduckgo.com",
        "default_basis": "External facts, statutory guidelines, or governmental benchmark reports retrieved via live search.",
    },
    "document_rag_search": {
        "name": "Indexed Project Documentation (RAG)",
        "category": "Uploaded Documents",
        "provider": "Local Document Vector RAG Store",
        "url": "https://github.com/geoailabs/disha",
        "default_basis": "Semantic vector similarity matching against user-uploaded project documents and master plans.",
    },
    "measure_distance": {
        "name": "Geodesic Distance Measurement",
        "category": "Geodesic GIS",
        "provider": "pyproj.Geod (WGS84 Ellipsoid)",
        "url": "https://proj.org/operations/geodesic.html",
        "default_basis": "Great-circle ellipsoidal path distance computed via pyproj.",
    },
    "measure_area": {
        "name": "Geodesic Area Measurement",
        "category": "Geodesic GIS",
        "provider": "pyproj.Geod (WGS84 Ellipsoid)",
        "url": "https://proj.org/operations/geodesic.html",
        "default_basis": "Ellipsoidal surface area computed on WGS84 reference ellipsoid.",
    },
}


def create_source_entry_from_tool(tool_name: str, args: dict, result_summary: Optional[str] = None) -> Optional[SourceEntry]:
    """Create a structured SourceEntry from a tool execution call."""
    reg = TOOL_SOURCE_REGISTRY.get(tool_name)
    if not reg:
        return None

    # Derive query scope description from tool arguments
    query_parts = []
    for k in ("name", "place_name", "query", "origin", "destination", "target_class", "amenity", "tags", "radius_m", "distance_m"):
        v = args.get(k)
        if v:
            query_parts.append(f"{k}: {v}")
    
    if args.get("names"):
        query_parts.append(f"names: {', '.join(args['names'])}")

    query_scope = "; ".join(query_parts) if query_parts else "Active study area / canvas extent"

    # Derive basis or assumptions
    basis = reg.get("default_basis", "")
    if result_summary:
        # If result mentions area or count, enrich basis note
        if "area_km2" in result_summary:
            try:
                data = json.loads(result_summary) if isinstance(result_summary, str) else result_summary
                if isinstance(data, dict) and "area_km2" in data:
                    basis += f" (Computed area: {data['area_km2']} km²)."
            except Exception:
                pass

    url = reg.get("url") or resolve_source_url(reg.get("name", ""), reg.get("provider", ""), reg.get("category", ""))

    return SourceEntry(
        name=reg["name"],
        category=reg["category"],
        provider=reg["provider"],
        query_scope=query_scope,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        basis_or_assumptions=basis,
        url=url,
    )


def extract_sources_from_markdown(content: str) -> list[SourceEntry]:
    """
    Parse an existing '## Data Sources & Methodology' or '## Sources' section from markdown.
    Extracts structured SourceEntry items from markdown tables or bulleted lists,
    preserving or resolving hyperlinks.
    """
    if not content:
        return []

    # Locate sources heading
    heading_pattern = re.compile(
        r'(?i)^#+\s+(?:data\s+sources\s*(?:&|and)\s*methodology|data\s+sources|sources\s*(?:&|and)\s*methodology|methodology\s*(?:&|and)\s*sources|sources|references)\b',
        re.MULTILINE,
    )
    match = heading_pattern.search(content)
    if not match:
        return []

    section_text = content[match.end():]
    # Stop at the next heading
    next_heading = re.search(r'(?i)^#+\s+', section_text, re.MULTILINE)
    if next_heading:
        section_text = section_text[:next_heading.start()]

    sources: list[SourceEntry] = []

    # 1. Try parsing markdown table
    table_lines = [line.strip() for line in section_text.splitlines() if line.strip().startswith("|")]
    if len(table_lines) >= 3:
        headers = [c.strip().lower() for c in table_lines[0].strip("|").split("|")]
        col_map = {}
        for idx, h in enumerate(headers):
            if any(k in h for k in ("source", "tool", "dataset", "name")):
                col_map["name"] = idx
            elif any(k in h for k in ("category", "type", "domain")):
                col_map["category"] = idx
            elif any(k in h for k in ("provider", "endpoint", "origin")):
                col_map["provider"] = idx
            elif any(k in h for k in ("scope", "query", "parameter", "extent")):
                col_map["query_scope"] = idx
            elif any(k in h for k in ("date", "time", "timestamp")):
                col_map["timestamp"] = idx
            elif any(k in h for k in ("basis", "assumption", "formula", "method", "standard", "norm")):
                col_map["basis_or_assumptions"] = idx
            elif any(k in h for k in ("url", "link", "href")):
                col_map["url"] = idx

        # If we identified at least a name column, parse data rows
        if "name" in col_map:
            for line in table_lines[2:]:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) <= max(col_map.values(), default=0):
                    continue
                name_raw = cells[col_map["name"]] if "name" in col_map else ""
                if not name_raw or name_raw.startswith("---"):
                    continue

                # Parse markdown link in name cell
                url_val = ""
                link_match = re.search(r'\[([^\]]+)\]\((https?://[^\)]+)\)', name_raw)
                if link_match:
                    name_val = link_match.group(1).strip()
                    url_val = link_match.group(2).strip()
                else:
                    name_val = name_raw

                name_val = re.sub(r'[*`]', '', name_val).strip()

                # Parse provider cell
                prov_raw = cells[col_map["provider"]].strip() if "provider" in col_map and col_map["provider"] < len(cells) else ""
                prov_link = re.search(r'\[([^\]]+)\]\((https?://[^\)]+)\)', prov_raw)
                if prov_link:
                    prov_val = re.sub(r'[*`]', '', prov_link.group(1)).strip()
                    if not url_val:
                        url_val = prov_link.group(2).strip()
                else:
                    prov_val = re.sub(r'[*`]', '', prov_raw).strip()

                cat_val = re.sub(r'[*`]', '', cells[col_map["category"]]).strip() if "category" in col_map and col_map["category"] < len(cells) else "General Source"
                scope_val = re.sub(r'[*`]', '', cells[col_map["query_scope"]]).strip() if "query_scope" in col_map and col_map["query_scope"] < len(cells) else ""
                ts_val = re.sub(r'[*`]', '', cells[col_map["timestamp"]]).strip() if "timestamp" in col_map and col_map["timestamp"] < len(cells) else ""
                basis_val = re.sub(r'[*`]', '', cells[col_map["basis_or_assumptions"]]).strip() if "basis_or_assumptions" in col_map and col_map["basis_or_assumptions"] < len(cells) else ""

                if "url" in col_map and col_map["url"] < len(cells):
                    custom_url = cells[col_map["url"]].strip().strip("<>")
                    if custom_url.startswith("http"):
                        url_val = custom_url

                if not url_val:
                    url_val = resolve_source_url(name_val, prov_val, cat_val)

                entry = SourceEntry(
                    name=name_val,
                    category=cat_val,
                    provider=prov_val,
                    query_scope=scope_val,
                    timestamp=ts_val,
                    basis_or_assumptions=basis_val,
                    url=url_val,
                )
                sources.append(entry)
            if sources:
                return sources

    # 2. Try parsing bullet list: - **Source Name**: details...
    bullet_pattern = re.compile(r'^\s*[-*]\s+\*\*([^*]+)\*\*[:\s]*(.*)', re.MULTILINE)
    for m in bullet_pattern.finditer(section_text):
        name_val = m.group(1).strip()
        desc_val = m.group(2).strip()
        url_val = ""
        link_m = re.search(r'\[([^\]]+)\]\((https?://[^\)]+)\)', name_val)
        if link_m:
            name_val = link_m.group(1).strip()
            url_val = link_m.group(2).strip()
        else:
            url_val = resolve_source_url(name_val, desc_val)

        sources.append(SourceEntry(
            name=name_val,
            category="Data Source",
            provider="",
            query_scope="",
            timestamp="",
            basis_or_assumptions=desc_val,
            url=url_val,
        ))

    # 3. Numbered list: 1. **Source Name**: details...
    if not sources:
        num_pattern = re.compile(r'^\s*\d+\.\s+\*\*([^*]+)\*\*[:\s]*(.*)', re.MULTILINE)
        for m in num_pattern.finditer(section_text):
            name_val = m.group(1).strip()
            desc_val = m.group(2).strip()
            url_val = ""
            link_m = re.search(r'\[([^\]]+)\]\((https?://[^\)]+)\)', name_val)
            if link_m:
                name_val = link_m.group(1).strip()
                url_val = link_m.group(2).strip()
            else:
                url_val = resolve_source_url(name_val, desc_val)

            sources.append(SourceEntry(
                name=name_val,
                category="Data Source",
                provider="",
                query_scope="",
                timestamp="",
                basis_or_assumptions=desc_val,
                url=url_val,
            ))

    return sources


def infer_sources_from_content_and_context(
    content: str,
    title: str = "",
    messages: Optional[list[dict]] = None,
    map_context: Optional[dict] = None,
) -> list[SourceEntry]:
    """
    Intelligently infer data sources, analytical bases, and authoritative URLs
    when an artifact was created without explicit tool calls or when saving chat summaries.
    """
    full_text = f"{title}\n{content}\n"
    if messages:
        for m in messages[-4:]:
            c = m.get("content")
            if isinstance(c, str):
                full_text += f"{c}\n"

    inferred: list[SourceEntry] = []
    text_lower = full_text.lower()

    # Detect Place / Geographic Scope
    place_scope = "Active study area"
    place_match = re.search(r'(?i)\b(?:in|for|of|at)\s+([A-Z][a-zA-Z\s]{2,25}(?:NCR|City|District|State|Region|Area)?)', full_text)
    if place_match:
        place_scope = place_match.group(1).strip()

    # 1. Air Quality (PM2.5, PM10, AQI, NO2, O3)
    if any(k in text_lower for k in ("pm2.5", "pm10", "aqi", "air quality", "µg/m³", "ug/m3", "no2", "so2")):
        inferred.append(SourceEntry(
            name="Open-Meteo Air Quality Index",
            category="Environmental & Air Quality",
            provider="Copernicus CAMS / Open-Meteo API",
            query_scope=f"{place_scope} atmospheric sensors",
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            basis_or_assumptions="Copernicus Atmosphere Monitoring Service (CAMS) European reanalysis models providing surface PM2.5, PM10, NO2, and composite AQI values.",
            url="https://open-meteo.com/en/docs/air-quality-api",
        ))

    # 2. Weather & Forecast
    if any(k in text_lower for k in ("weather", "forecast", "precipitation", "temperature", "humidity", "wind speed", "feels like", "7-day")):
        inferred.append(SourceEntry(
            name="Open-Meteo Weather Forecast & Climate",
            category="Meteorological & Climate",
            provider="Open-Meteo Weather API",
            query_scope=f"{place_scope} meteorological forecast",
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            basis_or_assumptions="High-resolution numerical weather prediction models (ECMWF, GFS, ICON) providing 7-day temperature, wind, and precipitation forecasts.",
            url="https://open-meteo.com/en/docs",
        ))

    # 3. Population & Demographics
    if any(k in text_lower for k in ("worldpop", "population", "demographic", "cohort", "inhabitants", "residents", "pop density")):
        inferred.append(SourceEntry(
            name="WorldPop 100m Population Count",
            category="Raster Demographics",
            provider="WorldPop (hub.worldpop.org)",
            query_scope=place_scope,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            basis_or_assumptions="100m building-constrained raster population grid (UN-adjusted) spatially aggregated within study area boundary.",
            url="https://hub.worldpop.org",
        ))

    # 4. OpenStreetMap / Amenities / Boundary
    if any(k in text_lower for k in ("openstreetmap", "osm", "amenities", "amenity", "school", "hospital", "transit stops", "overpass", "admin boundary", "boundary")):
        inferred.append(SourceEntry(
            name="OpenStreetMap Vector Features",
            category="Geospatial Vector",
            provider="OpenStreetMap (Overpass API)",
            query_scope=f"{place_scope} administrative extent",
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            basis_or_assumptions="Topological vector features and administrative boundary hierarchy extracted from OpenStreetMap.",
            url="https://www.openstreetmap.org",
        ))

    # 5. Land Use / Satellite LULC / NDVI
    if any(k in text_lower for k in ("land use", "built-up", "built up", "sentinel", "dynamic world", "ndvi", "lulc", "urban footprint")):
        inferred.append(SourceEntry(
            name="Satellite Land Use & Land Cover (LULC)",
            category="Earth Observation & Remote Sensing",
            provider="Dynamic World / Sentinel-2 (10m)",
            query_scope=place_scope,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            basis_or_assumptions="10-meter deep learning near-real-time satellite land cover classification (Sentinel-2 multi-spectral imagery).",
            url="https://dynamicworld.app",
        ))

    # 6. Routing & Mobility
    if any(k in text_lower for k in ("osrm", "route", "corridor", "travel time", "shortest path", "catchment", "isochrone", "walkshed")):
        inferred.append(SourceEntry(
            name="OSRM Multimodal Network Routing",
            category="Mobility & Transportation",
            provider="OSRM (Open Source Routing Machine)",
            query_scope=place_scope,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            basis_or_assumptions="Dijkstra shortest path algorithm evaluated over OpenStreetMap topological road network graph.",
            url="https://project-osrm.org",
        ))

    # 7. Zoning & Planning Regulations
    if any(k in text_lower for k in ("zoning", "master plan", "far ", "floor area ratio", "ground coverage", "land budget", "urdpfi", "setback")):
        inferred.append(SourceEntry(
            name="Master Plan Zoning & Planning Norms",
            category="Urban Planning & Regulations",
            provider="Municipal Development Regulations / Master Plan",
            query_scope=place_scope,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            basis_or_assumptions="Statutory Floor Area Ratio (FAR), ground coverage controls, and URDPFI planning allocation guidelines.",
            url="https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf",
        ))

    # 8. Geodesic GIS Math
    if any(k in text_lower for k in ("geodesic", "ellipsoidal", "area_km2", "hectares", "buffer", "centroid", "intersection", "sq km", "km²")):
        inferred.append(SourceEntry(
            name="Ellipsoidal Geodesic GIS Calculation",
            category="Geodesic GIS",
            provider="pyproj.Geod (WGS84 Ellipsoid)",
            query_scope=place_scope,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            basis_or_assumptions="True ellipsoidal surface area and geodesic distances computed on the WGS84 ellipsoid.",
            url="https://proj.org/operations/geodesic.html",
        ))

    # Check active map layers in map_context
    if map_context and "layers" in map_context:
        for layer in map_context.get("layers", []):
            lname = layer.get("name", "").lower()
            if "boundary" in lname and not any(s["name"] == "OpenStreetMap Vector Features" for s in inferred):
                inferred.append(SourceEntry(
                    name="OpenStreetMap Administrative Boundary",
                    category="Geospatial Vector",
                    provider="OpenStreetMap (Overpass / Nominatim)",
                    query_scope=layer.get("name", "Active boundary layer"),
                    timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    basis_or_assumptions="Boundary geometry resolved from OpenStreetMap administrative hierarchy.",
                    url="https://www.openstreetmap.org",
                ))

    return inferred


def synthesize_sources_section(
    telemetry_sources: list[SourceEntry],
    existing_content: str,
    title: str = "",
    messages: Optional[list[dict]] = None,
    map_context: Optional[dict] = None,
) -> tuple[str, list[SourceEntry]]:
    """
    Ensure the document content contains a complete '## Data Sources & Methodology' section
    and return the updated content alongside the deduplicated structured list of sources.
    Attaches authoritative URLs to both the markdown table and metadata entries.
    """
    existing_content = existing_content or ""
    parsed_existing = extract_sources_from_markdown(existing_content)

    # Merge telemetry sources and parsed existing sources (deduplicating by normalized name)
    combined: list[SourceEntry] = []
    seen_names = set()

    for s in parsed_existing + telemetry_sources:
        name_norm = re.sub(r'[^a-z0-9]', '', s.get("name", "").lower())
        if not name_norm or name_norm in seen_names:
            continue
        seen_names.add(name_norm)
        # Ensure URL is populated
        if not s.get("url"):
            s["url"] = resolve_source_url(s.get("name", ""), s.get("provider", ""), s.get("category", ""))
        combined.append(s)

    # If no sources recorded yet, intelligently infer from content and conversation context
    if not combined:
        inferred = infer_sources_from_content_and_context(
            existing_content,
            title=title,
            messages=messages,
            map_context=map_context,
        )
        if inferred:
            combined = inferred

    # Fallback to general workspace analytical entry if still empty
    if not combined:
        combined = [
            SourceEntry(
                name="Project Planning Synthesis",
                category="Planning Assessment",
                provider="Disha Analytical Workspace",
                query_scope="Project Study Area",
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                basis_or_assumptions="Internal spatial analysis and qualitative planning synthesis compiled within the workspace.",
                url="https://github.com/geoailabs/disha",
            )
        ]

    # Check if section heading is already present in existing content
    heading_pattern = re.compile(
        r'(?i)^#+\s+(?:data\s+sources\s*(?:&|and)\s*methodology|data\s+sources|sources\s*(?:&|and)\s*methodology|methodology\s*(?:&|and)\s*sources|sources|references)\b',
        re.MULTILINE,
    )
    has_section = bool(heading_pattern.search(existing_content))

    if has_section and parsed_existing:
        # Check if parsed sources have URLs; if any don't, we update metadata
        for s in combined:
            if not s.get("url"):
                s["url"] = resolve_source_url(s.get("name", ""), s.get("provider", ""), s.get("category", ""))
        return existing_content, combined

    # Format a standardized markdown table section with hyperlinks
    lines = [
        "",
        "## Data Sources & Methodology",
        "",
        "The analytical figures, spatial layers, and planning projections in this document were compiled on the following statutory, spatial, and mathematical basis:",
        "",
        "| Data Source / Tool | Category | Provider / Endpoint | Query Scope & Parameters | Date / Timestamp | Analytical Basis & Assumptions |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for s in combined:
        name = s.get("name", "Unknown Source").replace("|", "/")
        cat = s.get("category", "General").replace("|", "/")
        prov = s.get("provider", "Internal / Local").replace("|", "/")
        scope = s.get("query_scope", "Study Area").replace("|", "/")
        ts = s.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d")).replace("|", "/")
        basis = s.get("basis_or_assumptions", "Standard spatial calculations applied.").replace("|", "/")
        url = s.get("url") or resolve_source_url(name, prov, cat)
        s["url"] = url

        if url:
            lines.append(f"| [**{name}**]({url}) | {cat} | [`{prov}`]({url}) | {scope} | {ts} | {basis} |")
        else:
            lines.append(f"| **{name}** | {cat} | `{prov}` | {scope} | {ts} | {basis} |")

    lines.append("")
    section_md = "\n".join(lines)

    if has_section:
        # Replace empty/incomplete section with generated section
        m = heading_pattern.search(existing_content)
        if m:
            before = existing_content[:m.start()].rstrip()
            updated_content = f"{before}\n\n{section_md.strip()}\n"
            return updated_content, combined

    # Append to the end of the document
    updated_content = f"{existing_content.rstrip()}\n\n{section_md.strip()}\n"
    return updated_content, combined
