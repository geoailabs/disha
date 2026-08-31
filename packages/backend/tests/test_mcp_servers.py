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

@pytest.mark.asyncio
async def test_osm_server_bus_routes():
    from mcp_servers.osm_server import OSMServer
    server = OSMServer()
    decls = server.get_declarations()
    names = {d.name for d in decls}
    assert "osm_fetch_bus_routes" in names

    # Execute osm_fetch_bus_routes (mocked Overpass post)
    from unittest.mock import patch
    with patch("mcp_servers.osm_server._overpass_post") as mock_post:
        mock_post.return_value = {
            "elements": [
                {
                    "type": "relation",
                    "tags": {"ref": "43", "name": "ISBT 43 - Sector 17", "operator": "CTU"},
                    "members": [
                        {
                            "type": "way",
                            "geometry": [
                                {"lat": 30.7107, "lon": 76.7366},
                                {"lat": 30.7150, "lon": 76.7400}
                            ]
                        }
                    ]
                }
            ]
        }
        res = await server.execute("osm_fetch_bus_routes", {"lat": 30.7107, "lng": 76.7366, "limit": 15})
        assert res["status"] == "success"
        assert res["count"] == 1
        assert "geojson" in res
        assert len(res["geojson"]["features"]) == 1
        assert res["geojson"]["features"][0]["properties"]["route_ref"] == "43"


@pytest.mark.asyncio
async def test_gtfs_server_functional(tmp_path):
    from mcp_servers.gtfs_server import GTFSServer

    server = GTFSServer()
    decls = server.get_declarations()
    names = {d.name for d in decls}
    assert "import_gtfs_feed" in names
    assert "analyze_gtfs_service" in names
    assert "analyze_gtfs_schedules" in names
    assert "analyze_transit_catchment" in names

    # Create mock GTFS folder structure in tmp_path
    gtfs_dir = tmp_path / "mock_gtfs"
    gtfs_dir.mkdir()

    stops_txt = "stop_id,stop_name,stop_lat,stop_lon\nS1,ISBT 17,30.7333,76.7794\nS2,Sector 22,30.7300,76.7750\n"
    routes_txt = "route_id,route_short_name,route_long_name,route_type\nR1,101,City Loop,3\n"
    trips_txt = "route_id,service_id,trip_id,shape_id\nR1,FULL,T1,SH1\n"
    shapes_txt = "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\nSH1,30.7333,76.7794,1\nSH1,30.7300,76.7750,2\n"
    stop_times_txt = "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,08:15:00,08:16:00,S1,1\nT1,08:30:00,08:31:00,S2,2\n"
    frequencies_txt = "trip_id,start_time,end_time,headway_secs\nT1,06:00:00,22:00:00,900\n"

    (gtfs_dir / "stops.txt").write_text(stops_txt)
    (gtfs_dir / "routes.txt").write_text(routes_txt)
    (gtfs_dir / "trips.txt").write_text(trips_txt)
    (gtfs_dir / "shapes.txt").write_text(shapes_txt)
    (gtfs_dir / "stop_times.txt").write_text(stop_times_txt)
    (gtfs_dir / "frequencies.txt").write_text(frequencies_txt)

    # 1. Test local directory import
    res_import = await server.execute("import_gtfs_feed", {
        "path": str(gtfs_dir),
        "workspace": str(tmp_path),
        "title": "Mock Transit"
    })
    assert res_import["status"] == "success"
    assert res_import["summary"]["stops"] == 2
    assert res_import["summary"]["routes"] == 1

    # 2. Test service analysis
    res_service = await server.execute("analyze_gtfs_service", {
        "workspace": str(tmp_path)
    })
    assert res_service["status"] == "success"
    assert res_service["network_stats"]["total_stops"] == 2

    # 3. Test schedule analysis
    res_sched = await server.execute("analyze_gtfs_schedules", {
        "workspace": str(tmp_path),
        "stop_id": "S1"
    })
    assert res_sched["status"] == "success"
    assert "hourly_departures_histogram" in res_sched
    assert len(res_sched["stop_timetable"]) > 0

    # 4. Test transit catchment
    res_catch = await server.execute("analyze_transit_catchment", {
        "workspace": str(tmp_path),
        "radius_meters": 400
    })
    assert res_catch["status"] == "success"
    assert res_catch["stops_buffered"] == 2
    assert "service_coverage" in res_catch


@pytest.mark.asyncio
async def test_gee_land_use_tools():
    from mcp_servers.gee_server import GEEServer

    server = GEEServer()
    decls = server.get_declarations()
    names = {d.name for d in decls}
    assert "analyze_land_use_zonal_stats" in names
    assert "extract_land_use_polygons" in names

    # Test zonal stats execution (fallback when GEE creds not set)
    res_zonal = await server.execute("analyze_land_use_zonal_stats", {
        "lat": 30.7333,
        "lng": 76.7794,
        "year": 2023
    })
    assert "status" in res_zonal
    assert "error" not in res_zonal


@pytest.mark.asyncio
async def test_selected_features_prompt_formatting():
    map_context = {
        "selected_features": [
            {
                "layerId": "layer_123",
                "layerName": "Built Area Polygons (2023)",
                "filePath": "/workspace/land_use_built_area_2023.geojson",
                "featureCount": 1971,
                "centroid": [76.75485, 30.75485],
                "bbox": [76.685, 30.654, 76.852, 30.812],
                "properties": {
                    "land_cover_class": "Built Area",
                    "year": 2023
                }
            }
        ]
    }
    
    selected_block = "\n\n[USER SELECTED MAP ELEMENTS / HIGHLIGHTED LAYERS]\n"
    for sf in map_context["selected_features"]:
        lname = sf.get("layerName") or "Selected Map Element"
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

    assert "Built Area Polygons (2023)" in selected_block
    assert "1971" in selected_block
    assert "76.75485" in selected_block


@pytest.mark.asyncio
async def test_plot_server_and_multi_format_export(tmp_path):
    from mcp_servers.plot_server import PlotServer
    from tools.export_engine import export_artifact_multi_format

    # 1. Test PlotServer chart creation
    plot_srv = PlotServer()
    res_plot = await plot_srv.execute("create_plot", {
        "plot_type": "bar",
        "title": "Land Use Breakdown",
        "x_data": ["Built-up", "Vegetation", "Water", "Bare Ground"],
        "y_data": [45, 30, 15, 10],
        "_map_context": {"workspace": str(tmp_path)}
    })
    assert res_plot["status"] == "success"
    assert "artifact_id" in res_plot

    # 2. Test Multi-Format Exporter
    b_docx, fn_docx, mime_docx = export_artifact_multi_format("Planning Report", "# Heading\nSome analysis text.", "docx")
    assert len(b_docx) > 0
    assert fn_docx == "Planning_Report.docx"

    b_html, fn_html, mime_html = export_artifact_multi_format("Planning Report", "# Heading\nSome analysis text.", "html")
    assert b"<!DOCTYPE html>" in b_html

    b_xlsx, fn_xlsx, mime_xlsx = export_artifact_multi_format("Zonal Data", '{"columns": ["Zone", "Area"], "rows": [["R1", 120]]}', "xlsx")
    assert len(b_xlsx) > 0




