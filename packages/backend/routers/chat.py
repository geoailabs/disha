"""
Chat router — direct OpenAI integration with tool-calling loop.

Each WebSocket connection keeps a running message history and runs an
agentic loop:
  1. Send messages to OpenAI with tool definitions.
  2. Stream text deltas back to the frontend.
  3. Execute tool calls inline; map actions go straight to the WebSocket.
  4. Loop until the model stops calling tools.
"""

import asyncio
import contextvars
import json
import logging
import os
import sys
from pathlib import Path

# Task pipeline orchestrator (heap + queue based document compilation)
try:
    from tools.task_pipeline import (
        classify_tool_calls,
        needs_pipeline,
        patch_content_with_real_paths,
        inject_new_artifact_instruction,
    )
    _PIPELINE_AVAILABLE = True
except ImportError:
    _PIPELINE_AVAILABLE = False

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Make sure backend package is importable
_BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from database import DB_PATH
from mcp_servers.osm_server import OSMServer
from mcp_servers.gis_server import GISServer
from mcp_servers.weather_server import WeatherServer
from mcp_servers.zoning_server import ZoningServer
from mcp_servers.demographics_server import DemographicsServer
from mcp_servers.overture_server import OvertureServer
from mcp_servers.google_places_server import GooglePlacesServer
from mcp_servers.google_environment_server import GoogleEnvironmentServer
from mcp_servers.wms_server import WMSServer
from mcp_servers.gee_server import GEEServer
from mcp_servers.datameet_server import DatameetServer
from mcp_servers.network_server import NetworkServer
from mcp_servers.gtfs_server import GTFSServer
from mcp_servers.od_server import ODServer
from mcp_servers.scenario_server import ScenarioServer
from mcp_servers.its_server import ITSServer
from mcp_servers.emissions_server import EmissionsServer
from mcp_servers.plot_server import PlotServer
from tools.utility import UtilityServer
from tools.config import get_model as _get_model
from tools.google import google_maps_key_var
from tools.action_utils import send_action as _send_action
from tools.spatial_registry import spatial_registry
from domains import (
    SpatialHub,
    MobilityHub,
    EnvironmentHub,
    PlanningHub,
    DemographicsHub,
    PlacesHub,
    ScenariosHub,
    UtilityHub,
    ToolResult,
)

try:
    from shapely.geometry import shape as _shape
except ImportError:
    _shape = None

router = APIRouter()

_hubs = {
    "spatial": SpatialHub(),
    "mobility": MobilityHub(),
    "environment": EnvironmentHub(),
    "planning": PlanningHub(),
    "demographics": DemographicsHub(),
    "places": PlacesHub(),
    "scenarios": ScenariosHub(),
    "utility": UtilityHub(),
}

_stop_event_var: contextvars.ContextVar[asyncio.Event | None] = contextvars.ContextVar("chat_stop_event", default=None)


def _set_stop_event(stop_event: asyncio.Event | None) -> None:
    _stop_event_var.set(stop_event)


def _get_stop_event() -> asyncio.Event | None:
    return _stop_event_var.get()


def _is_cancelled() -> bool:
    event = _get_stop_event()
    return event is not None and event.is_set()


async def _send_action_if_allowed(ws: WebSocket, action: str, payload: dict) -> bool:
    if _is_cancelled():
        return False
    await _send_action(ws, action, payload)
    return True


def _env_openai_api_key() -> str:
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _env_google_maps_api_key() -> str:
    return (
        os.environ.get("GOOGLE_MAPS_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()


_env_key = _env_openai_api_key()
_client = AsyncOpenAI(api_key=_env_key) if _env_key else None

_servers = {
    "osm": OSMServer(),
    "gis": GISServer(),
    "weather": WeatherServer(),
    "zoning": ZoningServer(),
    "demographics": DemographicsServer(),
    "overture": OvertureServer(),
    "google_places": GooglePlacesServer(),
    "google_env": GoogleEnvironmentServer(),
    "wms": WMSServer(),
    "gee": GEEServer(),
    "datameet": DatameetServer(),
    "network": NetworkServer(),
    "gtfs": GTFSServer(),
    "od": ODServer(),
    "scenario": ScenarioServer(),
    "its": ITSServer(),
    "emissions": EmissionsServer(),
    "plot": PlotServer(),
    "utility": UtilityServer(db_path=DB_PATH),
}

# ── Action tool names (sent directly to frontend as map actions) ──────────────

_ACTION_TOOLS = {
    "fly_to", "fit_bounds", "add_marker", "add_markers", "clear_markers",
    "draw_line", "draw_polygon", "draw_circle", "add_geojson",
    "highlight_features", "set_layer_style", "style_layer", "toggle_layer", "remove_layer",
    "save_bookmark", "go_to_bookmark", "export_region_clip", "export_map_png", "export_map_jpeg", "export_map_pdf",
    "switch_basemap", "add_geojson_file", "add_gee_layer", "add_raster_overlay",
}

# ── System prompt ─────────────────────────────────────────────────────────────

DOCUMENT_SYSTEM_PROMPT = (
    "You are an expert urban planning analyst. The user has shared a map image or planning document with you. "
    "Carefully analyze what you see: land use patterns, zoning areas, transportation networks, "
    "infrastructure, built vs. open spaces, density patterns, boundaries, and any labels or legends. "
    "Answer questions thoroughly with professional planning insights. "
    "You can automatically align/georeference the active map image to the real-world coordinates on the map. "
    "To do this automatically, call autogeoreference_image. Alternatively, you can manually identify at least 3 visual landmarks on the image, search/geocode their real-world latitude/longitude (using geocode or osm_search), "
    "and call georeference_active_document with the control points (x,y normalized from 0.0 to 1.0, where 0,0 is top-left and 1,1 is bottom-right). "
    "Once georeferenced, you must digitize visual features (boundaries, areas, points of interest) from the image. "
    "Do NOT estimate coordinates manually. Instead, trace features by identifying their visual coordinate vertices (x,y percentages from 0.0 to 1.0) "
    "and call digitize_image_features to automatically translate them to real coordinates using the affine matrix. "
    "You may also query OSM/Overture in the georeferenced area to fetch matching digital vectors. "
    "You may save detailed analyses using the create_artifact tool and generate charts, histograms, or demographic distributions using create_plot."
)

SYSTEM_PROMPT = (
    "You are an expert urban planning assistant embedded in a desktop GIS application. "
    "You help with zoning analysis, land use planning, transportation networks, "
    "environmental impact, building codes, community development, and spatial analysis. "
    "Always respond in English regardless of the query language.\n\n"
    "AVAILABLE TOOLS:\n"
    "- Navigate: fly_to, fit_bounds\n"
    "- Markers: add_marker, add_markers (multi-marker requests become a grouped set of separate marker layers; pass a 'description' to show info in a hover popup), clear_markers\n"
    "- Layers: add_geojson (multiple point features are displayed as separate layers inside one group), toggle_layer, remove_layer, set_layer_style, style_layer\n"
    "- Highlight: highlight_features\n"
    "- Search: web_search, geocode, autogeoreference_image (extract landmarks and align active/attached map image automatically), georeference_active_document (align dropped map image to real-world coordinates using 3+ landmark GCPs), digitize_image_features (convert list of normalized x,y image coordinates to real-world GeoJSON features using the solved matrix)\n"
    "- OSM: osm_search (amenities, buildings, roads), "
    "osm_fetch_bus_routes (fetch actual transit/bus route lines around transit hubs, terminals, or city centers — ALWAYS prefer this when user asks for bus routes or transit lines), "
    "osm_boundary (city/district/state boundary polygons), "
    "osm_boundary_union (merge multiple boundaries into ONE polygon — server-side, no coordinate echoing), "
    "osm_reverse_geocode, osm_route_overview\n"
    "- Google Places (PREFER for commercial POIs — fresher and brand-named): "
    "places_autocomplete, place_details, nearby_places, "
    "nearby_places_in_polygon (polygon-clipped), places_density\n"
    "- Overture Maps (fallback for places; building footprints): "
    "overture_places_search, overture_buildings_search\n"
    "- Google Environment: get_elevation (terrain), get_air_quality_google "
    "(per-pollutant), get_solar_building (rooftop solar potential)\n"
    "- Weather: get_weather, get_air_quality (Open-Meteo fallback)\n"
    "- GIS: gis_buffer, gis_centroid, gis_area, gis_convex_hull, "
    "gis_point_in_polygon, gis_bounding_box, gis_union, "
    "gis_intersection (overlap of A & B), gis_difference (A minus B), "
    "gis_clip (crop a layer to a polygon), gis_dissolve (merge features, "
    "optionally by a property), gis_nearest (closest feature to a point), "
    "gis_spatial_join (tag points with the polygon they fall in), "
    "gis_filter (filter features from a loaded layer or dataset by attribute values e.g. district/state names, and render a new filtered layer on the map)\n"
    "- Bookmarks & Export: save_bookmark, go_to_bookmark, export_region_clip (clips vector layers to GeoJSON), export_map_png (exports/downloads composed map as PNG image figure), export_map_jpeg (exports/downloads composed map as JPEG image figure), export_map_pdf (exports/downloads composed map as PDF report figure)\n"
    "- Zoning: analyze_zones, detect_zone_overlaps\n"
    "- Artifacts & Documents: create_artifact (format: pdf/docx/jpeg/png/markdown/table/geojson), edit_artifact (edit/update a PDF, Word .docx, or markdown planning document: insert sections, map snapshot images, tables, and narrative text/descriptions under specific headings), list_artifacts, get_artifact, extract_attribute_table\n"
    "  To edit or compile a planning document based on user prompts (e.g., 'add this to the pdf under heading X', 'add the map image under heading Y with description Z', 'edit section A'), call edit_artifact with the title or ID, section_heading, content, and include_map_figure/figure_caption.\n"
    "  When editing a document to insert an existing image or chart artifact, ALWAYS set `image_artifact_id=37` (using the numeric artifact ID). NEVER use `include_map_figure=true` when inserting an existing saved image artifact.\n"
    "  extract_attribute_table extracts layer or shapefile properties/columns into a tabular artifact.\n"
    "  Re-adding geometry: call get_artifact to retrieve a geojson artifact's content, then pass it to add_geojson.\n"
    "- Reports: generate_report — generates a deep research urban planning report using web search. "
    "Use when user asks to generate/create/write a report or planning analysis.\n"
    "- Plots & Charts: create_plot (generate publication-ready bar, pie, histogram, line, scatter charts from numeric data/distribution arrays and save them directly as high-resolution image artifacts in the project workspace). "
    "Whenever the user asks for any chart, graph, or demographic/spatial distribution (e.g., 'pie chart of population', 'bar chart of land use', 'traffic distribution'), you MUST call create_plot with the appropriate plot_type ('pie', 'bar', 'histogram', 'line', 'scatter'), title, x_data (categories/slice labels), and y_data (numeric counts/percentages).\n"
    "- Street Network (NetworkX): fetch_street_network (automatically pull connected roads within current map bounds or coordinates to the workspace), "
    "analyze_street_network (topology metrics & bottleneck centrality on a road layer/file), "
    "find_shortest_path (Dijkstra routing between coordinates on a road layer/file), "
    "find_freight_route (optimal truck route avoiding residential streets and respecting weight/height restrictions), "
    "route_multi_stop (continuous multi-waypoint route along the road network). "
    "Always prefer passing `geojson_path` instead of passing the huge raw `geojson` object to avoid token and WebSocket payload constraints.\n"
    "- ITS & Parking: optimize_traffic_signal (Webster's Method traffic light timing optimizer), "
    "analyze_parking_requirements (zoning parking ECS demand calculator matched against OSM-mapped supply).\n"
    "- GTFS Transit: import_gtfs_feed (download URL or local workspace ZIP/folder — loads stops + route lines on the map), "
    "analyze_gtfs_service (compute service stats: route counts, trip frequencies, highest-frequency corridors), "
    "analyze_gtfs_schedules (calculate hourly peak vs off-peak headway histograms and stop arrival timetables), "
    "analyze_transit_catchment (generate 400m / 800m walking catchment service coverage buffer polygons).\n"
    "- OD Matrix: import_od_matrix (import CSV-based Origin-Destination matrix from a URL), "
    "generate_gravity_od_matrix (auto-generate trip productions/attractions from zone population & jobs and distribute them via doubly-constrained Furness/IPFP gravity decay model), "
    "calculate_mode_choice (split travel demand across car, two-wheeler, transit, and active travel modes using a multinomial logit model based on time/cost utilities), "
    "visualize_od_flows (render desire lines on the map weighted by trip volume; supports min_trips filter and top_n).\n"
    "- Planning Scenarios: generate_planning_scenarios (generate structured Baseline/Compact/TOD/Green scenario alternatives "
    "for a study area context; returns a markdown report with comparison table — always save the result to an artifact), "
    "compare_scenarios (score and rank 2+ named scenarios across criteria; integrates tailpipe emissions and ambient PM2.5 box model), "
    "estimate_scenario_emissions (calculate tailpipe CO2, PM2.5, NOx, CO emissions and estimate ambient PM2.5 concentrations using Gifford-Hanna box model).\n"
    "- Google Land Classification (GEE): get_land_cover (fetch Dynamic World or ESA WorldCover LULC layer "
    "for a given year — shows water/trees/grass/crops/built/bare classes), "
    "analyze_lulc_change (compare two years of Dynamic World to detect built-up expansion, deforestation, "
    "or wetland loss — adds a changed-areas mask + class-transition layer), "
    "analyze_land_use_zonal_stats (calculate exact area in km² and percentage composition breakdown of land cover classes inside a study polygon/boundary), "
    "extract_land_use_polygons (convert raster land cover classes into vector GeoJSON polygons loaded on the map), "
    "get_ndvi_layer (compute NDVI from Sentinel-2 to map vegetation density, green space, and urban heat islands). "
    "All GEE tools require the ee-*.json service account credentials file in the workspace root.\n"
    "- Public GIS Datasets: browse_datameet_catalog (list all available public GIS datasets "
    "with dataset_ids, titles, and categories — call this first before importing), "
    "import_public_dataset (download and load a named dataset: national boundaries, states, districts, "
    "railway lines, stations, rivers, highways, urban agglomerations, etc.), "
    "import_datameet_boundary (fetch state/district/village boundaries by administrative level).\n\n"
    "MAP CONTEXT:\n"
    "The current map state is appended to every message. It includes:\n"
    "- center: current map center coordinates [longitude, latitude].\n"
    "- zoom: current map zoom level.\n"
    "- bounds: current viewport (west,south,east,north) when available.\n"
    "- bookmarks: saved regions; use go_to_bookmark to navigate.\n"
    "- Layer list with geometry_data (actual coordinates for small layers, bbox for large ones).\n"
    "- selected_features: active map elements/layers highlighted by the user, providing layer name, attributes summary, centroid [lng, lat], bounding box, and file path.\n\n"
    "When the user refers to 'here', 'this location', 'current view', or 'current map', utilize the map 'Center' longitude and latitude coordinates from the Map Context. Do NOT call the 'geocode' tool with 'here' or 'this place'. For coordinate-based tools (like get_weather or get_air_quality), pass the latitude and longitude directly. For text-based tools (like web_search), call the 'osm_reverse_geocode' tool first to obtain a readable place name/address.\n\n"
    "IMPORTANT RULES:\n"
    "1. Do NOT add markers unless the user explicitly asks for markers or pins. When the user asks for multiple different points, use one add_markers call so the app creates a grouped set of separate marker layers.\n"
    "2. Do NOT repeat a tool call you already made. Call each tool ONCE per distinct item.\n"
    "3. osm_search, osm_boundary, overture_places_search, overture_buildings_search, "
    "nearby_places, and nearby_places_in_polygon results are AUTO-DISPLAYED on the map. "
    "Do NOT call add_geojson for data that was already returned by these tools. For "
    "COMMERCIAL POIs (restaurants, hotels, retail, services, schools, hospitals) PREFER "
    "nearby_places (Google) — it has the freshest brand names and category data. When the "
    "user asks for POIs INSIDE a drawn polygon / region / sector boundary (any non-circular "
    "area), use nearby_places_in_polygon — it returns only places that fall within the "
    "polygon. Use overture_places_search only when the Google tools return empty or "
    "upstream_unavailable. Use osm_search for non-commercial OSM-tagged features (water, "
    "infrastructure, hand-mapped local data).\n"
    "4. When using osm_boundary, pass country_code (e.g. 'IN', 'US', 'GB', 'FR', 'DE') when known to disambiguate places with identical names across multiple countries. If osm_boundary returns an error (no boundary polygon is mapped in OSM), do NOT try to draw a wrong fallback polygon or building footprint. Instead, call the geocode tool to resolve the place's coordinates, fly_to that centroid, and add a pin marker using add_marker with the place name as the label.\n"
    "5. Only call the tools the user's request requires. Do not add extra actions.\n"
    "6. When the user asks to navigate somewhere, use fly_to. Do not add markers unless asked.\n"
    "7. SUB-CITY BOUNDARIES (sectors, neighborhoods, wards, quarters, suburbs, subdivisions): call osm_boundary with "
    "place_type='suburb' (or 'neighbourhood'/'quarter') and parent='<city>'. Do NOT rely solely on admin_level, as "
    "sub-city units are frequently mapped with place tags rather than boundary relations in OSM. If a query returns empty, "
    "attempt: (a) alphanumeric name variations (e.g. 'Sector 30 A' vs 'Sector 30'), (b) alternate place_type tags "
    "('suburb', 'neighbourhood', 'quarter'), or (c) osm_search(feature_type='place', feature_value='suburb') near the city center.\n"
    "8. When finished, stop calling tools and respond with a brief summary of what you did.\n"
    "9. SINGLE POLYGON ACROSS MULTIPLE PLACES: when the user asks for ONE merged boundary or study area "
    "spanning multiple adjacent cities, districts, or boroughs (e.g. 'merge City A and City B into one polygon', "
    "'metropolitan study area'), call osm_boundary_union with all place names in a single call. Do NOT call "
    "osm_boundary multiple times and then try manual coordinate stitching.\n"
    "10. AIR QUALITY: prefer get_air_quality_google (per-pollutant breakdown, AQI, health "
    "recommendations). If Google returns an error, HTTP 403, or upstream_unavailable, IMMEDIATELY "
    "call get_air_quality (Open-Meteo, keyless fallback) so the user always receives live PM2.5, PM10, and AQI metrics.\n"
    "11. AMBIGUOUS PLACE NAMES: if the user types a partial or ambiguous place name, call "
    "places_autocomplete first to get candidate place_ids, then place_details on the best match "
    "to resolve to coordinates. Skip this for unambiguous queries — geocode is faster.\n"
    "12. STYLING A LAYER: to color a layer BY a property value, use style_layer — "
    "mode='categorized' for a string property (zone_code, land_use, route_name), "
    "mode='graduated' for a numeric property (population, density, area). You pass only "
    "the property and (optionally) ramp/classes; the app computes breaks and the palette. "
    "To put text on the map, pass label_property (e.g. the station/zone/route name). Use "
    "set_layer_style ONLY for a single flat color across the whole layer. Each layer in the "
    "map context carries a 'style' summary — do NOT re-issue a style_layer call that already "
    "matches the active mode/property.\n"
    "13. SPATIAL ANALYSIS: pass GeoJSON geometry to the gis_* overlay tools. For data already "
    "on the map, the map context includes each layer's geometry_data (full coords for small "
    "layers) — use it as the tool input. gis_intersection/difference/clip/dissolve render their "
    "result automatically (do NOT call add_geojson after). Use gis_clip to crop a layer to a "
    "boundary, gis_dissolve with group_by to merge parcels into districts, gis_spatial_join to "
    "tag points with their containing polygon, and gis_nearest for closest-feature queries.\n"
    "14. NAVIGATION ACCURACY: ALWAYS call the geocode tool first to resolve a place name to "
    "coordinates — never use your training-data knowledge for coordinates directly, as they "
    "can be outdated or wrong. Use the FIRST result returned by geocode for fly_to. "
    "Choose zoom based on place type: country=5, state=8, district=10, city/town=12, "
    "neighbourhood/sector=14, specific POI=16. Never use zoom>16 unless the user zooms in.\n"
    "15. LAYER EXISTENCE: Always check the 'Current map state' layers list to verify if a layer is actually loaded on the map. "
    "Do not assume a layer exists just because it was mentioned or loaded in a previous turn in the chat history. "
    "If a layer is missing from the 'Current map state' layers list, it has been deleted by the user, and you must call the "
    "appropriate tool to fetch/create it again if the user asks for it.\n"
    "16. MEASURE_DISTANCE AUTO-DRAW: when you call measure_distance, the backend automatically draws both a "
    "'Direct Distance N' layer (dashed blue straight line) and, if OSRM resolves, a 'Route Distance N' "
    "layer (solid red driving route with duration) on the map. Do NOT separately call draw_line or add_geojson "
    "to visualize the measurement — the layers appear automatically. Just narrate the result numbers to the user.\n"
    "17. PROJECT_POPULATION AUTO-ARTIFACT: when you call project_population and it succeeds, the backend "
    "automatically saves the full Markdown report as a named Artifact in the Artifacts panel (title: "
    "'Population Projection – <place> <year range>'). Do NOT paste the full projection table or report into "
    "the chat. Instead, narrate a brief 2-3 sentence summary of the key numbers "
    "(baseline, projected population at final target year, growth increment, land demand in hectares) and "
    "tell the user the report has been saved to Artifacts.\n"
    "18. BOUNDARY ADMIN LEVEL DISCLOSURE: When you fetch or display any administrative boundary "
    "(using osm_boundary or osm_boundary_union), always mention explicitly in your chat response "
    "which administrative level (e.g., admin_level=5 for district/county, admin_level=8 for city/municipality) "
    "was used or chosen.\n"
    "19. PLOT & CHART GENERATION: Call `create_plot` ONLY when a visual chart, graph, or multi-category breakdown is explicitly requested (e.g. 'bar chart of land use comparison', 'ward population distribution', 'trip modal split'). Provide at least 2 distinct categories in x_data and numeric counts in y_data. NEVER call `create_plot` for a single scalar value (e.g. stating 'Delhi population: 11.3 million' is a formatted number/table in markdown, NOT a 1-slice 100% pie chart). NEVER insert a chart/plot image where a map image was requested (e.g. do not put a population chart under a catchment heading).\n"
    "20. REGIONAL & METROPOLITAN BOUNDARIES (e.g. NCR / Delhi NCR, Greater London, Tri-State, MMR): When asked to display a metropolitan region consisting of multiple contiguous districts or states (e.g. 'Delhi NCR' or 'National Capital Region', which spans NCT Delhi and adjoining Haryana, Uttar Pradesh, and Rajasthan districts), retrieve and merge the contiguous district/state boundaries (using osm_boundary_union or import_datameet_boundary) so they form a clean boundary. If asked to mark both a central core (e.g. Delhi) and the broader metropolitan region (e.g. NCR) in different colors, add them as two separate distinct layers and style them with contrasting colors (e.g. green outline/fill for Delhi, blue or orange for NCR) using set_layer_style.\n"
    "21. JUNCTIONS AND POI PINNING: When pinning a specific point of interest, landmark, chowk, junction, or address (like 'Fountain Chowk' or 'Airport Chowk'), ALWAYS first call the `geocode` tool with the full descriptive name and containing context (e.g. 'Fountain Chowk, Sector 43, Chandigarh') to resolve its exact point coordinate. DO NOT call `osm_boundary` or `osm_search` for a specific junction/chowk unless you want to search for adjacent amenities or the city boundary. To display the pinned point on the map, call `add_marker` at the resolved coordinate. When the user asks to route/cross through waypoints, ensure each waypoint is geocoded and explicitly passed in the routing tool's `waypoints` argument, and pass the corresponding color or label if customized.\n"
    "22. AUTOMATIC ARTIFACT & MULTI-FORMAT EXPORT PERSISTENCE: Whenever you generate ANY planning report, summary card, demographic profile, plot/histogram, or structured analysis, call `create_artifact` with a descriptive title and format ('pdf', 'docx', 'html', 'png', 'jpg', 'xlsx', 'txt', 'json', 'markdown', 'table', 'geojson'). You CAN create PNG, JPEG, PDF, Word (.docx), HTML, and Excel (.xlsx) artifacts directly using `create_artifact`. For charts and histograms, call `create_plot` to generate clean plot image artifacts.\n"
    "23. ATTRIBUTE FILTERING & VECTOR SUBSETS: When the user asks to filter/extract/isolate specific features from a loaded layer or dataset (e.g. 'filter coastal districts in Tamil Nadu and Kerala', 'show only commercial parcels', 'extract expressways'), ALWAYS call `gis_filter` with the layer_name or path, target values array, and output_layer_name. Do NOT try to highlight features one by one, do NOT paste raw geometries in chat, and do NOT claim you cannot filter without asking the user for a file.\n"
    "24. MULTI-SELECTED LAYERS IN CHAT CONTEXT: When the user Shift-clicks or selects multiple layers on the map or in the layers sidebar panel, all selected layers appear under [USER SELECTED MAP ELEMENTS / HIGHLIGHTED LAYERS] with their layer names, centroids, and attributes. When the user asks to analyze, compare, overlay, buffer, intersect, or compute stats/charts for 'these layers', 'selected regions', or 'both areas', directly reference and process ALL selected layers by their exact names/attributes in your spatial GIS tools (e.g. gis_intersection, gis_difference, gis_area, gis_union) and demographic/plotting tools (create_plot).\n"
    "25. ZERO PLACEHOLDER POLICY IN ARTIFACTS / DOCUMENTS:\n"
    "  (a) STRICT PROHIBITION: NEVER emit placeholder sentences like 'Built-up land cover polygons for X should be inserted here as a map figure when the layer is available in the current map context', 'Insert image here', 'Map to be loaded', or 'Figure placeholder'.\n"
    "  (b) If the user asks to mark or extract a map feature (e.g. boundary, catchment, built-up area, zoning, transit), you MUST execute the respective tool (`osm_boundary`, `analyze_transit_catchment`/`gis_buffer`, `get_land_cover`/`osm_search`), adjust view with `fit_bounds`, export the map via `export_map_jpeg(save_to_artifacts=True)` to get the real artifact image path, and embed that path directly in the markdown as `![Caption](artifacts_store/<ID>.jpg)`.\n"
    "  (c) Every section requesting visual content MUST have its corresponding real image artifact generated and embedded.\n"
    "26. MULTI-STEP TASK EXECUTION — SEQUENTIAL PIPELINE (FETCH → EXPORT → COMPILE):\n"
    "  CRITICAL: The backend BLOCKS create_artifact if image references are missing or are placeholders.\n"
    "  You MUST follow this exact sequential flow across multiple tool-call rounds:\n"
    "  ROUND 1: osm_boundary_union(['Chandigarh','Panchkula','Mohali']) + fit_bounds\n"
    "  ROUND 2: export_map_jpeg(title='Tricity Area Map', save_to_artifacts=True) → returns file_path e.g. artifacts_store/42.jpg\n"
    "  ROUND 3: osm_boundary('Chandigarh') + fit_bounds\n"
    "  ROUND 4: export_map_jpeg(title='Chandigarh Map', save_to_artifacts=True) → returns file_path e.g. artifacts_store/43.jpg\n"
    "  ROUND 5: osm_boundary('Panchkula') + fit_bounds + export_map_jpeg(title='Panchkula Map', save_to_artifacts=True) → artifacts_store/44.jpg\n"
    "  ROUND 6: osm_boundary('Mohali') + fit_bounds + export_map_jpeg(title='Mohali Map', save_to_artifacts=True) → artifacts_store/45.jpg\n"
    "  ROUND 7: create_plot(plot_type='pie', title='Population Distribution - Tricity', x_data=['Chandigarh','Panchkula','Mohali'], y_data=[1200000,560000,800000]) → returns file_path artifacts_store/46.png\n"
    "  ROUND 8: create_artifact(title='Chandigarh report', format='docx', content='# Chandigarh report\\n\\n## Tricity Area\\n\\n![Tricity Area](artifacts_store/42.jpg)\\n\\n![Chandigarh](artifacts_store/43.jpg)\\n\\n![Panchkula](artifacts_store/44.jpg)\\n\\n![Mohali](artifacts_store/45.jpg)\\n\\n## Population Distribution\\n\\n![Population Distribution - Tricity](artifacts_store/46.png)')\n"
    "  RULES:\n"
    "  - Each export_map_jpeg call MUST have save_to_artifacts=True\n"
    "  - The file_path returned by each export_map_jpeg tool call is the EXACT path to use in ![...](path) in the document\n"
    "  - NEVER write artifacts_store/0.jpg or any path that was not returned by a tool call in this session\n"
    "  - NEVER use (map_snapshot) or (placeholder) as image references — these will be BLOCKED\n"
    "  - You MUST call osm_boundary/osm_boundary_union BEFORE each export_map_jpeg to show the correct region\n"
    "  - You have 35 rounds to complete the pipeline — use them all if needed\n"
    "27. ACTIVE EXECUTION OVER CACHED ASSUMPTIONS:\n"
    "  - When the user asks to generate, create, or compile a report with maps and data, always perform the active tool sequence to produce fresh, accurate visual layers and images for that specific request.\n"
    "  - Do NOT assume prior inventory items are complete if the user requests specific distinct maps. Each requested visual view must have its own distinct exported map figure.\n"
    "  - NEVER fabricate artifact IDs or file paths in chat text without executing the tool to create them.\n"
    "28. ALWAYS CREATE FRESH DOCUMENTS:\n"
    "  - EVERY call to create_artifact generates a BRAND NEW document with a new unique ID. NEVER reference an existing artifact_id in create_artifact — always create fresh.\n"
    "  - Do NOT check list_artifacts before creating. Just call create_artifact directly and a new document will be created.\n"
    "  - The same prompt asked twice will create two separate documents — that is the intended behavior.\n"
)


# ── Deep research helpers ──────────────────────────────────────────────────────

_RESEARCH_SYSTEM = """
You are a senior urban planning consultant, transportation planner, GIS analyst,
and infrastructure advisor with extensive experience preparing professional reports
for governments, municipalities, planning authorities, and international agencies.

Your reports should resemble documents prepared by professional planning firms,
government agencies, and infrastructure consultants.

Your responsibilities include:

• analysing spatial data
• interpreting GIS layers
• understanding land use
• evaluating transportation systems
• assessing infrastructure
• identifying planning challenges
• proposing practical planning strategies
• developing implementation roadmaps

Use all available information including:

- conversation history
- uploaded datasets
- GIS layers
- map context
- drawn geometries
- bookmarks
- web research

Do NOT generate generic AI summaries.

Always generate reports that could realistically be submitted to a planning authority.

When information is unavailable:

• explicitly state assumptions
• never fabricate measurements
• distinguish observed facts from inferred conclusions

Use a formal technical writing style.

Support conclusions with evidence whenever possible.

The report structure should depend on the requested report type.

Examples include:

• Comprehensive Mobility Plan
• Master Plan
• Traffic Impact Assessment
• Parking Strategy
• Infrastructure Assessment
• Land Use Study
• Transit Oriented Development Study
• Urban Design Report
• Road Safety Audit

If no report type is explicitly requested,
generate the most appropriate professional planning report.

CRITICAL FORMATTING REQUIREMENT:
You MUST always include a "Table of Contents" (Index) section at the very beginning of the report (immediately after the main title `# ...`).
Every entry in the Table of Contents MUST be a clickable Markdown link pointing to its corresponding section heading (e.g. `[1. Executive Summary](#1-executive-summary)` pointing to `## 1. Executive Summary`). Make sure the anchor slugs are fully lowercase, spaces are replaced with hyphens, and punctuation is removed.

Respond ONLY with Markdown.
"""


_RESEARCH_REPORT_TEMPLATE = """
Generate a professional planning report using the information provided below.

----------------------------

STEP 1

Determine the requested report type.

Possible examples include

- Comprehensive Mobility Plan
- Traffic Impact Assessment
- Parking Strategy
- Land Use Study
- Infrastructure Assessment
- Master Plan
- Urban Design Report

If the report type is explicitly mentioned in the conversation,
follow the accepted professional structure used for that report.

If not,
choose the most appropriate report type based on the discussion.

----------------------------

STEP 2

Use the accepted structure for that planning document.

Do NOT force a generic template.

Instead,
generate the sections that would normally appear in that report.

Examples

A Comprehensive Mobility Plan should include items such as

• Executive Summary
• Study Area
• Existing Conditions
• Land Use
• Transportation Network
• Mobility Challenges
• Future Demand
• Alternative Scenarios
• Recommended Mobility Plan
• Investment Strategy
• Implementation Roadmap
• Monitoring Framework

A Traffic Impact Assessment should instead include

• Existing Traffic
• Trip Generation
• Capacity Analysis
• Level of Service
• Junction Analysis
• Parking Demand
• Mitigation Measures

----------------------------

STEP 3

For every report

• explain observations

• explain why they matter

• support recommendations with evidence

• include quantitative information whenever available

• distinguish facts, assumptions, and recommendations

• interpret GIS data rather than listing it

• use tables where appropriate

• avoid generic consulting language

• avoid repeating the conversation

----------------------------

CRITICAL STYLE & FORMATTING RULES:
1. Always start the report with the main `# [Report Title]` followed immediately by a **Table of Contents** section.
2. Under the "Table of Contents" header, list all subsequent sections and subsections as clickable Markdown anchor links pointing to their respective headers in the document.
   - For example: `[1. Executive Summary](#1-executive-summary)` pointing to `## 1. Executive Summary`.
   - Ensure the anchor names are fully lowercase, spaces are replaced with hyphens, and punctuation is removed, matching standard Markdown page-jumping navigation.
3. The report should read like a document prepared by professional urban planning consultants.
"""


'''
_RESEARCH_SYSTEM = (
    "You are a professional urban planning report writer. "
    "Generate a well-structured, data-driven report in clean Markdown. "
    "Use the provided conversation, map data, and artifacts as your primary source. "
    "Enrich your analysis with publicly available information about the location. "
    "Respond ONLY with the Markdown report. Always respond in English."
)

_RESEARCH_REPORT_TEMPLATE = """Generate a comprehensive urban planning report based on the data below.

Structure the report with these sections:

# Urban Planning Report

## Executive Summary
(2-3 paragraph overview of the planning discussion, location, and key findings)

## Site Analysis
(Geographic context, existing conditions, basemap and layer data, drawn features, placed markers)

## Key Findings
(Main points from the conversation and analysis, enriched with current public data)

## Recommendations
(Actionable next steps based on the discussion and research)

## Appendix
(Data sources, layer descriptions, methodology notes, web sources consulted)

Be specific and professional. Reference the actual map data, drawn geometries, and conversation details provided.

---
"""
'''

def _build_research_prompt(
    messages: list[dict],
    map_context: dict | None,
    outline: str | None = None,
    artifacts: list[str] | None = None,
    workspace: str | None = None
) -> str:
    """Build the deep research prompt from conversation history, map context, outline, and workspace artifacts."""
    parts = [_RESEARCH_REPORT_TEMPLATE]

    # -------------------------------------------------------
    # Detect report type from the conversation
    # -------------------------------------------------------

    conversation_text = " ".join(
        m.get("content", "")
        for m in messages
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    ).lower()

    report_type = "Professional Planning Report"

    report_keywords = {
        "mobility plan": "Comprehensive Mobility Plan",
        "comprehensive mobility plan": "Comprehensive Mobility Plan",
        "cmp": "Comprehensive Mobility Plan",
        "traffic impact": "Traffic Impact Assessment",
        "parking": "Parking Strategy",
        "master plan": "Master Plan",
        "land use": "Land Use Study",
        "urban design": "Urban Design Report",
        "road safety": "Road Safety Audit",
        "infrastructure": "Infrastructure Assessment",
    }

    for keyword, name in report_keywords.items():
        if keyword in conversation_text:
            report_type = name
            break

    parts.append(f"# Requested Report Type\n\n{report_type}")

    if outline:
        parts.append(f"## Custom Report Outline / Guidelines\n{outline}")

    if workspace:
        # Include an index of available files in the workspace for discovery
        try:
            ws_dir = Path(workspace)
            if ws_dir.exists() and ws_dir.is_dir():
                files = [f.name for f in ws_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
                if files:
                    parts.append("## Available Workspace Files\n" + ", ".join(files))
        except Exception:
            pass

    if artifacts and workspace:
        parts.append("## Imported Workspace Artifacts\n")
        for art in artifacts:
            try:
                art_path = Path(workspace) / art
                if art_path.exists() and art_path.is_file():
                    content = art_path.read_text(encoding="utf-8")
                    # Safe truncation for token optimization
                    if len(content) > 10000:
                        content = content[:10000] + "\n... [TRUNCATED] ..."
                    parts.append(f"### File: {art}\n```\n{content}\n```")
            except Exception as e:
                parts.append(f"### File: {art}\nError reading file: {e}")

    if map_context:
        center = map_context.get("center", [])
        zoom = map_context.get("zoom", "")
        bounds = map_context.get("bounds", {})
        basemap = map_context.get("basemap", "")
        bookmarks = map_context.get("bookmarks", [])
        layers = map_context.get("layers", [])

        loc_lines = [f"**Center:** {center}", f"**Zoom:** {zoom}", f"**Basemap:** {basemap}"]
        if bounds:
            loc_lines.append(
                f"**Bounds:** W={bounds.get('west')}, S={bounds.get('south')}, "
                f"E={bounds.get('east')}, N={bounds.get('north')}"
            )
        parts.append("## Map Context\n" + "\n".join(loc_lines))

        if bookmarks:
            bm_lines = [
                f"- {b.get('name', '')}: bounds W={b.get('west')}, S={b.get('south')}, "
                f"E={b.get('east')}, N={b.get('north')}"
                for b in bookmarks
            ]
            parts.append("### Bookmarks\n" + "\n".join(bm_lines))

        if layers:
            layer_lines = []
            for layer in layers:
                name = layer.get("name", "unnamed")
                count = layer.get("featureCount", 0)
                geom_types = ", ".join(layer.get("geometryTypes", []))
                props = ", ".join(layer.get("properties", []))
                visible = layer.get("visible", True)
                line = f"- **{name}** ({count} features, {geom_types}, visible={visible})"
                if props:
                    line += f"\n  Properties: {props}"
                geo = layer.get("geometry_data")
                if geo:
                    if isinstance(geo, list):
                        line += f"\n  Coordinates: {json.dumps(geo)}"
                    elif isinstance(geo, dict) and "bbox" in geo:
                        line += f"\n  Bounding box: {geo['bbox']}"
                layer_lines.append(line)
            parts.append("### Layers\n" + "\n".join(layer_lines))

    # Include conversation (skip system and tool messages)
    conv_lines = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "user" and isinstance(content, str) and content.strip():
            conv_lines.append(f"**User:** {content}")
        elif role == "assistant" and isinstance(content, str) and content.strip():
            conv_lines.append(f"**Assistant:** {content}")
    if conv_lines:
        parts.append("## Conversation\n" + "\n\n".join(conv_lines))

    return "\n\n".join(parts)


async def _run_deep_research(
    messages: list[dict],
    map_context: dict | None,
    ws: WebSocket,
    outline: str | None = None,
    artifacts: list[str] | None = None,
    workspace: str | None = None,
    client: AsyncOpenAI | None = None
) -> str:
    """Run o4-mini-deep-research and stream progress back over the WebSocket.

    Sends these WS message types:
      research_start          — emitted once before the API call
      research_step           — one per web search (query string)
      research_reasoning_delta — incremental chunk of the model's reasoning summary
      research_text_delta     — incremental chunk of the report as it is written
      research_report         — final markdown text + citations list
      research_done           — terminal signal

    Returns a short result string for the tool message inserted into history.
    """
    await ws.send_text(json.dumps({"type": "research_start"}))

    prompt = _build_research_prompt(messages, map_context, outline=outline, artifacts=artifacts, workspace=workspace)

    def _extract_query(obj) -> str:
        """Pull the search query off a web_search_call item or its action.
        The `searching` event itself carries no query — it rides on the
        output item's `action.query`."""
        if obj is None:
            return ""
        action = getattr(obj, "action", None)
        q = getattr(action, "query", None) if action is not None else None
        return q or getattr(obj, "query", "") or ""

    try:
        got_text = False
        accumulated = ""           # report text assembled from output_text deltas
        seen_queries: set[str] = set()
        search_count = 0
        annotations_list = []      # accumulated streaming citations
        last_heartbeat = asyncio.get_event_loop().time()

        stop_event = _get_stop_event()

        openai_client = client or _client
        stream = await openai_client.responses.create(
            model="o4-mini-deep-research",
            input=prompt,
            instructions=_RESEARCH_SYSTEM,
            tools=[{"type": "web_search_preview"}],
            max_tool_calls=30,
            reasoning={"summary": "auto"},  # emit reasoning_summary deltas
            stream=True,
        )
        async for event in stream:
            if _is_cancelled():
                await ws.send_text(json.dumps({"type": "stopped"}))
                return json.dumps({"status": "cancelled"})

            # Send a heartbeat if >30 s have passed since the last WS message
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat > 30:
                try:
                    await ws.send_text(json.dumps({"type": "research_heartbeat"}))
                except Exception:
                    pass
                last_heartbeat = now

            event_type = getattr(event, "type", None)

            # A web_search_call item appears. The query is often absent in the
            # stream for this model, so emit a step regardless — using the query
            # text when present, a generic label otherwise.
            if event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item is not None and getattr(item, "type", None) == "web_search_call":
                    search_count += 1
                    query = _extract_query(item)
                    await ws.send_text(json.dumps({
                        "type": "research_step",
                        "query": query or f"web search #{search_count}",
                    }))
                    last_heartbeat = asyncio.get_event_loop().time()

            # Fallback: only fires if the item-added path didn't (older streams).
            elif event_type == "response.web_search_call.searching":
                query = _extract_query(event)
                if query and query not in seen_queries:
                    seen_queries.add(query)
                    search_count += 1
                    await ws.send_text(json.dumps({
                        "type": "research_step", "query": query,
                    }))
                    last_heartbeat = asyncio.get_event_loop().time()

            # The model's reasoning summary, streamed token-by-token.
            elif event_type == "response.reasoning_summary_text.delta":
                delta = getattr(event, "delta", "") or ""
                if delta:
                    await ws.send_text(json.dumps({
                        "type": "research_reasoning_delta", "delta": delta,
                    }))
                    last_heartbeat = asyncio.get_event_loop().time()

            # The report itself, streamed token-by-token.
            elif event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "") or ""
                if delta:
                    accumulated += delta
                    got_text = True
                    await ws.send_text(json.dumps({
                        "type": "research_text_delta", "delta": delta,
                    }))
                    last_heartbeat = asyncio.get_event_loop().time()

            # Intercept streaming annotations / web citations
            elif event_type and event_type.startswith("response.output_text.annotation"):
                annotation = getattr(event, "annotation", None)
                if annotation:
                    url = None
                    title = None
                    try:
                        url = getattr(annotation, "url", None)
                        title = getattr(annotation, "title", None)
                        if not url and hasattr(annotation, "url_citation"):
                            uc = getattr(annotation, "url_citation", None)
                            if uc:
                                url = getattr(uc, "url", None)
                                title = getattr(uc, "title", None)
                    except Exception:
                        pass
                    if not url and isinstance(annotation, dict):
                        url = annotation.get("url")
                        title = annotation.get("title")
                        if not url and "url_citation" in annotation:
                            uc = annotation["url_citation"]
                            if isinstance(uc, dict):
                                url = uc.get("url")
                                title = uc.get("title")
                    if url and url not in [a["url"] for a in annotations_list]:
                        annotations_list.append({"url": url, "title": title or url})

            # Final text for a content part — capture annotations (citations)
            # and the authoritative full text.
            elif event_type == "response.output_text.done":
                text = getattr(event, "text", None) or getattr(event, "output_text", None) or ""
                if text:
                    accumulated = text
                got_text = got_text or bool(text)
                
                # Also pull any final annotations out of this done event
                for item in getattr(event, "annotations", None) or []:
                    url = None
                    title = None
                    try:
                        url = getattr(item, "url", None)
                        title = getattr(item, "title", None)
                        if not url and hasattr(item, "url_citation"):
                            uc = getattr(item, "url_citation", None)
                            if uc:
                                url = getattr(uc, "url", None)
                                title = getattr(uc, "title", None)
                    except Exception:
                        pass
                    if not url and isinstance(item, dict):
                        url = item.get("url")
                        title = item.get("title")
                        if not url and "url_citation" in item:
                            uc = item["url_citation"]
                            if isinstance(uc, dict):
                                url = uc.get("url")
                                title = uc.get("title")
                    if url and url not in [a["url"] for a in annotations_list]:
                        annotations_list.append({"url": url, "title": title or url})

                await ws.send_text(json.dumps({
                    "type": "research_report",
                    "markdown": accumulated,
                    "citations": annotations_list,
                }))
                last_heartbeat = asyncio.get_event_loop().time()

        # If the stream ended without an output_text.done (e.g. only deltas),
        # still deliver whatever we accumulated as the final report.
        if got_text and accumulated:
            await ws.send_text(json.dumps({
                "type": "research_report",
                "markdown": accumulated,
                "citations": annotations_list,
            }))

        if not got_text:
            await ws.send_text(json.dumps({
                "type": "error",
                "code": "research_empty",
                "message": "Deep research completed but produced no report text.",
            }))
            return json.dumps({"error": "No report text produced."})

        await ws.send_text(json.dumps({"type": "research_done"}))
        return json.dumps({"status": "report_generated"})

    except Exception as exc:
        await ws.send_text(json.dumps({
            "type": "error",
            "code": "research_error",
            "message": str(exc),
        }))
        return json.dumps({"error": str(exc)})


# ── Build OpenAI tool definitions ─────────────────────────────────────────────

def _decl_to_openai(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def _build_tools() -> list[dict]:
    tools = []

    # Action tools
    action_defs = [
        ("fly_to", "Animate the map to specific coordinates", {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lng": {"type": "number"},
                "zoom": {"type": "number", "description": "Zoom level 1-20, default 15"},
            },
            "required": ["lat", "lng"],
        }),
        ("fit_bounds", "Fit the map view to a bounding box", {
            "type": "object",
            "properties": {
                "south": {"type": "number"}, "west": {"type": "number"},
                "north": {"type": "number"}, "east": {"type": "number"},
            },
            "required": ["south", "west", "north", "east"],
        }),
        ("add_marker", "Add a labeled marker pin on the map. Pass a description to show extra info in a popup when the user hovers the pin.", {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lng": {"type": "number"},
                "label": {"type": "string"}, "color": {"type": "string"},
                "description": {"type": "string", "description": "Optional details shown in a popup on hover"},
            },
            "required": ["lat", "lng", "label"],
        }),
        ("add_markers", "Add multiple markers at once. The app displays them as separate marker layers inside one layer group. Each marker may include a description shown in a popup on hover.", {
            "type": "object",
            "properties": {
                "markers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"}, "lng": {"type": "number"},
                            "label": {"type": "string"}, "color": {"type": "string"},
                            "description": {"type": "string", "description": "Optional details shown in a popup on hover"},
                        },
                        "required": ["lat", "lng", "label"],
                    },
                },
            },
            "required": ["markers"],
        }),
        ("clear_markers", "Remove all AI-placed markers from the map", {
            "type": "object", "properties": {},
        }),
        ("add_geojson", "Add GeoJSON to the map. FeatureCollections with multiple Point features are displayed as separate layers inside one group.", {
            "type": "object",
            "properties": {
                "geojson": {"type": "object", "description": "A GeoJSON FeatureCollection"},
                "name": {"type": "string"}, "color": {"type": "string"},
            },
            "required": ["geojson", "name"],
        }),
        ("highlight_features", "Highlight features in a loaded layer by a property value", {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"},
                "property_name": {"type": "string"},
                "property_value": {"type": "string"},
            },
            "required": ["layer_name", "property_name", "property_value"],
        }),
        ("set_layer_style", "Apply ONE flat fill/line color to an entire layer", {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"}, "fill_color": {"type": "string"},
                "line_color": {"type": "string"}, "opacity": {"type": "number"},
            },
            "required": ["layer_name"],
        }),
        ("style_layer", (
            "Apply DATA-DRIVEN symbology to a loaded layer: categorized colors by a "
            "string property (e.g. zone_code, route_name), graduated/choropleth colors "
            "by a numeric property (e.g. population, density), and/or text labels drawn "
            "from a property. The frontend computes the class breaks and category "
            "palette — you only pass mode, property, and optionally ramp/classes. "
            "Prefer this over set_layer_style whenever the user wants to color BY a "
            "property or show labels."
        ), {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["simple", "categorized", "graduated"],
                    "description": "categorized=color by string property; graduated=choropleth by numeric property; simple=clear data-driven styling.",
                },
                "property": {"type": "string", "description": "Feature property to drive color. Required for categorized/graduated."},
                "classification": {
                    "type": "string",
                    "enum": ["equal-interval", "quantile"],
                    "description": "Graduated only. Default quantile.",
                },
                "classes": {"type": "number", "description": "Graduated bucket count (2-9, default 5)."},
                "ramp": {"type": "string", "description": "Color ramp name: YlOrRd, Blues, Greens, Purples, Reds (graduated) or category (categorized)."},
                "categories": {
                    "type": "array",
                    "description": "Optional explicit value->color overrides for categorized mode.",
                    "items": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}, "color": {"type": "string"}},
                        "required": ["value", "color"],
                    },
                },
                "opacity": {"type": "number"},
                "label_property": {"type": "string", "description": "Property to draw as on-map text. Omit to leave labels unchanged."},
                "label_enabled": {"type": "boolean", "description": "Turn labels on/off."},
                "label_size": {"type": "number"},
                "label_color": {"type": "string"},
            },
            "required": ["layer_name", "mode"],
        }),
        ("toggle_layer", "Show or hide a map layer", {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"}, "visible": {"type": "boolean"},
            },
            "required": ["layer_name", "visible"],
        }),
        ("remove_layer", "Remove a layer from the map entirely", {
            "type": "object",
            "properties": {"layer_name": {"type": "string"}},
            "required": ["layer_name"],
        }),
        ("save_bookmark", "Save the current map region as a named bookmark", {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "south": {"type": "number"}, "west": {"type": "number"},
                "north": {"type": "number"}, "east": {"type": "number"},
                "zoom": {"type": "number"},
            },
            "required": ["name"],
        }),
        ("go_to_bookmark", "Fly the map to a previously saved bookmark by name", {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }),
        ("export_region_clip", "Clip all loaded layers to a bounding box and save as a GeoJSON file in workspace", {
            "type": "object",
            "properties": {
                "output_base_name": {"type": "string"},
                "south": {"type": "number"}, "west": {"type": "number"},
                "north": {"type": "number"}, "east": {"type": "number"},
            },
            "required": ["output_base_name"],
        }),
        ("export_map_png", "Export and download the current composed map figure as a publication-ready high-resolution PNG image (with title block, scale bar, legend, and north arrow). Also optionally saves it into the Artifacts panel.", {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Optional title for the exported map figure"},
                "save_to_artifacts": {"type": "boolean", "description": "If true, saves as an image artifact in the Artifacts tab instead of triggering a direct browser download"},
            },
        }),
        ("export_map_jpeg", "Export and download the current composed map figure as a JPEG image (with title block, scale bar, legend, and north arrow). Also optionally saves it into the Artifacts panel.", {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Optional title for the exported map figure"},
                "save_to_artifacts": {"type": "boolean", "description": "If true, saves as a JPG/JPEG artifact in the Artifacts tab instead of triggering a direct browser download"},
            },
        }),
        ("export_map_pdf", "Export and download the current composed map figure as a landscape A4 PDF report figure (with title block, scale bar, legend, and north arrow). Also optionally saves it into the Artifacts panel.", {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Optional title for the exported map figure"},
                "save_to_artifacts": {"type": "boolean", "description": "If true, saves as a PDF artifact in the Artifacts tab instead of triggering a direct browser download"},
            },
        }),
        ("switch_basemap", "Switch the map's background basemap (street, satellite, dark, light, terrain, topo, humanitarian)", {
            "type": "object",
            "properties": {
                "basemap": {
                    "type": "string",
                    "enum": ["street", "satellite", "dark", "light", "terrain", "topo", "humanitarian"],
                    "description": "Name of the basemap to switch to"
                }
            },
            "required": ["basemap"],
        }),
    ]
    for name, desc, params in action_defs:
        tools.append(_decl_to_openai(name, desc, params))

    # Domain Hub tools (Spatial, Mobility, Environment, Planning, Demographics, Places, Scenarios, Utility)
    for hub in _hubs.values():
        for decl in hub.get_declarations():
            tools.append(decl)

    # Deep research report generation
    tools.append(_decl_to_openai(
        "generate_report",
        (
            "Generate a comprehensive urban planning research report for the current project. "
            "Use this when the user asks to generate a report, create a report, write a planning report, "
            "or produce a deep research analysis. The report uses web search to enrich the analysis "
            "with current public data. This takes several minutes."
        ),
        {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Absolute path to the active workspace folder."
                },
                "outline": {
                    "type": "string",
                    "description": "Specific structured outline or guidelines to follow for the report (parsed from the user's instructions)."
                },
                "artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of workspace filenames/paths (e.g. ['zoning.geojson', 'mobility_plan.md']) representing existing files to load and incorporate."
                }
            },
            "required": ["workspace"]
        },
    ))

    return tools


_TOOLS = _build_tools()

# ── Tool execution ────────────────────────────────────────────────────────────

async def _execute_tool(
    name: str,
    args: dict,
    ws: WebSocket,
    messages: list[dict] | None = None,
    map_context: dict | None = None,
    client: AsyncOpenAI | None = None,
    active_image: dict | None = None,
) -> str:
    if _is_cancelled():
        return json.dumps({"status": "cancelled"})

    # 1. Sync live map layers to SpatialRegistry for real-time reactivity
    if map_context and "layers" in map_context:
        spatial_registry.sync_from_map_layers(map_context.get("layers"))

    # 2. Deep research report generation
    if name == "generate_report":
        return await _run_deep_research(
            messages=messages or [],
            map_context=map_context,
            ws=ws,
            outline=args.get("outline"),
            artifacts=args.get("artifacts"),
            workspace=args.get("workspace"),
            client=client
        )

    # 3a. create_artifact interceptor — enforce map-export-before-document contract
    #
    # If the AI calls create_artifact for a docx/pdf but the content references
    # images that need to be generated (marked as map_snapshot, placeholder, or
    # no real artifacts_store path), BLOCK and return an instruction to export first.
    # This covers the case where the model calls exports in a prior round but then
    # creates the doc without the real paths — or skips exports entirely.
    if name == "create_artifact":
        fmt = args.get("format", "markdown")
        content = args.get("content", "")
        if fmt in ("docx", "pdf", "html") and content:
            import re as _re
            # Detect if content asks for maps/images but only has placeholder refs
            _has_real_path = bool(_re.search(r'artifacts_store/\d+\.(jpg|jpeg|png|pdf)', content, _re.IGNORECASE))
            _has_placeholder = bool(_re.search(
                r'!\[[^\]]*\]\((map_snapshot|placeholder[^)]*|image_here[^)]*|#[^)]*|\.\.\.)\)',
                content, _re.IGNORECASE
            ))
            # Detect if the request MENTIONS map/image content but has NO embedded images at all
            _has_image_syntax = bool(_re.search(r'!\[', content))
            _mentions_map = bool(_re.search(
                r'\b(map|image|figure|boundary|tricity|chandigarh|panchkula|mohali|chart|pie|plot)\b',
                content, _re.IGNORECASE
            ))
            # Count how many distinct export_map calls appear in the current message history
            _recent_exports: list[dict] = []
            if messages:
                for _m in reversed(messages[-30:]):
                    if _m.get("role") == "tool":
                        try:
                            _r = json.loads(_m.get("content", "{}"))
                            if isinstance(_r, dict) and _r.get("file_path", "").startswith("artifacts_store/") and \
                               _r.get("format") in ("jpg", "jpeg", "png"):
                                _recent_exports.append(_r)
                        except Exception:
                            pass

            # If content has placeholder refs → model is hallucinating paths
            if _has_placeholder:
                missing_exports = []
                # Extract what images are referenced in the content
                for _m in _re.findall(r'!\[([^\]]+)\]\([^)]+\)', content):
                    missing_exports.append(_m)
                return json.dumps({
                    "status": "blocked",
                    "error": "PIPELINE VIOLATION: create_artifact was called with placeholder image references. You MUST call export_map_jpeg(save_to_artifacts=True) for EACH required map view FIRST, then call create_artifact with the real artifact_store/ID.jpg paths.",
                    "required_action": (
                        "1. For each required map view (Tricity merged, Chandigarh, Panchkula, Mohali), call:\n"
                        "   a. osm_boundary or osm_boundary_union to fetch the boundary\n"
                        "   b. fit_bounds to frame the view\n"
                        "   c. export_map_jpeg(title='<name>', save_to_artifacts=True) → note the returned file_path\n"
                        "2. For any charts: call create_plot(...) → note the returned file_path\n"
                        "3. THEN call create_artifact with the full document content using the REAL paths returned above.\n"
                        "   Example: ![Tricity Area](artifacts_store/42.jpg)"
                    ),
                    "placeholder_refs_found": missing_exports,
                })

            # If content mentions maps but has no image syntax at all → model skipped exports
            if _mentions_map and not _has_image_syntax and fmt == "docx":
                return json.dumps({
                    "status": "blocked",
                    "error": "PIPELINE VIOLATION: You are creating a Word document that should include map images, but no image references (![...](artifacts_store/...)) were found in the content. You must export the required map views first.",
                    "required_action": (
                        "For each required map view, call export_map_jpeg(title='...', save_to_artifacts=True) first, "
                        "then embed the returned file_path as ![Caption](artifacts_store/ID.jpg) in the document content, "
                        "then call create_artifact."
                    ),
                })

    # 3b. Map export tools with automatic artifact reservation

    if name in ("export_map_png", "export_map_jpeg", "export_map_pdf"):
        save_to_art = args.get("save_to_artifacts", True)
        title = args.get("title") or "Map Export"
        fmt = "jpg" if name == "export_map_jpeg" else ("png" if name == "export_map_png" else "pdf")
        workspace = map_context.get("workspace") if map_context else None

        if save_to_art:
            from tools.artifact_store import save_artifact as _save_artifact
            art_row = _save_artifact(
                title=title,
                artifact_type="sketch",
                format=fmt,
                content="",
                workspace=workspace,
            )
            art_id = art_row["id"]
            file_path_rel = art_row.get("file_path") or f"artifacts_store/{art_id}.{fmt}"

            args_with_id = {**args, "title": title, "artifact_id": art_id, "save_to_artifacts": True}
            if not await _send_action_if_allowed(ws, name, args_with_id):
                return json.dumps({"status": "cancelled"})

            await _send_action_if_allowed(ws, "refresh_artifacts", {"id": art_id})

            return json.dumps({
                "status": "success",
                "artifact_id": art_id,
                "file_path": file_path_rel,
                "title": title,
                "format": fmt,
                "message": f"Exported map figure '{title}' (Artifact ID: {art_id}, Path: {file_path_rel}). Reference in markdown documents using: ![{title}]({file_path_rel})",
            })
        else:
            if not await _send_action_if_allowed(ws, name, args):
                return json.dumps({"status": "cancelled"})
            return json.dumps({"status": "success", "message": f"'{name}' triggered download on map."})

    # 4. Map action tools (send directly to frontend)
    if name in _ACTION_TOOLS:
        if name == "draw_polygon":
            coords = args.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 3:
                ring = list(coords)
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                geom = {"type": "Polygon", "coordinates": [ring]}
                label = args.get("label") or "Drawn Polygon"
                reg_res = spatial_registry.register_or_get(
                    name=label,
                    geometry=geom,
                    source="ai_draw",
                    properties={"color": args.get("color")},
                )
                if reg_res["is_duplicate"]:
                    # Highlight existing layer and notify model
                    await _send_action_if_allowed(ws, "highlight_features", {"layer_name": reg_res["layer_name"]})
                    poly_data = reg_res["polygon"]
                    return json.dumps({
                        "status": "success",
                        "reused_existing": True,
                        "layer_name": reg_res["layer_name"],
                        "message": f"Polygon '{label}' matches existing layer '{reg_res['layer_name']}' ({reg_res['match_reason']}). Focused existing layer.",
                        "area_km2": poly_data.get("area_km2"),
                        "area_hectares": poly_data.get("area_hectares"),
                        "centroid": poly_data.get("centroid"),
                        "bbox": poly_data.get("bbox"),
                    })

        if not await _send_action_if_allowed(ws, name, args):
            return json.dumps({"status": "cancelled"})
        return json.dumps({"status": "success", "message": f"'{name}' executed on map."})

    # 4. Domain Hub tools (Spatial, Mobility, Environment, Planning, Demographics, Places, Scenarios, Utility)
    target_hub = next((h for h in _hubs.values() if name in h.tool_names), None)
    if target_hub:
        if _is_cancelled():
            return json.dumps({"status": "cancelled"})
        logger.debug(f"execute_tool hub={target_hub.name} name={name!r} args={args}")
        try:
            result: ToolResult = await target_hub.execute(
                name,
                args,
                {"_map_context": map_context, "_ws": ws, "_active_image": active_image, "_client": client},
            )
        except Exception as exc:
            logger.exception(f"Tool '{name}' failed in hub '{target_hub.name}'")
            return json.dumps({"status": "error", "error": f"Tool '{name}' failed with internal error: {str(exc)}"})

        # Auto-send map action if declared
        if result.map_action:
            if not await _send_action_if_allowed(ws, result.map_action["action"], result.map_action.get("payload", {})):
                return json.dumps({"status": "cancelled"})

        # Auto-save artifact if declared
        if result.artifact:
            try:
                from tools.artifact_store import save_artifact as _save_artifact
                _save_artifact(
                    title=result.artifact.get("title", "Report"),
                    artifact_type=result.artifact.get("artifact_type", "report"),
                    format=result.artifact.get("format", "markdown"),
                    content=result.artifact.get("content", ""),
                    workspace=map_context.get("workspace") if map_context else None,
                )
                await _send_action_if_allowed(ws, "refresh_artifacts", {})
            except Exception as _ae:
                logger.warning(f"Failed to auto-save artifact for tool '{name}': {_ae}")

        # Auto-refresh artifacts on frontend when an artifact or plot tool executes
        if name in ("create_artifact", "edit_artifact", "create_plot", "save_artifact"):
            try:
                res_dict = json.loads(result.to_json()) if hasattr(result, "to_json") else (result if isinstance(result, dict) else json.loads(str(result)))
                created_id = res_dict.get("id") or (res_dict.get("artifact", {}).get("id") if isinstance(res_dict.get("artifact"), dict) else None)
                await _send_action_if_allowed(ws, "refresh_artifacts", {"id": created_id} if created_id else {})
            except Exception:
                await _send_action_if_allowed(ws, "refresh_artifacts", {})

        return result.to_json()

    return json.dumps({"error": f"Unknown tool: {name}"})


# ── Agentic loop ──────────────────────────────────────────────────────────────

async def _run_agent(
    messages: list[dict],
    ws: WebSocket,
    client: AsyncOpenAI,
    tools: list[dict] | None = None,
    map_context: dict | None = None,
    active_image: dict | None = None,
) -> None:
    """Run the tool-calling loop until the model stops calling tools or errors."""
    if tools is None:
        tools = _TOOLS
    max_rounds = 35  # Complex pipelines (4 boundaries + 4 exports + chart + doc) need many rounds

    for _ in range(max_rounds):
        if _is_cancelled():
            raise asyncio.CancelledError()

        accumulated_text = ""
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = None
        assistant_msg_created = False

        try:
            stream = await client.chat.completions.create(
                model=_get_model(),
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                stream=True,
                timeout=60,
            )

            async for chunk in stream:
                if _is_cancelled():
                    raise asyncio.CancelledError()

                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue

                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason

                # Stream text to frontend
                if delta.content:
                    accumulated_text += delta.content
                    await ws.send_text(json.dumps({"type": "stream", "content": delta.content}))

                # Accumulate tool call deltas
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc.function.arguments

            # Add assistant message to history
            assistant_msg: dict = {"role": "assistant"}
            if accumulated_text:
                assistant_msg["content"] = accumulated_text
            else:
                assistant_msg["content"] = None
            if tool_calls_acc:
                assistant_msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls_acc.values()
                ]
            messages.append(assistant_msg)
            assistant_msg_created = True

            # If no tool calls, we're done. Tool calls MUST be answered even if
            # finish_reason == "stop" — leaving them unanswered breaks the next turn.
            if not tool_calls_acc:
                # ── Hallucination Detector ─────────────────────────────────────────
                # If the model generated chat text CLAIMING an artifact was saved
                # (e.g. "I created the Word document ... artifacts_store/32.docx")
                # WITHOUT actually calling create_artifact as a tool — it hallucinated.
                # 
                # OLD behaviour (REMOVED): auto-create a garbage document from the chat text.
                #   → This produced documents containing only the AI's chat response text,
                #     not the actual maps/charts the user requested.
                #
                # NEW behaviour: detect the hallucination and inject a correction message
                #   that forces the AI to perform the real tool calls in the next round.
                if accumulated_text:
                    import re as _re_hall
                    _art_claim = _re_hall.search(
                        r'artifacts_store/\d+\.(docx|pdf|html|xlsx|md|txt)',
                        accumulated_text, _re_hall.IGNORECASE
                    )
                    # Check if create_artifact / edit_artifact was ACTUALLY called and succeeded
                    # in the current turn (search only recent tool messages from this round)
                    _really_created = False
                    for _m in reversed(messages):
                        role = _m.get("role")
                        # Stop scanning when we hit the last user message (start of this turn)
                        if role == "user":
                            break
                        if role == "tool":
                            _tc = _m.get("content", "")
                            # create_artifact returns {"status": "created", "id": N, "format": "docx", ...}
                            # edit_artifact returns {"status": "updated", "id": N, ...}
                            if (
                                ('"status": "created"' in _tc or '"status": "updated"' in _tc)
                                and '"format"' in _tc
                                and '"id"' in _tc
                            ):
                                _really_created = True
                                break

                    if _art_claim and not _really_created:
                        logger.warning(
                            "[Hallucination Detected] Model claimed artifact was saved but "
                            "did not call create_artifact. Injecting correction message."
                        )
                        # Inject a system correction into the message history so the next
                        # loop iteration forces the model to actually call the tools.
                        messages.append({
                            "role": "user",
                            "content": (
                                "[SYSTEM CORRECTION] You claimed to have created a document "
                                f"('{_art_claim.group(0)}') but you did NOT call the "
                                "`create_artifact` tool. No document was actually saved. "
                                "You MUST now follow the sequential pipeline:\n"
                                "1. Call osm_boundary_union / osm_boundary + fit_bounds to load the correct boundary\n"
                                "2. Call export_map_jpeg(title='...', save_to_artifacts=True) for EACH required map view\n"
                                "3. Call create_plot(...) for any charts\n"
                                "4. THEN call create_artifact with the real artifact paths returned by the above tools.\n"
                                "Start NOW — do NOT respond with text first. Call the tools immediately."
                            ),
                        })
                        # Do NOT break — continue the loop to give the model a chance to fix itself
                        continue



                break

            # ── Pipeline Orchestrator (Heap + Queue) ────────────────────────────
            # When the model requests BOTH asset generation (map exports, plots)
            # AND document compilation (create_artifact) in the same turn, we MUST
            # run asset tools FIRST so their real file paths exist before the Word/PDF
            # is compiled.  This is the "queue drains before heap is closed" contract.

            tc_list = list(tool_calls_acc.values())

            # Strip stale artifact IDs so create_artifact always creates fresh docs
            if _PIPELINE_AVAILABLE:
                tc_list = inject_new_artifact_instruction(tc_list)

            use_pipeline = _PIPELINE_AVAILABLE and needs_pipeline(tc_list)

            if use_pipeline:
                asset_calls, document_calls = classify_tool_calls(tc_list)
                ordered_calls = asset_calls + document_calls
                logger.info(
                    f"[Pipeline] Queue phase: {[t['name'] for t in asset_calls]} "
                    f"| Heap phase: {[t['name'] for t in document_calls]}"
                )
            else:
                ordered_calls = tc_list

            # Collect asset results so we can patch document content
            asset_results: dict[str, dict] = {}
            asset_phase_done = False if use_pipeline else True

            for tc in ordered_calls:
                if _is_cancelled():
                    raise asyncio.CancelledError()

                tool_name = tc["name"]
                args_raw = tc.get("arguments") or ""
                try:
                    args = json.loads(args_raw) if args_raw else {}
                    args_error = None
                except json.JSONDecodeError as e:
                    args = {}
                    args_error = str(e)

                # When transitioning from asset phase to document phase, patch content
                if use_pipeline and not asset_phase_done and tool_name in ("create_artifact", "edit_artifact"):
                    asset_phase_done = True
                    if asset_results and args.get("content"):
                        patched = patch_content_with_real_paths(args["content"], asset_results)
                        if patched != args["content"]:
                            logger.info(f"[Pipeline] Patched {len(asset_results)} asset path(s) into document content")
                            args["content"] = patched
                            tc = {**tc, "arguments": json.dumps(args)}

                await ws.send_text(json.dumps({"type": "tool_use", "tool": tool_name, "args": args}))

                if args_error:
                    # Streaming was interrupted; return a structured error so the
                    # tool_call_id has a matching tool message and the next turn
                    # is well-formed.
                    result_str = json.dumps({
                        "error": "Arguments could not be parsed; streaming was interrupted.",
                        "detail": args_error,
                    })
                else:
                    result_str = await _execute_tool(tool_name, args, ws, messages=messages, map_context=map_context, client=client, active_image=active_image)

                # Record asset tool results for path patching
                if use_pipeline and tool_name in ("export_map_png", "export_map_jpeg", "export_map_pdf", "create_plot"):
                    try:
                        asset_results[tc["id"]] = json.loads(result_str)
                    except Exception:
                        pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

        except asyncio.CancelledError:
            # Handle task cancellation
            if not assistant_msg_created:
                if accumulated_text:
                    messages.append({"role": "assistant", "content": accumulated_text})
            else:
                # The assistant message is already in messages. Ensure all tool calls are answered.
                existing_tool_ids = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
                for tc in tool_calls_acc.values():
                    if tc.get("id") and tc["id"] not in existing_tool_ids:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({"status": "cancelled", "message": "Tool execution was cancelled by user."})
                        })
            raise
        except Exception as e:
            await ws.send_text(json.dumps({
                "type": "error",
                "code": _classify_error(e),
                "message": str(e),
            }))
            break


class ValidateKeyRequest(BaseModel):
    api_key: str

@router.post("/validate-key")
async def validate_key(req: ValidateKeyRequest):
    try:
        if not req.api_key or not req.api_key.strip():
            return {"valid": False, "error": "API Key is empty."}
        # Lightweight check to validate key
        temp_client = AsyncOpenAI(api_key=req.api_key.strip())
        await temp_client.models.list()
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@router.get("/key-status")
async def key_status():
    return {
        "openai": bool(_env_openai_api_key()),
        "google_maps": bool(_env_google_maps_api_key()),
    }


# ── WebSocket handler ─────────────────────────────────────────────────────────

@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()

    # Persistent message history for this connection
    messages: list[dict] = []
    stop_event: asyncio.Event | None = None
    active_task: asyncio.Task | None = None
    current_full_messages: list[dict] | None = None

    try:
        while True:
            if active_task is not None and not active_task.done():
                receive_task = asyncio.create_task(websocket.receive_text())
                done, pending = await asyncio.wait({active_task, receive_task}, return_when=asyncio.FIRST_COMPLETED)

                if active_task in done:
                    for p in pending:
                        p.cancel()
                    try:
                        await active_task
                    except (Exception, asyncio.CancelledError):
                        pass
                    active_task = None
                    if current_full_messages is not None:
                        new_history = []
                        for m in current_full_messages:
                            if m.get("role") == "system":
                                continue
                            if isinstance(m.get("content"), list):
                                # Strip image parts from stored history to save memory
                                text_parts = [p["text"] for p in m["content"] if p.get("type") == "text"]
                                new_history.append({"role": m["role"], "content": " ".join(text_parts)})
                            else:
                                new_history.append(m)
                        messages = new_history
                    current_full_messages = None
                    await websocket.send_text(json.dumps({"type": "end"}))
                    continue

                if receive_task in done:
                    for p in pending:
                        if p is not active_task:
                            p.cancel()
                    try:
                        data = receive_task.result()
                    except Exception:
                        data = None
                    if data is None:
                        continue
                    payload = json.loads(data)
                else:
                    continue
            else:
                data = await websocket.receive_text()
                payload = json.loads(data)

            if payload.get("type") == "stop":
                if stop_event is not None:
                    stop_event.set()
                if active_task and not active_task.done():
                    active_task.cancel()
                    try:
                        await active_task
                    except (Exception, asyncio.CancelledError):
                        pass
                    active_task = None
                await websocket.send_text(json.dumps({"type": "stopped"}))
                continue

            if payload.get("type") == "reset_history":
                messages = []
                continue

            if payload.get("type") == "question_response":
                from tools.utility import register_question_response
                register_question_response(websocket, payload.get("response"))
                continue

            if active_task is not None and not active_task.done():
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "code": "busy",
                    "message": "Another request is already running. Please wait or stop the current run first.",
                }))
                continue

            user_content = payload.get("content", "")
            map_context = payload.get("map_context")
            image_data = payload.get("image")  # {base64, mime_type} or None
            chat_attachments = payload.get("chat_attachments", [])
            history_payload = payload.get("history")
            api_key = (payload.get("api_key") or "").strip()
            if not api_key:
                api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()

            google_maps_api_key = (payload.get("google_maps_api_key") or "").strip()
            if not google_maps_api_key:
                google_maps_api_key = (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()

            # Set the context-local variable for this WebSocket iteration
            google_maps_key_var.set(google_maps_api_key)

            if not api_key:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "code": "auth",
                    "message": "OpenAI API key is missing. Please configure your API key in the settings panel or set OPENAI_API_KEY in your .env file."
                }))
                await websocket.send_text(json.dumps({"type": "end"}))
                continue

            client = AsyncOpenAI(api_key=api_key)

            if not user_content.strip():
                continue

            # Renderer can replay prior conversation on reconnect/model-switch
            # by passing `history`: a list of {role, content} pairs.
            if isinstance(history_payload, list):
                replayed: list[dict] = []
                for m in history_payload:
                    role = m.get("role")
                    content = m.get("content")
                    if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                        replayed.append({"role": role, "content": content})
                messages = replayed

            # Fallback to chat attachments for active_image if none in Document tab
            georef_target_image = image_data
            has_attached_image = False
            for att in chat_attachments:
                mtype = att.get("mime_type", "")
                if att.get("base64") and (mtype.startswith("image/") or "pdf" in mtype):
                    has_attached_image = True
                    if not georef_target_image:
                        georef_target_image = att

            is_document_mode = (image_data is not None) or has_attached_image
            system = f"{SYSTEM_PROMPT}\n\n{DOCUMENT_SYSTEM_PROMPT}" if is_document_mode else SYSTEM_PROMPT

            # Retrieve relevant text segments from RAG index if present
            workspace = map_context.get("workspace") if map_context else None
            if workspace and user_content:
                from routers.rag import query_rag_index_async
                try:
                    matched_chunks = await query_rag_index_async(
                        query=user_content,
                        api_key=api_key,
                        workspace=workspace
                    )
                    if matched_chunks:
                        context_str = "\n\n[CONTEXT FROM WORKSPACE DOCUMENTS]\n"
                        for chunk in matched_chunks:
                            context_str += f"From document '{chunk['docName']}' (Page {chunk['page']}):\n\"\"\"\n{chunk['text']}\n\"\"\"\n---\n"
                        system += context_str
                except Exception as e:
                    print(f"[RAG] Document search error: {e}")

            if map_context:
                system += f"\n\nCurrent map state:\n{json.dumps(map_context, indent=2)}"
                if map_context.get("selected_features"):
                    selected_block = "\n\n[USER SELECTED MAP ELEMENTS / HIGHLIGHTED LAYERS]\n"
                    for sf in map_context["selected_features"]:
                        lname = sf.get("layerName") or sf.get("properties", {}).get("layer_name") or "Selected Map Element"
                        props = sf.get("properties", {})
                        centroid = sf.get("centroid")
                        bbox = sf.get("bbox")
                        fpath = sf.get("filePath")
                        fcount = sf.get("featureCount")

                        selected_block += f"- Selected Element/Layer: {lname}\n"
                        if fpath:
                            selected_block += f"  File Path: {fpath}\n"
                        if fcount:
                            selected_block += f"  Feature Count: {fcount}\n"
                        if centroid:
                            selected_block += f"  Centroid: [lng={centroid[0]}, lat={centroid[1]}]\n"
                        if bbox:
                            selected_block += f"  Bounding Box: [W={bbox[0]}, S={bbox[1]}, E={bbox[2]}, N={bbox[3]}]\n"
                        if props:
                            clean_props = {k: v for k, v in props.items() if v is not None}
                            selected_block += f"  Properties: {json.dumps(clean_props)}\n"
                    user_content += selected_block

            tools = _TOOLS

            # Build unified message content parts for vision model
            content_list: list[dict] = [{"type": "text", "text": user_content}]
            if image_data and image_data.get("base64"):
                content_list.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_data['mime_type']};base64,{image_data['base64']}"
                    }
                })
            for att in chat_attachments:
                if att.get("base64"):
                    content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{att['mime_type']};base64,{att['base64']}"
                        }
                    })

            if len(content_list) > 1:
                user_msg = {"role": "user", "content": content_list}
            else:
                user_msg = {"role": "user", "content": user_content}

            full_messages = [{"role": "system", "content": system}] + messages
            full_messages.append(user_msg)

            stop_event = asyncio.Event()
            _set_stop_event(stop_event)
            current_full_messages = full_messages
            active_task = asyncio.create_task(_run_agent(full_messages, websocket, client, tools=tools, map_context=map_context, active_image=georef_target_image))

    except WebSocketDisconnect:
        if active_task and not active_task.done():
            active_task.cancel()
            try:
                await active_task
            except (Exception, asyncio.CancelledError):
                pass
    except Exception as e:
        if active_task and not active_task.done():
            active_task.cancel()
            try:
                await active_task
            except (Exception, asyncio.CancelledError):
                pass
        try:
            await websocket.send_text(json.dumps({
                "type": "error", "code": _classify_error(e), "message": str(e),
            }))
            await websocket.send_text(json.dumps({"type": "end"}))
        except Exception:
            pass


def _classify_error(e: Exception) -> str:
    """Map an exception to a short error code the UI can style on."""
    msg = str(e).lower()
    name = type(e).__name__
    if "api key" in msg or "openai_api_key" in msg or "401" in msg or name == "AuthenticationError":
        return "auth"
    if "429" in msg or "rate limit" in msg or name == "RateLimitError":
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg or name == "APITimeoutError":
        return "timeout"
    if "connection" in msg or name in ("APIConnectionError", "ConnectionError"):
        return "connection"
    if "404" in msg or "not found" in msg:
        return "not_found"
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return "upstream"
    return "internal"
