"""
Weather MCP Server

Provides weather and air quality data from Open-Meteo (free, no API key required).
"""

from __future__ import annotations

from llm.base import ToolDeclaration
from tools import cache, http as http_client

WMO_WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


class WeatherServer:
    description = "Weather and air quality data from Open-Meteo"
    tool_names = {"get_weather", "get_air_quality"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="get_weather",
                description="Get current weather and 7-day forecast for a location",
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude"},
                        "lng": {"type": "number", "description": "Longitude"},
                    },
                    "required": ["lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="get_air_quality",
                description=(
                    "Get Open-Meteo's current European AQI and pollutant concentrations for one coordinate. "
                    "This is not India's or the US's AQI; higher values indicate more polluted air. "
                    "Do not describe a single coordinate as an area-wide AQI."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude"},
                        "lng": {"type": "number", "description": "Longitude"},
                    },
                    "required": ["lat", "lng"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "get_weather":
            return await self._get_weather(args)
        elif tool_name == "get_air_quality":
            return await self._get_air_quality(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _get_weather(self, args: dict) -> dict:
        lat, lng = args.get("lat", 0), args.get("lng", 0)
        cache_key = {"lat": round(float(lat), 3), "lng": round(float(lng), 3)}

        async def _fetch() -> dict:
            return await http_client.fetch_json(
                "https://api.open-meteo.com/v1/forecast",
                namespace="open-meteo",
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,wind_direction_10m,weather_code,precipitation",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,sunrise,sunset",
                    "timezone": "auto",
                    "forecast_days": 7,
                },
            )

        try:
            data = await cache.get_or_fetch(
                namespace="open-meteo-weather",
                key=cache_key,
                ttl_seconds=3600,
                fetch_fn=_fetch,
            )
        except http_client.HTTPError as e:
            return {"error": str(e), "code": e.code}
        except Exception as e:
            return {"error": str(e)}

        try:
            current = data.get("current", {})
            weather_code = current.get("weather_code", 0)
            result = {
                "current": {
                    "temperature_c": current.get("temperature_2m"),
                    "feels_like_c": current.get("apparent_temperature"),
                    "humidity_pct": current.get("relative_humidity_2m"),
                    "wind_speed_kmh": current.get("wind_speed_10m"),
                    "wind_direction_deg": current.get("wind_direction_10m"),
                    "precipitation_mm": current.get("precipitation"),
                    "condition": WMO_WEATHER_CODES.get(weather_code, f"Code {weather_code}"),
                },
                "timezone": data.get("timezone", ""),
            }

            daily = data.get("daily", {})
            if daily.get("time"):
                result["forecast"] = [
                    {
                        "date": daily["time"][i],
                        "high_c": daily.get("temperature_2m_max", [None])[i],
                        "low_c": daily.get("temperature_2m_min", [None])[i],
                        "precipitation_mm": daily.get("precipitation_sum", [None])[i],
                        "condition": WMO_WEATHER_CODES.get(
                            daily.get("weather_code", [0])[i], "Unknown"
                        ),
                    }
                    for i in range(len(daily["time"]))
                ]

            return result
        except Exception as e:
            return {"error": str(e)}

    async def _get_air_quality(self, args: dict) -> dict:
        lat, lng = args.get("lat", 0), args.get("lng", 0)
        cache_key = {"lat": round(float(lat), 3), "lng": round(float(lng), 3)}

        async def _fetch() -> dict:
            return await http_client.fetch_json(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                namespace="open-meteo",
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "current": "european_aqi,pm10,pm2_5,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide",
                },
            )

        try:
            data = await cache.get_or_fetch(
                namespace="open-meteo-air",
                key=cache_key,
                ttl_seconds=3600,
                fetch_fn=_fetch,
            )
        except http_client.HTTPError as e:
            return {"error": str(e), "code": e.code}
        except Exception as e:
            return {"error": str(e)}

        try:
            current = data.get("current", {})
            aqi = current.get("european_aqi")
            # Open-Meteo's European AQI thresholds are not the US or India AQI thresholds.
            if aqi is None:
                quality = "Unavailable"
            elif aqi <= 20:
                quality = "Good"
            elif aqi <= 40:
                quality = "Fair"
            elif aqi <= 60:
                quality = "Moderate"
            elif aqi <= 80:
                quality = "Poor"
            elif aqi <= 100:
                quality = "Very Poor"
            else:
                quality = "Extremely Poor"

            pm25 = current.get("pm2_5")
            pm10 = current.get("pm10")

            result = {
                "european_aqi": aqi,
                "aqi_source": "Open-Meteo",
                "european_aqi_scale": "European AQI; higher values indicate more polluted air",
                "quality_label": quality,
                "sample_location": {"lat": float(lat), "lng": float(lng)},
                "pm2_5_ug_m3": pm25,
                "pm10_ug_m3": pm10,
                "nitrogen_dioxide_ug_m3": current.get("nitrogen_dioxide"),
                "ozone_ug_m3": current.get("ozone"),
                "sulphur_dioxide_ug_m3": current.get("sulphur_dioxide"),
                "carbon_monoxide_ug_m3": current.get("carbon_monoxide"),
                "units": "µg/m³ (all pollutants)",
            }
            return result
        except Exception as e:
            return {"error": str(e)}
