"""Place-bounded extraction: exact boundary, only requested categories, clipped streets."""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


class FakeWS:
    def __init__(self):
        import json
        self.json = json
        self.sent = []

    async def send_text(self, t):
        self.sent.append(self.json.loads(t))


@pytest.fixture
def osm_boundary(monkeypatch):
    """OSM boundary lookups return a 1°×1° square for any name except 'Pointville'."""
    async def fake_fetch(self, args):
        if args["name"] == "Pointville":
            return {"geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.5, 0.5]}, "properties": {}}]}, "name": "Pointville"}
        off = 1 if args["name"] == "East Town" else 0
        poly = {"type": "Polygon", "coordinates": [[[off, 0], [off + 1, 0], [off + 1, 1], [off, 1], [off, 0]]]}
        return {"geojson": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": poly, "properties": {}}]}, "name": args["name"]}

    monkeypatch.setattr("mcp_servers.osm_server.OSMServer._fetch_boundary", fake_fetch)
    monkeypatch.setattr("tools.spatial_registry.spatial_registry.get_polygon", lambda name: None)
    monkeypatch.setattr("tools.spatial_registry.spatial_registry.register_or_get", lambda **k: None)


@pytest.mark.asyncio
async def test_boundary_outlined_and_point_rejected(osm_boundary):
    from tools.boundary import BoundaryError, resolve_study_boundary
    ws = FakeWS()
    b = await resolve_study_boundary({"place_name": "Test Town", "_ws": ws, "_map_context": {}})
    assert b.name == "Test Town" and b.shape.geom_type == "Polygon"
    outline = [m for m in ws.sent if m["action"] == "add_geojson"][0]["payload"]
    assert outline["name"] == "Test Town boundary" and outline["fillOpacity"] == 0
    with pytest.raises(BoundaryError):
        await resolve_study_boundary({"place_name": "Pointville", "_map_context": {}})


@pytest.mark.asyncio
async def test_multi_place_region_is_union(osm_boundary):
    from tools.boundary import resolve_study_boundary
    b = await resolve_study_boundary({"place_names": ["Test Town", "East Town"], "region_name": "Twin City", "_map_context": {}})
    assert b.name == "Twin City"
    assert b.bbox == {"west": 0.0, "south": 0.0, "east": 2.0, "north": 1.0}
    assert 24000 < b.area_km2 < 25000  # two 1°×1° cells at the equator


@pytest.mark.asyncio
async def test_osm_search_returns_only_requested_category_inside_boundary(osm_boundary, monkeypatch):
    from domains.spatial_hub import SpatialHub

    elements = [
        # hospital campus (area) with a department inside it → counted once
        {"type": "way", "id": 1, "tags": {"amenity": "hospital", "name": "General Hospital"},
         "geometry": [{"lon": 0.1, "lat": 0.1}, {"lon": 0.2, "lat": 0.1}, {"lon": 0.2, "lat": 0.2}, {"lon": 0.1, "lat": 0.2}, {"lon": 0.1, "lat": 0.1}]},
        {"type": "node", "id": 2, "lat": 0.15, "lon": 0.15, "tags": {"amenity": "hospital", "name": "Trauma Wing"}},
        # same hospital mapped as a node 50 m away → duplicate
        {"type": "node", "id": 3, "lat": 0.5, "lon": 0.5, "tags": {"amenity": "hospital", "name": "City Hospital"}},
        {"type": "node", "id": 4, "lat": 0.5004, "lon": 0.5, "tags": {"healthcare": "hospital", "name": "City Hospital"}},
        # outside the boundary → excluded
        {"type": "node", "id": 5, "lat": 0.5, "lon": 1.5, "tags": {"amenity": "hospital", "name": "Far Hospital"}},
        # a clinic must NOT appear among hospitals
        {"type": "node", "id": 6, "lat": 0.3, "lon": 0.3, "tags": {"amenity": "clinic", "name": "Clinic"}},
    ]

    async def fake_overpass(query, timeout=0):
        return {"elements": elements}

    monkeypatch.setattr("tools.osm_extract.fetch_overpass", fake_overpass)
    ws = FakeWS()
    res = await SpatialHub().execute("osm_search", {"category": "hospitals", "place_name": "Test Town"},
                                     {"_ws": ws, "_map_context": {"layers": []}})
    assert res.status == "success"
    row = res.data["results"][0]
    assert row["count"] == 2, row                          # General Hospital + City Hospital
    assert row["merged_duplicates_or_campus_parts"] == 2   # Trauma Wing + duplicate node
    assert row["outside_boundary_excluded"] == 1           # Far Hospital
    assert res.map_action["payload"]["name"] == "Hospitals - Test Town"
    names = {f["properties"]["name"] for f in res.map_action["payload"]["geojson"]["features"]}
    assert names == {"General Hospital", "City Hospital"}


@pytest.mark.asyncio
async def test_osm_search_unknown_place_does_not_fall_back(monkeypatch):
    async def none_found(self, args):
        return {"error": "No boundary found"}
    monkeypatch.setattr("mcp_servers.osm_server.OSMServer._fetch_boundary", none_found)
    monkeypatch.setattr("tools.spatial_registry.spatial_registry.get_polygon", lambda name: None)
    from mcp_servers.osm_server import OSMServer
    res = await OSMServer().execute("osm_search", {"category": "schools", "place_name": "Nowhere"})
    assert res["code"] == "boundary_unresolved"


def test_street_stats_counts_intersections_inside_only():
    from shapely.geometry import shape
    from mcp_servers.network_server import _street_network_stats
    nodes = {1: (0.1, 0.5), 2: (0.5, 0.5), 3: (0.9, 0.5), 4: (0.5, 0.9), 5: (1.5, 0.5), 6: (1.5, 0.9), 7: (1.2, 0.5)}
    ways = [
        {"id": 10, "nodes": [1, 2, 3]},   # through-road
        {"id": 11, "nodes": [2, 4]},      # side road → node 2 is an intersection (degree 3)
        {"id": 12, "nodes": [7, 5, 6]},   # outside
        {"id": 13, "nodes": [5, 7]},
    ]
    feats = [{"type": "Feature", "properties": {"highway": "primary"},
              "geometry": {"type": "LineString", "coordinates": [[0.1, 0.5], [0.9, 0.5]]}}]
    st = _street_network_stats(feats, ways, nodes, shape(SQUARE), 12300.0)
    assert st["intersections"] == 1
    assert st["length_by_class_km"]["primary"] > 80
    assert st["intersection_density_per_km2"] == round(1 / 12300.0, 3)


def test_categories_are_specific():
    from tools.osm_categories import OSM_CATEGORIES, normalise_category
    assert normalise_category("Hospital") == "hospitals"
    assert normalise_category("shopping malls") == "malls"
    assert ("amenity", "clinic|doctors") not in OSM_CATEGORIES["hospitals"]["tags"]
    assert OSM_CATEGORIES["malls"]["tags"] == [("shop", "mall")]


def test_completion_check_flags_boundary_only_answer_to_road_request():
    """'plot the <city> road boundary' answered with only osm_boundary must not be 'verified'."""
    import json
    from tools.task_pipeline import assess_task_completion
    messages = [
        {"role": "user", "content": "plot the chandigarh road boundary"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
            "function": {"name": "osm_boundary", "arguments": json.dumps({"name": "Chandigarh"})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"status": "success", "displayed_on_map": True})},
        {"role": "assistant", "content": "The Chandigarh boundary has been plotted."},
    ]
    res = assess_task_completion(messages, 0)
    assert res["status"] == "failed"
    assert not res["checks"]["requested_features_present"]
    assert any("fetch_street_network" in f for f in res["failures"])

    messages[1]["tool_calls"][0]["function"] = {"name": "fetch_street_network", "arguments": json.dumps({"place_name": "Chandigarh"})}
    assert assess_task_completion(messages, 0)["status"] == "verified"


def test_plain_fire_layer_request_does_not_demand_comparison():
    import json
    from tools.task_pipeline import assess_task_completion
    messages = [
        {"role": "user", "content": "show modis active fires in mohali for 2024"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
            "function": {"name": "get_modis_layer", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"status": "success"})},
    ]
    assert assess_task_completion(messages, 0)["status"] == "verified"


@pytest.mark.asyncio
async def test_export_targets_layers_plotted_this_turn_and_waits_for_image(tmp_path):
    """'plot all hospitals … and export it' → export frames exactly the new layers, and
    the tool only reports success once the app has written the image file."""
    import asyncio
    import json
    from routers import chat

    ws_dir = tmp_path
    sent = []

    class AppWS:
        async def send_text(self, text):
            msg = json.loads(text)
            sent.append(msg)
            if msg.get("action") == "export_map_jpeg":
                async def write_later():
                    await asyncio.sleep(1.0)  # capture takes time (framing + tile loading)
                    d = ws_dir / ".disha" / "artifacts_store"
                    d.mkdir(parents=True, exist_ok=True)
                    (d / f"{msg['payload']['artifact_id']}.jpg").write_bytes(b"\xff\xd8" + b"0" * 500)
                asyncio.get_running_loop().create_task(write_later())

    ws = AppWS()
    chat._turn_layers_var.set([])
    rec = chat._RecordingSocket(ws)
    # layers added this turn by tools (directly over the socket and via map_action)
    await rec.send_text(json.dumps({"type": "action", "action": "add_geojson", "payload": {"name": "Chandigarh boundary"}}))
    await chat._send_action_if_allowed(ws, "add_geojson_file", {"name": "Hospitals - Chandigarh", "path": "x"})

    out = json.loads(await chat._execute_tool(
        "export_map_jpeg", {"title": "Hospitals in Chandigarh", "save_to_artifacts": True}, ws,
        messages=[], map_context={"workspace": str(ws_dir), "layers": []},
    ))
    assert out["status"] == "success", out
    export = [m for m in sent if m.get("action") == "export_map_jpeg"][0]["payload"]
    assert export["layers_to_show"] == ["Hospitals - Chandigarh", "Chandigarh boundary"]


def test_recording_socket_keeps_question_identity():
    """ask_question futures are keyed by the real connection, not the proxy."""
    from routers.chat import _RecordingSocket
    from tools import utility

    class RealWS:
        pass

    real = RealWS()
    proxy = _RecordingSocket(real)
    import asyncio
    loop = asyncio.new_event_loop()
    fut = loop.create_future()
    utility._active_questions[id(getattr(proxy, "_real_ws", proxy))] = fut
    utility.register_question_response(real, "yes")
    assert fut.result() == "yes"
    loop.close()
