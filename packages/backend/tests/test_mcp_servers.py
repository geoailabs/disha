import sys
import os
import json
import pytest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools.utility import UtilityServer
from mcp_servers.gis_server import GISServer
from mcp_servers.zoning_server import ZoningServer

@pytest.mark.asyncio
async def test_utility_server_declarations_and_math(tmp_path):
    db_file = tmp_path / "test_disha.db"
    server = UtilityServer(db_path=db_file)
    decls = server.get_declarations()
    assert len(decls) > 0
    names = {d.name if hasattr(d, "name") else d["name"] for d in decls}
    assert "measure_distance" in names
    assert "measure_area" in names

    # Functional test: measure_distance between two points
    res = await server.execute("measure_distance", {
        "points": [[-74.0060, 40.7128], [-73.9352, 40.7306]]
    })
    assert "direct" in res
    assert res["direct"]["distance_km"] > 0
    assert res["direct"]["distance_miles"] > 0

@pytest.mark.asyncio
async def test_gis_server_functional():
    server = GISServer()
    
    # Polygon GeoJSON payload
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-74.0060, 40.7128],
                        [-74.0060, 40.7138],
                        [-74.0050, 40.7138],
                        [-74.0050, 40.7128],
                        [-74.0060, 40.7128]
                    ]]
                },
                "properties": {"name": "Test Polygon"}
            }
        ]
    }
    
    res = await server.execute("gis_area", {"geojson": geojson_data})
    assert "error" not in res
    assert "area_sqm" in res or "total_area_sqm" in res or "area_km2" in res or "area_hectares" in res

@pytest.mark.asyncio
async def test_zoning_server_functional():
    server = ZoningServer()
    decls = server.get_declarations()
    assert len(decls) > 0
    
    geojson_zones = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-74.0060, 40.7128],
                        [-74.0060, 40.7138],
                        [-74.0050, 40.7138],
                        [-74.0050, 40.7128],
                        [-74.0060, 40.7128]
                    ]]
                },
                "properties": {"zone_code": "R1", "zone_label": "Residential High Density"}
            }
        ]
    }
    
    # Functional test: analyze zones
    res = await server.execute("analyze_zones", {"geojson": geojson_zones})
    assert "error" not in res
    assert "zones" in res or "summary" in res or "breakdown" in res or "status" in res
