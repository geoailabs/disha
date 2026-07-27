"""Shared artifact storage — used by both HTTP router and AI tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from database import get_connection

_BACKEND_DIR = Path(__file__).parent.parent  # packages/backend/
ARTIFACTS_DIR = _BACKEND_DIR / "artifacts_store"
ARTIFACTS_DIR.mkdir(exist_ok=True)

def get_artifacts_dir(workspace: str | None = None) -> Path:
    if workspace:
        ws_dir = Path(workspace) / ".disha" / "artifacts_store"
        ws_dir.mkdir(parents=True, exist_ok=True)
        return ws_dir
    return ARTIFACTS_DIR

ALLOWED_FORMATS = {"markdown", "table", "image", "geojson"}


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


def save_artifact(
    title: str,
    artifact_type: str,
    format: str,
    *,
    content: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
    file_ext: Optional[str] = None,
    meta: Optional[dict] = None,
    workspace: Optional[str] = None,
) -> dict:
    """Create an artifact row + optional file. Returns the full row as a dict."""
    if format not in ALLOWED_FORMATS:
        raise ValueError(
            f"Invalid format '{format}'. Must be one of: {', '.join(sorted(ALLOWED_FORMATS))}"
        )

    # --- Validate / enrich per format ---
    final_content: str = content or ""
    final_meta: Optional[dict] = meta.copy() if meta else None

    if format == "markdown":
        # content stored as-is; no file needed
        pass

    elif format == "table":
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

    elif format == "geojson":
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

    elif format == "image":
        if not file_bytes:
            raise ValueError("Image artifact requires 'file_bytes'.")
        # content must be non-NULL per DB schema; store empty string
        final_content = ""

    # --- Insert row first to get auto-increment id ---
    meta_json = json.dumps(final_meta) if final_meta is not None else None

    conn = get_connection(workspace)
    try:
        cursor = conn.execute(
            "INSERT INTO artifacts (title, content, artifact_type, format, meta) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, final_content, artifact_type, format, meta_json),
        )
        artifact_id = cursor.lastrowid
        # For image format, defer commit until after file write so we don't
        # leave an orphaned row if the disk write fails.
        if format != "image":
            conn.commit()

        file_path_rel: Optional[str] = None

        if format == "image" and file_bytes:
            ext = (file_ext or "bin").lstrip(".")
            # Use Pillow to get image dimensions and mime type
            try:
                from PIL import Image
                import io

                img = Image.open(io.BytesIO(file_bytes))
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
            if meta:
                image_meta = {**image_meta, **meta}
            meta_json = json.dumps(image_meta)

            filename = f"{artifact_id}.{ext}"
            file_path_full = get_artifacts_dir(workspace) / filename
            try:
                file_path_full.write_bytes(file_bytes)
            except OSError:
                conn.rollback()
                raise
            # store as relative path from ARTIFACTS_DIR parent (backend dir)
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
