from __future__ import annotations
import os
import json
import math
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from llm.base import ToolDeclaration
from mcp_servers.osm_server import _overpass_post, OverpassError, _sanitize_osm_token

def _resolve_workspace(workspace_arg: str) -> str:
    """Resolve workspace path to the actual repository root.
    
    If the path is empty, relative, or the placeholder '/workspace',
    we resolve it dynamically to the repository root.
    """
    arg = workspace_arg.strip()
    if not arg or arg == "/workspace" or arg == "." or not Path(arg).is_absolute():
        here = Path(__file__).resolve()
        # packages/backend/mcp_servers/network_server.py -> repo root
        return str(here.parent.parent.parent.parent)
    return arg


def haversine_distance(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    """Calculate the Haversine distance in meters between two points (lng, lat)."""
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    R = 6371000  # radius of Earth in meters
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def _get_z_level(properties: dict) -> int:
    """Parse Z-level of a feature from layer, tunnel, or bridge tags."""
    if "layer" in properties:
        try:
            return int(properties["layer"])
        except (ValueError, TypeError):
            pass
    if properties.get("tunnel") in ("yes", "true", "1", 1):
        return -1
    if properties.get("bridge") in ("yes", "true", "1", 1):
        return 1
    return 0


def _is_oneway(properties: dict) -> str:
    """Determine the one-way status of a road way."""
    oneway = str(properties.get("oneway", "")).lower().strip()
    if oneway in ("yes", "true", "1"):
        return "yes"
    if oneway in ("-1", "reverse"):
        return "reverse"
    if properties.get("highway") == "motorway" and oneway != "no":
        return "yes"
    if properties.get("junction") == "roundabout" and oneway != "no":
        return "yes"
    return "no"

def _get_edge_weight(props: dict, distance_meters: float) -> float:
    """Calculate penalized routing weight to prevent routing through private/service alleys."""
    multiplier = 1.0
    highway = str(props.get("highway", "")).lower()
    service = str(props.get("service", "")).lower()
    access = str(props.get("access", "")).lower()
    
    if access in ("private", "no"):
        multiplier *= 10.0
    if service in ("parking_aisle", "driveway"):
        multiplier *= 5.0
    elif highway == "service":
        multiplier *= 3.0
        
    if highway in ("footway", "pedestrian", "path", "cycleway", "steps"):
        multiplier *= 5.0
        
    return distance_meters * multiplier

def _build_networkx_graph(geojson_data: dict) -> any:
    """Build a networkx MultiDiGraph from GeoJSON LineStrings with Z-levels, one-ways, weights, and filters."""
    import networkx as nx
    G = nx.MultiDiGraph()
    
    # Store restriction relations in graph metadata if present in geojson
    if isinstance(geojson_data, dict) and "restrictions" in geojson_data:
        G.graph["restrictions"] = geojson_data["restrictions"]
    
    features = []
    if not geojson_data:
        return G
    if geojson_data.get("type") == "FeatureCollection":
        features = geojson_data.get("features", [])
    elif geojson_data.get("type") == "Feature":
        features = [geojson_data]
    else:
        features = [{"type": "Feature", "geometry": geojson_data, "properties": {}}]
        
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        g_type = geom.get("type")
        props = feat.get("properties") or {}
        
        # 1. Construction & Proposed Road Filter
        highway = str(props.get("highway", "")).lower()
        if highway in ("construction", "proposed"):
            continue
        if "construction" in props or "proposed" in props:
            continue
            
        coords_list = []
        if g_type == "LineString":
            coords_list = [geom.get("coordinates", [])]
        elif g_type == "MultiLineString":
            coords_list = geom.get("coordinates", [])
            
        z_level = _get_z_level(props)
        oneway_status = _is_oneway(props)
        
        for coords in coords_list:
            L = len(coords)
            if L < 2:
                continue
                
            for idx in range(L - 1):
                u_lng, u_lat = coords[idx][0], coords[idx][1]
                # Use z=0 for endpoints to allow connections/ramps
                u_z = 0 if (idx == 0) else z_level
                u = (u_lng, u_lat, u_z)
                
                v_lng, v_lat = coords[idx+1][0], coords[idx+1][1]
                v_z = 0 if (idx+1 == L - 1) else z_level
                v = (v_lng, v_lat, v_z)
                
                length = haversine_distance((u_lng, u_lat), (v_lng, v_lat))
                weight = _get_edge_weight(props, length)
                
                edge_props = {
                    "length": length,
                    "weight": weight,
                    "highway": props.get("highway", "residential"),
                    "name": props.get("name", "unnamed"),
                    "osm_id": props.get("osm_id") or props.get("id"),
                    "access": props.get("access"),
                    "service": props.get("service")
                }
                
                if oneway_status == "yes":
                    G.add_edge(u, v, **edge_props)
                elif oneway_status == "reverse":
                    G.add_edge(v, u, **edge_props)
                else:
                    G.add_edge(u, v, **edge_props)
                    G.add_edge(v, u, **edge_props)
    return G


def _build_freight_graph(geojson_data: dict, truck_weight: float | None, truck_height: float | None, avoid_residential: bool) -> any:
    """Build a networkx MultiDiGraph optimized for freight vehicles."""
    import networkx as nx
    G = nx.MultiDiGraph()
    
    if isinstance(geojson_data, dict) and "restrictions" in geojson_data:
        G.graph["restrictions"] = geojson_data["restrictions"]
    
    features = []
    if not geojson_data:
        return G
    if geojson_data.get("type") == "FeatureCollection":
        features = geojson_data.get("features", [])
    elif geojson_data.get("type") == "Feature":
        features = [geojson_data]
    else:
        features = [{"type": "Feature", "geometry": geojson_data, "properties": {}}]
        
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        g_type = geom.get("type")
        props = feat.get("properties") or {}
        
        # 1. Construction filter
        highway = str(props.get("highway", "")).lower()
        if highway in ("construction", "proposed"):
            continue
            
        # 2. Freight access & vehicle restrictions
        # If road has maxweight or maxheight tags, evaluate them
        maxweight = props.get("maxweight")
        if maxweight and truck_weight is not None:
            try:
                # Parse numeric weight (tonnes). E.g. '12t' or '12' or '12.5'
                val_str = "".join([c for c in str(maxweight) if c.isdigit() or c == "."])
                if val_str and float(val_str) < truck_weight:
                    continue # Blocked due to weight limit
            except Exception:
                pass
                
        maxheight = props.get("maxheight")
        if maxheight and truck_height is not None:
            try:
                # Parse height. E.g. '3.8 m' or '3.8'
                val_str = "".join([c for c in str(maxheight) if c.isdigit() or c == "."])
                if val_str and float(val_str) < truck_height:
                    continue # Blocked due to height limit
            except Exception:
                pass
                
        # Access tags
        hgv = str(props.get("hgv", "")).lower()
        goods = str(props.get("goods", "")).lower()
        motor_vehicle = str(props.get("motor_vehicle", "")).lower()
        access = str(props.get("access", "")).lower()
        
        if hgv in ("no", "private") or goods in ("no", "private") or motor_vehicle in ("no", "private") or access in ("no", "private"):
            continue # Blocked for heavy goods / trucks
            
        coords_list = []
        if g_type == "LineString":
            coords_list = [geom.get("coordinates", [])]
        elif g_type == "MultiLineString":
            coords_list = geom.get("coordinates", [])
            
        z_level = _get_z_level(props)
        oneway_status = _is_oneway(props)
        
        for coords in coords_list:
            L = len(coords)
            if L < 2:
                continue
                
            for idx in range(L - 1):
                u_lng, u_lat = coords[idx][0], coords[idx][1]
                u_z = 0 if (idx == 0) else z_level
                u = (u_lng, u_lat, u_z)
                
                v_lng, v_lat = coords[idx+1][0], coords[idx+1][1]
                v_z = 0 if (idx+1 == L - 1) else z_level
                v = (v_lng, v_lat, v_z)
                
                length = haversine_distance((u_lng, u_lat), (v_lng, v_lat))
                
                # Dynamic cost weight calculation
                multiplier = 1.0
                
                # Check for residential/minor roads penalty
                if avoid_residential:
                    if highway in ("residential", "living_street", "service", "pedestrian", "footway", "steps", "path"):
                        multiplier *= 10.0
                    elif highway in ("unclassified", "tertiary"):
                        multiplier *= 3.0
                        
                # Standard penalties
                service = str(props.get("service", "")).lower()
                if service in ("parking_aisle", "driveway"):
                    multiplier *= 5.0
                
                weight = length * multiplier
                
                edge_props = {
                    "length": length,
                    "weight": weight,
                    "highway": highway or "residential",
                    "properties": props
                }
                
                if oneway_status == "no":
                    G.add_edge(u, v, **edge_props)
                    G.add_edge(v, u, **edge_props)
                elif oneway_status == "yes":
                    G.add_edge(u, v, **edge_props)
                elif oneway_status == "reverse":
                    G.add_edge(v, u, **edge_props)
                    
    return G



def simplify_graph_topology(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Simplify the graph topology by consolidating degree-2 pseudo-nodes in a single pass."""
    import networkx as nx
    H = G.copy()
    
    for node in list(H.nodes):
        if node not in H:
            continue
        predecessors = list(H.predecessors(node))
        successors = list(H.successors(node))
        neighbors = set(predecessors + successors)
        if node in neighbors:
            neighbors.remove(node)
        if len(neighbors) != 2:
            continue
            
        u, v = list(neighbors)
        
        has_uv_path = False
        has_vu_path = False
        
        # Check u -> node -> v
        if H.has_edge(u, node) and H.has_edge(node, v):
            len_u_n = min(d.get("length", 0) for d in H[u][node].values())
            len_n_v = min(d.get("length", 0) for d in H[node][v].values())
            wt_u_n = min(d.get("weight", len_u_n) for d in H[u][node].values())
            wt_n_v = min(d.get("weight", len_n_v) for d in H[node][v].values())
            H.add_edge(u, v, length=len_u_n + len_n_v, weight=wt_u_n + wt_n_v)
            has_uv_path = True
            
        # Check v -> node -> u
        if H.has_edge(v, node) and H.has_edge(node, u):
            len_v_n = min(d.get("length", 0) for d in H[v][node].values())
            len_n_u = min(d.get("length", 0) for d in H[node][u].values())
            wt_v_n = min(d.get("weight", len_v_n) for d in H[v][node].values())
            wt_n_u = min(d.get("weight", len_n_u) for d in H[node][u].values())
            H.add_edge(v, u, length=len_v_n + len_n_u, weight=wt_v_n + wt_n_u)
            has_vu_path = True

            
        if has_uv_path or has_vu_path:
            H.remove_node(node)
            
    return H

def _build_expanded_graph(G: nx.MultiDiGraph) -> nx.DiGraph:
    """Build a dual expanded DiGraph where nodes are edges of G, and transitions are allowed."""
    import networkx as nx
    E = nx.DiGraph()
    
    restrictions = G.graph.get("restrictions", [])
    
    # Create nodes in E corresponding to edges in G
    for u, v, key, data in G.edges(keys=True, data=True):
        E.add_node((u, v, key), length=data.get("length", 0), weight=data.get("weight", 0))
        
    # Create transitions in E
    for v in G.nodes:
        in_edges = list(G.in_edges(v, keys=True, data=True))
        out_edges = list(G.out_edges(v, keys=True, data=True))
        
        for u, _, k1, d1 in in_edges:
            for _, w, k2, d2 in out_edges:
                is_restricted = False
                w1_id = d1.get("osm_id")
                w2_id = d2.get("osm_id")
                
                v_lng, v_lat = v[0], v[1]
                
                for r in restrictions:
                    r_type = r.get("type", "")
                    r_from = r.get("from_way")
                    r_to = r.get("to_way")
                    r_lng = r.get("via_lng")
                    r_lat = r.get("via_lat")
                    
                    # Coordinate matching with floating point tolerance
                    if abs(v_lng - r_lng) < 1e-6 and abs(v_lat - r_lat) < 1e-6:
                        if w1_id == r_from and w2_id == r_to:
                            if "no_" in r_type or r_type in ("no_left_turn", "no_right_turn", "no_straight_on", "no_u_turn"):
                                is_restricted = True
                                break
                                
                if not is_restricted:
                    E.add_edge((u, v, k1), (v, w, k2), weight=d2.get("weight", 0), length=d2.get("length", 0))
                    
    return E

def _find_shortest_path_with_restrictions(G: nx.MultiDiGraph, source: tuple, target: tuple) -> tuple[list, float]:

    """Find shortest path in G from source to target enforcing turn restrictions."""
    import networkx as nx
    restrictions = G.graph.get("restrictions", [])
    if not restrictions:
        path = nx.shortest_path(G, source=source, target=target, weight="weight")
        path_length = 0.0
        for i in range(len(path) - 1):
            u, v = path[i], path[i+1]
            path_length += min(d.get("length", 0) for d in G[u][v].values())
        return path, path_length
        
    E = _build_expanded_graph(G)
    E.add_node("__start__")
    for _, v, key, data in G.out_edges(source, keys=True, data=True):
        E.add_edge("__start__", (source, v, key), weight=data.get("weight", 0), length=data.get("length", 0))
        
    E.add_node("__end__")
    for u, _, key, data in G.in_edges(target, keys=True, data=True):
        E.add_edge((u, target, key), "__end__", weight=0, length=0)
        
    path_edges = nx.shortest_path(E, source="__start__", target="__end__", weight="weight")
    path = []
    path_length = 0.0
    for edge in path_edges:
        if isinstance(edge, tuple) and len(edge) == 3:
            u_node, v_node, k_node = edge
            if not path:
                path.append(u_node)
            path.append(v_node)
            path_length += G[u_node][v_node][k_node].get("length", 0)
            
    return path, path_length


def _street_network_stats(features: list, ways: list, nodes: dict, boundary_shape, area_km2: float | None) -> dict:
    """Geodesic lengths by road class, intersections and densities inside the study area."""
    from collections import Counter, defaultdict
    from pyproj import Geod
    from shapely.geometry import Point, shape
    from shapely.prepared import prep

    geod = Geod(ellps="WGS84")
    by_class: dict[str, float] = defaultdict(float)
    total = 0.0
    for f in features:
        try:
            length = abs(geod.geometry_length(shape(f["geometry"]))) / 1000.0
        except Exception:
            continue
        total += length
        by_class[f["properties"].get("highway") or "unknown"] += length

    # Node degree from the OSM topology: a node used by ways with ≥3 incident segments
    # is an intersection; degree 1 is a dead end. Only nodes inside the study area count.
    degree: Counter = Counter()
    for w in ways:
        nds = w.get("nodes") or []
        for i, nid in enumerate(nds):
            degree[nid] += 1 if i in (0, len(nds) - 1) else 2
    inside = prep(boundary_shape) if boundary_shape is not None else None
    intersections = dead_ends = 0
    for nid, d in degree.items():
        if d < 3 and d != 1:
            continue
        c = nodes.get(nid)
        if not c or (inside is not None and not inside.contains(Point(c))):
            continue
        if d >= 3:
            intersections += 1
        else:
            dead_ends += 1
    out = {
        "total_length_km": round(total, 3),
        "length_by_class_km": {k: round(v, 3) for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])},
        "intersections": intersections,
        "dead_ends": dead_ends,
    }
    if area_km2:
        out["area_km2"] = round(area_km2, 3)
        out["road_density_km_per_km2"] = round(total / area_km2, 3)
        out["intersection_density_per_km2"] = round(intersections / area_km2, 3)
    if intersections + dead_ends:
        out["connectivity_ratio"] = round(intersections / (intersections + dead_ends), 3)
    return out


class NetworkServer:
    description = "Street Network Analysis & Shortest Path Routing"
    tool_names = {
        "analyze_street_network",
        "find_shortest_path",
        "find_freight_route",
        "route_multi_stop",
        "fetch_street_network",
        "assign_traffic_flows"
    }

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="analyze_street_network",
                description=(
                    "Analyze a road network GeoJSON to calculate topological metrics "
                    "(intersection counts, road lengths, intersection density) and identify traffic bottlenecks "
                    "using Betweenness Centrality. Saves results inside the active workspace."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "GeoJSON FeatureCollection containing LineString road/street lines. Optional if geojson_path is provided."
                        },
                        "geojson_path": {
                            "type": "string",
                            "description": "Optional: Absolute path to a saved road network GeoJSON file in the workspace (preferred over passing huge geojson object)."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional: Title for the map layer (e.g. 'Bottleneck Nodes')."
                        }
                    },
                    "required": ["workspace"]
                }
            ),
            ToolDeclaration(
                name="find_shortest_path",
                description=(
                    "Calculate the shortest path routing between two lat/lng coordinates using a road network GeoJSON. "
                    "Saves the routing path as a LineString GeoJSON file in the workspace and displays it on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "GeoJSON FeatureCollection containing LineString road lines. Optional if geojson_path is provided."
                        },
                        "geojson_path": {
                            "type": "string",
                            "description": "Optional: Absolute path to a saved road network GeoJSON file in the workspace (preferred over passing huge geojson object)."
                        },
                        "start_lat": {"type": "number", "description": "Latitude coordinate of the starting point."},
                        "start_lng": {"type": "number", "description": "Longitude coordinate of the starting point."},
                        "end_lat": {"type": "number", "description": "Latitude coordinate of the ending point."},
                        "end_lng": {"type": "number", "description": "Longitude coordinate of the ending point."},
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional: Title for the map layer (e.g. 'Shortest Route')."
                        },
                        "start_label": {
                            "type": "string",
                            "description": "Optional: Name/label for the starting waypoint pin (e.g. 'ISBT Sector-43')."
                        },
                        "end_label": {
                            "type": "string",
                            "description": "Optional: Name/label for the destination waypoint pin (e.g. 'ISBT Zirakpur')."
                        },
                        "color": {
                            "type": "string",
                            "description": "Optional: Hex color code for the route line (e.g. '#8a3324')."
                        }
                    },
                    "required": ["start_lat", "start_lng", "end_lat", "end_lng", "workspace"]
                }
            ),
            ToolDeclaration(
                name="find_freight_route",
                description=(
                    "Calculate the optimal route for freight vehicles/trucks, respecting weight, height, and width constraints "
                    "and penalizing minor/residential streets by 10x to favor primary truck corridors. "
                    "Saves the resulting route as a LineString GeoJSON in the workspace and displays it on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "GeoJSON FeatureCollection containing LineString road lines. Optional if geojson_path is provided."
                        },
                        "geojson_path": {
                            "type": "string",
                            "description": "Optional: Absolute path to a saved road network GeoJSON file in the workspace."
                        },
                        "start_lat": {"type": "number", "description": "Latitude coordinate of the starting point."},
                        "start_lng": {"type": "number", "description": "Longitude coordinate of the starting point."},
                        "end_lat": {"type": "number", "description": "Latitude coordinate of the ending point."},
                        "end_lng": {"type": "number", "description": "Longitude coordinate of the ending point."},
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "truck_weight_tonnes": {
                            "type": "number",
                            "description": "Optional: Truck gross weight in tonnes. Blocks links where maxweight is exceeded."
                        },
                        "truck_height_meters": {
                            "type": "number",
                            "description": "Optional: Truck clearance height in meters. Blocks links where maxheight is exceeded."
                        },
                        "avoid_residential": {
                            "type": "boolean",
                            "default": True,
                            "description": "Whether to apply a 10x cost penalty to minor and residential streets to stay on commercial/freight highways."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional: Title for the map layer (e.g. 'Freight Route')."
                        },
                        "start_label": {
                            "type": "string",
                            "description": "Optional: Name/label for the starting waypoint pin (e.g. 'ISBT Sector-43')."
                        },
                        "end_label": {
                            "type": "string",
                            "description": "Optional: Name/label for the destination waypoint pin (e.g. 'ISBT Zirakpur')."
                        },
                        "color": {
                            "type": "string",
                            "description": "Optional: Hex color code for the route line (e.g. '#8a3324')."
                        }
                    },
                    "required": ["start_lat", "start_lng", "end_lat", "end_lng", "workspace"]
                }
            ),
            ToolDeclaration(
                name="route_multi_stop",
                description=(
                    "Generate an explicit multi-stop route along a road network GeoJSON, "
                    "connecting a sequence of waypoints (stops/origins/destinations) in order. "
                    "Uses Dijkstra shortest-path routing between each consecutive pair of stops. "
                    "Returns a single continuous LineString route and per-leg distance/time stats."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "GeoJSON FeatureCollection containing LineString road lines. Optional if geojson_path is provided."
                        },
                        "geojson_path": {
                            "type": "string",
                            "description": "Optional: Absolute path to a saved road network GeoJSON file in the workspace (preferred over passing huge geojson object)."
                        },
                        "waypoints": {
                            "type": "array",
                            "description": "Ordered list of waypoints to route through. Each waypoint: {lat, lng, label}.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                    "label": {"type": "string"}
                                },
                                "required": ["lat", "lng"]
                            }
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Name for the output route layer."
                        },
                        "color": {
                            "type": "string",
                            "description": "Optional: Hex color code for the route line (e.g. '#8a3324')."
                        }
                    },
                    "required": ["waypoints", "workspace"]
                }
            ),
            ToolDeclaration(
                name="fetch_street_network",
                description=(
                    "Fetch the street/road network from OpenStreetMap. When the user names a place pass place_name (or place_names): "
                    "the official boundary is outlined and ONLY the streets inside it are drawn (clipped at the boundary). Returns "
                    "total length and length by road class (km), intersections, dead ends, road density and intersection density "
                    "computed for that area only. Saves GeoJSON to the workspace and displays it on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "use_current_bounds": {
                            "type": "boolean",
                            "description": "If true, fetches streets within the current map viewport bounds instead of using lat/lng/radius_meters."
                        },
                        "lat": {
                            "type": "number",
                            "description": "Center latitude. Optional if use_current_bounds is true or if map center is available."
                        },
                        "lng": {
                            "type": "number",
                            "description": "Center longitude. Optional if use_current_bounds is true or if map center is available."
                        },
                        "radius_meters": {
                            "type": "number",
                            "description": "Search radius in meters (default 1500, max 10000)."
                        },
                        "highway_types": {
                            "type": "string",
                            "description": "Pipe-separated list of highway types to fetch (e.g. 'primary|secondary|tertiary|residential'). Defaults to standard drivable streets."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional name for the generated map layer (e.g. 'Downtown Streets'). Defaults to 'Street Network'."
                        },
                        "boundary_layer_name": {
                            "type": "string",
                            "description": "Optional: Name of a polygon layer in the active map context (e.g., 'Sector 1 boundary'). If provided, the fetched streets will be strictly clipped to the boundaries of this polygon."
                        },
                        "place_name": {"type": "string", "description": "Place whose official boundary polygon defines the study area (preferred whenever the user names a place)."},
                        "place_names": {"type": "array", "items": {"type": "string"}, "description": "Several places merged into one study area (e.g. a tri-city region)."},
                        "region_name": {"type": "string", "description": "Label for a merged multi-place region."},
                        "country_code": {"type": "string", "description": "ISO alpha-2 code to disambiguate the place."},
                        "network_type": {"type": "string", "enum": ["drive", "major", "arterial", "walk", "cycle", "all"], "description": "Road classes: drive (default, incl. highways/trunk roads), major, arterial, walk, cycle, all. Ignored if highway_types is given."}
                    },
                    "required": ["workspace"]
                }
            ),
            ToolDeclaration(
                name="assign_traffic_flows",
                description=(
                    "Run an Origin-Destination (OD) traffic assignment analysis. Routes trip flows from the OD matrix "
                    "onto the actual road network graph, accumulating traffic volumes on each road segment. "
                    "Saves the results as a styled LineString GeoJSON layer showing traffic load and displays it on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "geojson_path": {
                            "type": "string",
                            "description": "Optional: Absolute path to a saved road network GeoJSON file in the workspace. If not specified, looks for 'street_network.geojson' in the workspace."
                        },
                        "od_matrix_path": {
                            "type": "string",
                            "description": "Optional: Absolute path to 'od_matrix.json' in the workspace. If not specified, looks for 'od_matrix.json' in the workspace."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional: Title for the map layer (e.g. 'Assigned Traffic Flows')."
                        }
                    },
                    "required": ["workspace"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "analyze_street_network":
            return await self._analyze_street_network(args)
        if tool_name == "find_shortest_path":
            return await self._find_shortest_path(args)
        if tool_name == "find_freight_route":
            return await self._find_freight_route(args)
        if tool_name == "route_multi_stop":
            return await self._route_multi_stop(args)
        if tool_name == "fetch_street_network":
            return await self._fetch_street_network(args)
        if tool_name == "assign_traffic_flows":
            return await self._assign_traffic_flows(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _analyze_street_network(self, args: dict) -> dict:
        geojson_path = args.get("geojson_path", "").strip()
        geojson = args.get("geojson")
        workspace = _resolve_workspace(args.get("workspace", ""))
        title = args.get("title", "").strip() or "Junction Bottlenecks"
        ws = args.get("_ws")

        if geojson_path:
            try:
                with open(geojson_path) as f:
                    geojson = json.load(f)
            except Exception as e:
                return {"error": f"Failed to load GeoJSON from path '{geojson_path}': {str(e)}"}

        if not geojson:
            return {"error": "Either 'geojson' or 'geojson_path' must be provided."}
        if not workspace:
            return {"error": "workspace is required to save output layers"}

        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx library is not installed on the system."}

        try:
            G = _build_networkx_graph(geojson)
            if not G.nodes:
                return {"error": "GeoJSON contains no valid LineString coordinates to build a graph."}

            # 1. Compute basic statistics
            total_nodes = len(G.nodes)
            total_edges = len(G.edges)
            
            # Road lengths
            total_len_m = sum(d.get("length", 0) for _, _, d in G.edges(data=True))
            
            # Intersection nodes (nodes with degree > 2)
            intersections = [n for n, deg in G.degree() if deg > 2]
            total_intersections = len(intersections)
            
            # Study area bounding box
            lngs = [n[0] for n in G.nodes]
            lats = [n[1] for n in G.nodes]
            min_lng, max_lng = min(lngs), max(lngs)
            min_lat, max_lat = min(lats), max(lats)
            
            w_m = haversine_distance((min_lng, min_lat), (max_lng, min_lat))
            h_m = haversine_distance((min_lng, min_lat), (min_lng, max_lat))
            area_sq_km = (w_m * h_m) / 1_000_000.0
            
            density = total_intersections / max(0.001, area_sq_km)

            # 2. Compute Traffic Bottlenecks (Betweenness Centrality)
            G_simplified = simplify_graph_topology(G)
            centrality = nx.betweenness_centrality(G_simplified, weight="weight")

            sorted_nodes = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
            top_count = max(1, int(len(sorted_nodes) * 0.05))
            top_nodes = sorted_nodes[:top_count]


            # Generate GeoJSON Point layer
            bottleneck_features = []
            for idx, (node, score) in enumerate(top_nodes):
                bottleneck_features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [node[0], node[1]]
                    },
                    "properties": {
                        "id": idx + 1,
                        "centrality_score": round(score, 4),
                        "degree": G.degree(node)
                    }
                })
            
            out_geojson = {
                "type": "FeatureCollection",
                "features": bottleneck_features
            }

            # Save to workspace
            filename = "junction_bottlenecks.geojson"
            target_path = Path(workspace) / filename
            with open(target_path, "w") as f:
                json.dump(out_geojson, f, indent=2)

            # Dispatch action to client
            if ws:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(target_path),
                        "name": title
                    }
                }))

            return {
                "status": "success",
                "displayed_on_map": True,
                "summary": {
                    "total_nodes": total_nodes,
                    "total_edges": total_edges,
                    "total_road_length_km": round(total_len_m / 1000.0, 2),
                    "total_intersections": total_intersections,
                    "estimated_area_sq_km": round(area_sq_km, 3),
                    "intersection_density_per_sq_km": round(density, 2),
                    "bottlenecks_count": len(bottleneck_features)
                },
                "output_layer": str(target_path)
            }

        except Exception as e:
            return {"error": f"Topological network analysis failed: {str(e)}"}

    async def _find_shortest_path(self, args: dict) -> dict:
        geojson_path = args.get("geojson_path", "").strip()
        geojson = args.get("geojson")
        start_lat = float(args.get("start_lat", 0))
        start_lng = float(args.get("start_lng", 0))
        end_lat = float(args.get("end_lat", 0))
        end_lng = float(args.get("end_lng", 0))
        workspace = _resolve_workspace(args.get("workspace", ""))
        color = args.get("color", "").strip() or "#8a3324"
        start_label = args.get("start_label", "").strip() or "Start"
        end_label = args.get("end_label", "").strip() or "Destination"

        if geojson_path:
            try:
                with open(geojson_path) as f:
                    geojson = json.load(f)
            except Exception as e:
                return {"error": f"Failed to load GeoJSON from path '{geojson_path}': {str(e)}"}

        if not geojson:
            return {"error": "Either 'geojson' or 'geojson_path' must be provided."}
        if not workspace:
            return {"error": "workspace is required to save route outputs"}

        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx library is not installed on the system."}

        try:
            G = _build_networkx_graph(geojson)
            if not G.nodes:
                return {"error": "GeoJSON contains no valid LineString coordinates."}

            # Snap coordinates to the largest weakly connected component (ensures routable paths)
            components = list(nx.weakly_connected_components(G))
            if components:
                largest_cc = max(components, key=len)
                nodes_to_search = largest_cc
            else:
                nodes_to_search = G.nodes

            start_coord = (start_lng, start_lat)
            end_coord = (end_lng, end_lat)
            
            closest_start = None
            closest_end = None
            min_d_start = float("inf")
            min_d_end = float("inf")
            
            for node in nodes_to_search:
                d_start = haversine_distance((node[0], node[1]), start_coord)
                if d_start < min_d_start:
                    min_d_start = d_start
                    closest_start = node
                    
                d_end = haversine_distance((node[0], node[1]), end_coord)
                if d_end < min_d_end:
                    min_d_end = d_end
                    closest_end = node

            if not closest_start or not closest_end:
                return {"error": "Could not identify start or end node projections on the largest connected network component."}


            # Execute shortest path respecting turn restrictions, weights, and one-ways
            path, path_length = _find_shortest_path_with_restrictions(G, closest_start, closest_end)



            # Build LineString geometry
            coords = [[n[0], n[1]] for n in path]
            route_geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": {
                        "name": title,
                        "length_meters": round(path_length, 1),
                        "estimated_travel_time_mins": round((path_length / 11.1) / 60.0, 1)  # assuming 40 km/h average
                    }
                }]
            }

            # Save route file to workspace
            filename = "shortest_route.geojson"
            target_path = Path(workspace) / filename
            with open(target_path, "w") as f:
                json.dump(route_geojson, f, indent=2)

            # Generate and save start/end markers as a stops layer in the workspace
            stops_filename = "shortest_route_stops.geojson"
            stops_target_path = Path(workspace) / stops_filename
            stops_geojson = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(start_lng), float(start_lat)]},
                        "properties": {
                            "stop_index": 1,
                            "label": start_label
                        }
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(end_lng), float(end_lat)]},
                        "properties": {
                            "stop_index": 2,
                            "label": end_label
                        }
                    }
                ]
            }
            with open(stops_target_path, "w") as f:
                json.dump(stops_geojson, f, indent=2)

            # Dispatch action
            if ws:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(target_path),
                        "name": title,
                        "color": color
                    }
                }))
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(stops_target_path),
                        "name": f"{title} – Stops",
                        "color": "#e6194b"  # Distinct red for stops
                    }
                }))

            return {
                "status": "success",
                "displayed_on_map": True,
                "route_stats": {
                    "total_distance_meters": round(path_length, 1),
                    "estimated_travel_time_mins": round((path_length / 11.1) / 60.0, 1),
                    "closest_start_offset_meters": round(min_d_start, 1),
                    "closest_end_offset_meters": round(min_d_end, 1)
                },
                "output_layer": str(target_path)
            }


        except nx.NetworkXNoPath:
            return {"error": "No topological path exists between the start and end coordinates."}
        except Exception as e:
            return {"error": f"Shortest path calculation failed: {str(e)}"}

    async def _find_freight_route(self, args: dict) -> dict:
        geojson_path = args.get("geojson_path", "").strip()
        geojson = args.get("geojson")
        start_lat = float(args.get("start_lat", 0))
        start_lng = float(args.get("start_lng", 0))
        end_lat = float(args.get("end_lat", 0))
        end_lng = float(args.get("end_lng", 0))
        workspace = _resolve_workspace(args.get("workspace", ""))
        title = args.get("title", "").strip() or "Freight Route"
        truck_weight = args.get("truck_weight_tonnes")
        truck_height = args.get("truck_height_meters")
        avoid_res = bool(args.get("avoid_residential", True))
        ws = args.get("_ws")
        color = args.get("color", "").strip() or "#8a3324"
        start_label = args.get("start_label", "").strip() or "Start"
        end_label = args.get("end_label", "").strip() or "Destination"

        if truck_weight is not None:
            truck_weight = float(truck_weight)
        if truck_height is not None:
            truck_height = float(truck_height)

        if geojson_path:
            try:
                with open(geojson_path) as f:
                    geojson = json.load(f)
            except Exception as e:
                return {"error": f"Failed to load GeoJSON from path '{geojson_path}': {str(e)}"}

        if not geojson:
            return {"error": "Either 'geojson' or 'geojson_path' must be provided."}
        if not workspace:
            return {"error": "workspace is required to save route outputs"}

        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx library is not installed on the system."}

        try:
            G = _build_freight_graph(geojson, truck_weight, truck_height, avoid_res)
            if not G.nodes:
                return {"error": "GeoJSON contains no valid LineString coordinates after applying freight filters."}

            components = list(nx.weakly_connected_components(G))
            if components:
                largest_cc = max(components, key=len)
                nodes_to_search = largest_cc
            else:
                nodes_to_search = G.nodes

            start_coord = (start_lng, start_lat)
            end_coord = (end_lng, end_lat)
            
            closest_start = None
            closest_end = None
            min_d_start = float("inf")
            min_d_end = float("inf")
            
            for node in nodes_to_search:
                d_start = haversine_distance((node[0], node[1]), start_coord)
                if d_start < min_d_start:
                    min_d_start = d_start
                    closest_start = node
                    
                d_end = haversine_distance((node[0], node[1]), end_coord)
                if d_end < min_d_end:
                    min_d_end = d_end
                    closest_end = node

            if not closest_start or not closest_end:
                return {"error": "Could not identify start or end node projections on the largest connected network component."}

            path, path_length = _find_shortest_path_with_restrictions(G, closest_start, closest_end)

            coords = [[n[0], n[1]] for n in path]
            route_geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": {
                        "name": title,
                        "length_meters": round(path_length, 1),
                        "estimated_travel_time_mins": round((path_length / 8.3) / 60.0, 1),  # assuming 30 km/h for trucks
                        "truck_weight_tonnes": truck_weight,
                        "truck_height_meters": truck_height
                    }
                }]
            }

            filename = "freight_route.geojson"
            target_path = Path(workspace) / filename
            with open(target_path, "w") as f:
                json.dump(route_geojson, f, indent=2)

            # Generate and save start/end markers as a stops layer in the workspace
            stops_filename = "freight_route_stops.geojson"
            stops_target_path = Path(workspace) / stops_filename
            stops_geojson = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(start_lng), float(start_lat)]},
                        "properties": {
                            "stop_index": 1,
                            "label": start_label
                        }
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(end_lng), float(end_lat)]},
                        "properties": {
                            "stop_index": 2,
                            "label": end_label
                        }
                    }
                ]
            }
            with open(stops_target_path, "w") as f:
                json.dump(stops_geojson, f, indent=2)

            if ws:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(target_path),
                        "name": title,
                        "color": color
                    }
                }))
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(stops_target_path),
                        "name": f"{title} – Stops",
                        "color": "#e6194b"  # Distinct red for stops
                    }
                }))

            return {
                "status": "success",
                "displayed_on_map": True,
                "route_stats": {
                    "total_distance_meters": round(path_length, 1),
                    "estimated_travel_time_mins": round((path_length / 8.3) / 60.0, 1),
                    "closest_start_offset_meters": round(min_d_start, 1),
                    "closest_end_offset_meters": round(min_d_end, 1)
                },
                "output_layer": str(target_path)
            }

        except nx.NetworkXNoPath:
            return {"error": "No topological path exists between the start and end coordinates after applying freight filters."}
        except Exception as e:
            return {"error": f"Freight routing calculation failed: {str(e)}"}

    async def _route_multi_stop(self, args: dict) -> dict:
        geojson_path = args.get("geojson_path", "").strip()
        geojson = args.get("geojson")
        waypoints = args.get("waypoints", [])
        workspace = _resolve_workspace(args.get("workspace", ""))
        title = args.get("title", "Multi-Stop Route").strip()
        ws = args.get("_ws")
        color = args.get("color", "").strip() or "#8a3324"

        if geojson_path:
            try:
                with open(geojson_path) as f:
                    geojson = json.load(f)
            except Exception as e:
                return {"error": f"Failed to load GeoJSON from path '{geojson_path}': {str(e)}"}

        if not geojson:
            return {"error": "Either 'geojson' or 'geojson_path' must be provided."}
        if len(waypoints) < 2:
            return {"error": "At least 2 waypoints are required for multi-stop routing."}
        if not workspace:
            return {"error": "workspace is required"}

        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx library is not installed."}

        try:
            G = _build_networkx_graph(geojson)
            if not G.nodes:
                return {"error": "GeoJSON contains no valid LineString coordinates."}

            components = list(nx.weakly_connected_components(G))
            if components:
                largest_cc = max(components, key=len)
                nodes_list = list(largest_cc)
            else:
                nodes_list = list(G.nodes)

            def closest_node(lat: float, lng: float) -> tuple:
                coord = (lng, lat)
                best = min(nodes_list, key=lambda n: haversine_distance((n[0], n[1]), coord))
                return best


            all_coords = []
            legs = []
            total_dist = 0.0

            for i in range(len(waypoints) - 1):
                wp_a = waypoints[i]
                wp_b = waypoints[i + 1]

                node_a = closest_node(float(wp_a["lat"]), float(wp_a["lng"]))
                node_b = closest_node(float(wp_b["lat"]), float(wp_b["lng"]))

                try:
                    path, leg_len = _find_shortest_path_with_restrictions(G, node_a, node_b)

                except nx.NetworkXNoPath:

                    return {"error": f"No path found between waypoint {i+1} and {i+2}."}

                leg_coords = [[n[0], n[1]] for n in path]
                # Avoid duplicating the junction point between legs
                if all_coords and leg_coords:
                    leg_coords = leg_coords[1:]
                all_coords.extend(leg_coords)

                legs.append({
                    "from": wp_a.get("label", f"Stop {i+1}"),
                    "to": wp_b.get("label", f"Stop {i+2}"),
                    "distance_m": round(leg_len, 1),
                    "est_time_mins": round((leg_len / 11.1) / 60.0, 1)
                })
                total_dist += leg_len

            # Build output GeoJSON
            route_geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": all_coords},
                    "properties": {
                        "name": title,
                        "total_distance_m": round(total_dist, 1),
                        "total_est_time_mins": round((total_dist / 11.1) / 60.0, 1),
                        "stops": len(waypoints)
                    }
                }]
            }

            # Save waypoint markers too
            stop_features = []
            for idx, wp in enumerate(waypoints):
                stop_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(wp["lng"]), float(wp["lat"])]},
                    "properties": {
                        "stop_index": idx + 1,
                        "label": wp.get("label", f"Stop {idx+1}")
                    }
                })
            stops_geojson = {"type": "FeatureCollection", "features": stop_features}

            # Write files
            route_path = Path(workspace) / "multi_stop_route.geojson"
            stops_path = Path(workspace) / "multi_stop_waypoints.geojson"

            with open(route_path, "w") as f:
                json.dump(route_geojson, f)
            with open(stops_path, "w") as f:
                json.dump(stops_geojson, f)

            # Dispatch to map
            if ws:
                await ws.send_text(json.dumps({
                    "type": "action", "action": "add_geojson_file",
                    "payload": {
                        "path": str(route_path),
                        "name": title,
                        "color": color
                    }
                }))
                await ws.send_text(json.dumps({
                    "type": "action", "action": "add_geojson_file",
                    "payload": {
                        "path": str(stops_path),
                        "name": f"{title} – Stops",
                        "color": "#e6194b"  # Distinct red for stops
                    }
                }))

            return {
                "status": "success",
                "displayed_on_map": True,
                "total_stops": len(waypoints),
                "total_distance_m": round(total_dist, 1),
                "total_est_time_mins": round((total_dist / 11.1) / 60.0, 1),
                "legs": legs,
                "output_route": str(route_path)
            }

        except Exception as e:
            return {"error": f"Multi-stop routing failed: {str(e)}"}

    async def _fetch_street_network(self, args: dict) -> dict:
        workspace = _resolve_workspace(args.get("workspace", ""))
        use_current_bounds = args.get("use_current_bounds", False)
        title = args.get("title", "").strip() or "Street Network"
        ws = args.get("_ws")
        map_context = args.get("_map_context")

        if not workspace:
            return {"error": "workspace is required"}

        # Study area: a named place / multi-place region / boundary layer / given polygon is
        # resolved to its exact polygon (outlined on the map). Radius / viewport mode is only
        # for "around here" requests.
        from tools.boundary import BoundaryError, boundary_args_present, resolve_study_boundary
        shapely_shape = None
        boundary = None
        if boundary_args_present(args):
            try:
                boundary = await resolve_study_boundary(args)
            except BoundaryError as exc:
                return {"error": str(exc), "code": "boundary_unresolved"}
            shapely_shape = boundary.shape
            if title == "Street Network":
                title = f"Street Network - {boundary.name}"

        bounds = map_context.get("bounds") if isinstance(map_context, dict) else None

        if boundary is not None:
            if boundary.area_km2 > 6000:
                return {"error": f"The study area '{boundary.name}' is {round(boundary.area_km2)} km²; street extraction is limited to 6000 km². Use a smaller area or highway_types='motorway|trunk|primary'.", "code": "too_large"}
            bbox_filter = boundary.overpass_bbox
        elif use_current_bounds and bounds and all(bounds.get(k) is not None for k in ["south", "west", "north", "east"]):
            s = bounds["south"]
            w = bounds["west"]
            n = bounds["north"]
            e = bounds["east"]
            # Diagonal safety check
            diag = haversine_distance((w, s), (e, n))
            if diag > 15000:
                return {
                    "error": f"Requested search bounds are too large (diagonal {round(diag/1000, 1)}km > 15km). Pass place_name to use the place's boundary instead."
                }
            bbox_filter = f"({s},{w},{n},{e})"
        else:
            lat = args.get("lat")
            lng = args.get("lng")
            if lat is None or lng is None:
                center = map_context.get("center") if isinstance(map_context, dict) else None
                if center:
                    if isinstance(center, dict):
                        lat = center.get("lat") or center.get("latitude")
                        lng = center.get("lng") or center.get("longitude")
                    elif isinstance(center, (list, tuple)) and len(center) >= 2:
                        lng = center[0]
                        lat = center[1]

                if lat is None or lng is None:
                    return {"error": "Pass place_name (preferred) or lat/lng to determine the study area."}

            # Capped at 7.5km (15km diameter search area) to prevent Overpass timeouts
            radius = min(int(args.get("radius_meters", 1500)), 7500)
            bbox_filter = f"(around:{radius},{lat},{lng})"

        # Construct highway tag filter
        highway_types = args.get("highway_types")
        if highway_types:
            if isinstance(highway_types, list):
                vals = [_sanitize_osm_token(h) for h in highway_types if h]
            else:
                vals = [_sanitize_osm_token(h) for h in str(highway_types).split("|") if h]
            vals = [v for v in vals if v]
            if vals:
                tag_filter = f'["highway"~"^({"|".join(vals)})$"]'
            else:
                tag_filter = '["highway"]'
        else:
            presets = {
                # Drivable public streets. 'trunk' = national/state highways (was missing before).
                "drive": "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service",
                "major": "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link",
                "arterial": "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link",
                "walk": "footway|pedestrian|path|steps|living_street|residential|unclassified|tertiary|secondary|primary|service|track",
                "cycle": "cycleway|path|residential|living_street|unclassified|tertiary|secondary|primary|service",
                "all": "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service|pedestrian|footway|cycleway|path|steps|track",
            }
            preset = str(args.get("network_type") or "drive").lower()
            chosen = presets.get(preset, presets["drive"])
            tag_filter = f'["highway"~"^({chosen})$"]'

        overpass_query = f"""
[out:json][timeout:180][maxsize:1073741824];
(
  way{tag_filter}{bbox_filter};
  relation["type"="restriction"]{bbox_filter};
);
out body;
>;
out skel qt;
"""

        try:
            data = await _overpass_post(overpass_query, timeout=200.0 if boundary is not None else 35.0)
            
            nodes: dict[int, tuple[float, float]] = {}
            ways: list[dict] = []
            restrictions: list[dict] = []
            
            for el in data.get("elements", []):
                if el["type"] == "node":
                    nodes[el["id"]] = (el.get("lon"), el.get("lat"))
                elif el["type"] == "way":
                    ways.append(el)
                elif el["type"] == "relation" and el.get("tags", {}).get("type") == "restriction":
                    restrictions.append(el)
                    
            parsed_restrictions = []
            for r in restrictions:
                tags = r.get("tags", {})
                rest_type = tags.get("restriction", "")
                from_way = None
                to_way = None
                via_node = None
                for m in r.get("members", []):
                    m_role = m.get("role")
                    m_type = m.get("type")
                    m_ref = m.get("ref")
                    if m_role == "from" and m_type == "way":
                        from_way = m_ref
                    elif m_role == "to" and m_type == "way":
                        to_way = m_ref
                    elif m_role == "via" and m_type == "node":
                        via_node = m_ref
                if from_way and to_way and via_node:
                    via_coord = nodes.get(via_node)
                    if via_coord:
                        parsed_restrictions.append({
                            "type": rest_type,
                            "from_way": from_way,
                            "to_way": to_way,
                            "via_lng": via_coord[0],
                            "via_lat": via_coord[1]
                        })

                    
            def extract_linestrings(geom):
                if geom.is_empty:
                    return []
                if geom.geom_type == "LineString":
                    return [geom]
                if geom.geom_type == "MultiLineString":
                    return list(geom.geoms)
                if geom.geom_type == "GeometryCollection":
                    lines = []
                    for g in geom.geoms:
                        lines.extend(extract_linestrings(g))
                    return lines
                return []

            features = []
            for el in ways:
                tags = el.get("tags", {})
                coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
                if len(coords) >= 2:
                    if shapely_shape:
                        from shapely.geometry import LineString as ShapelyLineString
                        try:
                            line = ShapelyLineString(coords)
                            if not line.is_valid:
                                from shapely.validation import make_valid
                                line = make_valid(line)
                                
                            if not line.intersects(shapely_shape):
                                continue
                            clipped = line.intersection(shapely_shape)
                            for part in extract_linestrings(clipped):
                                part_coords = list(part.coords)
                                if len(part_coords) >= 2:
                                    features.append({
                                        "type": "Feature",
                                        "geometry": {
                                            "type": "LineString",
                                            "coordinates": part_coords
                                        },
                                        "properties": {
                                            "osm_id": el["id"],
                                            "highway": tags.get("highway", ""),
                                            "name": tags.get("name", "unnamed"),
                                            **{k: v for k, v in tags.items() if k not in ["name", "highway"]}
                                        }
                                    })
                        except Exception as exc:
                            logger.warning(f"Clipping failed for way {el.get('id')}: {exc}")

                    else:
                        features.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": coords
                            },
                            "properties": {
                                "osm_id": el["id"],
                                "highway": tags.get("highway", ""),
                                "name": tags.get("name", "unnamed"),
                                **{k: v for k, v in tags.items() if k not in ["name", "highway"]}
                            }
                        })

            if not features:
                return {
                    "error": "No street network features were found in the study area."
                }

            stats = _street_network_stats(features, ways, nodes, shapely_shape, boundary.area_km2 if boundary else None)

            out_geojson = {
                "type": "FeatureCollection",
                "features": features,
                "restrictions": parsed_restrictions
            }

            # Slugify title for filename
            slug = "".join(c if c.isalnum() or c in "._-" else "_" for c in title.lower())
            filename = f"{slug}.geojson"
            target_path = Path(workspace) / filename

            with open(target_path, "w") as f:
                json.dump(out_geojson, f)

            result = {
                "status": "success",
                "displayed_on_map": True,
                "features_count": len(features),
                "output_layer": str(target_path),
                "title": title,
                "network_type": str(args.get("network_type") or ("custom" if args.get("highway_types") else "drive")),
                **stats,
            }
            if boundary is not None:
                result["study_area"] = boundary.summary()
                result["clipped_to_boundary"] = True
            return result

        except OverpassError as e:
            return {
                "error": f"The Overpass API server is currently busy or rate-limiting requests. Please wait a few seconds or try a smaller search area. (Details: {str(e)})"
            }
        except Exception as e:
            return {"error": f"Failed to fetch street network: {str(e)}"}

    async def _assign_traffic_flows(self, args: dict) -> dict:
        from collections import defaultdict
        workspace = _resolve_workspace(args.get("workspace", ""))
        geojson_path = args.get("geojson_path", "").strip()
        od_matrix_path = args.get("od_matrix_path", "").strip()
        title = args.get("title", "Assigned Traffic Flows").strip()
        ws = args.get("_ws")

        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        if not geojson_path:
            geojson_path = str(ws_path / "street_network.geojson")
        if not od_matrix_path:
            od_matrix_path = str(ws_path / "od_matrix.json")

        # 1. Load files
        if not Path(geojson_path).exists():
            return {"error": f"Street network file not found at: {geojson_path}. Please fetch street network first."}
        if not Path(od_matrix_path).exists():
            return {"error": f"OD matrix file not found at: {od_matrix_path}. Please import OD matrix first."}

        try:
            with open(geojson_path) as f:
                geojson = json.load(f)
            with open(od_matrix_path) as f:
                od_records = json.load(f)
        except Exception as e:
            return {"error": f"Failed to load datasets: {str(e)}"}

        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx library is not installed on the system."}

        try:
            G = _build_networkx_graph(geojson)
            if not G.nodes:
                return {"error": "GeoJSON contains no valid road nodes."}

            # 2. Get list of nodes in largest weakly connected component
            components = list(nx.weakly_connected_components(G))
            if components:
                largest_cc = max(components, key=len)
                nodes_list = list(largest_cc)
            else:
                nodes_list = list(G.nodes)

            # Helper to project coordinates onto network component nodes
            def project_node(coord: tuple[float, float]) -> tuple:
                return min(nodes_list, key=lambda n: haversine_distance((n[0], n[1]), coord))

            # 3. Initialize edge flow dictionary
            # Key format: (u, v, key)
            edge_volumes = defaultdict(float)

            # 4. Route each OD flow
            assigned_trips = 0
            routed_count = 0
            no_path_count = 0

            for record in od_records:
                origin = record.get("origin")
                dest = record.get("dest")
                trips = float(record.get("trips", 1))

                if not origin or not dest:
                    continue

                # Project
                node_a = project_node((origin[0], origin[1]))
                node_b = project_node((dest[0], dest[1]))

                if node_a == node_b:
                    continue

                try:
                    # Find shortest path using turn restrictions and weights
                    path, path_length = _find_shortest_path_with_restrictions(G, node_a, node_b)
                    
                    # Accumulate trips along path edges
                    for i in range(len(path) - 1):
                        u, v = path[i], path[i+1]
                        # Find the correct edge key in G matching this transition
                        best_key = None
                        min_w = float("inf")
                        if G.has_edge(u, v):
                            for key, data in G[u][v].items():
                                w = data.get("weight", data.get("length", 1.0))
                                if w < min_w:
                                    min_w = w
                                    best_key = key
                        if best_key is not None:
                            edge_volumes[(u, v, best_key)] += trips
                    
                    assigned_trips += trips
                    routed_count += 1
                except nx.NetworkXNoPath:
                    no_path_count += 1
                except Exception:
                    no_path_count += 1

            if not edge_volumes:
                return {"error": f"No flows could be successfully routed. Project mapped {len(od_records)} rows; {no_path_count} failed pathfinding."}

            # 5. Build GeoJSON representing the assigned flow lines
            max_volume = max(edge_volumes.values())
            min_volume = min(edge_volumes.values())

            def get_stroke_width(vol: float) -> float:
                if max_volume == min_volume:
                    return 3.0
                return 1.5 + 6.5 * (vol - min_volume) / (max_volume - min_volume)

            # Map the aggregated volumes back onto the original GeoJSON features
            out_features = []
            for u, v, key, data in G.edges(keys=True, data=True):
                vol = edge_volumes.get((u, v, key), 0.0)
                if vol <= 0.0:
                    continue

                # Reconstruct geometry
                coords = list(data.get("geometry", {}).get("coordinates", [u[:2], v[:2]]))
                props = {**data}
                if "geometry" in props:
                    del props["geometry"]
                props["assigned_volume"] = round(vol, 1)
                props["stroke_width"] = round(get_stroke_width(vol), 1)

                out_features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": props
                })

            out_geojson = {
                "type": "FeatureCollection",
                "features": out_features
            }

            out_path = ws_path / "assigned_traffic_flows.geojson"
            with open(out_path, "w") as f:
                json.dump(out_geojson, f, indent=2)

            # 6. Find top bottleneck streets (group by name)
            street_volumes = defaultdict(float)
            for (u, v, key), vol in edge_volumes.items():
                name = G[u][v][key].get("name", "Unnamed Street")
                street_volumes[name] = max(street_volumes[name], vol)

            sorted_streets = sorted(street_volumes.items(), key=lambda x: x[1], reverse=True)
            top_bottlenecks = [
                {"street_name": name, "peak_volume": round(vol, 1)}
                for name, vol in sorted_streets[:5]
            ]

            # 7. Dispatch action
            if ws:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(out_path),
                        "name": title
                    }
                }))

            return {
                "status": "success",
                "displayed_on_map": True,
                "trips_assigned": assigned_trips,
                "flows_routed": routed_count,
                "flows_failed": no_path_count,
                "flow_stats": {
                    "min_edge_volume": round(min_volume, 1),
                    "max_edge_volume": round(max_volume, 1),
                    "average_edge_volume": round(sum(edge_volumes.values()) / len(edge_volumes), 1)
                },
                "top_bottlenecks": top_bottlenecks,
                "output_layer": str(out_path)
            }

        except Exception as e:
            return {"error": f"Traffic assignment failed: {str(e)}"}
