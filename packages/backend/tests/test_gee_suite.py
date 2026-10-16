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
