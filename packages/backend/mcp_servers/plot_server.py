"""
Plot MCP Server — Enables the AI assistant to generate publication-ready
charts, histograms, bar plots, pie charts, and scatter plots using Matplotlib/Seaborn,
saving them into the workspace artifacts store as image artifacts.
"""
from __future__ import annotations

import io
import json

from llm.base import ToolDeclaration
from tools.artifact_store import save_artifact


class PlotServer:
    description: str = "Generate publication-ready charts, histograms, bar plots, and demographic visualizations, saving them as image artifacts."
    tool_names: set[str] = {"create_plot"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="create_plot",
                description=(
                    "Generate a publication-ready chart or histogram (bar, histogram, pie, line, scatter) "
                    "from data arrays/dict and save it directly as an image artifact in the project workspace."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "plot_type": {
                            "type": "string",
                            "enum": ["bar", "histogram", "pie", "line", "scatter"],
                            "description": "Type of visualization to generate.",
                        },
                        "title": {
                            "type": "string",
                            "description": "Title of the chart/histogram.",
                        },
                        "x_data": {
                            "type": "array",
                            "items": {"type": ["string", "number"]},
                            "description": "Categories or values for the X axis.",
                        },
                        "y_data": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Numeric values for the Y axis (heights/counts/frequencies).",
                        },
                        "x_label": {
                            "type": "string",
                            "description": "Label for the X axis.",
                        },
                        "y_label": {
                            "type": "string",
                            "description": "Label for the Y axis.",
                        },
                        "color_palette": {
                            "type": "string",
                            "description": "Color theme: 'viridis', 'teal', 'coral', 'indigo', 'sunset', 'landuse'.",
                        },
                    },
                    "required": ["plot_type", "title", "x_data"],
                },
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "create_plot":
            return self._create_plot(args)
        return {"error": f"Unknown tool '{tool_name}'"}

    def _create_plot(self, args: dict) -> dict:
        try:
            import matplotlib
            matplotlib.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt

            plot_type = args.get("plot_type", "bar")
            title = args.get("title", "Geospatial Data Chart")
            x_data = args.get("x_data", [])
            y_data = args.get("y_data", [])
            x_label = args.get("x_label", "")
            y_label = args.get("y_label", "")
            palette_name = args.get("color_palette", "teal")
            map_context = args.get("_map_context", {})
            workspace = map_context.get("workspace") if map_context else None

            if not x_data:
                return {"error": "x_data cannot be empty."}

            fig, ax = plt.subplots(figsize=(8, 4.8), dpi=200)

            # Palette definitions
            colors_map = {
                "teal": "#0d9488",
                "indigo": "#4f46e5",
                "coral": "#f97316",
                "sunset": ["#0284c7", "#38bdf8", "#fbbf24", "#f97316", "#ef4444"],
                "landuse": ["#22c55e", "#ef4444", "#3b82f6", "#eab308", "#a855f7", "#64748b"],
            }
            color_choice = colors_map.get(palette_name, "#0284c7")

            # Apply clean dark/modern theme styling
            fig.patch.set_facecolor('#0f172a')
            ax.set_facecolor('#1e293b')
            ax.spines['bottom'].set_color('#475569')
            ax.spines['left'].set_color('#475569')
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.tick_params(colors='#94a3b8', labelsize=9)
            ax.grid(True, linestyle='--', alpha=0.15, color='#cbd5e1')

            if plot_type == "bar":
                if not y_data:
                    return {"error": "y_data required for bar chart."}
                colors = color_choice if isinstance(color_choice, list) else [color_choice] * len(x_data)
                bars = ax.bar(x_data, y_data, color=colors[:len(x_data)], width=0.55, edgecolor='#0f172a', linewidth=0.8)
                for bar in bars:
                    h = bar.get_height()
                    ax.annotate(f'{h:g}',
                                xy=(bar.get_x() + bar.get_width() / 2, h),
                                xytext=(0, 3),
                                textcoords="offset points",
                                ha='center', va='bottom', color='#f8fafc', fontsize=8, fontweight='bold')

            elif plot_type == "histogram":
                vals = y_data if y_data else x_data
                ax.hist(vals, bins=10, color='#38bdf8', edgecolor='#0f172a', alpha=0.85)

            elif plot_type == "pie":
                if not y_data:
                    return {"error": "y_data required for pie chart."}
                pie_colors = color_choice if isinstance(color_choice, list) else plt.cm.tab10.colors
                wedges, texts, autotexts = ax.pie(
                    y_data,
                    labels=x_data,
                    autopct='%1.1f%%',
                    startangle=140,
                    colors=pie_colors[:len(x_data)],
                    textprops=dict(color="#f8fafc", fontsize=9),
                    wedgeprops=dict(width=0.45, edgecolor='#0f172a', linewidth=1.5)
                )
                for at in autotexts:
                    at.set_color('#ffffff')
                    at.set_weight('bold')

            elif plot_type == "line":
                if not y_data:
                    return {"error": "y_data required for line plot."}
                ax.plot(x_data, y_data, marker='o', color='#38bdf8', linewidth=2.2, markersize=6, markerfacecolor='#0284c7')

            elif plot_type == "scatter":
                if not y_data:
                    return {"error": "y_data required for scatter plot."}
                ax.scatter(x_data, y_data, color='#f97316', s=45, alpha=0.85, edgecolors='#ffffff', linewidths=0.5)

            if title:
                ax.set_title(title, color='#f8fafc', fontsize=12, fontweight='bold', pad=12)
            if x_label:
                ax.set_xlabel(x_label, color='#cbd5e1', fontsize=9.5, labelpad=8)
            if y_label:
                ax.set_ylabel(y_label, color='#cbd5e1', fontsize=9.5, labelpad=8)

            plt.tight_layout()

            # Render to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
            plt.close(fig)
            img_bytes = buf.getvalue()

            # Save as image artifact
            artifact = save_artifact(
                title=title,
                artifact_type="plot",
                format="image",
                file_bytes=img_bytes,
                file_ext="png",
                workspace=workspace,
            )

            return {
                "status": "success",
                "artifact_id": artifact["id"],
                "file_path": artifact.get("file_path"),
                "title": title,
                "plot_type": plot_type,
            }
        except Exception as exc:
            return {"error": f"Failed to generate plot: {str(exc)}"}
