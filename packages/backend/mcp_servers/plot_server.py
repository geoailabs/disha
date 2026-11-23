"""
Plot MCP Server — publication-ready Plotly charts saved as downloadable image
artifacts (PNG), with an interactive HTML version and the Plotly figure stored
alongside. Rendering lives in tools/charts.py (Matplotlib fallback included).
"""
from __future__ import annotations

from llm.base import ToolDeclaration
from tools.charts import CHART_TYPES, ChartError, normalise_spec, render_png, save_chart


def render_line_panels(
    title: str,
    panels: list[dict],
    x_label: str = "",
    y_label: str = "",
    footnote: str = "",
    y_suffix: str = "",
) -> bytes:
    """Stacked multi-series line panels → PNG bytes (gaps preserved)."""
    spec = normalise_spec({
        "plot_type": "line", "title": title, "panels": panels,
        "x_label": x_label, "y_label": y_label, "footnote": footnote, "y_suffix": y_suffix,
    })
    png, _fig, _engine = render_png(spec)
    return png


class PlotServer:
    description: str = "Generate accurate Plotly charts (line, bar, pie, area, scatter, box, heatmap, treemap, radar, …) saved as downloadable image artifacts."
    tool_names: set[str] = {"create_plot"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="create_plot",
                description=(
                    "Create an accurate Plotly chart from data you ALREADY HAVE from tool results and save it as a "
                    "downloadable PNG image artifact (plus an interactive HTML version). Use the exact numbers returned by "
                    "tools — never invent, round away, or repeat values to fill gaps (use null for missing points). "
                    "Types: line (one or many lines via `series`), area, stacked_area, bar, grouped_bar, stacked_bar, "
                    "horizontal_bar, pie, donut, histogram, scatter, bubble, box, violin, heatmap, treemap, funnel, "
                    "waterfall, radar."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "plot_type": {"type": "string", "enum": CHART_TYPES, "description": "Chart type."},
                        "title": {"type": "string", "description": "Chart title."},
                        "subtitle": {"type": "string", "description": "Optional subtitle (e.g. data source, place, period)."},
                        "x_data": {
                            "type": "array",
                            "items": {"type": ["string", "number"]},
                            "description": "Categories / x values (pie & treemap: labels).",
                        },
                        "y_data": {
                            "type": "array",
                            "items": {"type": ["number", "null"]},
                            "description": "Values for a single series (one per x_data item). For several series use `series`.",
                        },
                        "series": {
                            "type": "object",
                            "description": (
                                "Several series: {\"<name>\": [one value per x_data item, null for missing]}. "
                                "Used by line/area/stacked_area/grouped_bar/stacked_bar/horizontal_bar/scatter/radar; "
                                "for box/violin/histogram each series is a list of raw observations."
                            ),
                        },
                        "z_data": {"type": "array", "items": {"type": "array", "items": {"type": ["number", "null"]}}, "description": "heatmap: 2-D values, one row per y_categories entry."},
                        "y_categories": {"type": "array", "items": {"type": "string"}, "description": "heatmap: row labels."},
                        "sizes": {"type": "array", "items": {"type": "number"}, "description": "bubble: size value per point."},
                        "parents": {"type": "array", "items": {"type": "string"}, "description": "treemap: parent label per item ('' for root)."},
                        "colors": {"type": "object", "description": "Optional {series or category name: '#hex'}."},
                        "x_label": {"type": "string", "description": "X axis label."},
                        "y_label": {"type": "string", "description": "Y axis label (include units)."},
                        "y_suffix": {"type": "string", "description": "Optional unit suffix for y ticks, e.g. '%'."},
                        "footnote": {"type": "string", "description": "Optional source / note text under the chart."},
                        "theme": {"type": "string", "enum": ["dark", "light"], "description": "Default dark."},
                    },
                    "required": ["plot_type", "title"],
                },
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "create_plot":
            import asyncio
            return await asyncio.get_event_loop().run_in_executor(None, self._create_plot, args)
        return {"error": f"Unknown tool '{tool_name}'"}

    def _create_plot(self, args: dict) -> dict:
        map_context = args.get("_map_context") or {}
        workspace = args.get("_workspace") or (map_context.get("workspace") if map_context else None)
        try:
            spec = normalise_spec(args)
            saved = save_chart(spec, workspace)
        except ChartError as exc:
            return {"status": "error", "error": str(exc)}
        except Exception as exc:
            return {"status": "error", "error": f"Failed to generate plot: {exc}"}
        return {
            "status": "success",
            "artifact_id": saved["artifact_id"],
            "file_path": saved["file_path"],
            "interactive_html": saved["interactive_html"],
            "title": saved["title"],
            "plot_type": saved["plot_type"],
            "engine": saved["engine"],
            "series_count": len(spec.get("series") or {}) or len(spec.get("panels") or []),
        }
