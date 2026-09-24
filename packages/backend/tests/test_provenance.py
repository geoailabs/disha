import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import json
import pytest
from tools.provenance import (
    create_source_entry_from_tool,
    extract_sources_from_markdown,
    synthesize_sources_section,
    SourceEntry,
)
from tools.artifact_store import save_artifact, read_artifact


def test_create_source_entry_from_tool():
    """Verify tool telemetry mapping for common spatial & analytical tools."""
    # 1. OSM Boundary
    entry_osm = create_source_entry_from_tool("osm_boundary", {"name": "South Delhi"})
    assert entry_osm is not None
    assert "OpenStreetMap" in entry_osm["name"]
    assert entry_osm["category"] == "Geospatial Vector"
    assert "South Delhi" in entry_osm["query_scope"]

    # 2. WorldPop population
    entry_wp = create_source_entry_from_tool("worldpop_population", {"place_name": "Sector 17"})
    assert entry_wp is not None
    assert "WorldPop" in entry_wp["name"]
    assert entry_wp["category"] == "Raster Demographics"
    assert "100m" in entry_wp["basis_or_assumptions"]

    # 3. Route
    entry_route = create_source_entry_from_tool("route", {"origin": "Point A", "destination": "Point B"})
    assert entry_route is not None
    assert "OSRM" in entry_route["name"]
    assert entry_route["category"] == "Mobility & Transportation"
    assert "Dijkstra" in entry_route["basis_or_assumptions"]


def test_extract_sources_from_markdown_table():
    """Verify parsing of structured markdown sources tables."""
    content = (
        "# Regional Study\n\n"
        "Summary findings of the area.\n\n"
        "## Data Sources & Methodology\n\n"
        "| Data Source / Tool | Category | Provider / Endpoint | Query Scope & Parameters | Date / Timestamp | Analytical Basis & Assumptions |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| **OpenStreetMap Administrative Boundary** | Geospatial Vector | `OpenStreetMap` | South Delhi | 2026-09-22 | Geodesic area calculated on WGS84 |\n"
        "| **WorldPop 100m Population** | Raster Demographics | `WorldPop API` | Study Buffer | 2026-09-22 | 100m raster aggregation |\n"
    )
    sources = extract_sources_from_markdown(content)
    assert len(sources) == 2
    assert sources[0]["name"] == "OpenStreetMap Administrative Boundary"
    assert sources[0]["category"] == "Geospatial Vector"
    assert "South Delhi" in sources[0]["query_scope"]
    assert "Geodesic" in sources[0]["basis_or_assumptions"]

    assert sources[1]["name"] == "WorldPop 100m Population"
    assert sources[1]["category"] == "Raster Demographics"


def test_extract_sources_from_markdown_bullets():
    """Verify parsing of bulleted markdown sources sections."""
    content = (
        "# Land Use Report\n\n"
        "## Sources & Methodology\n"
        "- **OpenStreetMap**: Overpass API querying amenity=school within boundary.\n"
        "- **URDPFI Guidelines**: Minimum 10% open space allocation standard.\n"
    )
    sources = extract_sources_from_markdown(content)
    assert len(sources) == 2
    assert sources[0]["name"] == "OpenStreetMap"
    assert "Overpass" in sources[0]["basis_or_assumptions"]
    assert sources[1]["name"] == "URDPFI Guidelines"
    assert "URDPFI" in sources[1]["basis_or_assumptions"] or "10%" in sources[1]["basis_or_assumptions"]


def test_synthesize_sources_section_auto_appends():
    """Verify that synthesize_sources_section appends markdown and returns structured sources when section is missing."""
    initial_content = "# Urban Mobility Assessment\n\nThe corridor experiences heavy peak traffic."
    telemetry = [
        SourceEntry(
            name="OSRM Route Corridor",
            category="Mobility & Transportation",
            provider="OSRM API",
            query_scope="Origin: Airport, Dest: CBD",
            timestamp="2026-09-22 10:00 UTC",
            basis_or_assumptions="Topological road network shortest path",
        )
    ]

    updated_content, merged = synthesize_sources_section(telemetry, initial_content)
    assert "## Data Sources & Methodology" in updated_content
    assert "[**OSRM Route Corridor**](https://project-osrm.org)" in updated_content
    assert len(merged) == 1
    assert merged[0]["name"] == "OSRM Route Corridor"
    assert merged[0]["url"] == "https://project-osrm.org"


def test_artifact_store_sources_persistence(tmp_path):
    """Verify SQLite persistence of meta.sources through save_artifact and read_artifact."""
    ws = str(tmp_path / "workspace")
    content = (
        "# Zoning Brief\n\n"
        "## Data Sources & Methodology\n\n"
        "| Data Source / Tool | Category | Provider / Endpoint | Query Scope & Parameters | Date / Timestamp | Analytical Basis & Assumptions |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| **Master Plan 2041** | Planning Regulations | `Local Authority` | Sector 5 | 2026-09-22 | Permissible FAR 2.5 |\n"
    )

    saved = save_artifact(
        title="Zoning Brief",
        artifact_type="report",
        format="markdown",
        content=content,
        workspace=ws,
    )

    art_id = saved["id"]
    retrieved = read_artifact(art_id, workspace=ws)
    assert retrieved is not None
    assert retrieved["meta"] is not None
    meta_dict = json.loads(retrieved["meta"])
    assert "sources" in meta_dict
    assert len(meta_dict["sources"]) == 1
    assert meta_dict["sources"][0]["name"] == "Master Plan 2041"
    assert "FAR 2.5" in meta_dict["sources"][0]["basis_or_assumptions"]
    assert meta_dict["sources"][0].get("url")  # verified URL resolved


def test_extract_sources_with_markdown_links():
    """Verify that extract_sources_from_markdown accurately extracts URL hyperlinks."""
    content = (
        "# Environmental Summary\n\n"
        "## Data Sources & Methodology\n\n"
        "| Data Source / Tool | Category | Provider / Endpoint | Query Scope & Parameters | Date / Timestamp | Analytical Basis & Assumptions |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| [**Open-Meteo Air Quality**](https://open-meteo.com/en/docs/air-quality-api) | Air Quality | [`Copernicus CAMS`](https://open-meteo.com) | Delhi NCR | 2026-09-22 | CAMS atmospheric models |\n"
    )
    sources = extract_sources_from_markdown(content)
    assert len(sources) == 1
    assert sources[0]["name"] == "Open-Meteo Air Quality"
    assert sources[0]["url"] == "https://open-meteo.com/en/docs/air-quality-api"


def test_synthesize_sources_generates_clickable_links():
    """Verify that synthesize_sources_section includes markdown hyperlinks in table output."""
    initial = "# Weather Report\n\nWeather report details..."
    telemetry = [
        SourceEntry(
            name="Open-Meteo Weather Forecast",
            category="Meteorological & Climate",
            provider="Open-Meteo Weather API",
            query_scope="Delhi NCR",
            timestamp="2026-09-22",
            basis_or_assumptions="Numerical weather prediction",
            url="https://open-meteo.com/en/docs",
        )
    ]
    updated, sources = synthesize_sources_section(telemetry, initial)
    assert "[**Open-Meteo Weather Forecast**](https://open-meteo.com/en/docs)" in updated
    assert len(sources) == 1
    assert sources[0]["url"] == "https://open-meteo.com/en/docs"
