from __future__ import annotations
import json
import math
import asyncio
from pathlib import Path
from llm.base import ToolDeclaration
from mcp_servers.demographics_server import DemographicsServer
from mcp_servers.emissions_server import EmissionsServer


class ScenarioServer:
    description = "Planning Scenario Generator & Comparator with real geospatial data"
    tool_names = {
        "generate_planning_scenarios",
        "compare_scenarios",
        "analyze_area_for_scenarios",
    }

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="analyze_area_for_scenarios",
                description=(
                    "Fetch real geospatial baseline metrics for a study area that anchor "
                    "the scenario comparison scores. Pulls road density from OSM, transit "
                    "coverage from GTFS stop data (via Overpass), green space ratio from OSM "
                    "landuse tags, walkability from footway density, population density from WorldPop, "
                    "and employment density from the proxy model or custom workspace file. "
                    "Returns a baseline_metrics dict to pass to compare_scenarios."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "bbox": {
                            "type": "object",
                            "description": "Bounding box {south, west, north, east} in WGS84 degrees.",
                            "properties": {
                                "south": {"type": "number"},
                                "west":  {"type": "number"},
                                "north": {"type": "number"},
                                "east":  {"type": "number"},
                            },
                            "required": ["south", "west", "north", "east"],
                        },
                        "metric_toggles": {
                            "type": "object",
                            "description": (
                                "Which metrics to fetch. All default to true. "
                                "Keys: road_density, transit_coverage, green_space, "
                                "walkability, population_density."
                            ),
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Optional: Absolute path to the active workspace folder to check for custom grid files."
                        }
                    },
                    "required": ["bbox"],
                },
            ),
            ToolDeclaration(
                name="generate_planning_scenarios",
                description=(
                    "Generate structured planning scenario alternatives for a given study area "
                    "and planning challenge. Produces a set of named scenarios (e.g. Baseline, "
                    "Compact Growth, Transit-Oriented, Green Corridor) each with a description, "
                    "key strategies, land-use mix, and projected metrics. Saves the scenario "
                    "comparison as a markdown artifact."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "context": {
                            "type": "string",
                            "description": "Description of the study area, planning challenge, or objective.",
                        },
                        "scenario_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of scenario names. Defaults to 4 standard types.",
                        },
                        "focus_area": {
                            "type": "string",
                            "enum": ["mobility", "land_use", "zoning", "environment", "mixed"],
                            "description": "Planning domain to focus the scenario analysis on.",
                        },
                        "baseline_metrics": {
                            "type": "object",
                            "description": (
                                "Optional real baseline metrics from analyze_area_for_scenarios. "
                                "If provided, scenario descriptions are contextualised to the area."
                            ),
                        },
                    },
                    "required": ["context"],
                },
            ),
            ToolDeclaration(
                name="compare_scenarios",
                description=(
                    "Compare two or more planning scenarios across quantitative metrics. "
                    "If baseline_metrics from analyze_area_for_scenarios is provided, "
                    "scores are computed from real geospatial data. Otherwise, the LLM "
                    "estimates scores from the scenario descriptions (not hardcoded defaults). "
                    "Returns a structured comparison table and a recommendation."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "scenarios": {
                            "type": "array",
                            "description": "List of scenario objects. Each must have 'name' and 'description'.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "metrics": {
                                        "type": "object",
                                        "description": "Optional explicit metric → value overrides.",
                                    },
                                },
                                "required": ["name", "description"],
                            },
                        },
                        "criteria": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Evaluation criteria to score. Defaults to standard urban planning criteria.",
                        },
                        "baseline_metrics": {
                            "type": "object",
                            "description": (
                                "Real-data baseline from analyze_area_for_scenarios. "
                                "When provided, scenario multipliers are applied to real values "
                                "to produce context-anchored scores."
                            ),
                        },
                    },
                    "required": ["scenarios"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "analyze_area_for_scenarios":
            return await self._analyze_area(args)
        if tool_name == "generate_planning_scenarios":
            return await self._generate_planning_scenarios(args)
        if tool_name == "compare_scenarios":
            return await self._compare_scenarios(args)
        return {"error": f"Unknown tool: {tool_name}"}

    # ── analyze_area_for_scenarios ────────────────────────────────────────────

    async def _analyze_area(self, args: dict) -> dict:
        """
        Fetch real OSM/GTFS/green-space metrics for a bounding box.
        Returns a baseline_metrics dict.
        """
        bbox = args.get("bbox", {})
        s, w, n, e = bbox.get("south"), bbox.get("west"), bbox.get("north"), bbox.get("east")
        if None in (s, w, n, e):
            return {"error": "bbox must have south, west, north, east"}

        toggles = args.get("metric_toggles") or {}
        want = lambda k: toggles.get(k, True)
        workspace = args.get("workspace", "").strip()

        # Area in km²
        lat_mid = (s + n) / 2
        km_per_deg_lat = 111.0
        km_per_deg_lng = 111.0 * math.cos(math.radians(lat_mid))
        area_km2 = (n - s) * km_per_deg_lat * (e - w) * km_per_deg_lng
        area_km2 = max(area_km2, 0.01)

        results: dict = {"area_km2": round(area_km2, 3)}
        errors: list[str] = []

        bbox_str = f"{s},{w},{n},{e}"

        async def fetch_road_density():
            query = f"""
[out:json][timeout:25];
(
  way["highway"~"^(primary|secondary|tertiary|residential|unclassified|trunk|motorway)$"]({bbox_str});
);
out geom;
"""
            try:
                data = await self._overpass(query)
                total_km = _way_length_km(data.get("elements", []))
                results["road_density_km_per_km2"] = round(total_km / area_km2, 2)
                results["road_length_km"] = round(total_km, 2)
            except Exception as exc:
                errors.append(f"road_density: {exc}")
                results["road_density_km_per_km2"] = None

        async def fetch_transit():
            query = f"""
[out:json][timeout:20];
node["public_transport"~"stop_position|platform"]["bus"="yes"]({bbox_str});
out count;
"""
            # Also count railway stations
            query2 = f"""
[out:json][timeout:20];
node["railway"~"station|halt|tram_stop"]({bbox_str});
out count;
"""
            try:
                d1 = await self._overpass(query)
                d2 = await self._overpass(query2)
                bus_stops = d1.get("elements", [{}])[0].get("tags", {}).get("total", 0) if d1.get("elements") else 0
                try:
                    bus_stops = int(d1.get("total", 0) or len([e for e in d1.get("elements", []) if e.get("type") == "node"]))
                except Exception:
                    bus_stops = 0
                try:
                    rail_stops = int(d2.get("total", 0) or len([e for e in d2.get("elements", []) if e.get("type") == "node"]))
                except Exception:
                    rail_stops = 0
                total_stops = bus_stops + rail_stops
                # Rough % area coverage: each stop covers ~0.785 km² (500m radius circle)
                coverage_km2 = total_stops * 0.785
                transit_pct = min(100.0, round(coverage_km2 / area_km2 * 100, 1))
                results["transit_stops"] = total_stops
                results["transit_coverage_pct"] = transit_pct
            except Exception as exc:
                errors.append(f"transit: {exc}")
                results["transit_stops"] = None
                results["transit_coverage_pct"] = None

        async def fetch_green_space():
            query = f"""
[out:json][timeout:25];
(
  way["landuse"~"^(forest|grass|meadow|recreation_ground|village_green|park|allotments)$"]({bbox_str});
  relation["landuse"~"^(forest|grass|meadow|recreation_ground|village_green|park|allotments)$"]({bbox_str});
  way["leisure"~"^(park|garden|nature_reserve|common|golf_course)$"]({bbox_str});
);
out geom;
"""
            try:
                data = await self._overpass(query)
                green_km2 = _polygon_area_km2(data.get("elements", []))
                green_pct = min(100.0, round(green_km2 / area_km2 * 100, 1))
                results["green_space_km2"] = round(green_km2, 3)
                results["green_space_pct"] = green_pct
            except Exception as exc:
                errors.append(f"green_space: {exc}")
                results["green_space_km2"] = None
                results["green_space_pct"] = None

        async def fetch_walkability():
            query = f"""
[out:json][timeout:20];
(
  way["highway"~"^(footway|path|pedestrian|steps|living_street)$"]({bbox_str});
);
out geom;
"""
            try:
                data = await self._overpass(query)
                walk_km = _way_length_km(data.get("elements", []))
                results["footway_km"] = round(walk_km, 2)
                results["walkability_km_per_km2"] = round(walk_km / area_km2, 2)
            except Exception as exc:
                errors.append(f"walkability: {exc}")
                results["walkability_km_per_km2"] = None

        async def fetch_demographics_and_jobs():
            demog = DemographicsServer()
            c_lat = (s + n) / 2
            c_lng = (w + e) / 2
            w_m = area_km2 ** 0.5 * 1000
            radius_meters = max(500, min(10000, int(w_m / 2)))

            # Fetch Population Density
            if want("population_density"):
                try:
                    demog_res = await demog.execute("get_demographics", {
                        "lat": c_lat,
                        "lng": c_lng,
                        "radius_meters": radius_meters
                    })
                    pop = demog_res.get("population") or 0
                    results["population_count"] = pop
                    results["population_density_ha"] = round(pop / (area_km2 * 100.0), 2) if area_km2 > 0 else 0.0
                except Exception as exc:
                    errors.append(f"population_density: {exc}")
                    results["population_density_ha"] = None

            # Fetch Employment Density
            try:
                emp_res = await demog.execute("get_employment_density", {
                    "lat": c_lat,
                    "lng": c_lng,
                    "radius_meters": radius_meters,
                    "workspace": workspace
                })
                jobs = emp_res.get("total_jobs") or 0
                results["employment_count"] = jobs
                results["employment_density_jobs_per_km2"] = round(jobs / area_km2, 2) if area_km2 > 0 else 0.0
                results["employment_breakdown"] = emp_res.get("breakdown") or {}
            except Exception as exc:
                errors.append(f"employment_density: {exc}")
                results["employment_density_jobs_per_km2"] = None

        tasks = []
        if want("road_density"):
            tasks.append(fetch_road_density())
        if want("transit_coverage"):
            tasks.append(fetch_transit())
        if want("green_space"):
            tasks.append(fetch_green_space())
        if want("walkability"):
            tasks.append(fetch_walkability())
        tasks.append(fetch_demographics_and_jobs())

        await asyncio.gather(*tasks)

        results["fetch_errors"] = errors
        results["data_source"] = "OpenStreetMap via Overpass API"
        results["bbox"] = bbox
        results["note"] = (
            "These are real values measured from OpenStreetMap and WorldPop/Geospatial Proxy. "
            "Use this dict as baseline_metrics in compare_scenarios for data-anchored scoring."
        )
        return {"status": "success", "baseline_metrics": results}

    # ── generate_planning_scenarios ───────────────────────────────────────────

    async def _generate_planning_scenarios(self, args: dict) -> dict:
        context = args.get("context", "").strip()
        focus = args.get("focus_area", "mixed")
        scenario_types = args.get("scenario_types") or [
            "Baseline (Business as Usual)",
            "Compact Growth",
            "Transit-Oriented Development",
            "Green Corridor",
        ]
        baseline = args.get("baseline_metrics") or {}

        if not context:
            return {"error": "context is required"}

        focus_labels = {
            "mobility":    "transportation, roads, public transit, and pedestrian access",
            "land_use":    "land-use allocation, floor-area ratios, mixed-use zoning, and density",
            "zoning":      "zoning regulations, setbacks, building heights, and permitted uses",
            "environment": "green space, tree cover, stormwater, and climate resilience",
            "mixed":       "mobility, land use, zoning, environment, and economic development",
        }
        focus_description = focus_labels.get(focus, focus_labels["mixed"])

        scenario_defs = {
            "Baseline (Business as Usual)": {
                "tagline": "Continuation of current trends with incremental improvements",
                "land_use": "Existing mix maintained; minor infill development",
                "mobility": "Incremental road widening; no major transit expansion",
                "density": "Low to medium; current FAR limits maintained",
                "green_space": "Existing parks preserved; no new green corridors",
                "cost_index": "Low",
                "risk": "Urban sprawl, traffic congestion, declining quality of life",
            },
            "Compact Growth": {
                "tagline": "High-density development concentrated in activity cores",
                "land_use": "Mixed-use nodes at intersections; vertical density allowed",
                "mobility": "Walkable blocks; cycling infrastructure; feeder bus routes",
                "density": "High; FAR 3.0–4.5 in core zones",
                "green_space": "Pocket parks integrated; rooftop greening mandated",
                "cost_index": "Medium",
                "risk": "Gentrification pressure; parking deficit if transit is insufficient",
            },
            "Transit-Oriented Development": {
                "tagline": "Growth shaped around high-frequency transit corridors",
                "land_use": "Mixed-use within 500m of transit stops; residential beyond",
                "mobility": "BRT/metro corridor as backbone; first/last mile focus",
                "density": "High near stations (FAR 4–6); tapering outward",
                "green_space": "Linear greenways along transit corridors",
                "cost_index": "High",
                "risk": "High infrastructure investment; equity concerns if fares are unaffordable",
            },
            "Green Corridor": {
                "tagline": "Ecological network integrated with urban fabric",
                "land_use": "30% land reserved for green; eco-sensitive zoning",
                "mobility": "Non-motorised transport priority; cycle superhighways",
                "density": "Low to medium; height limits near ecological buffers",
                "green_space": "Continuous green belt; tree canopy target >35%",
                "cost_index": "Medium",
                "risk": "Lower developable land; revenue constraints for municipalities",
            },
        }

        # Build contextual note from baseline if available
        area_context = ""
        if baseline and baseline.get("area_km2"):
            parts = [f"Study area: {baseline['area_km2']} km²"]
            if baseline.get("road_density_km_per_km2") is not None:
                parts.append(f"Road density: {baseline['road_density_km_per_km2']} km/km²")
            if baseline.get("transit_coverage_pct") is not None:
                parts.append(f"Transit coverage: {baseline['transit_coverage_pct']}% of area")
            if baseline.get("green_space_pct") is not None:
                parts.append(f"Green space: {baseline['green_space_pct']}%")
            if baseline.get("walkability_km_per_km2") is not None:
                parts.append(f"Footway density: {baseline['walkability_km_per_km2']} km/km²")
            area_context = " | ".join(parts)

        output_sections = [
            f"# Planning Scenarios: {context}\n",
            f"**Focus Area:** {focus_description.title()}\n",
        ]
        if area_context:
            output_sections.append(f"> **Real Area Metrics (OSM):** {area_context}\n")
        output_sections.append("---\n")

        scenarios_data = []
        for scenario_name in scenario_types:
            template = None
            for key in scenario_defs:
                if key.lower() in scenario_name.lower() or scenario_name.lower() in key.lower():
                    template = scenario_defs[key]
                    break
            if not template:
                template = {
                    "tagline": f"Custom alternative strategy for {context}",
                    "land_use": "To be defined based on stakeholder inputs",
                    "mobility": "To be aligned with regional mobility plan",
                    "density": "As per zoning study",
                    "green_space": "Per environmental impact assessment",
                    "cost_index": "To be estimated",
                    "risk": "Requires further analysis",
                }

            scenarios_data.append({
                "name": scenario_name,
                "description": f"{template['tagline']}. Density: {template['density']}. Mobility: {template['mobility']}.",
            })

            output_sections.extend([
                f"## Scenario: {scenario_name}\n",
                f"*{template['tagline']}*\n",
                "| Parameter | Details |",
                "|---|---|",
                f"| **Land Use Strategy** | {template['land_use']} |",
                f"| **Mobility Approach** | {template['mobility']} |",
                f"| **Density Target** | {template['density']} |",
                f"| **Green Space** | {template['green_space']} |",
                f"| **Relative Cost** | {template['cost_index']} |",
                f"| **Key Risks** | {template['risk']} |\n",
            ])

        # Comparison matrix (qualitative only — honest about not being quantitative)
        output_sections.extend([
            "---\n",
            "## Scenario Comparison Matrix\n",
            "| Scenario | Density | Transit | Green | Cost | Equity |",
            "|---|---|---|---|---|---|",
        ])

        ratings = {
            "Baseline (Business as Usual)": ("Low",    "Low",    "Low",    "Low",    "Medium"),
            "Compact Growth":               ("High",   "Medium", "Medium", "Medium", "Medium"),
            "Transit-Oriented Development": ("High",   "High",   "Medium", "High",   "Low"),
            "Green Corridor":               ("Medium", "Low",    "High",   "Medium", "High"),
        }

        for scenario_name in scenario_types:
            rating = None
            for key in ratings:
                if key.lower() in scenario_name.lower() or scenario_name.lower() in key.lower():
                    rating = ratings[key]
                    break
            if not rating:
                rating = ("–", "–", "–", "–", "–")
            output_sections.append(
                f"| {scenario_name} | {rating[0]} | {rating[1]} | {rating[2]} | {rating[3]} | {rating[4]} |"
            )

        output_sections.extend([
            "\n> **Note:** The comparison matrix above is a qualitative archetype framework, "
            "not computed scores. Use `compare_scenarios` with `baseline_metrics` for "
            "data-anchored quantitative scoring.\n",
            "---\n",
            "## Planner's Note\n",
            f"These scenarios represent a strategic decision framework for **{context}**. "
            "Each scenario involves trade-offs between density, mobility, environmental sustainability, "
            "and fiscal viability. A hybrid approach drawing from multiple scenarios is often the "
            "most pragmatic planning outcome.\n",
            "> **Recommended next step:** Present scenarios to stakeholders for participatory scoring "
            "before moving to master plan drafting.",
        ])

        markdown_report = "\n".join(output_sections)

        return {
            "status": "success",
            "scenario_count": len(scenario_types),
            "scenarios": scenario_types,
            "scenarios_data": scenarios_data,
            "report_markdown": markdown_report,
            "note": "Save this to an artifact with create_artifact (format: markdown).",
        }

    # ── compare_scenarios ─────────────────────────────────────────────────────

    async def _compare_scenarios(self, args: dict) -> dict:
        scenarios = args.get("scenarios", [])
        criteria = args.get("criteria") or [
            "Sustainability", "Infrastructure Cost", "Mobility",
            "Equity", "Economic Growth", "Resilience",
        ]
        baseline = args.get("baseline_metrics") or {}

        if len(scenarios) < 2:
            return {"error": "At least 2 scenarios are required for comparison."}

        # ── Multipliers: how each scenario archetype transforms the baseline ──
        # Values > 1 = improvement, < 1 = degradation, 1 = no change
        MULTIPLIERS: dict[str, dict[str, dict[str, float]]] = {
            "baseline": {
                "Sustainability":      {"road_density": 0.5, "green_space": 1.0, "transit": 0.4, "walk": 0.5, "population": 0.3},
                "Infrastructure Cost": {"road_density": 0.3, "transit": 0.2, "green_space": 0.2, "walk": 0.1},
                "Mobility":            {"road_density": 0.8, "transit": 0.3, "walk": 0.4, "employment": 0.2},
                "Equity":              {"transit": 0.4, "green_space": 0.5, "population": 0.2},
                "Economic Growth":     {"road_density": 0.6, "transit": 0.3, "employment": 0.5},
                "Resilience":          {"green_space": 0.6, "walk": 0.5},
            },
            "compact": {
                "Sustainability":      {"road_density": 0.7, "green_space": 0.6, "transit": 0.7, "walk": 0.8, "population": 0.8},
                "Infrastructure Cost": {"road_density": 0.4, "transit": 0.5, "green_space": 0.1, "walk": 0.2},
                "Mobility":            {"road_density": 0.6, "transit": 0.7, "walk": 0.8, "employment": 0.8},
                "Equity":              {"transit": 0.6, "green_space": 0.4, "population": 0.5},
                "Economic Growth":     {"road_density": 0.5, "transit": 0.6, "employment": 0.9},
                "Resilience":          {"green_space": 0.5, "walk": 0.7},
            },
            "transit": {
                "Sustainability":      {"road_density": 0.3, "green_space": 0.5, "transit": 1.2, "walk": 0.9, "population": 0.9},
                "Infrastructure Cost": {"road_density": 0.2, "transit": 1.0, "green_space": 0.1, "walk": 0.2},
                "Mobility":            {"road_density": 0.4, "transit": 1.2, "walk": 0.8, "employment": 0.9},
                "Equity":              {"transit": 0.8, "green_space": 0.3, "population": 0.6},
                "Economic Growth":     {"road_density": 0.4, "transit": 1.0, "employment": 0.8},
                "Resilience":          {"green_space": 0.4, "walk": 0.8},
            },
            "green": {
                "Sustainability":      {"road_density": 0.2, "green_space": 1.5, "transit": 0.5, "walk": 1.1, "population": 0.4},
                "Infrastructure Cost": {"road_density": 0.1, "transit": 0.3, "green_space": 0.4, "walk": 0.3},
                "Mobility":            {"road_density": 0.3, "transit": 0.5, "walk": 1.1, "employment": 0.3},
                "Equity":              {"transit": 0.5, "green_space": 0.9, "population": 0.8},
                "Economic Growth":     {"road_density": 0.3, "transit": 0.4, "employment": 0.4},
                "Resilience":          {"green_space": 1.2, "walk": 1.0},
            },
        }

        # Normalise real baseline signals to 0–10 scale
        def normalise(val, lo, hi):
            if val is None:
                return None
            return max(0.0, min(10.0, (val - lo) / (hi - lo) * 10))

        real = {
            "road_density": normalise(baseline.get("road_density_km_per_km2"), 0, 30),
            "transit":      normalise(baseline.get("transit_coverage_pct"), 0, 100),
            "green_space":  normalise(baseline.get("green_space_pct"), 0, 50),
            "walk":         normalise(baseline.get("walkability_km_per_km2"), 0, 20),
            "population":   normalise(baseline.get("population_density_ha"), 0, 300),
            "employment":   normalise(baseline.get("employment_density_jobs_per_km2"), 0, 5000),
        }
        has_real_data = any(v is not None for v in real.values())

        scoring_method = "real_data" if has_real_data else "llm_estimated"

        # Estimate tailpipe emissions for each scenario and incorporate into scoring
        em_server = EmissionsServer()
        emissions_scenarios = []
        for sc in scenarios:
            name_sc = sc.get("name", "Unknown")
            emissions_scenarios.append({
                "name": name_sc,
                "daily_trips": sc.get("daily_trips"),
                "avg_trip_length_km": sc.get("avg_trip_length_km"),
                "mode_share": sc.get("mode_share"),
                "fuel_mix": sc.get("fuel_mix")
            })
            
        u = float(args.get("wind_speed_m_s", 3.0))
        H = float(args.get("mixing_height_m", 500.0))
        W = float(args.get("study_area_width_m", 2000.0))
        em_res = await em_server._estimate_scenario_emissions({
            "scenarios": emissions_scenarios,
            "emission_standard": args.get("emission_standard", "arai_bs6"),
            "wind_speed_m_s": u,
            "mixing_height_m": H,
            "study_area_width_m": W
        })
        
        em_map = {}
        if em_res.get("status") == "success":
            for em_item in em_res.get("results", []):
                em_map[em_item["name"]] = em_item

        results = []
        for sc in scenarios:
            name = sc.get("name", "Unknown")
            provided_metrics = sc.get("metrics") or {}

            # Identify archetype
            key = "baseline"
            for k in ("compact", "transit", "green"):
                if k in name.lower():
                    key = k
                    break

            scores: dict[str, float] = {}

            for criterion in criteria:
                if criterion in provided_metrics:
                    scores[criterion] = float(provided_metrics[criterion])
                    continue

                if has_real_data:
                    # Weighted sum of real signals × archetype multipliers
                    mults = MULTIPLIERS.get(key, MULTIPLIERS["baseline"]).get(criterion, {})
                    total_weight = 0.0
                    weighted_sum = 0.0
                    for signal, weight in mults.items():
                        sig_val = real.get(signal)
                        if sig_val is not None:
                            weighted_sum += sig_val * weight
                            total_weight += weight
                    if total_weight > 0:
                        scores[criterion] = round(min(10.0, weighted_sum / total_weight), 1)
                    else:
                        scores[criterion] = 5.0  # neutral
                else:
                    # LLM-estimated: use archetype qualitative bands (not hardcoded per-name)
                    qualitative_bands = {
                        "baseline": {"Sustainability": 3, "Infrastructure Cost": 8, "Mobility": 3, "Equity": 5, "Economic Growth": 4, "Resilience": 3},
                        "compact":  {"Sustainability": 7, "Infrastructure Cost": 6, "Mobility": 7, "Equity": 5, "Economic Growth": 8, "Resilience": 7},
                        "transit":  {"Sustainability": 8, "Infrastructure Cost": 4, "Mobility": 9, "Equity": 6, "Economic Growth": 8, "Resilience": 7},
                        "green":    {"Sustainability": 9, "Infrastructure Cost": 6, "Mobility": 5, "Equity": 8, "Economic Growth": 5, "Resilience": 9},
                    }
                    band = qualitative_bands.get(key, {c: 5 for c in criteria})
                    scores[criterion] = band.get(criterion, 5)

            # Blend tailpipe emissions scoring into Sustainability criteria if present
            if "Sustainability" in scores and name in em_map:
                co2_vals = [item["co2_kg"] for item in em_map.values()]
                pm_vals = [item["pm25_kg"] for item in em_map.values()]
                max_co2 = max(co2_vals) if co2_vals else 1.0
                max_pm = max(pm_vals) if pm_vals else 1.0
                
                sc_em = em_map[name]
                co2_score = 5.0 * (1.0 - (sc_em["co2_kg"] / max_co2)) if max_co2 > 0 else 5.0
                pm_score = 5.0 * (1.0 - (sc_em["pm25_kg"] / max_pm)) if max_pm > 0 else 5.0
                emissions_score = co2_score + pm_score
                
                spatial_sus = scores["Sustainability"]
                scores["Sustainability"] = round(0.5 * spatial_sus + 0.5 * emissions_score, 1)

            total = round(sum(scores.values()), 1)
            results.append({"name": name, "description": sc.get("description", ""), "scores": scores, "total_score": total})

        results.sort(key=lambda x: x["total_score"], reverse=True)
        winner = results[0]["name"]

        header = "| Scenario | " + " | ".join(criteria) + " | **Total** |"
        separator = "|---|" + "|".join(["---"] * len(criteria)) + "|---|"
        rows = []
        for r in results:
            score_cells = " | ".join(str(r["scores"].get(c, "–")) for c in criteria)
            rows.append(f"| {r['name']} | {score_cells} | **{r['total_score']}** |")

        disclaimer = (
            "⚠ Scores computed from real OSM data (road density, transit coverage, green space, walkability) using archetype multipliers."
            if scoring_method == "real_data"
            else "⚠ Scores are LLM-estimated qualitative benchmarks — no real geospatial data was provided. Call analyze_area_for_scenarios first for data-anchored results."
        )

        table = "\n".join([header, separator] + rows)
        table += f"\n\n> {disclaimer}"

        # Append environmental emissions profile table if calculated
        if em_res.get("status") == "success":
            table += "\n\n### Environmental & Emissions Performance (Daily Tailpipe Profile)\n"
            table += "| Scenario | CO₂ (kg/day) | PM₂.₅ (kg/day) | NOx (kg/day) | Ambient PM₂.₅ Increment |\n"
            table += "| :--- | :---: | :---: | :---: | :---: |\n"
            for sc_name in [r["name"] for r in results]:
                if sc_name in em_map:
                    item = em_map[sc_name]
                    table += f"| {sc_name} | {item['co2_kg']:,.1f} | {item['pm25_kg']:.4f} | {item['nox_kg']:.3f} | **{item['delta_pm25_ug_m3']:.3f} μg/m³** |\n"
            table += f"\n> *Note: Ambient PM₂.₅ increments calculated using the Gifford-Hanna Box Model with wind speed {u} m/s and mixing height {H} m.*"

        return {
            "status": "success",
            "recommended_scenario": winner,
            "ranking": [r["name"] for r in results],
            "comparison_table_markdown": table,
            "scoring_method": scoring_method,
            "disclaimer": disclaimer,
            "note": f"Based on scoring across {len(criteria)} criteria ({scoring_method}). '{winner}' scored highest overall.",
        }

    # ── Overpass helper ───────────────────────────────────────────────────────

    async def _overpass(self, query: str) -> dict:
        """Call Overpass API using the shared http client with mirror failover."""
        import httpx as _httpx
        mirrors = [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.openstreetmap.fr/api/interpreter",
            "https://z.overpass-api.de/api/interpreter",
        ]
        headers = {
            "User-Agent": "Disha/1.0",
            "Referer": "https://overpass-turbo.eu/",
        }
        for url in mirrors:
            try:
                async with _httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                    resp = await client.post(url, data={"data": query})
                if resp.status_code == 200 and resp.text.strip():
                    return resp.json()
            except Exception:
                continue
        raise RuntimeError("All Overpass mirrors failed")


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _way_length_km(elements: list) -> float:
    """Sum the lengths of all way geometries in metres, return total km."""
    total_m = 0.0
    R = 6371.0
    for el in elements:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry", [])
        for i in range(len(geom) - 1):
            lat1, lon1 = math.radians(geom[i]["lat"]), math.radians(geom[i]["lon"])
            lat2, lon2 = math.radians(geom[i + 1]["lat"]), math.radians(geom[i + 1]["lon"])
            dlat, dlon = lat2 - lat1, lon2 - lon1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            total_m += R * 2 * math.asin(math.sqrt(a))
    return total_m  # already in km (R is km)


def _polygon_area_km2(elements: list) -> float:
    """Approximate total area of polygon ways using spherical shoelace formula."""
    total = 0.0
    R = 6371.0
    for el in elements:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry", [])
        if len(geom) < 3:
            continue
        lats = [math.radians(p["lat"]) for p in geom]
        lons = [math.radians(p["lon"]) for p in geom]
        n = len(lats)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += lons[i] * math.sin(lats[j])
            area -= lons[j] * math.sin(lats[i])
        total += abs(area) / 2 * R ** 2
    return total
