"""Plotly chart engine for Disha.

Every chart the app produces (create_plot, land-cover time series, JSON chart
artifacts) is built here as a Plotly figure from the exact numbers supplied:

* PNG  — exported with Kaleido and saved as the downloadable image artifact
         (same artifact type/format as before, so downloads & document
         embedding keep working).
* HTML — an interactive version written next to the PNG
         (artifacts_store/<id>.html, sharing one plotly.min.js).
* JSON — the Plotly figure is stored in the artifact meta for re-rendering.

If Plotly or Kaleido/Chrome is unavailable, a Matplotlib fallback renders the
basic chart types so a downloadable PNG is still produced.

Accuracy rules: values are never interpolated or filled — `None` stays a gap;
series lengths are validated against the x axis; integer years get one tick
per year.
"""

from __future__ import annotations

import io
import json
import logging
import math
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CHART_TYPES = [
    "line", "area", "stacked_area", "bar", "grouped_bar", "stacked_bar", "horizontal_bar",
    "pie", "donut", "histogram", "scatter", "bubble", "box", "violin", "heatmap",
    "treemap", "funnel", "waterfall", "radar",
]

PALETTE = [
    "#2563eb", "#f97316", "#16a34a", "#dc2626", "#9333ea", "#ca8a04",
    "#0891b2", "#db2777", "#64748b", "#65a30d", "#7c3aed", "#0d9488",
]

_THEMES = {
    "dark": {"paper": "#0f172a", "plot": "#1e293b", "font": "#e2e8f0", "grid": "rgba(203,213,225,0.15)", "muted": "#94a3b8"},
    "light": {"paper": "#ffffff", "plot": "#ffffff", "font": "#0f172a", "grid": "rgba(15,23,42,0.10)", "muted": "#475569"},
}

_kaleido_lock = threading.Lock()
_kaleido_started = False


class ChartError(ValueError):
    """Invalid chart specification."""


# ── Validation helpers ────────────────────────────────────────────────────────

def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ChartError(f"Non-numeric value {v!r} in chart data.")
    return None if math.isnan(f) else f


def _nums(values: Any, name: str) -> list[float | None]:
    if not isinstance(values, (list, tuple)):
        raise ChartError(f"'{name}' must be a list of numbers.")
    return [_num(v) for v in values]


def _is_year_axis(x: list) -> bool:
    try:
        return bool(x) and all(float(v).is_integer() and 1800 <= float(v) <= 2200 for v in x)
    except (TypeError, ValueError):
        return False


def normalise_spec(args: dict) -> dict:
    """Validate a create_plot style request into a clean chart spec."""
    plot_type = str(args.get("plot_type") or "bar").lower().strip()
    aliases = {"multi_line": "line", "donut_chart": "donut", "column": "bar", "barh": "horizontal_bar", "stacked": "stacked_bar"}
    plot_type = aliases.get(plot_type, plot_type)
    if plot_type not in CHART_TYPES:
        raise ChartError(f"Unsupported plot_type '{plot_type}'. Supported: {', '.join(CHART_TYPES)}.")

    spec: dict = {
        "plot_type": plot_type,
        "title": str(args.get("title") or "Chart"),
        "subtitle": str(args.get("subtitle") or ""),
        "x_label": str(args.get("x_label") or ""),
        "y_label": str(args.get("y_label") or ""),
        "footnote": str(args.get("footnote") or ""),
        "theme": "light" if str(args.get("theme") or "").lower() == "light" else "dark",
        "colors": args.get("colors") if isinstance(args.get("colors"), dict) else {},
        "y_suffix": str(args.get("y_suffix") or ""),
        # Series observed only at intervals (e.g. 5-yearly releases): draw a dotted line
        # between their real observations instead of isolated dots. Values are not filled.
        "connect": [str(n) for n in (args.get("connect") or [])],
    }

    panels = args.get("panels")
    if panels:
        if not isinstance(panels, list):
            raise ChartError("'panels' must be a list.")
        spec["panels"] = []
        for i, p in enumerate(panels):
            x = list(p.get("x") or [])
            series = p.get("series") or {}
            for name, ys in series.items():
                if len(ys) != len(x):
                    raise ChartError(f"Panel {i + 1} series '{name}' has {len(ys)} values for {len(x)} x points.")
            spec["panels"].append({
                "subtitle": str(p.get("subtitle") or ""),
                "x": x,
                "series": {str(k): _nums(v, k) for k, v in series.items()},
                "colors": p.get("colors") or {},
                "connect": [str(n) for n in (p.get("connect") or [])],
            })
        spec["plot_type"] = "line" if plot_type not in ("line", "area", "bar", "grouped_bar", "stacked_bar") else plot_type
        return spec

    x = list(args.get("x_data") or args.get("labels") or [])
    spec["x"] = x
    series = args.get("series")
    y = args.get("y_data") if args.get("y_data") is not None else args.get("values")

    if plot_type == "heatmap":
        z = args.get("z_data")
        if not isinstance(z, list) or not z or not all(isinstance(r, list) for r in z):
            raise ChartError("heatmap needs z_data as a 2-D list (rows × columns).")
        rows = list(args.get("y_categories") or [f"Row {i + 1}" for i in range(len(z))])
        if len(rows) != len(z):
            raise ChartError("y_categories must have one entry per z_data row.")
        if x and any(len(r) != len(x) for r in z):
            raise ChartError("Each z_data row must have one value per x_data column.")
        spec["z"] = [_nums(r, "z_data") for r in z]
        spec["y_categories"] = rows
        return spec

    if plot_type == "treemap":
        if not x or y is None:
            raise ChartError("treemap needs x_data (labels) and y_data (values).")
        parents = list(args.get("parents") or [""] * len(x))
        if len(parents) != len(x) or len(y) != len(x):
            raise ChartError("treemap labels, values and parents must have equal length.")
        spec.update({"y": _nums(y, "y_data"), "parents": parents})
        return spec

    if plot_type in ("histogram", "box", "violin") and not series:
        values = y if y is not None else x
        spec["series"] = {spec["y_label"] or "values": _nums(values, "y_data")}
        spec["x"] = []
        return spec
    if plot_type in ("box", "violin", "histogram") and series:
        spec["series"] = {str(k): _nums(v, k) for k, v in series.items()}
        spec["x"] = []
        return spec

    if not x:
        raise ChartError("x_data cannot be empty.")
    if series:
        if not isinstance(series, dict):
            raise ChartError("'series' must be an object {name: [values]}.")
        bad = [k for k, v in series.items() if not isinstance(v, list) or len(v) != len(x)]
        if bad:
            raise ChartError(f"Each series must have exactly {len(x)} values (one per x_data item); invalid: {bad}")
        spec["series"] = {str(k): _nums(v, k) for k, v in series.items()}
    else:
        if y is None:
            raise ChartError(f"y_data (or series) is required for a {plot_type} chart.")
        if len(y) != len(x):
            raise ChartError(f"x_data has {len(x)} items but y_data has {len(y)}.")
        spec["series"] = {spec["y_label"] or "value": _nums(y, "y_data")}

    if plot_type in ("pie", "donut"):
        vals = next(iter(spec["series"].values()))
        if len(x) < 2:
            raise ChartError("Pie/donut charts need at least 2 categories; don't chart a single value as 100%.")
        if any(v is not None and v < 0 for v in vals):
            raise ChartError("Pie/donut values cannot be negative.")
    if plot_type == "bubble":
        sizes = args.get("sizes")
        if not isinstance(sizes, list) or len(sizes) != len(x):
            raise ChartError("bubble charts need 'sizes' with one value per point.")
        spec["sizes"] = _nums(sizes, "sizes")
    return spec


# ── Plotly figure construction ───────────────────────────────────────────────

def _color(spec_colors: dict, name: str, i: int) -> str:
    return spec_colors.get(name) or PALETTE[i % len(PALETTE)]


def build_figure(spec: dict):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    th = _THEMES[spec.get("theme", "dark")]
    t = spec["plot_type"]
    colors = spec.get("colors") or {}

    if spec.get("panels"):
        panels = spec["panels"]
        fig = make_subplots(
            rows=len(panels), cols=1, shared_xaxes=False, vertical_spacing=0.12,
            subplot_titles=[p["subtitle"] for p in panels],
        )
        seen: set[str] = set()
        for r, p in enumerate(panels, start=1):
            for i, (name, ys) in enumerate(p["series"].items()):
                c = p["colors"].get(name) or _color(colors, name, i)
                sparse = name in p.get("connect", []) or name in spec.get("connect", [])
                fig.add_trace(go.Scatter(
                    x=p["x"], y=ys, name=name, mode="lines+markers", connectgaps=sparse,
                    line=dict(color=c, width=2.4, dash="dot" if sparse else "solid"), marker=dict(size=7 if sparse else 6),
                    legendgroup=name, showlegend=name not in seen,
                    hovertemplate=f"{name}<br>%{{x}}: %{{y:.2f}}{spec.get('y_suffix', '')}<extra></extra>",
                ), row=r, col=1)
                seen.add(name)
        all_x = sorted({x for p in panels for x in p["x"]}, key=lambda v: (str(type(v)), v))
        if _is_year_axis(all_x):
            for r in range(1, len(panels) + 1):
                fig.update_xaxes(range=[min(all_x) - 0.5, max(all_x) + 0.5], dtick=1, tickangle=-45, row=r, col=1)
        height = 380 * len(panels) + 120
    else:
        fig = go.Figure()
        x = spec.get("x") or []
        series = spec.get("series") or {}
        hover_suffix = spec.get("y_suffix", "")
        if t in ("line", "area", "stacked_area"):
            for i, (name, ys) in enumerate(series.items()):
                kw: dict = {}
                if t == "area":
                    kw["fill"] = "tozeroy"
                if t == "stacked_area":
                    kw.update(stackgroup="one")
                sparse = name in spec.get("connect", [])
                fig.add_trace(go.Scatter(
                    x=x, y=ys, name=name, mode="lines+markers" if t == "line" else "lines",
                    connectgaps=sparse, line=dict(color=_color(colors, name, i), width=2.4, dash="dot" if sparse else "solid"),
                    hovertemplate=f"{name}<br>%{{x}}: %{{y:.2f}}{hover_suffix}<extra></extra>", **kw,
                ))
        elif t in ("bar", "grouped_bar", "stacked_bar", "horizontal_bar"):
            horizontal = t == "horizontal_bar"
            single = len(series) == 1
            for i, (name, ys) in enumerate(series.items()):
                if single and t == "bar":
                    marker_color = [colors.get(str(c)) or PALETTE[j % len(PALETTE)] for j, c in enumerate(x)]
                else:
                    marker_color = _color(colors, name, i)
                fig.add_trace(go.Bar(
                    x=ys if horizontal else x, y=x if horizontal else ys, name=name,
                    orientation="h" if horizontal else "v", marker_color=marker_color,
                    text=[None if v is None else f"{v:,.4g}" for v in ys], textposition="auto",
                    hovertemplate=f"{name}<br>%{{{'y' if horizontal else 'x'}}}: %{{{'x' if horizontal else 'y'}:,.4g}}{hover_suffix}<extra></extra>",
                ))
            fig.update_layout(barmode="stack" if t == "stacked_bar" else "group", showlegend=not single)
        elif t in ("pie", "donut"):
            vals = next(iter(series.values()))
            fig.add_trace(go.Pie(
                labels=x, values=vals, hole=0.45 if t == "donut" else 0,
                marker=dict(colors=[colors.get(str(c)) or PALETTE[j % len(PALETTE)] for j, c in enumerate(x)]),
                textinfo="label+percent", sort=False,
            ))
        elif t == "histogram":
            for i, (name, vals) in enumerate(series.items()):
                fig.add_trace(go.Histogram(x=[v for v in vals if v is not None], name=name,
                                           marker_color=_color(colors, name, i), opacity=0.8))
            fig.update_layout(barmode="overlay")
        elif t in ("box", "violin"):
            for i, (name, vals) in enumerate(series.items()):
                clean = [v for v in vals if v is not None]
                if t == "box":
                    fig.add_trace(go.Box(y=clean, name=name, marker_color=_color(colors, name, i), boxmean=True))
                else:
                    fig.add_trace(go.Violin(y=clean, name=name, line_color=_color(colors, name, i), box_visible=True, meanline_visible=True))
        elif t in ("scatter", "bubble"):
            for i, (name, ys) in enumerate(series.items()):
                marker: dict = dict(color=_color(colors, name, i), size=9, line=dict(width=0.5, color="#ffffff"))
                if t == "bubble":
                    smax = max([s for s in spec["sizes"] if s] or [1])
                    marker.update(size=spec["sizes"], sizemode="area", sizeref=2.0 * smax / (45 ** 2), sizemin=4)
                fig.add_trace(go.Scatter(x=x, y=ys, name=name, mode="markers", marker=marker))
        elif t == "heatmap":
            fig.add_trace(go.Heatmap(z=spec["z"], x=x or None, y=spec["y_categories"], colorscale="Viridis",
                                     hoverongaps=False, texttemplate="%{z:.4~g}"))
        elif t == "treemap":
            fig.add_trace(go.Treemap(labels=x, parents=spec["parents"], values=spec["y"], branchvalues="total",
                                     textinfo="label+value+percent root"))
        elif t == "funnel":
            vals = next(iter(series.values()))
            fig.add_trace(go.Funnel(y=x, x=vals, textinfo="value+percent initial"))
        elif t == "waterfall":
            vals = next(iter(series.values()))
            fig.add_trace(go.Waterfall(x=x, y=vals, text=[None if v is None else f"{v:,.4g}" for v in vals],
                                       connector=dict(line=dict(color=th["muted"]))))
        elif t == "radar":
            for i, (name, ys) in enumerate(series.items()):
                fig.add_trace(go.Scatterpolar(r=ys + ys[:1], theta=list(x) + list(x[:1]), name=name, fill="toself",
                                              line=dict(color=_color(colors, name, i))))
        if t not in ("pie", "donut", "treemap", "radar", "funnel") and _is_year_axis(x):
            fig.update_xaxes(dtick=1, tickangle=-45 if len(x) > 10 else 0)
        height = 560

    title_text = f"<b>{spec['title']}</b>"
    if spec.get("subtitle") and not spec.get("panels"):
        title_text += f"<br><span style='font-size:13px;color:{th['muted']}'>{spec['subtitle']}</span>"
    fig.update_layout(
        title=dict(text=title_text, x=0.5, xanchor="center", font=dict(size=18)),
        paper_bgcolor=th["paper"], plot_bgcolor=th["plot"],
        font=dict(family="Inter, Segoe UI, Arial, sans-serif", color=th["font"], size=13),
        legend=dict(orientation="v", x=1.02, y=1, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=70, r=40, t=90 if not spec.get("panels") else 110, b=((120 if spec.get("panels") else 100) + 16 * (len(spec.get("footnote") or "") // 150)) if spec.get("footnote") else 60),
        height=height, width=1100, hovermode="x unified" if t in ("line", "area", "stacked_area") else "closest",
    )
    if t not in ("pie", "donut", "treemap", "radar", "funnel"):
        fig.update_xaxes(gridcolor=th["grid"], zeroline=False, title_text=spec.get("x_label") or None)
        fig.update_yaxes(gridcolor=th["grid"], zeroline=False, title_text=spec.get("y_label") or None,
                         ticksuffix=spec.get("y_suffix") or None)
        if spec.get("panels") and spec.get("x_label"):
            fig.update_xaxes(title_text=None)
            fig.update_xaxes(title_text=spec["x_label"], row=len(spec["panels"]), col=1)
    if spec.get("footnote"):
        import textwrap
        foot = "<br>".join(textwrap.wrap(spec["footnote"], 150))
        fig.add_annotation(text=foot, xref="paper", yref="paper", x=0, y=-0.02,
                           yshift=-60 if not spec.get("panels") else -70, showarrow=False, align="left",
                           font=dict(size=11, color=th["muted"]), xanchor="left", yanchor="top")
    return fig


# ── Export ────────────────────────────────────────────────────────────────────

def _ensure_kaleido_server() -> None:
    """Keep one headless browser alive so repeated exports are fast."""
    global _kaleido_started
    if _kaleido_started:
        return
    try:
        import kaleido
        if hasattr(kaleido, "start_sync_server"):
            kaleido.start_sync_server(silence_warnings=True)
    except Exception as exc:
        logger.debug(f"Kaleido persistent server unavailable: {exc}")
    _kaleido_started = True


def figure_to_png(fig) -> bytes:
    import warnings
    with _kaleido_lock:
        _ensure_kaleido_server()
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="The kopts argument is ignored")
            return fig.to_image(format="png", scale=2)


# ── Matplotlib fallback (basic types) ────────────────────────────────────────

def _mpl_png(spec: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    th = _THEMES[spec.get("theme", "dark")]
    panels = spec.get("panels") or [{"subtitle": spec.get("subtitle", ""), "x": spec.get("x") or [], "series": spec.get("series") or {}, "colors": {}}]
    t = spec["plot_type"]
    fig, axes = plt.subplots(len(panels), 1, figsize=(10, 4.6 * len(panels)), dpi=170, squeeze=False)
    fig.patch.set_facecolor(th["paper"])
    for ax, p in zip(axes[:, 0], panels):
        ax.set_facecolor(th["plot"])
        ax.tick_params(colors=th["muted"])
        for sp in ax.spines.values():
            sp.set_color(th["muted"])
        x = p["x"]
        series = p["series"]
        if t in ("pie", "donut"):
            vals = next(iter(series.values()))
            ax.pie(vals, labels=x, autopct="%1.1f%%", textprops=dict(color=th["font"]),
                   wedgeprops=dict(width=0.45) if t == "donut" else None)
        elif t in ("bar", "grouped_bar", "stacked_bar", "horizontal_bar"):
            n = len(series)
            idx = list(range(len(x)))
            bottom = [0.0] * len(x)
            for i, (name, ys) in enumerate(series.items()):
                vals = [v or 0 for v in ys]
                c = p["colors"].get(name) or _color(spec.get("colors") or {}, name, i)
                if t == "horizontal_bar":
                    ax.barh(idx, vals, color=c, label=name)
                elif t == "stacked_bar":
                    ax.bar(idx, vals, bottom=bottom, color=c, label=name)
                    bottom = [b + v for b, v in zip(bottom, vals)]
                else:
                    w = 0.8 / n
                    ax.bar([j + i * w - 0.4 + w / 2 for j in idx], vals, width=w, color=c, label=name)
            (ax.set_yticks if t == "horizontal_bar" else ax.set_xticks)(idx)
            (ax.set_yticklabels if t == "horizontal_bar" else ax.set_xticklabels)([str(v) for v in x], rotation=0 if t == "horizontal_bar" else 45)
        elif t == "histogram":
            for i, (name, vals) in enumerate(series.items()):
                ax.hist([v for v in vals if v is not None], bins=15, alpha=0.8, label=name, color=_color({}, name, i))
        elif t == "scatter":
            for i, (name, ys) in enumerate(series.items()):
                ax.scatter(x, ys, label=name, color=_color({}, name, i))
        else:  # line / area / others fall back to lines
            for i, (name, ys) in enumerate(series.items()):
                c = p["colors"].get(name) or _color(spec.get("colors") or {}, name, i)
                ax.plot(x, [float("nan") if v is None else v for v in ys], marker="o", color=c, label=name, linewidth=2)
            if _is_year_axis(x):
                ax.set_xticks(x)
                ax.set_xticklabels([str(int(v)) for v in x], rotation=45)
        if p.get("subtitle"):
            ax.set_title(p["subtitle"], color=th["font"], fontsize=10)
        ax.set_ylabel(spec.get("y_label", ""), color=th["font"])
        ax.grid(True, alpha=0.15)
        if t not in ("pie", "donut") and len(series) > 1:
            leg = ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
            for txt in leg.get_texts():
                txt.set_color(th["font"])
    axes[-1, 0].set_xlabel(spec.get("x_label", ""), color=th["font"])
    fig.suptitle(spec["title"], color=th["font"], fontweight="bold")
    if spec.get("footnote"):
        fig.text(0.01, 0.005, spec["footnote"], color=th["muted"], fontsize=7)
    plt.tight_layout(rect=(0, 0.03, 1, 0.96))
    buf = io.BytesIO()
    plt.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ── Public API ────────────────────────────────────────────────────────────────

def render_png(spec: dict) -> tuple[bytes, Any, str]:
    """Return (png_bytes, plotly_figure_or_None, engine)."""
    try:
        fig = build_figure(spec)
    except ImportError:
        fig = None
    if fig is not None:
        try:
            return figure_to_png(fig), fig, "plotly"
        except Exception as exc:
            logger.warning(f"Plotly PNG export failed ({exc}); using Matplotlib fallback.")
    basic = {"line", "area", "stacked_area", "bar", "grouped_bar", "stacked_bar", "horizontal_bar", "pie", "donut", "histogram", "scatter"}
    if spec["plot_type"] not in basic:
        raise ChartError(
            f"'{spec['plot_type']}' charts need Plotly with Kaleido (Chrome) for image export, which is unavailable."
        )
    return _mpl_png(spec), fig, "matplotlib"


def save_chart(spec: dict, workspace: str | None, overwrite: bool = False) -> dict:
    """Render and save a chart as a downloadable PNG artifact (+ interactive HTML)."""
    from tools.artifact_store import save_artifact, get_artifacts_dir

    png, fig, engine = render_png(spec)
    meta: dict = {"chart_engine": engine, "plot_type": spec["plot_type"]}
    if fig is not None:
        try:
            meta["plotly_figure"] = json.loads(fig.to_json())
        except Exception:
            pass
    row = save_artifact(
        title=spec["title"], artifact_type="plot", format="image",
        file_bytes=png, file_ext="png", meta=meta, workspace=workspace, overwrite=overwrite,
    )
    html_rel = None
    if fig is not None:
        try:
            out_dir = Path(get_artifacts_dir(workspace))
            html_path = out_dir / f"{row['id']}.html"
            # One shared plotly.min.js per artifacts folder keeps each chart small.
            fig.write_html(str(html_path), include_plotlyjs="directory", full_html=True,
                           config={"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}})
            html_rel = str(Path("artifacts_store") / html_path.name)
        except Exception as exc:
            logger.debug(f"Interactive HTML export failed: {exc}")
    return {
        "artifact_id": row["id"],
        "file_path": row.get("file_path"),
        "interactive_html": html_rel,
        "title": spec["title"],
        "plot_type": spec["plot_type"],
        "engine": engine,
    }
