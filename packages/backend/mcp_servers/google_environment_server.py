"""Google Maps Platform — environment APIs.

Three tools:
  - ``get_elevation``         — WGS84 elevation per point (legacy Elevation API).
  - ``get_air_quality_google``— Per-pollutant current conditions (Air Quality v1).
  - ``get_solar_building``    — Rooftop solar potential (Solar v1 ``buildingInsights``).

Each tool is wrapped in :func:`tools.cache.get_or_fetch` with a TTL chosen
for how fast the underlying signal moves: terrain is forever (30d),
rooftops effectively forever (30d), AQI hourly. On any Google failure the
tool returns ``{"error": ..., "code": "upstream_unavailable"}`` so the LLM
can fall back to existing weather/OSM tools without crashing.
"""

from __future__ import annotations

from llm.base import ToolDeclaration
from tools import cache
from tools.google import GoogleUnavailable, call_legacy, call_v1


_ELEVATION_URL = "https://maps.googleapis.com/maps/api/elevation/json"
_AIR_QUALITY_URL = "https://airquality.googleapis.com/v1/currentConditions:lookup"
_SOLAR_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"

_ELEVATION_BATCH_MAX = 250  # Google allows ~512; leave headroom.


class GoogleEnvironmentServer:
    description = "Google Maps Platform: elevation, air quality (per-pollutant), rooftop solar potential"
    tool_names = {"get_elevation", "get_air_quality_google", "get_solar_building"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="get_elevation",
                description=(
                    "Get terrain elevation (meters above WGS84 ellipsoid) for one or more points. "
                    "Useful for slope/drainage analysis and feasibility studies. Pass a list of "
                    "{lat,lng} objects — up to 250 per call."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "points": {
                            "type": "array",
                            "description": "List of {lat, lng} points",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                },
                                "required": ["lat", "lng"],
                            },
                        },
                    },
                    "required": ["points"],
                },
            ),
            ToolDeclaration(
                name="get_air_quality_google",
                description=(
                    "Current air quality at a location — Google Air Quality API. Returns a "
                    "Universal AQI (UAQI; higher values indicate cleaner air) and, where available, "
                    "the location's local AQI "
                    "plus per-pollutant concentrations (PM2.5, PM10, NO2, O3, SO2, CO) and the "
                    "dominant pollutant. Report the returned index value and category exactly; "
                    "lower values indicate worse air. Do not claim this is an India/US AQI."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                    },
                    "required": ["lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="get_solar_building",
                description=(
                    "Estimate rooftop solar potential for a building near (lat, lng) — Google "
                    "Solar API ``buildingInsights:findClosest``. Returns max panel count, max "
                    "array area in m², annual sunshine hours, and carbon-offset factor. Only "
                    "covers regions where Google has rooftop imagery — many Indian cities are "
                    "supported, but high-rise / informal buildings may return no_data. "
                    "Caller should NOT retry; the response is authoritative for this lat/lng."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "required_quality": {
                            "type": "string",
                            "description": "Minimum imagery quality: HIGH, MEDIUM, or LOW (default LOW).",
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                        },
                    },
                    "required": ["lat", "lng"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "get_elevation":
            return await self._get_elevation(args)
        if tool_name == "get_air_quality_google":
            return await self._get_air_quality(args)
        if tool_name == "get_solar_building":
            return await self._get_solar(args)
        return {"error": f"Unknown tool: {tool_name}"}

    # ── Elevation ──────────────────────────────────────────────────────────

    async def _get_elevation(self, args: dict) -> dict:
        raw_points = args.get("points") or []
        if not isinstance(raw_points, list) or not raw_points:
            return {"error": "points must be a non-empty list of {lat, lng}", "code": "bad_request"}

        points: list[tuple[float, float]] = []
        for p in raw_points[:_ELEVATION_BATCH_MAX]:
            try:
                points.append((float(p["lat"]), float(p["lng"])))
            except (KeyError, TypeError, ValueError):
                continue
        if not points:
            return {"error": "No valid {lat, lng} pairs in points", "code": "bad_request"}

        cache_key = {
            "points": [(round(lat, 5), round(lng, 5)) for lat, lng in points],
        }
        locations = "|".join(f"{lat},{lng}" for lat, lng in points)

        async def _fetch() -> dict:
            payload = await call_legacy(
                _ELEVATION_URL,
                namespace="google_elevation",
                params={"locations": locations},
            )
            results = []
            for r in payload.get("results", []) or []:
                loc = r.get("location") or {}
                results.append({
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng"),
                    "elevation_m": r.get("elevation"),
                    "resolution_m": r.get("resolution"),
                })
            return {"results": results}

        try:
            return await cache.get_or_fetch(
                namespace="google_elevation",
                key=cache_key,
                ttl_seconds=86_400 * 30,
                fetch_fn=_fetch,
            )
        except GoogleUnavailable as e:
            return {"error": str(e), "code": "upstream_unavailable"}

    # ── Air Quality ────────────────────────────────────────────────────────

    async def _get_air_quality(self, args: dict) -> dict:
        try:
            lat = float(args["lat"])
            lng = float(args["lng"])
        except (KeyError, TypeError, ValueError):
            return {"error": "lat and lng are required numbers", "code": "bad_request"}

        cache_key = {"lat": round(lat, 4), "lng": round(lng, 4)}

        async def _fetch() -> dict:
            body = {
                "location": {"latitude": lat, "longitude": lng},
                "universalAqi": True,
                "extraComputations": [
                    "DOMINANT_POLLUTANT_CONCENTRATION",
                    "POLLUTANT_CONCENTRATION",
                    "POLLUTANT_ADDITIONAL_INFO",
                    "HEALTH_RECOMMENDATIONS",
                    "LOCAL_AQI",
                ],
            }
            payload = await call_v1(
                _AIR_QUALITY_URL,
                namespace="google_environment",
                method="POST",
                json_body=body,
            )

            indexes = payload.get("indexes") or []
            primary = next((i for i in indexes if i.get("code") == "uaqi"), {})
            reported_indexes = [
                {
                    "code": index.get("code"),
                    "display_name": index.get("displayName"),
                    "aqi": index.get("aqi"),
                    "aqi_display": index.get("aqiDisplay"),
                    "category": index.get("category"),
                }
                for index in indexes
            ]
            local_indexes = [index for index in reported_indexes if index.get("code") != "uaqi"]
            pollutants = []
            for p in payload.get("pollutants") or []:
                conc = p.get("concentration") or {}
                pollutants.append({
                    "code": p.get("code"),
                    "display_name": p.get("displayName"),
                    "full_name": p.get("fullName"),
                    "concentration": conc.get("value"),
                    "units": conc.get("units"),
                })
            return {
                "aqi": primary.get("aqi"),
                "aqi_display": primary.get("aqiDisplay"),
                "category": primary.get("category"),
                "aqi_index": primary.get("code") or None,
                "aqi_scale": (
                    "Google Universal AQI; higher values indicate cleaner air"
                    if primary else None
                ),
                "aqi_status": "available" if primary else "Google Universal AQI was not returned",
                "indexes": reported_indexes,
                "local_indexes": local_indexes,
                "dominant_pollutant": primary.get("dominantPollutant"),
                "pollutants": pollutants,
                "health_recommendations": payload.get("healthRecommendations") or {},
                "region_code": payload.get("regionCode"),
                "observation_time": payload.get("dateTime"),
                "sample_location": {"lat": lat, "lng": lng},
            }

        try:
            return await cache.get_or_fetch(
                namespace="google_environment_aq",
                key=cache_key,
                ttl_seconds=3600,  # AQI updates hourly
                fetch_fn=_fetch,
            )
        except GoogleUnavailable as e:
            return {"error": str(e), "code": "upstream_unavailable"}

    # ── Solar Building Insights ────────────────────────────────────────────

    async def _get_solar(self, args: dict) -> dict:
        try:
            lat = float(args["lat"])
            lng = float(args["lng"])
        except (KeyError, TypeError, ValueError):
            return {"error": "lat and lng are required numbers", "code": "bad_request"}

        required_quality = (args.get("required_quality") or "LOW").upper()
        if required_quality not in {"HIGH", "MEDIUM", "LOW"}:
            required_quality = "LOW"

        cache_key = {
            "lat": round(lat, 5),
            "lng": round(lng, 5),
            "quality": required_quality,
        }

        async def _fetch() -> dict:
            payload = await call_v1(
                _SOLAR_URL,
                namespace="google_environment",
                method="GET",
                params={
                    "location.latitude": lat,
                    "location.longitude": lng,
                    "requiredQuality": required_quality,
                },
            )

            potential = payload.get("solarPotential") or {}
            financial_summary = None
            financial_analyses = potential.get("financialAnalyses") or []
            if financial_analyses:
                # Pick the median bill case as a representative summary.
                mid = financial_analyses[len(financial_analyses) // 2]
                financial_summary = {
                    "monthly_bill_usd": (mid.get("monthlyBill") or {}).get("units"),
                    "panel_config_index": mid.get("panelConfigIndex"),
                }

            center = payload.get("center") or {}
            return {
                "name": payload.get("name"),
                "center": {"lat": center.get("latitude"), "lng": center.get("longitude")},
                "postal_code": payload.get("postalCode"),
                "administrative_area": payload.get("administrativeArea"),
                "region_code": payload.get("regionCode"),
                "imagery_quality": payload.get("imageryQuality"),
                "imagery_date": payload.get("imageryDate"),
                "max_array_panels_count": potential.get("maxArrayPanelsCount"),
                "max_array_area_m2": potential.get("maxArrayAreaMeters2"),
                "max_sunshine_hours_per_year": potential.get("maxSunshineHoursPerYear"),
                "carbon_offset_factor_kg_per_mwh": potential.get("carbonOffsetFactorKgPerMwh"),
                "panel_capacity_watts": potential.get("panelCapacityWatts"),
                "panel_height_m": potential.get("panelHeightMeters"),
                "panel_width_m": potential.get("panelWidthMeters"),
                "financial_summary": financial_summary,
            }

        try:
            return await cache.get_or_fetch(
                namespace="google_environment_solar",
                key=cache_key,
                ttl_seconds=86_400 * 30,
                fetch_fn=_fetch,
            )
        except GoogleUnavailable as e:
            msg = str(e).lower()
            # Google returns NOT_FOUND when no rooftop data exists at the location.
            if "not_found" in msg or "no building" in msg:
                return {
                    "error": "no rooftop data at this location",
                    "code": "no_data",
                    "lat": lat,
                    "lng": lng,
                }
            return {"error": str(e), "code": "upstream_unavailable"}
