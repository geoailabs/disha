"""Shared artifact storage — used by both HTTP router and AI tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from database import get_connection

_DEFAULT_ART_DIR = Path.home() / ".disha" / "artifacts_store"
ARTIFACTS_DIR = Path(os.environ.get("DISHA_ARTIFACTS_DIR", str(_DEFAULT_ART_DIR)))
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

def get_artifacts_dir(workspace: str | None = None) -> Path:
    if workspace:
        ws_dir = Path(workspace) / ".disha" / "artifacts_store"
        ws_dir.mkdir(parents=True, exist_ok=True)
        return ws_dir
    return ARTIFACTS_DIR

ALLOWED_FORMATS = {"markdown", "table", "image", "geojson", "html", "pdf", "docx", "txt", "xlsx", "json", "png", "jpg", "jpeg"}


def _extract_coordinates(geometry: dict) -> list[list[float]]:
    """Recursively extract all coordinate pairs from a GeoJSON geometry."""
    coords: list[list[float]] = []
    geom_type = geometry.get("type", "")
    raw = geometry.get("coordinates")
    if raw is None:
        return coords

    def _flatten(obj):
        if not obj:
            return
        # A coordinate pair is a list/tuple of numbers (len 2 or 3)
        if isinstance(obj[0], (int, float)):
            coords.append(obj)
        else:
            for item in obj:
                _flatten(item)

    _flatten(raw)
    return coords


def _compute_bbox(geojson: dict) -> list[float]:
    """Compute [minLon, minLat, maxLon, maxLat] from a GeoJSON object."""
    all_coords: list[list[float]] = []

    def _gather(obj):
        t = obj.get("type", "")
        if t == "FeatureCollection":
            for f in obj.get("features", []):
                _gather(f)
        elif t == "Feature":
            geom = obj.get("geometry")
            if geom:
                all_coords.extend(_extract_coordinates(geom))
        elif t in ("Point", "MultiPoint", "LineString", "MultiLineString",
                   "Polygon", "MultiPolygon", "GeometryCollection"):
            all_coords.extend(_extract_coordinates(obj))

    _gather(geojson)

    if not all_coords:
        return [0.0, 0.0, 0.0, 0.0]

    lons = [c[0] for c in all_coords]
    lats = [c[1] for c in all_coords]
    return [min(lons), min(lats), max(lons), max(lats)]


def _render_chart_from_json(title: str, json_str: str) -> Optional[bytes]:
    """Auto-render a matplotlib chart from JSON string containing labels/values or x_data/y_data."""
    try:
        data = json.loads(json_str.strip())
        if not isinstance(data, dict):
            return None
        labels = data.get("labels") or data.get("x_data") or data.get("categories") or []
        values = data.get("values") or data.get("y_data") or data.get("counts") or data.get("data") or []
        if not labels or not values:
            return None

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import io

        fig, ax = plt.subplots(figsize=(8, 4.8), dpi=200)
        fig.patch.set_facecolor('#0f172a')
        ax.set_facecolor('#1e293b')

        ptype = data.get("plot_type") or ("pie" if "pie" in title.lower() or "distribution" in title.lower() else "bar")
        if ptype == "pie":
            colors = plt.cm.tab10.colors
            wedges, texts, autotexts = ax.pie(
                values,
                labels=labels,
                autopct='%1.1f%%',
                startangle=140,
                colors=colors[:len(labels)],
                textprops=dict(color="#f8fafc", fontsize=9.5),
                wedgeprops=dict(width=0.45, edgecolor='#0f172a', linewidth=1.5),
            )
            for at in autotexts:
                at.set_color('#ffffff')
                at.set_weight('bold')
        else:
            ax.bar(labels, values, color="#0284c7", width=0.55, edgecolor='#0f172a')
            ax.tick_params(colors='#94a3b8', labelsize=9)
            ax.grid(True, linestyle='--', alpha=0.15, color='#cbd5e1')

        ax.set_title(title, color='#f8fafc', fontsize=12, fontweight='bold', pad=12)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return None


def save_artifact(
    title: str,
    artifact_type: str,
    format: str,
    *,
    content: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
    file_ext: Optional[str] = None,
    meta: Optional[dict] = None,
    artifact_id: Optional[int] = None,
    overwrite: bool = False,
    workspace: Optional[str] = None,
) -> dict:
    """Create or update an artifact row + optional file. Returns the full row as a dict."""
    fmt = format.lower()
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(
            f"Invalid format '{format}'. Must be one of: {', '.join(sorted(ALLOWED_FORMATS))}"
        )

    # --- Validate / enrich per format ---
    final_content: str = content or ""
    final_meta: Optional[dict] = meta.copy() if meta else None
    actual_file_bytes: Optional[bytes] = file_bytes
    is_img = fmt in ("image", "png", "jpg", "jpeg", "webp", "gif")

    # If image content is provided as base64 data string, decode it
    if is_img and not actual_file_bytes and content:
        import base64
        trimmed = content.strip()
        if trimmed.startswith("data:image/") and ";base64," in trimmed:
            b64_str = trimmed.split(";base64,")[1]
            try:
                actual_file_bytes = base64.b64decode(b64_str)
            except Exception:
                pass
        elif len(trimmed) > 100 and not trimmed.startswith(("{", "<", "#", "http")):
            try:
                actual_file_bytes = base64.b64decode(trimmed)
            except Exception:
                pass

        # If image content is JSON with chart data (labels/values), auto-render plot image
        if not actual_file_bytes and (trimmed.startswith("{") or trimmed.startswith("[")):
            rendered = _render_chart_from_json(title, trimmed)
            if rendered:
                actual_file_bytes = rendered

    if fmt == "markdown":
        # content stored as-is; no file needed
        pass

    elif fmt == "table":
        if not content:
            raise ValueError("Table artifact requires 'content' with JSON {columns, rows}.")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Table content must be valid JSON: {exc}") from exc
        if not isinstance(data, dict) or "columns" not in data or "rows" not in data:
            raise ValueError("Table content must be a JSON object with 'columns' and 'rows' keys.")
        columns = data["columns"]
        rows = data["rows"]
        if not isinstance(columns, list):
            raise ValueError("Table 'columns' must be a list.")
        if not isinstance(rows, list):
            raise ValueError("Table 'rows' must be a list of lists.")
        row_meta = {"row_count": len(rows)}
        if final_meta:
            final_meta = {**row_meta, **final_meta}
        else:
            final_meta = row_meta
        final_content = content

    elif fmt == "geojson":
        if not content:
            raise ValueError("GeoJSON artifact requires 'content' with a GeoJSON string.")
        try:
            geojson = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"GeoJSON content must be valid JSON: {exc}") from exc
        if not isinstance(geojson, dict) or "type" not in geojson:
            raise ValueError("GeoJSON content must be a JSON object with a 'type' field.")

        # Count features
        geojson_type = geojson.get("type")
        if geojson_type == "FeatureCollection":
            feature_count = len(geojson.get("features", []))
        elif geojson_type == "Feature":
            feature_count = 1
        else:
            feature_count = 1  # geometry object

        bbox = _compute_bbox(geojson)
        geo_meta = {"feature_count": feature_count, "bbox": bbox}
        if final_meta:
            final_meta = {**geo_meta, **final_meta}
        else:
            final_meta = geo_meta
        final_content = content

    elif is_img:
        # Keep any description/content text or default to empty string
        final_content = (content or "") if not (content or "").startswith("data:image/") else ""

    # --- Insert or update row ---
    meta_json = json.dumps(final_meta) if final_meta is not None else None

    conn = get_connection(workspace)
    try:
        # Case 1: Specific artifact_id provided (e.g. updating pre-reserved export ID)
        if artifact_id is not None:
            existing = conn.execute(
                "SELECT id, title, artifact_type, format, content, meta, file_path, created_at, updated_at "
                "FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            if existing:
                file_path_rel = existing["file_path"]
                if actual_file_bytes:
                    ext = (file_ext or ("docx" if fmt == "docx" else ("pdf" if fmt == "pdf" else ("jpg" if fmt in ("jpg", "jpeg") else ("png" if fmt in ("png", "image") else fmt))))).lstrip(".")
                    if is_img:
                        try:
                            from PIL import Image
                            import io
                            img = Image.open(io.BytesIO(actual_file_bytes))
                            width, height = img.size
                            img_format = (img.format or ext).lower()
                            mime_map = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
                            mime = mime_map.get(img_format, f"image/{img_format}")
                        except Exception:
                            width, height, mime = 0, 0, f"image/{ext}"
                        img_meta = {"width": width, "height": height, "mime": mime}
                        final_meta = {**img_meta, **(final_meta or {})}
                        meta_json = json.dumps(final_meta)

                    filename = f"{artifact_id}.{ext}"
                    file_path_full = get_artifacts_dir(workspace) / filename
                    file_path_full.write_bytes(actual_file_bytes)
                    file_path_rel = str(Path("artifacts_store") / filename)

                conn.execute(
                    "UPDATE artifacts SET content = ?, format = ?, meta = ?, file_path = ?, title = COALESCE(?, title), updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (final_content, fmt, meta_json, file_path_rel, title, artifact_id),
                )
                conn.commit()
                updated = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
                return dict(updated)

        # Case 2: Explicit overwrite requested by title + artifact_type
        if overwrite:
            existing = conn.execute(
                "SELECT id, title, artifact_type, format, content, meta, file_path, created_at, updated_at "
                "FROM artifacts WHERE title = ? AND artifact_type = ? ORDER BY id DESC LIMIT 1",
                (title, artifact_type),
            ).fetchone()
            if existing:
                art_id = existing["id"]
                file_path_rel = existing["file_path"]
                if actual_file_bytes:
                    ext = (file_ext or ("docx" if fmt == "docx" else ("pdf" if fmt == "pdf" else fmt))).lstrip(".")
                    filename = f"{art_id}.{ext}"
                    file_path_full = get_artifacts_dir(workspace) / filename
                    file_path_full.write_bytes(actual_file_bytes)
                    file_path_rel = str(Path("artifacts_store") / filename)

                conn.execute(
                    "UPDATE artifacts SET content = ?, format = ?, meta = ?, file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (final_content, fmt, meta_json, file_path_rel, art_id),
                )
                conn.commit()
                updated = conn.execute("SELECT * FROM artifacts WHERE id = ?", (art_id,)).fetchone()
                return dict(updated)

        # Case 3: Create clean new artifact row
        cursor = conn.execute(
            "INSERT INTO artifacts (title, content, artifact_type, format, meta) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, final_content, artifact_type, fmt, meta_json),
        )
        artifact_id = cursor.lastrowid
        # Defer commit for images until file write succeeds
        if not is_img:
            conn.commit()

        file_path_rel: Optional[str] = None

        if actual_file_bytes:
            ext = (file_ext or ("docx" if fmt == "docx" else ("pdf" if fmt == "pdf" else ("jpg" if fmt in ("jpg", "jpeg") else ("png" if fmt in ("png", "image") else fmt))))).lstrip(".")
            if is_img:
                try:
                    from PIL import Image
                    import io

                    img = Image.open(io.BytesIO(actual_file_bytes))
                    width, height = img.size
                    img_format = (img.format or ext).lower()
                    mime_map = {
                        "jpeg": "image/jpeg",
                        "jpg": "image/jpeg",
                        "png": "image/png",
                        "gif": "image/gif",
                        "webp": "image/webp",
                        "bmp": "image/bmp",
                        "tiff": "image/tiff",
                    }
                    mime = mime_map.get(img_format, f"image/{img_format}")
                except Exception:
                    width, height, mime = 0, 0, f"image/{ext}"

                image_meta = {"width": width, "height": height, "mime": mime}
                if final_meta:
                    image_meta = {**image_meta, **final_meta}
                meta_json = json.dumps(image_meta)

            filename = f"{artifact_id}.{ext}"
            file_path_full = get_artifacts_dir(workspace) / filename
            try:
                file_path_full.write_bytes(actual_file_bytes)
            except OSError:
                conn.rollback()
                raise
            file_path_rel = str(Path("artifacts_store") / filename)

            conn.execute(
                "UPDATE artifacts SET file_path = ?, meta = ? WHERE id = ?",
                (file_path_rel, meta_json, artifact_id),
            )
            conn.commit()

        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def read_artifact(artifact_id: int, workspace: Optional[str] = None) -> Optional[dict]:
    """Return full artifact row (including resolved payload), or None if not found."""
    conn = get_connection(workspace)
    try:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def delete_artifact(artifact_id: int, workspace: Optional[str] = None) -> None:
    """Delete artifact row and its file (if any)."""
    conn = get_connection(workspace)
    try:
        row = conn.execute(
            "SELECT file_path FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if not row:
            return

        file_path = row["file_path"]
        if file_path:
            filename = Path(file_path).name
            full_path = get_artifacts_dir(workspace) / filename
            try:
                full_path.unlink(missing_ok=True)
            except Exception:
                pass

        conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        conn.commit()
    finally:
        conn.close()


def list_artifacts(workspace: Optional[str] = None) -> list[dict]:
    """Return all artifact rows with previews and file paths."""
    conn = get_connection(workspace)
    try:
        rows = conn.execute(
            "SELECT id, title, artifact_type, format, meta, "
            "SUBSTR(content, 1, 200) as preview, file_path, created_at, updated_at "
            "FROM artifacts ORDER BY position ASC, updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

