import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, Response
from models import ArtifactCreate, ArtifactUpdate
from fastapi import Query
from tools.artifact_store import save_artifact, read_artifact, delete_artifact, ARTIFACTS_DIR, get_artifacts_dir
from database import get_connection

router = APIRouter()


@router.get("")
async def list_artifacts(workspace: str | None = Query(None)):
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


@router.post("", status_code=201)
async def create_artifact(artifact: ArtifactCreate, workspace: str | None = Query(None)):
    """Create a text-based artifact via JSON body (backward-compatible route)."""
    try:
        result = save_artifact(
            title=artifact.title,
            artifact_type=artifact.artifact_type,
            format=artifact.format,
            content=artifact.content if artifact.content else None,
            meta=artifact.meta if isinstance(artifact.meta, dict) else None,
            workspace=workspace,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/upload", status_code=201)
async def upload_artifact(
    title: str = Form(...),
    artifact_type: str = Form("note"),
    format: str = Form("image"),
    content: str = Form(""),
    meta: str = Form(""),
    file: UploadFile = File(None),
    workspace: str | None = Form(None),
):
    """Create an artifact via multipart form — intended for image uploads."""
    try:
        file_bytes = await file.read() if file else None
        file_ext = Path(file.filename).suffix.lstrip(".") if file and file.filename else None
        meta_dict = json.loads(meta) if meta else None
        result = save_artifact(
            title=title,
            artifact_type=artifact_type,
            format=format,
            content=content if content else None,
            file_bytes=file_bytes,
            file_ext=file_ext,
            meta=meta_dict,
            workspace=workspace,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/reorder")
async def reorder_artifacts(payload: dict, workspace: str | None = Query(None)):
    order = payload.get("order", [])
    conn = get_connection(workspace)
    try:
        for index, art_id in enumerate(order):
            conn.execute(
                "UPDATE artifacts SET position = ? WHERE id = ?",
                (index, art_id)
            )
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


@router.get("/{artifact_id}")
async def get_artifact_http(artifact_id: int, workspace: str | None = Query(None)):
    row = read_artifact(artifact_id, workspace)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return row


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: int, workspace: str | None = Query(None)):
    row = read_artifact(artifact_id, workspace)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    fmt = row.get("format", "markdown")

    if fmt == "image":
        fp = row.get("file_path")
        if not fp:
            raise HTTPException(status_code=404, detail="No file for this artifact")
        filename = Path(fp).name
        full_path = get_artifacts_dir(workspace) / filename
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File missing from disk")
        mime = (json.loads(row["meta"]) if row.get("meta") else {}).get(
            "mime", "application/octet-stream"
        )
        return FileResponse(str(full_path), media_type=mime, filename=Path(fp).name)

    # Text formats: serve as their native file type
    ext_map = {
        "markdown": ("md", "text/markdown"),
        "table": ("csv", "text/csv"),
        "geojson": ("geojson", "application/geo+json"),
    }
    ext, media_type = ext_map.get(fmt, ("txt", "text/plain"))
    content = row.get("content", "")

    if fmt == "table":
        import io
        import csv

        data = json.loads(content) if content else {"columns": [], "rows": []}
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(data.get("columns", []))
        w.writerows(data.get("rows", []))
        content = buf.getvalue()

    title_safe = (
        (row.get("title") or "artifact").replace(" ", "_").replace("/", "-")[:40]
    )
    return Response(
        content=content.encode(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{title_safe}.{ext}"'},
    )


@router.get("/{artifact_id}/docx")
async def download_artifact_docx(artifact_id: int, workspace: str | None = Query(None)):
    import tempfile
    from tools.doc_exporter import markdown_to_docx
    from fastapi.responses import FileResponse

    row = read_artifact(artifact_id, workspace)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    
    content = row.get("content", "")
    title = row.get("title") or "artifact"
    title_safe = title.replace(" ", "_").replace("/", "-")[:40]
    
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
        
    try:
        markdown_to_docx(content, tmp_path)
        return FileResponse(
            tmp_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{title_safe}.docx"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Word document: {str(e)}")


@router.get("/{artifact_id}/latex")
async def download_artifact_latex(artifact_id: int, background_tasks: BackgroundTasks, workspace: str | None = Query(None)):
    import tempfile
    from tools.md_to_pdf import convert as md_convert

    row = read_artifact(artifact_id, workspace)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content = row.get("content", "")
    title = row.get("title") or "Urban Planning Report"
    title_safe = title.replace(" ", "_").replace("/", "-")[:50]

    temp_dir = tempfile.mkdtemp()
    md_path = Path(temp_dir) / "input.md"
    tex_path = Path(temp_dir) / f"{title_safe}.tex"

    try:
        md_path.write_text(content, encoding="utf-8")
        md_convert(str(md_path), str(tex_path), tex_only=True)
        background_tasks.add_task(_cleanup_temp_dir, temp_dir)
        return FileResponse(
            str(tex_path),
            media_type="application/x-tex",
            filename=f"{title_safe}.tex",
        )
    except FileNotFoundError as e:
        _cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        _cleanup_temp_dir(temp_dir)
        raise HTTPException(
            status_code=503,
            detail=(
                "LaTeX export is unavailable — no conversion backend is installed on this server.\n"
                "Ask your administrator to run: pip install pypandoc_binary\n"
                f"Details: {e}"
            ),
        )
    except Exception as e:
        _cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=500, detail=f"Failed to generate LaTeX document: {e}")


def _cleanup_temp_dir(temp_dir_path: str):
    import shutil
    try:
        shutil.rmtree(temp_dir_path)
    except Exception:
        pass


@router.get("/{artifact_id}/pdf")
async def download_artifact_pdf(artifact_id: int, background_tasks: BackgroundTasks, workspace: str | None = Query(None)):
    import tempfile
    from tools.md_to_pdf import convert as md_convert

    row = read_artifact(artifact_id, workspace)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content = row.get("content", "")
    title = row.get("title") or "Urban Planning Report"
    title_safe = title.replace(" ", "_").replace("/", "-")[:50]

    temp_dir = tempfile.mkdtemp()
    md_path = Path(temp_dir) / "input.md"
    pdf_path = Path(temp_dir) / f"{title_safe}.pdf"

    try:
        md_path.write_text(content, encoding="utf-8")
        md_convert(str(md_path), str(pdf_path), tex_only=False)
        background_tasks.add_task(_cleanup_temp_dir, temp_dir)
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=f"{title_safe}.pdf",
        )
    except FileNotFoundError as e:
        _cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        _cleanup_temp_dir(temp_dir)
        raise HTTPException(
            status_code=503,
            detail=(
                "PDF export is unavailable — no conversion backend is installed on this server.\n"
                "Ask your administrator to run: pip install pypandoc_binary\n"
                f"Details: {e}"
            ),
        )
    except Exception as e:
        _cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF document: {e}")




@router.put("/{artifact_id}")
async def update_artifact(artifact_id: int, update: ArtifactUpdate, workspace: str | None = Query(None)):
    conn = get_connection(workspace)
    try:
        existing = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Artifact not found")

        fields, values = [], []
        if update.title is not None:
            fields.append("title = ?")
            values.append(update.title)
        if update.content is not None and existing["format"] != "image":
            fields.append("content = ?")
            values.append(update.content)
        if update.artifact_type is not None:
            fields.append("artifact_type = ?")
            values.append(update.artifact_type)
        if update.meta is not None:
            fields.append("meta = ?")
            values.append(
                json.dumps(update.meta) if not isinstance(update.meta, str) else update.meta
            )

        if fields:
            fields.append("updated_at = CURRENT_TIMESTAMP")
            values.append(artifact_id)
            conn.execute(
                f"UPDATE artifacts SET {', '.join(fields)} WHERE id = ?", values
            )
            conn.commit()

        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.delete("/{artifact_id}")
async def delete_artifact_http(artifact_id: int, workspace: str | None = Query(None)):
    conn = get_connection(workspace)
    try:
        existing = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if not existing:
        raise HTTPException(status_code=404, detail="Artifact not found")
    delete_artifact(artifact_id, workspace)
    return {"deleted": True}


@router.post("/clear_temp")
async def clear_temp_artifacts(workspace: str | None = Query(None)):
    conn = get_connection(workspace)
    try:
        conn.execute("DELETE FROM artifacts")
        conn.commit()
        return {"status": "success"}
    finally:
        conn.close()


@router.post("/{artifact_id}/export")
@router.get("/{artifact_id}/export")
async def export_artifact_endpoint(
    artifact_id: int,
    format: str = Query("pdf"),
    map_image_base64: str | None = Form(None),
    workspace: str | None = Query(None),
):
    from tools.export_engine import export_artifact_multi_format

    row = read_artifact(artifact_id, workspace)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")

    title = row.get("title") or "Artifact Export"
    content = row.get("content") or ""
    meta_dict = json.loads(row["meta"]) if row.get("meta") else {}

    file_bytes, filename, mime_type = export_artifact_multi_format(
        title=title,
        content=content,
        format_target=format,
        map_image_base64=map_image_base64,
        meta=meta_dict,
        workspace=workspace,
    )

    return Response(
        content=file_bytes,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
