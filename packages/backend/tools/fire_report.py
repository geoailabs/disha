"""MODIS fire comparison report: year selection, rendering and one-report-per-turn upsert.

Rules (shared by the legacy chat loop and the OpenCode runtime):
* Years compared = the year(s) the user asked for + the present (current) year.
  No year asked → the current year only (year-to-date).
* Every fire comparison produced during one user turn — whether from
  `compare_modis_fire_history` or the automatic comparison attached to a MODIS
  fire layer — is merged into ONE report artifact that is updated in place.
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

REPORT_KIND = "modis_fire_comparison"
MAX_YEARS = 11

_lock = threading.Lock()
# workspace key -> {"id": int, "years": [...], "results": [...], ...} for the current turn
_turn_reports: dict[str, dict] = {}


def begin_turn(workspace: str | None = None) -> None:
    """Start a new user turn: the next fire comparison creates a fresh report."""
    with _lock:
        if workspace is None:
            _turn_reports.clear()
        else:
            _turn_reports.pop(str(workspace), None)


def _as_year(value: Any) -> int | None:
    try:
        y = int(str(value).strip()[:4])
    except (TypeError, ValueError):
        return None
    return y if 2000 <= y <= date.today().year else None


def resolve_years(args: dict, today: date | None = None) -> tuple[list[int], str | None]:
    """Return (sorted years, error) following the asked-year + present-year rule."""
    current = (today or date.today()).year
    start, end = _as_year(args.get("start_year")), _as_year(args.get("end_year"))
    if args.get("start_year") or args.get("end_year"):
        if (args.get("start_year") and start is None) or (args.get("end_year") and end is None):
            return [], f"Years must be between 2000 (start of MODIS fire records) and {current}."
        end = end or current
        start = start or end
        if end < start:
            start, end = end, start
        years = list(range(start, end + 1))
    else:
        asked: list[Any] = []
        if args.get("year") is not None:
            asked.append(args.get("year"))
        asked.extend(args.get("years") or [])
        parsed = [_as_year(y) for y in asked]
        if any(p is None for p in parsed):
            return [], f"Years must be between 2000 (start of MODIS fire records) and {current}."
        years = sorted(set(parsed) | {current})
    if len(years) > MAX_YEARS:
        return [], f"At most {MAX_YEARS} years can be compared in one report."
    return years, None


def compute_differences(annual: dict, years: list[int]) -> dict:
    """Differences of every year against the present (last) year and between consecutive years."""
    deltas: dict[str, dict] = {}
    pairs = list(zip(years, years[1:]))
    if len(years) > 2:
        pairs.append((years[0], years[-1]))
    for prev, curr in pairs:
        p = annual.get(str(prev)) or {}
        c = annual.get(str(curr)) or {}
        pb, cb = float(p.get("burned_area_hectares", 0) or 0), float(c.get("burned_area_hectares", 0) or 0)
        pf, cf = float(p.get("active_fire_pixel_days", 0) or 0), float(c.get("active_fire_pixel_days", 0) or 0)
        deltas[f"{prev}_to_{curr}"] = {
            "burned_area_hectares_difference": round(cb - pb, 3),
            "burned_area_percent_difference": round((cb - pb) / pb * 100, 2) if pb else None,
            "active_fire_pixel_days_difference": round(cf - pf, 3),
        }
    return deltas


def render_report(result: dict) -> tuple[str, str]:
    """Return (title, markdown) for a comparison result."""
    years: list[int] = [int(y) for y in result.get("years") or []]
    rows = result.get("results") or []
    names = [str(r.get("village", "Area")) for r in rows]
    place_label = ", ".join(names[:4]) + (f" +{len(names) - 4} more" if len(names) > 4 else "")
    year_label = " vs ".join(str(y) for y in years) if len(years) <= 3 else f"{years[0]}–{years[-1]}"
    title = f"MODIS Fire Comparison — {place_label} ({year_label})"

    partial = result.get("partial_year") or {}
    lines = [
        f"# {title}",
        "",
        "Source: NASA MODIS MCD64A1 burned area and FIRMS active-fire observations via Google Earth Engine, "
        "computed strictly inside each resolved area boundary.",
        "",
    ]
    if partial:
        lines.append(
            f"> {partial.get('year')} is year-to-date (as of {partial.get('as_of')}). "
            f"Latest MCD64A1 burned-area data available: {partial.get('burned_area_data_through') or 'not yet published'}; "
            f"latest FIRMS data: {partial.get('active_fire_data_through') or 'not yet published'}."
        )
        lines.append("")
    lines += [
        "| Area | Year | Burned area (ha) | Active-fire pixel-days |",
        "|---|---:|---:|---:|",
    ]
    for row in rows:
        name = str(row.get("village", "Area")).replace("|", "\\|")
        annual = row.get("annual") or {}
        for y in years:
            m = annual.get(str(y), {})
            suffix = " (YTD)" if partial and int(partial.get("year", 0)) == y else ""
            lines.append(
                f"| {name} | {y}{suffix} | {m.get('burned_area_hectares', 0)} | {m.get('active_fire_pixel_days', 0)} |"
            )
    if len(years) > 1:
        lines += ["", "## Differences", ""]
        for row in rows:
            lines += [
                f"### {row.get('village', 'Area')}",
                "",
                "| Interval | Burned area difference (ha) | Burned area difference (%) | Active-fire pixel-day difference |",
                "|---|---:|---:|---:|",
            ]
            for interval, d in (row.get("differences") or {}).items():
                pct = d.get("burned_area_percent_difference")
                lines.append(
                    f"| {interval.replace('_to_', ' → ')} | {d.get('burned_area_hectares_difference', 0)} | "
                    f"{'—' if pct is None else pct} | {d.get('active_fire_pixel_days_difference', 0)} |"
                )
            lines.append("")
    unresolved = result.get("unresolved_villages") or []
    if unresolved:
        lines += ["", "Unresolved areas (no boundary found, not computed): " + ", ".join(map(str, unresolved))]
    lines += [
        "",
        "## Data Sources & Methodology",
        "",
        "| Data Source / Tool | Category | Provider / Endpoint | Query Scope & Parameters | Date / Timestamp | Analytical Basis & Assumptions |",
        "|---|---|---|---|---|---|",
        f"| [**MODIS MCD64A1 Burned Area**](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD64A1) | Earth Observation | NASA LP DAAC via Google Earth Engine | Areas: {place_label}; years: {', '.join(map(str, years))} | {date.today().isoformat()} | Pixels with BurnDate > 0 in the calendar year; area summed with ee.Image.pixelArea() at 500 m |",
        f"| [**FIRMS Active Fires**](https://developers.google.com/earth-engine/datasets/catalog/FIRMS) | Earth Observation | NASA FIRMS via Google Earth Engine | Areas: {place_label}; years: {', '.join(map(str, years))} | {date.today().isoformat()} | Daily T21 brightness > 300 K counted as fire pixel-days at 1 km |",
    ]
    return title, "\n".join(lines)


def merge_results(existing: dict, new: dict) -> dict:
    """Merge two comparison results (union of years and areas; newer values win)."""
    years = sorted({int(y) for y in (existing.get("years") or [])} | {int(y) for y in (new.get("years") or [])})
    by_name: dict[str, dict] = {}
    for row in (existing.get("results") or []) + (new.get("results") or []):
        name = str(row.get("village"))
        merged = by_name.setdefault(name, {"village": name, "annual": {}})
        merged["annual"].update(row.get("annual") or {})
    rows = []
    for row in by_name.values():
        row["differences"] = compute_differences(row["annual"], [y for y in years if str(y) in row["annual"]])
        rows.append(row)
    unresolved = sorted(set(existing.get("unresolved_villages") or []) | set(new.get("unresolved_villages") or []) - set(by_name))
    return {
        **existing,
        **new,
        "years": years,
        "start_year": years[0] if years else None,
        "end_year": years[-1] if years else None,
        "results": rows,
        "unresolved_villages": unresolved,
        "partial_year": new.get("partial_year") or existing.get("partial_year"),
    }


def build_artifact(result: dict) -> dict:
    title, content = render_report(result)
    return {
        "title": title,
        "artifact_type": "report",
        "format": "markdown",
        "content": content,
        "meta": {"kind": REPORT_KIND, "result": {k: v for k, v in result.items() if k != "message"}},
    }


def upsert_turn_report(artifact: dict, workspace: str | None) -> dict:
    """Save a fire comparison artifact, merging into this turn's existing report if any."""
    from tools.artifact_store import save_artifact

    key = str(workspace)
    new_result = (artifact.get("meta") or {}).get("result") or {}
    with _lock:
        current = _turn_reports.get(key)
        if current:
            merged = merge_results(current["result"], new_result)
            art = build_artifact(merged)
            row = save_artifact(
                title=art["title"], artifact_type=art["artifact_type"], format=art["format"],
                content=art["content"], meta=art["meta"], artifact_id=current["id"], workspace=workspace,
            )
            _turn_reports[key] = {"id": row["id"], "result": merged}
            return row
        row = save_artifact(
            title=artifact["title"], artifact_type=artifact.get("artifact_type", "report"),
            format=artifact.get("format", "markdown"), content=artifact.get("content", ""),
            meta=artifact.get("meta"), overwrite=True, workspace=workspace,
        )
        _turn_reports[key] = {"id": row["id"], "result": new_result}
        return row


def turn_report_id(workspace: str | None) -> int | None:
    with _lock:
        current = _turn_reports.get(str(workspace))
        return current["id"] if current else None


def save_tool_artifact(artifact: dict, workspace: str | None) -> dict:
    """Single entry point for hub-declared artifacts (fire reports are de-duplicated)."""
    from tools.artifact_store import save_artifact

    if (artifact.get("meta") or {}).get("kind") == REPORT_KIND:
        return upsert_turn_report(artifact, workspace)
    return save_artifact(
        title=artifact.get("title", "Report"),
        artifact_type=artifact.get("artifact_type", "report"),
        format=artifact.get("format", "markdown"),
        content=artifact.get("content", ""),
        meta=artifact.get("meta"),
        workspace=workspace,
    )


def looks_like_fire_report(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in ("modis", "fire", "burn", "firms", "stubble"))
