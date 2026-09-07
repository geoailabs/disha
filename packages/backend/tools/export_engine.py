"""
Multi-Format Export Engine — Generates downloadable files in DOCX, PDF, HTML,
XLSX, TXT, JSON, and Image formats from stored artifacts, markdown reports, and map context.
"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Optional


def _resolve_image_bytes(image_ref: str, workspace: Optional[str] = None) -> Optional[bytes]:
    """Resolve an image reference (base64 data URI, artifacts_store path, artifact ID, or workspace path) to raw bytes."""
    if not image_ref:
        return None
    trimmed = image_ref.strip().replace("\\", "/")
    if trimmed.startswith("data:image/") and ";base64," in trimmed:
        try:
            return base64.b64decode(trimmed.split(";base64,")[1])
        except Exception:
            return None

    from pathlib import Path
    from tools.artifact_store import get_artifacts_dir, read_artifact, list_artifacts

    p = Path(trimmed)
    if p.is_file():
        try:
            return p.read_bytes()
        except Exception:
            pass

    if workspace:
        wp = Path(workspace) / trimmed
        if wp.is_file():
            try:
                return wp.read_bytes()
            except Exception:
                pass
        wp2 = Path(workspace) / ".disha" / trimmed
        if wp2.is_file():
            try:
                return wp2.read_bytes()
            except Exception:
                pass

    art_dir = get_artifacts_dir(workspace)
    ap = art_dir / p.name
    if ap.is_file():
        try:
            return ap.read_bytes()
        except Exception:
            pass

    # Resolve by artifact ID if reference is numeric stem
    stem = p.stem
    if stem.isdigit():
        try:
            art = read_artifact(int(stem), workspace)
            if art:
                # If artifact has JSON chart data, auto-render chart
                cnt = (art.get("content") or "").strip()
                if cnt.startswith("{") and ("labels" in cnt or "values" in cnt or "x_data" in cnt):
                    from tools.artifact_store import _render_chart_from_json
                    rendered = _render_chart_from_json(art.get("title", "Chart"), cnt)
                    if rendered:
                        if art.get("file_path"):
                            try:
                                (art_dir / Path(art["file_path"]).name).write_bytes(rendered)
                            except Exception:
                                pass
                        return rendered

                if art.get("file_path"):
                    fp = Path(workspace or ".") / art["file_path"] if workspace else Path(art["file_path"])
                    if fp.is_file() and fp.stat().st_size > 20:
                        return fp.read_bytes()
                    ap2 = art_dir / Path(art["file_path"]).name
                    if ap2.is_file() and ap2.stat().st_size > 20:
                        return ap2.read_bytes()
        except Exception:
            pass

    # Resolve by searching artifact list by title or keyword if reference is a label or title
    try:
        arts = list_artifacts(workspace=workspace)
        clean_ref = trimmed.lower().replace("_", " ").replace("-", " ")
        # 1. Exact title match
        for a in arts:
            title = (a.get("title") or "").strip().lower()
            if title and (title == clean_ref or title == trimmed.lower()):
                if a.get("file_path"):
                    ap_match = art_dir / Path(a["file_path"]).name
                    if ap_match.is_file():
                        return ap_match.read_bytes()
        # 2. Strict word boundary / prefix match (do not match general multi-word titles for single city names)
        for a in arts:
            title = (a.get("title") or "").strip().lower()
            if title and len(clean_ref) > 3:
                # Match only if clean_ref is a distinct word or start of title
                if clean_ref == title or title.startswith(clean_ref + " ") or f" {clean_ref} " in f" {title} ":
                    if a.get("file_path"):
                        ap_match = art_dir / Path(a["file_path"]).name
                        if ap_match.is_file():
                            return ap_match.read_bytes()
    except Exception:
        pass

    return None


def export_artifact_multi_format(
    title: str,
    content: str,
    format_target: str,
    *,
    map_image_base64: Optional[str] = None,
    meta: Optional[dict] = None,
    workspace: Optional[str] = None,
) -> tuple[bytes, str, str]:
    """
    Exports content into the specified target format (docx, pdf, html, xlsx, txt, json).
    Returns tuple of (file_bytes, filename, mime_type).
    """
    fmt = format_target.lower().lstrip(".")
    safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_") or "export"

    if fmt == "docx":
        b = generate_docx_export(title, content, map_image_base64=map_image_base64, workspace=workspace)
        return b, f"{safe_title}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    elif fmt == "html":
        b = generate_html_export(title, content, map_image_base64=map_image_base64, workspace=workspace)
        return b, f"{safe_title}.html", "text/html"

    elif fmt == "pdf":
        b = generate_pdf_export(title, content, map_image_base64=map_image_base64, workspace=workspace)
        return b, f"{safe_title}.pdf", "application/pdf"

    elif fmt == "xlsx":
        b = generate_xlsx_export(title, content, meta=meta)
        return b, f"{safe_title}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    elif fmt in ("png", "jpg", "jpeg"):
        if map_image_base64:
            raw_b64 = map_image_base64.split(",")[1] if "," in map_image_base64 else map_image_base64
            raw_bytes = base64.b64decode(raw_b64)
            if fmt in ("jpg", "jpeg"):
                from PIL import Image as PILImage
                with PILImage.open(io.BytesIO(raw_bytes)) as pil_img:
                    rgb_img = pil_img.convert("RGB")
                    jpg_buf = io.BytesIO()
                    rgb_img.save(jpg_buf, format="JPEG", quality=95)
                    return jpg_buf.getvalue(), f"{safe_title}.jpg", "image/jpeg"
            return raw_bytes, f"{safe_title}.png", "image/png"
        else:
            from PIL import Image as PILImage
            img = PILImage.new("RGB", (800, 600), color=(255, 255, 255))
            buf = io.BytesIO()
            img.save(buf, format="JPEG" if fmt in ("jpg", "jpeg") else "PNG")
            ext = "jpg" if fmt in ("jpg", "jpeg") else "png"
            mime = "image/jpeg" if fmt in ("jpg", "jpeg") else "image/png"
            return buf.getvalue(), f"{safe_title}.{ext}", mime

    elif fmt in ("json", "geojson"):
        if content.strip().startswith("{") or content.strip().startswith("["):
            out_str = content
        else:
            out_str = json.dumps({"title": title, "content": content, "meta": meta or {}}, indent=2)
        return out_str.encode("utf-8"), f"{safe_title}.json", "application/json"

    elif fmt == "txt":
        out_str = f"{title}\n{'=' * len(title)}\n\n{content}"
        return out_str.encode("utf-8"), f"{safe_title}.txt", "text/plain"

    else:
        return content.encode("utf-8"), f"{safe_title}.md", "text/markdown"


def _add_docx_markdown_paragraph(doc_or_cell, text: str, style: Optional[str] = None):
    """Add a paragraph with parsed inline formatting (**bold**, *italic*, `code`)."""
    from docx.shared import Pt, RGBColor
    if hasattr(doc_or_cell, 'add_paragraph'):
        p = doc_or_cell.add_paragraph(style=style)
    else:
        p = doc_or_cell.paragraphs[0]
        if style:
            p.style = style

    pattern = re.compile(r'(\*\*\*.*?\*\*\*|\*\*.*?\*\*|\*.*?\*|`.*?`|[^_*`]+)')
    tokens = pattern.findall(text)
    for token in tokens:
        if token.startswith('***') and token.endswith('***'):
            run = p.add_run(token[3:-3])
            run.bold = True
            run.italic = True
        elif token.startswith('**') and token.endswith('**'):
            run = p.add_run(token[2:-2])
            run.bold = True
        elif token.startswith('*') and token.endswith('*'):
            run = p.add_run(token[1:-1])
            run.italic = True
        elif token.startswith('`') and token.endswith('`'):
            run = p.add_run(token[1:-1])
            run.font.name = 'Consolas'
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(79, 70, 229)
        else:
            p.add_run(token)
    return p


def generate_docx_export(
    title: str,
    markdown_content: str,
    map_image_base64: Optional[str] = None,
    workspace: Optional[str] = None,
) -> bytes:
    """Generate a formatted Word .docx document using python-docx with embedded figures and tables."""
    import docx
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = docx.Document()

    # Configure Margins
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # Document Header Title
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_title = p_title.add_run(title)
    run_title.font.name = 'Calibri'
    run_title.font.size = Pt(22)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(15, 23, 42)

    doc.add_paragraph()

    # Embed Composed Map Snapshot if available
    if map_image_base64:
        try:
            if "," in map_image_base64:
                raw_bytes = base64.b64decode(map_image_base64.split(",")[1])
            else:
                raw_bytes = base64.b64decode(map_image_base64)

            img_stream = io.BytesIO(raw_bytes)
            p_img = doc.add_paragraph()
            p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run_img = p_img.add_run()
            run_img.add_picture(img_stream, width=Inches(5.8))
            
            p_cap = doc.add_paragraph()
            p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run_cap = p_cap.add_run(f"Figure: Composed Map Snapshot for {title}")
            run_cap.font.italic = True
            run_cap.font.size = Pt(9.5)
            run_cap.font.color.rgb = RGBColor(100, 116, 139)
            doc.add_paragraph()
        except Exception as exc:
            print(f"[DOCX Export] Image embed error: {exc}")

    img_pattern = re.compile(r'!\[(.*?)\]\((.*?)\)')
    lines = markdown_content.splitlines()

    in_table = False
    table_data = []

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # 1. Handle Markdown Table Block
        if s.startswith('|'):
            in_table = True
            cells = [c.strip() for c in s.split('|')[1:-1]]
            is_separator = all(re.match(r'^:?-+:?$', c) for c in cells) if cells else False
            if not is_separator:
                table_data.append(cells)
            i += 1
            continue
        elif in_table:
            if table_data:
                max_cols = max(len(row) for row in table_data)
                table = doc.add_table(rows=len(table_data), cols=max_cols)
                table.style = 'Table Grid'
                for r_idx, row_cells in enumerate(table_data):
                    for c_idx, val in enumerate(row_cells):
                        if c_idx < max_cols:
                            cell = table.rows[r_idx].cells[c_idx]
                            _add_docx_markdown_paragraph(cell, val)
            in_table = False
            table_data = []

        if not s:
            i += 1
            continue

        # 2. Handle Image Embeds
        img_match = img_pattern.search(s)
        if img_match:
            alt = img_match.group(1).strip()
            src = img_match.group(2).strip()
            raw_img_bytes = _resolve_image_bytes(src, workspace)
            if raw_img_bytes:
                try:
                    img_stream = io.BytesIO(raw_img_bytes)
                    p_img = doc.add_paragraph()
                    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run_img = p_img.add_run()
                    run_img.add_picture(img_stream, width=Inches(5.5))
                    if alt:
                        p_cap = doc.add_paragraph()
                        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        run_cap = p_cap.add_run(f"Figure: {alt}")
                        run_cap.font.italic = True
                        run_cap.font.size = Pt(9.5)
                        run_cap.font.color.rgb = RGBColor(100, 116, 139)
                    i += 1
                    continue
                except Exception as exc:
                    print(f"[DOCX Export] Inline image error: {exc}")

        # 3. Handle Headings
        if s.startswith("#"):
            h_match = re.match(r'^(#+)\s+(.*)', s)
            if h_match:
                level = len(h_match.group(1))
                h_text = h_match.group(2)
                h = doc.add_heading(h_text, level=min(level, 6))
                if h.runs:
                    colors = {
                        1: RGBColor(15, 23, 42),
                        2: RGBColor(30, 41, 59),
                        3: RGBColor(51, 65, 85),
                        4: RGBColor(71, 85, 105),
                    }
                    h.runs[0].font.color.rgb = colors.get(level, RGBColor(71, 85, 105))
            i += 1
            continue

        # 4. Handle Bullet Lists
        if s.startswith(("- ", "* ")):
            _add_docx_markdown_paragraph(doc, s[2:], style='List Bullet')
            i += 1
            continue

        # 5. Handle Numbered Lists
        num_match = re.match(r'^\d+\.\s+(.*)', s)
        if num_match:
            _add_docx_markdown_paragraph(doc, num_match.group(1), style='List Number')
            i += 1
            continue

        # 6. Standard Paragraph with inline styles
        p = _add_docx_markdown_paragraph(doc, s)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.space_after = Pt(4)
        i += 1

    if in_table and table_data:
        max_cols = max(len(row) for row in table_data)
        table = doc.add_table(rows=len(table_data), cols=max_cols)
        table.style = 'Table Grid'
        for r_idx, row_cells in enumerate(table_data):
            for c_idx, val in enumerate(row_cells):
                if c_idx < max_cols:
                    cell = table.rows[r_idx].cells[c_idx]
                    _add_docx_markdown_paragraph(cell, val)

    out_stream = io.BytesIO()
    doc.save(out_stream)
    return out_stream.getvalue()


def generate_html_export(
    title: str,
    markdown_content: str,
    map_image_base64: Optional[str] = None,
    workspace: Optional[str] = None,
) -> bytes:
    """Generate a self-contained styled HTML file with embedded images."""
    import markdown as md_lib

    img_pattern = re.compile(r'!\[(.*?)\]\((.*?)\)')
    def _img_replacer(match):
        alt = match.group(1).strip()
        src = match.group(2).strip()
        raw_b = _resolve_image_bytes(src, workspace)
        if raw_b:
            mime = "image/jpeg" if src.lower().endswith((".jpg", ".jpeg")) else "image/png"
            b64_uri = f"data:{mime};base64,{base64.b64encode(raw_b).decode('ascii')}"
            return f'<div class="figure-container"><img src="{b64_uri}" alt="{alt}" class="map-img"/><p class="caption">Figure: {alt}</p></div>'
        return match.group(0)

    processed_md = img_pattern.sub(_img_replacer, markdown_content)
    html_body = md_lib.markdown(processed_md, extensions=['tables', 'fenced_code', 'toc'])

    img_html = ""
    if map_image_base64:
        src = map_image_base64 if map_image_base64.startswith("data:") else f"data:image/png;base64,{map_image_base64}"
        img_html = f"""
        <div class="figure-container">
            <img src="{src}" alt="Map View" class="map-img"/>
            <p class="caption">Figure: Composed Map View & Spatial Overlays</p>
        </div>
        """

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            max-width: 900px;
            margin: 40px auto;
            padding: 24px;
            color: #1e293b;
            background-color: #ffffff;
            line-height: 1.6;
        }}
        h1 {{ font-size: 2.2rem; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }}
        h2 {{ font-size: 1.6rem; color: #1e293b; margin-top: 24px; }}
        h3 {{ font-size: 1.25rem; color: #334155; }}
        table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
        th, td {{ border: 1px solid #cbd5e1; padding: 10px 14px; text-align: left; }}
        th {{ background-color: #f1f5f9; color: #0f172a; font-weight: 600; }}
        code {{ background-color: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
        pre {{ background-color: #0f172a; color: #f8fafc; padding: 16px; border-radius: 8px; overflow-x: auto; }}
        .figure-container {{ text-align: center; margin: 24px 0; }}
        .map-img {{ max-width: 100%; height: auto; border-radius: 8px; border: 1px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }}
        .caption {{ font-size: 0.9rem; color: #64748b; font-style: italic; margin-top: 8px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {img_html}
    {html_body}
</body>
</html>"""
    return full_html.encode("utf-8")


def generate_pdf_export(
    title: str,
    markdown_content: str,
    map_image_base64: Optional[str] = None,
    workspace: Optional[str] = None,
) -> bytes:
    """Generate a clean, 100% valid PDF file using ReportLab (with WeasyPrint fallback)."""
    try:
        from weasyprint import HTML
        html_bytes = generate_html_export(title, markdown_content, map_image_base64=map_image_base64, workspace=workspace)
        return HTML(string=html_bytes.decode("utf-8")).write_pdf()
    except Exception:
        pass

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from PIL import Image as PILImage

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
        story = []

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=20,
            leading=24,
            textColor=colors.HexColor('#0f172a'),
            spaceAfter=12
        )
        h2_style = ParagraphStyle(
            'DocH2',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=17,
            textColor=colors.HexColor('#1e293b'),
            spaceBefore=10,
            spaceAfter=4
        )
        body_style = ParagraphStyle(
            'DocBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor('#334155'),
            spaceAfter=5
        )
        caption_style = ParagraphStyle(
            'DocCaption',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=8.5,
            leading=11,
            alignment=1,
            textColor=colors.HexColor('#64748b'),
            spaceAfter=10
        )

        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 8))

        if map_image_base64:
            try:
                raw_b64 = map_image_base64.split(",")[1] if "," in map_image_base64 else map_image_base64
                img_data = base64.b64decode(raw_b64)
                img_io = io.BytesIO(img_data)

                with PILImage.open(img_io) as pil_img:
                    orig_w, orig_h = pil_img.size

                max_w = 500.0
                max_h = 320.0
                aspect = orig_w / float(orig_h) if orig_h > 0 else 1.0

                if orig_w / max_w > orig_h / max_h:
                    final_w = max_w
                    final_h = max_w / aspect
                else:
                    final_h = max_h
                    final_w = max_h * aspect

                rl_img = RLImage(io.BytesIO(img_data), width=final_w, height=final_h)
                story.append(rl_img)
                story.append(Paragraph(f"Figure: Composed Map Snapshot for {title}", caption_style))
                story.append(Spacer(1, 6))
            except Exception as e:
                print(f"[ReportLab PDF] Image embed notice: {e}")

        img_pattern = re.compile(r'!\[(.*?)\]\((.*?)\)')
        lines = markdown_content.splitlines()
        for line in lines:
            s = line.strip()
            if not s:
                continue

            clean_s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            img_match = img_pattern.search(s)
            if img_match:
                alt = img_match.group(1).strip()
                src = img_match.group(2).strip()
                raw_img_bytes = _resolve_image_bytes(src, workspace)
                if raw_img_bytes:
                    try:
                        with PILImage.open(io.BytesIO(raw_img_bytes)) as pil_img:
                            orig_w, orig_h = pil_img.size
                        max_w = 480.0
                        max_h = 280.0
                        aspect = orig_w / float(orig_h) if orig_h > 0 else 1.0
                        if orig_w / max_w > orig_h / max_h:
                            final_w = max_w
                            final_h = max_w / aspect
                        else:
                            final_h = max_h
                            final_w = max_h * aspect
                        rl_img = RLImage(io.BytesIO(raw_img_bytes), width=final_w, height=final_h)
                        story.append(rl_img)
                        if alt:
                            story.append(Paragraph(f"Figure: {alt}", caption_style))
                        story.append(Spacer(1, 6))
                        continue
                    except Exception as e:
                        print(f"[ReportLab PDF] Inline image error: {e}")

            if s.startswith("# "):
                story.append(Paragraph(clean_s[2:], title_style))
            elif s.startswith("## ") or s.startswith("### "):
                story.append(Paragraph(clean_s.lstrip("#").strip(), h2_style))
            elif s.startswith("- ") or s.startswith("* "):
                story.append(Paragraph(f"• {clean_s[2:]}", body_style))
            else:
                story.append(Paragraph(clean_s, body_style))

        doc.build(story)
        return buffer.getvalue()
    except Exception as e:
        print(f"[Export Engine] PDF generation error: {e}")
        return b"%PDF-1.4\n%EOF"


def generate_xlsx_export(
    title: str,
    content: str,
    meta: Optional[dict] = None,
) -> bytes:
    """Generate Excel .xlsx workbook from tabular JSON content or markdown tables."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Analysis Data"

    try:
        data = json.loads(content)
        if isinstance(data, dict) and "columns" in data and "rows" in data:
            columns = data["columns"]
            rows = data["rows"]
            ws.append(columns)
            for r in rows:
                ws.append(r)
        else:
            ws.append(["Title", title])
            ws.append(["Content", content])
    except Exception:
        ws.append(["Title", title])
        ws.append(["Content", content])

    out_stream = io.BytesIO()
    wb.save(out_stream)
    return out_stream.getvalue()
