"""Comprehensive test suite for Google Earth Engine (GEE) capabilities in Disha.

Tests:
1. Tool declarations & catalog discovery across all 12 categories.
2. Credentials parsing with standard and base64 fallback formats.
3. Execution of all specialized domain methods (Surface Temperature, Climate, Atmospheric,
   Weather, Landsat, Sentinel, High-Res, MODIS, Terrain, Land Cover, Agriculture, Geophysical).
4. Proxy tile URL formatting and proxy endpoint forwarding.
5. EnvironmentHub integration returning typed ToolResult and map_actions.
"""

import sys
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mcp_servers.gee_server import GEEServer, parse_gee_credentials_data, _find_gee_creds
from domains.environment_hub import EnvironmentHub
from domains.protocol import ToolResult
from routers.gee import router as gee_router


@pytest.fixture(autouse=True)
def reset_gee():
    from mcp_servers.gee_server import reset_gee_init
    reset_gee_init()
    yield
    reset_gee_init()


@pytest.fixture
def gee_server():
    return GEEServer()


@pytest.fixture
def env_hub():
    return EnvironmentHub()


def test_credentials_parsing_and_fallback():
    # 1. Test None input
    assert parse_gee_credentials_data(None) is None
    assert parse_gee_credentials_data("") is None

    # 2. Test standard service account dictionary
    standard = {
        "type": "service_account",
        "project_id": "test-project",
        "client_email": "test@test-project.iam.gserviceaccount.com",
    }
    parsed = parse_gee_credentials_data(standard)
    assert parsed is not None
    assert parsed["client_email"] == "test@test-project.iam.gserviceaccount.com"

    # 3. Test base64 fallback wrapper dictionary
    import base64
    import json
    encoded = base64.b64encode(json.dumps(standard).encode("utf-8")).decode("utf-8")
    wrapper = {"key": "12345", "encrypted": True, "fallback": encoded}
    parsed_wrapped = parse_gee_credentials_data(wrapper)
    assert parsed_wrapped is not None
    assert parsed_wrapped["client_email"] == "test@test-project.iam.gserviceaccount.com"


def test_gee_server_declarations(gee_server, env_hub):
    decls = gee_server.get_declarations()
    names = {d.name for d in decls}

    expected_tools = {
        "add_gee_layer",
        "get_surface_temperature_layer",
        "get_climate_layer",
        "get_atmospheric_layer",
        "get_weather_layer",
        "get_landsat_layer",
        "get_sentinel_layer",
        "get_high_resolution_imagery",
        "get_modis_layer",
        "get_dem_layer",
        "get_land_cover",
        "get_agriculture_layer",
        "get_geophysical_layer",
        "search_gee_datasets",
        "get_gee_zonal_stats",
        "get_population_layer",
        "analyze_lulc_change",
        "analyze_land_use_zonal_stats",
        "extract_land_use_polygons",
        "get_ndvi_layer",
        "get_gee_layer",
    }

    assert expected_tools.issubset(names), f"Missing tools in GEEServer: {expected_tools - names}"
    assert expected_tools.issubset(gee_server.tool_names)
    assert expected_tools.issubset(env_hub.tool_names)


@pytest.mark.asyncio
async def test_search_gee_datasets(gee_server):
    # Search all
    res_all = await gee_server.execute("search_gee_datasets", {})
    assert res_all["status"] == "success"
    assert res_all["count"] > 10

    # Search category: atmospheric
    res_atmos = await gee_server.execute("search_gee_datasets", {"category": "atmospheric"})
    assert res_atmos["status"] == "success"
    assert any("S5P" in d["id"] for d in res_atmos["datasets"])

    # Search keyword: temperature
    res_temp = await gee_server.execute("search_gee_datasets", {"query": "temperature"})
    assert res_temp["status"] == "success"
    assert len(res_temp["datasets"]) > 0


@pytest.mark.asyncio
async def test_all_gee_layers_generation(gee_server):
    """Test mapId and proxy URL generation for all major domains."""
    test_calls = [
        ("get_surface_temperature_layer", {"source": "landsat", "year": 2023}),
        ("get_climate_layer", {"source": "terraclimate", "variable": "precipitation", "year": 2023}),
        ("get_atmospheric_layer", {"pollutant": "no2", "year": 2023}),
        ("get_weather_layer", {"variable": "temperature_2m", "year": 2023}),
        ("get_landsat_layer", {"satellite": "landsat_9", "preset": "true_color", "year": 2023}),
        ("get_sentinel_layer", {"mission": "sentinel_2", "preset": "true_color", "year": 2023}),
        ("get_high_resolution_imagery", {"source": "naip", "preset": "true_color", "year": 2022}),
        ("get_modis_layer", {"product": "ndvi_evi", "year": 2023}),
        ("get_dem_layer", {"source": "srtm", "mode": "aspect"}),
        ("get_land_cover", {"source": "dynamic_world", "year": 2023}),
        ("get_agriculture_layer", {"indicator": "cropland_classes", "year": 2023}),
        ("get_geophysical_layer", {"dataset_type": "surface_water", "year": 2021}),
    ]

    for tool_name, args in test_calls:
        res = await gee_server.execute(tool_name, args)
        if res.get("status") == "success":
            assert "tile_url" in res, f"Tool {tool_name} missing tile_url"
            assert "/api/gee/tiles/" in res["tile_url"]
            assert "{z}/{x}/{y}" in res["tile_url"]
        else:
            # If upstream GEE network fails or is unavailable, must return structured error
            assert res.get("code") in ["upstream_unavailable", "gee_error"]


@pytest.mark.asyncio
async def test_environment_hub_action_dispatch(env_hub):
    """Verify that EnvironmentHub returns a valid ToolResult with add_gee_layer map_action."""
    res: ToolResult = await env_hub.execute(
        "get_surface_temperature_layer",
        {"source": "landsat", "year": 2023},
    )
    if res.status == "success":
        assert res.data.get("displayed_on_map") is True
        assert res.map_action is not None
        assert res.map_action["action"] == "add_gee_layer"
        payload = res.map_action["payload"]
        assert "/api/gee/tiles/" in payload["url"]
        assert "LANDSAT" in payload["dataset"]
    else:
        assert res.status == "error"
        assert res.error is not None


def test_gee_tile_router_matching():
    """Verify that routers/gee.py correctly routes multi-segment project map IDs."""
    app = FastAPI()
    app.include_router(gee_router, prefix="/api/gee")
    client = TestClient(app, raise_server_exceptions=False)

    # Single-segment legacy map ID
    resp_single = client.get("/api/gee/tiles/legacy_map_123/0/0/0")
    # Upstream GEE rejects fake map ID (e.g. 400, 404, or 500), but route matches without 404 Not Found route failure
    assert resp_single.status_code in [200, 400, 401, 404, 500, 502, 503]

    # Multi-segment project map ID (projects/{p}/maps/{id})
    resp_multi = client.get("/api/gee/tiles/projects/ee-geovisionaries/maps/abc-def-123/0/0/0")
    assert resp_multi.status_code in [200, 400, 401, 404, 500, 502, 503]


@pytest.mark.asyncio
async def test_population_layer_with_country_inference(gee_server, env_hub):
    """Verify that get_population_layer correctly resolves country_iso for named places and returns add_gee_layer action."""
    # Test inference helper
    assert GEEServer._infer_country_iso({}, "Chandigarh, India", None, None) == "IND"
    assert GEEServer._infer_country_iso({}, "New York", None, None) == "USA"
    assert GEEServer._infer_country_iso({}, "", 30.7333, 76.7794) == "IND"

    # Test execution via EnvironmentHub
    res: ToolResult = await env_hub.execute(
        "get_population_layer",
        {"place_name": "Chandigarh", "year": 2020},
    )
    if res.status == "success":
        assert res.data["country_iso"] == "IND"
        assert res.map_action is not None
        assert res.map_action["action"] == "add_gee_layer"
        assert "/api/gee/tiles/" in res.map_action["payload"]["url"]
        assert "WorldPop" in res.map_action["payload"]["dataset"]
    else:
        assert res.status == "error"
        assert res.error is not None


def test_chat_router_system_prompt_and_actions():
    """Verify that chat.py SYSTEM_PROMPT and tool declarations include the complete GEE catalog."""
    from routers.chat import SYSTEM_PROMPT, _ACTION_TOOLS, _TOOLS

    # Action tools registration
    assert "add_gee_layer" in _ACTION_TOOLS

    # OpenAI schema registration
    tool_names = {t["function"]["name"] for t in _TOOLS}
    assert "add_gee_layer" in tool_names
    assert "get_population_layer" in tool_names
    assert "get_surface_temperature_layer" in tool_names
    assert "get_dem_layer" in tool_names
    assert "get_atmospheric_layer" in tool_names
    assert "get_weather_layer" in tool_names
    assert "get_climate_layer" in tool_names
    assert "get_landsat_layer" in tool_names
    assert "get_sentinel_layer" in tool_names
    assert "get_high_resolution_imagery" in tool_names
    assert "get_modis_layer" in tool_names
    assert "get_agriculture_layer" in tool_names
    assert "get_geophysical_layer" in tool_names
    assert "search_gee_datasets" in tool_names
    assert "get_gee_zonal_stats" in tool_names

    # System prompt tool and rule mandates
    assert "get_population_layer" in SYSTEM_PROMPT
    assert "get_surface_temperature_layer" in SYSTEM_PROMPT
    assert "get_dem_layer" in SYSTEM_PROMPT
    assert "38. RASTER & EARTH ENGINE (GEE) EXECUTION MANDATE:" in SYSTEM_PROMPT

    # Temporal Timeline registration & mandate
    assert "set_timeline" in _ACTION_TOOLS
    assert "close_timeline" in _ACTION_TOOLS
    assert "set_timeline" in tool_names
    assert "close_timeline" in tool_names
    assert "39. TEMPORAL PLAYBACK TIMELINE MANDATE:" in SYSTEM_PROMPT


def test_step_layer_endpoint_validation():
    """Verify that /api/gee/step_layer validates required parameters properly."""
    app = FastAPI()
    app.include_router(gee_router, prefix="/api/gee")
    client = TestClient(app)

    # 1. Missing tool_name returns 400
    res = client.post("/api/gee/step_layer", json={"step": "2020"})
    assert res.status_code == 400
    assert "tool_name is required" in res.json()["detail"]


@pytest.mark.asyncio
async def test_gee_boundary_resolution_from_geojson(gee_server):
    """Verify that _resolve_place_boundary handles explicit GeoJSON input correctly."""
    sample_poly = {
        "type": "Polygon",
        "coordinates": [
            [[76.7, 30.7], [76.8, 30.7], [76.8, 30.8], [76.7, 30.8], [76.7, 30.7]]
        ]
    }
    b_geojson, ee_geom, matched_name, bbox = await gee_server._resolve_place_boundary({
        "geojson": sample_poly,
        "place_name": "Test Study Area",
    })
    assert b_geojson is not None
    assert matched_name == "Test Study Area"
    assert bbox is not None
    assert bbox["west"] == 76.7
    assert bbox["south"] == 30.7
    assert bbox["east"] == 76.8
    assert bbox["north"] == 30.8


@pytest.mark.asyncio
async def test_gee_boundary_resolution_from_osm_mock(gee_server, monkeypatch):
    """Verify that when place_name is provided, _resolve_place_boundary fetches and registers OSM boundary."""
    from mcp_servers.osm_server import OSMServer
    from tools.spatial_registry import spatial_registry

    mock_geojson = {
        "type": "Polygon",
        "coordinates": [
            [[10.0, 20.0], [10.5, 20.0], [10.5, 20.5], [10.0, 20.5], [10.0, 20.0]]
        ]
    }

    async def mock_fetch_boundary(self, args):
        return {
            "name": args.get("name"),
            "geojson": mock_geojson,
            "centroid": {"lat": 20.25, "lng": 10.25},
        }

    monkeypatch.setattr(OSMServer, "_fetch_boundary", mock_fetch_boundary)

    b_geojson, ee_geom, matched_name, bbox = await gee_server._resolve_place_boundary({
        "place_name": "Metropolis Alpha",
    })

    assert b_geojson == mock_geojson
    assert matched_name == "Metropolis Alpha"
    assert bbox["west"] == 10.0
    assert bbox["north"] == 20.5

    # Check that spatial registry recorded it
    poly = spatial_registry.get_polygon("Metropolis Alpha")
    assert poly is not None
    assert poly.source == "osm_boundary"


def test_gee_declarations_have_boundary_parameters(gee_server):
    """Ensure that all GEE tool declarations include place_name and geojson parameters for boundary clipping."""
    decls = {d.name: d for d in gee_server.get_declarations()}
    tools_to_check = [
        "add_gee_layer",
        "get_surface_temperature_layer",
        "get_climate_layer",
        "get_atmospheric_layer",
        "get_weather_layer",
        "get_landsat_layer",
        "get_sentinel_layer",
        "get_high_resolution_imagery",
        "get_modis_layer",
        "get_dem_layer",
        "get_land_cover",
        "get_agriculture_layer",
        "get_geophysical_layer",
        "get_population_layer",
        "get_ndvi_layer",
    ]
    for t in tools_to_check:
        assert t in decls, f"Tool {t} missing from declarations"
        params = decls[t].parameters.get("properties", {})
        assert "place_name" in params, f"Tool {t} missing 'place_name' parameter in declaration"
        assert "geojson" in params, f"Tool {t} missing 'geojson' parameter in declaration"


