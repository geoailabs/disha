"""WorldPop async population stats client.

WorldPop's `wpgppop` is a 100m gridded global population product (2000-2020).
The API is task-based: submit a polygon, get a `taskid`, poll until finished.

This module exposes one function — :func:`population_in_polygon` — that hides
the polling and returns ``None`` on any upstream error so callers can fall
through to a backup data source (OSM tag scrape) without raising.

Results are cached for 30 days; population grids update annually at most.
"""

from __future__ import annotations

import asyncio
import json

from tools import cache, http as http_client


_STATS_URL = "https://api.worldpop.org/v1/services/stats"
_TASK_URL = "https://api.worldpop.org/v1/tasks/"
_DATASET = "wpgppop"
_DEFAULT_YEAR = 2020
_POLL_INTERVAL = 1.5
_POLL_TIMEOUT = 60.0


class WorldPopUnavailable(RuntimeError):
    """Raised internally when no usable population number can be obtained."""


async def _submit(geometry: dict, year: int = _DEFAULT_YEAR) -> str:
    geom_str = json.dumps(geometry, separators=(",", ":"))
    resp = await http_client.fetch_json(
        _STATS_URL,
        namespace="worldpop",
        params={
            "dataset": _DATASET,
            "year": year,
            "geojson": geom_str,
            "runasync": "true",
        },
    )
    taskid = (resp or {}).get("taskid")
    if not taskid:
        raise WorldPopUnavailable(f"No taskid in WorldPop response: {resp}")
    return taskid


async def _poll(taskid: str) -> float | None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + _POLL_TIMEOUT
    while True:
        resp = await http_client.fetch_json(
            _TASK_URL + taskid,
            namespace="worldpop",
        )
        status = (resp or {}).get("status", "")
        if status == "finished":
            if resp.get("error"):
                raise WorldPopUnavailable(
                    resp.get("error_message") or "WorldPop reported error"
                )
            data = resp.get("data") or {}
            pop = data.get("total_population")
            return float(pop) if pop is not None else None
        if status == "failed" or (resp or {}).get("error"):
            raise WorldPopUnavailable(
                (resp or {}).get("error_message") or f"task {taskid} failed"
            )
        if loop.time() > deadline:
            raise WorldPopUnavailable(
                f"task {taskid} did not finish within {_POLL_TIMEOUT:.0f}s"
            )
        await asyncio.sleep(_POLL_INTERVAL)


async def population_in_polygon(geometry: dict, year: int | None = None) -> float | None:
    """Return total population inside a GeoJSON Polygon/MultiPolygon, or ``None``.

    Supports years 2000-2020 (WorldPop wpgppop product range). Defaults to 2020.
    Returns ``None`` on any upstream error so callers can degrade gracefully.
    Cached 30 days, keyed on the geometry JSON + dataset + year.
    """
    if not geometry or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return None

    valid_year = min(max(int(year or _DEFAULT_YEAR), 2000), 2020)

    cache_key = {
        "geom": json.dumps(geometry, sort_keys=True, separators=(",", ":")),
        "dataset": _DATASET,
        "year": valid_year,
    }

    async def _fetch() -> dict:
        taskid = await _submit(geometry, year=valid_year)
        pop = await _poll(taskid)
        return {"population": pop}

    try:
        result = await cache.get_or_fetch(
            namespace="worldpop",
            key=cache_key,
            ttl_seconds=86_400 * 30,
            fetch_fn=_fetch,
        )
    except (http_client.HTTPError, WorldPopUnavailable):
        return None
    except Exception:
        return None

    return (result or {}).get("population")
