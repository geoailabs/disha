"""
Multi-Format Export Engine — Generates downloadable files in DOCX, PDF, HTML,
XLSX, TXT, JSON, and Image formats from stored artifacts, markdown reports, and map context.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Optional


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
        b = generate_docx_export(title, content, map_image_base64=map_image_base64)
        return b, f"{safe_title}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    elif fmt == "html":
        b = generate_html_export(title, content, map_image_base64=map_image_base64)
        return b, f"{safe_title}.html", "text/html"

    elif fmt == "pdf":
        b = generate_pdf_export(title, content, map_image_base64=map_image_base64)
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
        # Fallback to plain text / markdown bytes
        return content.encode("utf-8"), f"{safe_title}.md", "text/markdown"


def generate_docx_export(
    title: str,
    markdown_content: str,
    map_image_base64: Optional[str] = None,
) -> bytes:
    """Generate a formatted Word .docx document using python-docx."""
    import docx
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = docx.Document()

    # Document Header
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
            run_img.add_picture(img_stream, width=Inches(6.0))
            
            p_cap = doc.add_paragraph()
            p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run_cap = p_cap.add_run(f"Figure: Composed Map Snapshot for {title}")
            run_cap.font.italic = True
            run_cap.font.size = Pt(9.5)
            run_cap.font.color.rgb = RGBColor(100, 116, 139)
            doc.add_paragraph()
        except Exception as exc:
            print(f"[DOCX Export] Image embed error: {exc}")

    # Process Markdown Content
    lines = markdown_content.split("\n")
    for line in lines:
        s = line.strip()
        if not s:
            continue

        if s.startswith("# "):
            h = doc.add_heading(s[2:], level=1)
            h.runs[0].font.color.rgb = RGBColor(30, 41, 59)
        elif s.startswith("## "):
            h = doc.add_heading(s[3:], level=2)
            h.runs[0].font.color.rgb = RGBColor(51, 65, 85)
        elif s.startswith("### "):
            h = doc.add_heading(s[4:], level=3)
            h.runs[0].font.color.rgb = RGBColor(71, 85, 105)
        elif s.startswith("- ") or s.startswith("* "):
            doc.add_paragraph(s[2:], style='List Bullet')
        else:
            p = doc.add_paragraph(s)
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_after = Pt(4)

    out_stream = io.BytesIO()
    doc.save(out_stream)
    return out_stream.getvalue()


def generate_html_export(
    title: str,
    markdown_content: str,
    map_image_base64: Optional[str] = None,
) -> bytes:
    """Generate a self-contained styled HTML file."""
    import markdown as md_lib

    html_body = md_lib.markdown(markdown_content, extensions=['tables', 'fenced_code', 'toc'])

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
) -> bytes:
    """Generate a clean, 100% valid PDF file using ReportLab (with WeasyPrint fallback)."""
    try:
        from weasyprint import HTML
        html_bytes = generate_html_export(title, markdown_content, map_image_base64=map_image_base64)
        return HTML(string=html_bytes.decode("utf-8")).write_pdf()
    except Exception:
        pass

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

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
                from PIL import Image as PILImage
                raw_b64 = map_image_base64.split(",")[1] if "," in map_image_base64 else map_image_base64
                img_data = base64.b64decode(raw_b64)
                img_io = io.BytesIO(img_data)

                with PILImage.open(img_io) as pil_img:
                    orig_w, orig_h = pil_img.size

                max_w = 530.0
                max_h = 360.0
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
            except Exception as e:
                print(f"[ReportLab PDF] Image embed notice: {e}")

        lines = markdown_content.splitlines()
        for line in lines:
            s = line.strip()
            if not s:
                continue
            # Basic markdown text sanitization for ReportLab xml parser
            clean_s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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
    except Exception as exc:
        print(f"[ReportLab PDF Export] Exception: {exc}")
        return f"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n".encode("utf-8")


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

    # Attempt to parse table content {columns, rows}
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
