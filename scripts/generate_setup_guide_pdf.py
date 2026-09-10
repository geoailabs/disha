#!/usr/bin/env python3
"""
Generate DISHA First-Time User & Developer Setup Guide (PDF).
Design aesthetic: Minimalist Monochrome (High contrast black-and-white, print-friendly,
crisp typography, structured tables, boxed alerts, high-resolution annotated screenshots,
and running headers/footers with page numbers).
"""

import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    PageBreak,
    Image,
)
from reportlab.pdfgen import canvas

# Dimensions for Letter (8.5 x 11 inches)
PAGE_WIDTH, PAGE_HEIGHT = letter
MARGIN = 46  # ~0.64 in
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * MARGIN)  # 520 pt


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to compute total page count and draw running headers and footers.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_decorations(self, page_count):
        self.saveState()

        # Running Header (pages > 1)
        if self._pageNumber > 1:
            self.setFont("Helvetica-Bold", 7.5)
            self.setFillColor(colors.HexColor("#222222"))
            self.drawString(MARGIN, PAGE_HEIGHT - 32, "DISHA")
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#555555"))
            self.drawString(MARGIN + 32, PAGE_HEIGHT - 32, "|   First-Time User & Developer Setup Guide")

            # Document subtitle on right
            self.drawRightString(
                PAGE_WIDTH - MARGIN,
                PAGE_HEIGHT - 32,
                "GeoAI Labs · Desktop Spatial IDE"
            )

            # Thin header rule
            self.setStrokeColor(colors.HexColor("#222222"))
            self.setLineWidth(0.75)
            self.line(MARGIN, PAGE_HEIGHT - 36, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 36)

        # Running Footer (all pages)
        self.setStrokeColor(colors.HexColor("#444444"))
        self.setLineWidth(0.5)
        self.line(MARGIN, 38, PAGE_WIDTH - MARGIN, 38)

        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#444444"))
        self.drawString(
            MARGIN,
            26,
            "DISHA Setup Manual  ·  https://github.com/geoailabs/disha"
        )
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(PAGE_WIDTH - MARGIN, 26, page_str)

        self.restoreState()


def build_setup_guide_pdf(output_path: str):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=46,
        bottomMargin=46,
    )

    styles = getSampleStyleSheet()

    # Custom Minimalist Monochrome Typography Styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.black,
        spaceAfter=4,
    )

    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#333333"),
        spaceAfter=8,
    )

    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#444444"),
    )

    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.black,
        spaceBefore=8,
        spaceAfter=2,
        keepWithNext=True,
    )

    h2_style = ParagraphStyle(
        "Heading2_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#111111"),
        spaceBefore=6,
        spaceAfter=2,
        keepWithNext=True,
    )

    h3_style = ParagraphStyle(
        "Heading3_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#222222"),
        spaceBefore=4,
        spaceAfter=1.5,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        "Body_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#111111"),
        spaceAfter=4,
    )

    code_style = ParagraphStyle(
        "Code_Custom",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.black,
    )

    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white,
    )

    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#111111"),
    )

    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=table_cell_style,
        fontName="Helvetica-Bold",
    )

    table_cell_code = ParagraphStyle(
        "TableCellCode",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=7,
        leading=8.5,
        textColor=colors.black,
    )

    callout_title_style = ParagraphStyle(
        "CalloutTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.black,
        spaceAfter=2,
    )

    callout_body_style = ParagraphStyle(
        "CalloutBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#222222"),
    )

    fig_caption_style = ParagraphStyle(
        "FigureCaption",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#222222"),
        alignment=0,
    )

    def section_header(num_str: str, text: str):
        return [
            Paragraph(f"{num_str}. {text.upper()}", h1_style),
            HRFlowable(
                width="100%",
                thickness=1.2,
                color=colors.black,
                spaceBefore=1,
                spaceAfter=4,
            ),
        ]

    def sub_header(text: str):
        return Paragraph(text, h2_style)

    def minor_header(text: str):
        return Paragraph(text, h3_style)

    def callout_box(badge: str, title: str, text: str, code: str = None):
        flowables = [
            Paragraph(f"<b>[{badge.upper()}]</b> {title}", callout_title_style),
            Spacer(1, 1.5),
            Paragraph(text, callout_body_style),
        ]
        if code:
            flowables.extend([
                Spacer(1, 2.5),
                Paragraph(f"<code>{code}</code>", code_style)
            ])

        t = Table([[flowables]], colWidths=[PRINTABLE_WIDTH])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f6f6")),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#333333")),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    def code_box(code_lines: list[str]):
        content = "<br/>".join(
            line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(" ", "&nbsp;")
            for line in code_lines
        )
        p = Paragraph(content, code_style)
        t = Table([[p]], colWidths=[PRINTABLE_WIDTH])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfbfb")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        return t

    def figure_box(image_rel_path: str, fig_num: int, title: str, desc: str, width: float = 440, height: float = 247.5):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        img_path = os.path.join(base_dir, image_rel_path)
        if not os.path.exists(img_path):
            raise FileNotFoundError(f"Screenshot not found: {img_path}")

        img = Image(img_path, width=width, height=height)
        caption_text = f"<b>Figure {fig_num}: {title}.</b> {desc}"
        caption_p = Paragraph(caption_text, fig_caption_style)

        inner_table = Table([[img], [caption_p]], colWidths=[width])
        inner_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (0, 0), 0.75, colors.HexColor("#333333")),
            ("TOPPADDING", (0, 0), (-1, 0), 0),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
            ("LEFTPADDING", (0, 0), (-1, 0), 0),
            ("RIGHTPADDING", (0, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 1), (0, 1), 3),
            ("BOTTOMPADDING", (0, 1), (0, 1), 1),
            ("LEFTPADDING", (0, 1), (0, 1), 1),
            ("RIGHTPADDING", (0, 1), (0, 1), 1),
        ]))

        outer_table = Table([[inner_table]], colWidths=[PRINTABLE_WIDTH])
        outer_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        return outer_table

    story = []

    # ─────────────────────────────────────────────────────────────────────────────
    # PAGE 1: TITLE, ARCHITECTURE PRIMER & SYSTEM REQUIREMENTS
    # ─────────────────────────────────────────────────────────────────────────────
    header_content = [
        [
            Paragraph("DISHA", ParagraphStyle("TitleMain", parent=title_style, fontSize=24, leading=26)),
            Paragraph(
                "DOCUMENT CLASSIFICATION: TECHNICAL &amp; USER GUIDE<br/>"
                "RELEASE: VERSION 1.0 · MARCH 2026<br/>"
                "REPOSITORY: github.com/geoailabs/disha",
                ParagraphStyle("HeaderMetaRight", parent=meta_style, alignment=2)
            )
        ]
    ]
    t_head = Table(header_content, colWidths=[PRINTABLE_WIDTH * 0.42, PRINTABLE_WIDTH * 0.58])
    t_head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(t_head)
    story.append(Spacer(1, 3))
    story.append(Paragraph("First-Time User &amp; Developer Setup Guide", ParagraphStyle("SubMain", parent=subtitle_style, fontName="Helvetica-Bold", fontSize=11.5, leading=14.5, textColor=colors.black)))
    story.append(Paragraph(
        "A step-by-step technical manual covering desktop installation, developer source setup, "
        "system diagnostics, API credential configuration, workspace management, and your first end-to-end geospatial workflow.",
        ParagraphStyle("SubText", parent=body_style, textColor=colors.HexColor("#333333"))
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.black, spaceBefore=3, spaceAfter=5))

    story.extend(section_header("1", "Architecture Primer & System Overview"))
    story.append(Paragraph(
        "<b>Disha</b> is a geospatial-first, AI-native desktop Integrated Development Environment (IDE) engineered "
        "specifically for urban, regional, and environmental planners. It bridges computational GIS, agentic AI reasoning, "
        "and cartographic production into a unified desktop application.",
        body_style
    ))
    story.append(Paragraph(
        "The software is structured as a two-tier architecture running entirely on your local machine:",
        body_style
    ))

    arch_table_data = [
        [
            Paragraph("Subsystem", table_header_style),
            Paragraph("Technology Stack", table_header_style),
            Paragraph("Port / Protocol", table_header_style),
            Paragraph("Primary Responsibilities", table_header_style),
        ],
        [
            Paragraph("Desktop Frontend", table_cell_bold),
            Paragraph("Electron, React, Vite, MapLibre GL JS, Turf.js", table_cell_style),
            Paragraph("Chromium Renderer (IPC)", table_cell_style),
            Paragraph("Interactive WebGL map canvas, vector rendering, layer styling, attribute editing, streaming AI chat.", table_cell_style),
        ],
        [
            Paragraph("Analytical Backend", table_cell_bold),
            Paragraph("Python 3.11+, FastAPI, Uvicorn, DuckDB, GeoPandas", table_cell_style),
            Paragraph("localhost:8765<br/>HTTP &amp; WebSocket", table_cell_code),
            Paragraph("7+1 Planning Domain Hubs, geodesic geometry math, OSM/DataMeet extraction, polygon registry, DuckDB spatial ingestion.", table_cell_style),
        ],
    ]
    t_arch = Table(arch_table_data, colWidths=[80, 125, 95, 220])
    t_arch.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_arch)
    story.append(Spacer(1, 3))

    story.append(Paragraph(
        "<b>The 7+1 Domain Hub Engine:</b> Analytical requests in Disha do not route through generic language prompts. "
        "Instead, the Python backend deploys 8 specialized domain modules: (1) <b>SpatialHub</b> (geodesic buffering, overlays, "
        "polygon registry), (2) <b>MobilityHub</b> (road routing, GTFS transit, OD flows), (3) <b>EnvironmentHub</b> (Earth Engine LULC, "
        "weather, air quality), (4) <b>PlanningHub</b> (zoning compliance, master plan vision analysis), (5) <b>DemographicsHub</b> (WorldPop, "
        "cohort projections), (6) <b>PlacesHub</b> (Google Places, 3D buildings), (7) <b>ScenariosHub</b> (MCDA scoring), and "
        "(+1) <b>UtilityHub</b> (geocoding, live web research, artifact persistence).",
        body_style
    ))
    story.append(Spacer(1, 2))

    story.extend(section_header("2", "System Requirements & Prerequisites"))
    req_data = [
        [
            Paragraph("Component", table_header_style),
            Paragraph("Minimum Requirement", table_header_style),
            Paragraph("Recommended Configuration", table_header_style),
            Paragraph("Notes / Considerations", table_header_style),
        ],
        [
            Paragraph("Operating System", table_cell_bold),
            Paragraph("macOS 12+, Windows 10 (64-bit), Ubuntu 22.04+ / Debian", table_cell_style),
            Paragraph("macOS 14+ (Sonoma/Sequoia) or Windows 11 (64-bit)", table_cell_style),
            Paragraph("Native Apple Silicon (arm64) and Intel (x64) binaries available.", table_cell_style),
        ],
        [
            Paragraph("Memory (RAM)", table_cell_bold),
            Paragraph("8 GB RAM", table_cell_style),
            Paragraph("16 GB or 32 GB RAM", table_cell_style),
            Paragraph("Large GeoJSON layers and DuckDB spatial queries benefit from &gt;8 GB.", table_cell_style),
        ],
        [
            Paragraph("Storage Space", table_cell_bold),
            Paragraph("2 GB free disk space", table_cell_style),
            Paragraph("5 GB+ free SSD space", table_cell_style),
            Paragraph("Accommodates cached basemap tiles, spatial layers, and artifacts.", table_cell_style),
        ],
        [
            Paragraph("Developer Tools<br/><i>(Source Build Only)</i>", table_cell_bold),
            Paragraph("Node.js &gt;= 18.x, pnpm &gt;= 8.x<br/>Python &gt;= 3.11", table_cell_code),
            Paragraph("Node.js 20+ LTS, pnpm 9+<br/>Python 3.12, Homebrew (macOS)", table_cell_code),
            Paragraph("Not required if installing pre-built .dmg, .exe installer, or .zip package.", table_cell_style),
        ],
        [
            Paragraph("PDF Rendering Lib<br/><i>(Optional)</i>", table_cell_bold),
            Paragraph("Pango C-library (libpango)", table_cell_style),
            Paragraph("Installed via system package manager (brew / apt)", table_cell_style),
            Paragraph("Required for WeasyPrint deep research PDF report exports.", table_cell_style),
        ],
    ]
    t_req = Table(req_data, colWidths=[80, 130, 130, 180])
    t_req.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_req)

    # ─────────────────────────────────────────────────────────────────────────────
    # PAGE 2: INSTALLATION PATHWAY A (PRE-BUILT DESKTOP APPLICATION)
    # ─────────────────────────────────────────────────────────────────────────────
    story.append(PageBreak())

    story.extend(section_header("3", "Installation Pathway A: Pre-Built Desktop App"))
    story.append(Paragraph(
        "For urban planners, municipal analysts, and GIS specialists who want to use Disha directly without configuring "
        "a coding environment, follow the platform-specific instructions below:",
        body_style
    ))

    # macOS
    story.append(sub_header("A. macOS Installation (DMG / ZIP)"))
    story.append(Paragraph(
        "1. Download the latest release asset: <code>Disha-x.x.x-arm64.dmg</code> (Apple Silicon M1/M2/M3/M4) or <code>Disha-x.x.x.dmg</code> (Intel).<br/>"
        "2. Double-click the <code>.dmg</code> file to open the installer window.<br/>"
        "3. Drag the <b>Disha</b> application icon into the <b>/Applications</b> directory.<br/>"
        "4. Double-click <b>Disha</b> in Applications to launch the IDE.",
        body_style
    ))
    story.append(callout_box(
        "SECURITY NOTICE",
        "macOS Gatekeeper Warning ('Unidentified Developer')",
        "Because community builds may not be notarized with an Apple Developer certificate, macOS may present: "
        "<i>'Disha cannot be opened because it is from an unidentified developer'</i>.<br/>"
        "<b>To bypass:</b> Right-click (or Control-click) <code>Disha.app</code> in Finder, select <b>Open</b>, and click <b>Open</b> in the pop-up prompt. "
        "Alternatively, navigate to <b>System Settings -&gt; Privacy &amp; Security</b>, scroll down to 'Security', and click <b>Open Anyway</b>."
    ))
    story.append(Spacer(1, 4))

    # Windows
    story.append(sub_header("B. Windows Installation (Installer / Portable ZIP)"))
    story.append(Paragraph(
        "1. Download <code>Disha-Setup-x.x.x.exe</code> (Standard Windows Installer) or <code>Disha-x.x.x-win.zip</code> (Portable Archive).<br/>"
        "2. If using the <code>.exe</code> installer, execute the setup wizard and follow the on-screen prompts.",
        body_style
    ))
    story.append(callout_box(
        "CRITICAL WARNING",
        "Mandatory Extraction for Windows ZIP Archives (Rule 1)",
        "If you downloaded the <b>.zip</b> archive, <b>DO NOT</b> double-click <code>Disha.exe</code> directly inside Windows Explorer's compressed folder preview!<br/>"
        "Windows runs files in a temporary sandboxed directory (<code>%TEMP%</code>), isolating the Electron app from the frozen Python backend binary. "
        "This prevents the backend from spawning and causes a perpetual 'Connecting to backend...' failure.<br/>"
        "<b>Required Action:</b> Right-click the <code>.zip</code> file -&gt; select <b>'Extract All...'</b> -&gt; choose a permanent folder "
        "(e.g., <code>C:\\Program Files\\Disha</code> or <code>C:\\Users\\&lt;User&gt;\\AppData\\Local\\Disha</code>) -&gt; launch <code>Disha.exe</code> from the extracted folder.",
    ))
    story.append(Spacer(1, 3))
    story.append(callout_box(
        "WINDOWS DEFENDER",
        "SmartScreen Alert ('Windows protected your PC')",
        "Windows SmartScreen may display: <i>'Windows protected your PC -- Microsoft Defender SmartScreen prevented an unrecognized app from starting'</i>.<br/>"
        "<b>To bypass:</b> Click the underlined <b>'More info'</b> link, then click the <b>'Run anyway'</b> button."
    ))
    story.append(Spacer(1, 4))

    # Linux
    story.append(sub_header("C. Linux Installation (AppImage / DEB)"))
    story.append(Paragraph(
        "1. <b>AppImage:</b> Download <code>Disha-x.x.x.AppImage</code>, grant execution rights, and run:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;<code>chmod +x Disha-x.x.x.AppImage &amp;&amp; ./Disha-x.x.x.AppImage</code><br/>"
        "2. <b>Debian/Ubuntu:</b> Download <code>disha_x.x.x_amd64.deb</code> and install via: <code>sudo dpkg -i disha_x.x.x_amd64.deb</code>.",
        body_style
    ))
    story.append(Spacer(1, 3))
    story.append(callout_box(
        "VERIFICATION CHECKLIST",
        "Confirming Desktop Installation Success",
        "After launching Disha, verify two indicators in the application window:<br/>"
        "1. The <b>interactive MapLibre canvas</b> renders in the center with the default Street basemap.<br/>"
        "2. The <b>connection indicator dot</b> in the top right of the Chat Panel turns <b>solid green</b> (confirming the embedded Python backend on port 8765 is active and healthy)."
    ))

    # ─────────────────────────────────────────────────────────────────────────────
    # PAGE 3: INSTALLATION PATHWAY B (DEVELOPER & SOURCE SETUP)
    # ─────────────────────────────────────────────────────────────────────────────
    story.append(PageBreak())

    story.extend(section_header("4", "Installation Pathway B: Developer & Source Setup"))
    story.append(Paragraph(
        "For developers extending the 7+1 Domain Hubs, writing new map actions, or contributing to the codebase, "
        "set up the full development environment with hot-reloading for both the Electron frontend and FastAPI backend:",
        body_style
    ))

    story.append(minor_header("Step 1: Clone Repository & Install Node Dependencies"))
    story.append(code_box([
        "# Clone the repository from GitHub",
        "git clone https://github.com/geoailabs/disha.git",
        "cd disha",
        "",
        "# Install workspace packages and Electron tooling via pnpm",
        "pnpm install",
    ]))
    story.append(Spacer(1, 3))

    story.append(minor_header("Step 2: Create Python Virtual Environment & Install GIS Dependencies"))
    story.append(code_box([
        "# Navigate to backend package",
        "cd packages/backend",
        "",
        "# Create an isolated Python 3.11+ virtual environment named .buildenv",
        "python3 -m venv .buildenv",
        "",
        "# Activate virtual environment",
        "source .buildenv/bin/activate        # On Windows: .buildenv\\Scripts\\activate",
        "",
        "# Upgrade pip and install all spatial, GIS, and domain dependencies",
        "pip install --upgrade pip",
        "pip install -r requirements.txt",
        "",
        "# Return to repository root",
        "cd ../..",
    ]))
    story.append(Spacer(1, 3))

    story.append(minor_header("Step 3: (Optional) Install System Pango Library for PDF Reports"))
    story.append(Paragraph(
        "Disha utilizes WeasyPrint for rendering multi-search cited deep research reports to PDF. This requires the Pango C-library:",
        body_style
    ))
    story.append(code_box([
        "# macOS (via Homebrew)",
        "brew install pango",
        "",
        "# Ubuntu / Debian Linux",
        "sudo apt update && sudo apt install -y libpango1.0-dev libharfbuzz-dev",
    ]))
    story.append(Spacer(1, 3))

    story.append(minor_header("Step 4: Launch the Development Environment"))
    story.append(Paragraph(
        "You can launch both the Python backend (uvicorn on port 8765) and Electron frontend (electron-vite) together, or run them in separate terminals:",
        body_style
    ))
    story.append(code_box([
        "# Option 1: Unified launch (recommended for quick startup)",
        "pnpm dev",
        "",
        "# Option 2: Split terminals (recommended for debugging backend tool logs)",
        "# Terminal 1 -- Python FastAPI backend (uvicorn with hot reload on port 8765)",
        "cd packages/backend && source .buildenv/bin/activate && python -m uvicorn main:app --reload --port 8765",
        "",
        "# Terminal 2 -- Electron React desktop frontend (electron-vite with HMR)",
        "pnpm --filter @disha/desktop dev",
    ]))
    story.append(Spacer(1, 3))

    story.append(minor_header("Step 5: Run Automated Tests & Verifications"))
    story.append(code_box([
        "# Run full Python unit test suite across all 7+1 domain hubs",
        "cd packages/backend && .buildenv/bin/pytest tests/",
        "",
        "# Run frontend typecheck and production bundler build",
        "pnpm --filter @disha/desktop exec tsc --noEmit",
        "pnpm --filter @disha/desktop build",
    ]))

    # ─────────────────────────────────────────────────────────────────────────────
    # PAGE 4: FIRST LAUNCH & SYSTEM DIAGNOSTICS (FIGURE 1)
    # ─────────────────────────────────────────────────────────────────────────────
    story.append(PageBreak())

    story.extend(section_header("5", "First Launch & System Diagnostics"))
    story.append(Paragraph(
        "When Disha launches for the first time, it automatically performs an automated background diagnostic health check. "
        "This self-testing dashboard verifies reachability to public geospatial endpoints, validates installed Python spatial "
        "dependencies, and inspects active API credentials before you begin your planning analysis.",
        body_style
    ))

    # Figure 1: System Diagnostics Dashboard
    story.append(figure_box(
        image_rel_path="assets/screenshots/optimized/01_system_diagnostics.jpg",
        fig_num=1,
        title="Automated System Diagnostics & Health Check Dashboard",
        desc="Disha tests reachability for OpenStreetMap Overpass, Nominatim geocoding, OSRM routing, Open-Meteo weather APIs, and Python GIS libraries (GeoPandas, Shapely, PyProj). Amber indicators highlight actions required for OpenAI credentials and workspace selection.",
        width=440,
        height=247.5,
    ))
    story.append(Spacer(1, 3))

    story.append(sub_header("Diagnostic Health Check Breakdown"))
    story.append(Paragraph(
        "The diagnostic checks evaluate the complete computational and network stack of your local machine:",
        body_style
    ))

    diag_table_data = [
        [
            Paragraph("Diagnostic Check", table_header_style),
            Paragraph("Service / Component Tested", table_header_style),
            Paragraph("Status Indicator", table_header_style),
            Paragraph("Operational Significance", table_header_style),
        ],
        [
            Paragraph("OSM Overpass API", table_cell_bold),
            Paragraph("OpenStreetMap vector extraction", table_cell_style),
            Paragraph("[PASS] Green", table_cell_bold),
            Paragraph("Required for fetching road networks, building footprints, amenities, and transit lines.", table_cell_style),
        ],
        [
            Paragraph("Nominatim Geocoder", table_cell_bold),
            Paragraph("OSM forward &amp; reverse geocoding", table_cell_style),
            Paragraph("[PASS] Green", table_cell_bold),
            Paragraph("Powers natural language map queries (e.g., 'Fly to Connaught Place').", table_cell_style),
        ],
        [
            Paragraph("OSRM Routing Server", table_cell_bold),
            Paragraph("Open Source Routing Machine", table_cell_style),
            Paragraph("[PASS] Green", table_cell_bold),
            Paragraph("Computes turn-by-turn driving, cycling, and walking routes between spatial points.", table_cell_style),
        ],
        [
            Paragraph("Open-Meteo Weather", table_cell_bold),
            Paragraph("Atmospheric forecast model", table_cell_style),
            Paragraph("[PASS] Green", table_cell_bold),
            Paragraph("Retrieves real-time temperature, wind speed, precipitation, and air quality metrics.", table_cell_style),
        ],
        [
            Paragraph("Python GIS Libraries", table_cell_bold),
            Paragraph("GeoPandas, Shapely, Fiona, PyProj", table_cell_style),
            Paragraph("[PASS] Green", table_cell_bold),
            Paragraph("Executes true ellipsoidal geodesic area, buffering, overlays, and CRS transformations.", table_cell_style),
        ],
        [
            Paragraph("OpenAI API Connection", table_cell_bold),
            Paragraph("AI Reasoning &amp; Agent Loop", table_cell_style),
            Paragraph("[ACTION REQUIRED] Amber", table_cell_bold),
            Paragraph("Requires your API key (Section 7A) to activate natural language reasoning and tool execution.", table_cell_style),
        ],
        [
            Paragraph("Workspace Write Access", table_cell_bold),
            Paragraph("Local File System Directory", table_cell_style),
            Paragraph("[ACTION REQUIRED] Amber", table_cell_bold),
            Paragraph("Prompts you to select a workspace folder (Section 8) to persist layers and chat sessions.", table_cell_style),
        ],
    ]
    t_diag = Table(diag_table_data, colWidths=[95, 115, 80, 230])
    t_diag.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story.append(t_diag)
    story.append(Spacer(1, 3))

    story.append(callout_box(
        "FIRST-TIME LAUNCH CHECKLIST",
        "Dismissing the Diagnostics Modal",
        "If all network and GIS checks display <b>[PASS] Green</b>, click the <b>'X'</b> close button in the top-right corner of the modal. "
        "You can now proceed to explore the map interface and configure your credentials."
    ))

    # ─────────────────────────────────────────────────────────────────────────────
    # PAGE 5: INTERFACE ANATOMY & OPERATIONAL ZONES (FIGURE 2)
    # ─────────────────────────────────────────────────────────────────────────────
    story.append(PageBreak())

    story.extend(section_header("6", "Interface Anatomy & Operational Zones"))
    story.append(Paragraph(
        "Upon closing the diagnostic modal, you enter the main Disha desktop IDE. The interface is engineered "
        "as a unified command center designed for spatial analysis, layer symbology, and AI-driven planning operations:",
        body_style
    ))

    # Figure 2: Main Workspace Overview
    story.append(figure_box(
        image_rel_path="assets/screenshots/optimized/02_main_workspace_clean.jpg",
        fig_num=2,
        title="Complete Disha Spatial IDE Workspace Layout",
        desc="The desktop IDE layout features the Top Title Bar with workspace controls and basemap switcher (1), interactive MapLibre WebGL canvas (2), collapsible Left Data Panels (3), Urban Planning Assistant (4), and on-canvas Geometry Drawing Controls (5).",
        width=440,
        height=247.5,
    ))
    story.append(Spacer(1, 3))

    anatomy_data = [
        [
            Paragraph("Operational Zone", table_header_style),
            Paragraph("Location", table_header_style),
            Paragraph("Key Controls & Interaction Modes", table_header_style),
        ],
        [
            Paragraph("1. Title Bar & Workspace Controls", table_cell_bold),
            Paragraph("Top Window Bar", table_cell_style),
            Paragraph("<b>Open Workspace:</b> Selects project folder.  <b>Basemap Dropdown:</b> 7 free raster basemaps (OSM, Satellite, Carto Dark/Light, Topo).  <b>Export:</b> Figure rendering &amp; GeoJSON clipping.", table_cell_style),
        ],
        [
            Paragraph("2. Interactive Map Canvas", table_cell_bold),
            Paragraph("Center Viewport", table_cell_style),
            Paragraph("High-performance MapLibre GL WebGL engine.<br/>"
                      "<b>Pan:</b> Left-drag.  <b>Zoom:</b> Scroll wheel / +/- buttons.  <b>Box Zoom:</b> Shift + left-drag.<br/>"
                      "<b>Tilt / Pitch:</b> Right-drag vertically.  <b>Rotate Bearing:</b> Right-drag horizontally.<br/>"
                      "<b>Inspect / Street View:</b> Right-click canvas at any location to drop pin or view panorama.", table_cell_style),
        ],
        [
            Paragraph("3. Left Sidebar Panels", table_cell_bold),
            Paragraph("Left Panel (Collapsible)", table_cell_style),
            Paragraph("<b>Files Tab:</b> Browse workspace files (.geojson, .shp, .gpkg, .kml, .csv).<br/>"
                      "<b>Layers Tab:</b> Toggle visibility, reorder, adjust opacity, launch <b>Symbology Editor</b>, and open <b>Attribute Table</b>.<br/>"
                      "<b>Artifacts Tab:</b> Saved research reports, demographic profiles, and exported figures.<br/>"
                      "<b>Documents Tab:</b> Drop PDF plans or aerial images for AI vision analysis.", table_cell_style),
        ],
        [
            Paragraph("4. AI Planning Assistant", table_cell_bold),
            Paragraph("Right Panel (Collapsible)", table_cell_style),
            Paragraph("Streaming natural-language reasoning interface.<br/>"
                      "<b>Status Dot:</b> Green = backend live on :8765; Red = disconnected.<br/>"
                      "<b>Model Selector:</b> Choose OpenAI models.  <b>Deep Research Toggle:</b> Multi-step web search.<br/>"
                      "<b>API Settings Button ('API' Gear):</b> In-app credentials configuration drawer.", table_cell_style),
        ],
        [
            Paragraph("5. On-Map Drawing Toolbar", table_cell_bold),
            Paragraph("Floating Canvas Controls", table_cell_style),
            Paragraph("<b>Geometry Drawing Tools:</b> Draw Points, Lines, Polygons directly on map.<br/>"
                      "<b>Compass Widget:</b> Click to instantly reset bearing to North and reset pitch to flat.", table_cell_style),
        ],
    ]
    t_anat = Table(anatomy_data, colWidths=[115, 95, 310])
    t_anat.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story.append(t_anat)
    story.append(Spacer(1, 3))

    story.append(callout_box(
        "MAP NAVIGATION TIP",
        "Fluid Spatial Navigation Shortcuts",
        "- <b>Reset Orientation:</b> Click the Compass widget in the top-right of the map to instantly re-orient North.<br/>"
        "- <b>Inspect Coordinates:</b> Right-clicking any spot on the map displays its exact WGS84 latitude and longitude.<br/>"
        "- <b>Expand Canvas:</b> Click the toggle buttons in the top-right header to collapse the sidebars for full-screen cartography."
    ))

    # ─────────────────────────────────────────────────────────────────────────────
    # PAGE 6: CONFIGURATION & WORKSPACE MANAGEMENT (FIGURE 3)
    # ─────────────────────────────────────────────────────────────────────────────
    story.append(PageBreak())

    story.extend(section_header("7", "Initial Configuration & API Credentials"))
    story.append(Paragraph(
        "Disha works immediately for map navigation, manual geometry drawing, vector importing, and attribute inspection. "
        "To activate the AI Planning Assistant, multi-step agent reasoning, and satellite remote sensing, configure your credentials below:",
        body_style
    ))

    # Figure 3: API Settings Drawer
    story.append(figure_box(
        image_rel_path="assets/screenshots/optimized/03_api_settings_drawer.jpg",
        fig_num=3,
        title="In-App API Credentials & Settings Drawer",
        desc="Opened by clicking the gear icon ('API') in the Chat Panel header. Allows immediate entry for your OpenAI API key (required), Google Maps key (optional), and Google Earth Engine Service Account JSON file without modifying system files.",
        width=410,
        height=230.5,
    ))
    story.append(Spacer(1, 2))

    story.append(sub_header("A. Configuring Your OpenAI API Key (Required for AI Chat)"))
    story.append(Paragraph(
        "1. Click the <b>API Settings Button</b> (gear icon labeled <code>API</code>) in the top-right corner of the Chat Panel.<br/>"
        "2. Paste your key (<code>sk-proj-...</code>) into the <b>OPENAI API KEY (REQUIRED)</b> input field.<br/>"
        "3. Click the blue <b>Save</b> button. The button confirms with 'Saved!' and the status changes to <i>'OpenAI API Key active'</i>.<br/>"
        "4. Click the <code>API</code> gear icon again to collapse the drawer.",
        body_style
    ))
    story.append(Paragraph(
        "<i>Developer Alternative:</i> Set the key in your terminal or <code>.env</code> file: <code>export OPENAI_API_KEY=\"sk-proj-...\"</code>.",
        body_style
    ))
    story.append(Spacer(1, 2))

    story.append(sub_header("B. Google Maps & Earth Engine Credentials (Optional)"))
    story.append(Paragraph(
        "- <b>Google Maps API Key:</b> Unlocks Google Places search, POI attribute lookups, elevation profiles, and air quality indices.<br/>"
        "- <b>Google Earth Engine:</b> Unlocks satellite LULC classification and NDVI vegetation indices. Click <b>'Import JSON File'</b> in the "
        "<code>API</code> drawer, select your Google Cloud Service Account JSON key, and click <b>'Save GEE Credentials'</b>.",
        body_style
    ))
    story.append(Spacer(1, 3))

    story.extend(section_header("8", "Creating & Managing Your Workspace"))
    story.append(Paragraph(
        "Disha operates on a <b>folder-as-workspace</b> model. Opening a folder binds the IDE to that local directory, enabling "
        "persistent auto-saving of map layers, symbology styles, and AI conversation history.",
        body_style
    ))
    story.append(Paragraph(
        "<b>How to Open a Workspace:</b> Click <b>'Open Workspace'</b> in the top title bar (or press <code>Cmd+O</code> / <code>Ctrl+O</code>) "
        "and choose a directory (e.g., <code>~/Documents/UrbanPlan2030</code>). Disha organizes your project structure automatically:",
        body_style
    ))
    story.append(code_box([
        "my-urban-workspace/                    <-- Your chosen project root folder",
        "|-- project.json                       <-- Auto-saved state: layers, symbology, viewport, chat history",
        "|-- documents.json                     <-- Metadata for attached planning documents & vision sessions",
        "|-- .disha/                            <-- Hidden metadata directory",
        "|   \\-- layers/                        <-- Materialized GeoJSON layers generated by AI chat tools",
        "|       |-- boundary_delhi.geojson",
        "|       \\-- buffer_metro_lines.geojson",
        "|-- zoning_parcels.shp                 <-- Your raw spatial datasets (Shapefile, GeoPackage, CSV, etc.)",
        "\\-- master_plan_2030.pdf              <-- Planning documents for Vision AI analysis",
    ]))
    story.append(Spacer(1, 2))
    story.append(callout_box(
        "PERSISTENCE GUARDRAIL",
        "Safe Auto-Save & Closing Practices",
        "Disha continuously auto-saves your map viewport, layer symbology, bookmarks, and chat conversations to <code>project.json</code>. "
        "When closing or switching workspaces, Disha ensures all in-flight saves flush to disk before unloading state. "
        "To avoid corruption, always use the window close button or title bar menu rather than terminating the process via task manager."
    ))

    # ─────────────────────────────────────────────────────────────────────────────
    # PAGE 7: HANDS-ON TUTORIAL (FIGURE 4)
    # ─────────────────────────────────────────────────────────────────────────────
    story.append(PageBreak())

    story.extend(section_header("9", "Hands-On Tutorial: Your First 5 Minutes in Disha"))
    story.append(Paragraph(
        "Follow this 6-step golden path tutorial to verify that your map engine, vector ingestion, AI assistant, "
        "and cartographic export tools are operating properly:",
        body_style
    ))

    tut_steps = [
        ("Step 1: Navigate the Map via Natural Language",
         "Type into the Chat Panel: <i>'Fly to Chandigarh, India and zoom into Sector 17'</i>.<br/>"
         "<b>Verification:</b> The MapLibre canvas smoothly animates, transitions camera coordinates, and centers Sector 17."),

        ("Step 2: Retrieve Administrative Boundaries & Calculate Geodesic Area",
         "Type into the Chat Panel: <i>'Fetch the boundary of Central Park, New York and calculate its area in hectares'</i>.<br/>"
         "<b>Verification:</b> The assistant calls <code>osm_boundary</code> via SpatialHub, merges boundary rings, computes true ellipsoidal "
         "geodesic area (~341 ha), materializes a new vector layer on the canvas, and reports the area."),

        ("Step 3: Perform Proximity Analysis & Spatial Buffering",
         "Type into the Chat Panel: <i>'Find all hospitals within a 2 km buffer around the current map center'</i>.<br/>"
         "<b>Verification:</b> The assistant generates a 2,000-meter buffer polygon, executes an Overpass POI query, and drops interactive pins."),

        ("Step 4: Import Local GIS Data (Shapefile / CSV / GeoJSON)",
         "Drag any <code>.geojson</code>, <code>.shp</code>, or <code>.csv</code> into your workspace folder. Click the file in the <b>Files Tab</b>.<br/>"
         "<b>Verification:</b> DuckDB spatial reprojects the coordinates to WGS84, adds it to the <b>Layers Tab</b>, and centers the camera. "
         "Click the table icon on the layer to open the spreadsheet <b>Attribute Table</b>."),

        ("Step 5: Apply Data-Driven Symbology & Automatic Legend",
         "Select a layer and type: <i>'Style this layer categorized by zone_code and display labels'</i>.<br/>"
         "<b>Verification:</b> Features receive distinct colors based on attributes, on-map labels appear, and a floating legend renders."),

        ("Step 6: Export a Publication-Ready Map Figure",
         "Click the <b>Export</b> tab in the left sidebar. Set a figure title and click <b>Download PNG</b> or <b>Download PDF</b>.<br/>"
         "<b>Verification:</b> A high-resolution figure is generated with an integrated cartographic title block, graphic scale bar, north arrow, live legend, and data attribution."),
    ]

    for title, desc in tut_steps[:5]:
        story.append(minor_header(title))
        story.append(Paragraph(desc, body_style))
        story.append(Spacer(1, 1.5))

    story.append(minor_header(tut_steps[5][0]))
    story.append(Paragraph(tut_steps[5][1], body_style))
    story.append(Spacer(1, 2))

    # Figure 4: Publication Figure Export
    story.append(figure_box(
        image_rel_path="assets/screenshots/optimized/05_export_tab.jpg",
        fig_num=4,
        title="Publication Figure & Cartographic Export Panel",
        desc="Accessed from the Export tab in the left sidebar. Bakes dynamic scale bars, north arrows, custom title blocks, and legends directly into publication figures (PNG/JPEG/PDF), or exports layers clipped to the active map extent.",
        width=410,
        height=230.5,
    ))
    story.append(Spacer(1, 2))

    story.append(callout_box(
        "PRO TIP: MULTI-CONVERSATION THREADS",
        "Organizing Analytical Workflows",
        "Use the <b>'+'</b> button in the Chat Panel to maintain separate conversational threads for different planning tasks "
        "(e.g., one thread for environmental baseline assessment, another for zoning compliance, and another for transit routing). "
        "All conversations are persisted independently in your workspace's <code>project.json</code>."
    ))

    # ─────────────────────────────────────────────────────────────────────────────
    # PAGE 8: TROUBLESHOOTING & SHORTCUTS CHEAT SHEET
    # ─────────────────────────────────────────────────────────────────────────────
    story.append(PageBreak())

    story.extend(section_header("10", "Troubleshooting & Frequently Asked Questions"))

    faq_data = [
        [
            Paragraph("Symptom / Error Message", table_header_style),
            Paragraph("Root Cause", table_header_style),
            Paragraph("Diagnostic & Resolution Steps", table_header_style),
        ],
        [
            Paragraph("Status dot is Red:<br/><i>'Connecting to backend...'</i>", table_cell_bold),
            Paragraph("FastAPI backend on port 8765 is not reachable or failed to start.", table_cell_style),
            Paragraph("1. For Pre-built Windows app: verify you extracted the ZIP (Section 3B).<br/>"
                      "2. For Developers: ensure virtualenv is active and run:<br/>"
                      "<code>python -m uvicorn main:app --port 8765</code><br/>"
                      "3. Check port 8765 conflict: <code>lsof -i :8765</code> or <code>netstat -ano | findstr 8765</code>.", table_cell_style),
        ],
        [
            Paragraph("Chat response:<br/><i>'An OpenAI API Key is required...'</i>", table_cell_bold),
            Paragraph("No OpenAI API key has been supplied to the backend.", table_cell_style),
            Paragraph("Click the <b>API Settings Button</b> ('API' Gear) at the top of the Chat Panel, paste your <code>sk-...</code> key, and click <b>Save</b> (Section 7A).", table_cell_style),
        ],
        [
            Paragraph("Deep Research error:<br/><i>'cannot load library libpango-1.0-0'</i>", table_cell_bold),
            Paragraph("WeasyPrint requires system Pango C-libraries for PDF rendering.", table_cell_style),
            Paragraph("Install Pango via your OS package manager:<br/>"
                      "<b>macOS:</b> <code>brew install pango</code><br/>"
                      "<b>Linux:</b> <code>sudo apt install -y libpango1.0-dev</code>", table_cell_style),
        ],
        [
            Paragraph("Imported layer does not appear on the map canvas", table_cell_bold),
            Paragraph("Invalid CRS coordinates or camera not centered on layer.", table_cell_style),
            Paragraph("1. Click the <b>Zoom to Layer</b> (target crosshair) icon next to the layer in the Layers Tab.<br/>"
                      "2. Ensure coordinates are valid WGS84 lat/lng (latitude between -90 and 90, longitude between -180 and 180).", table_cell_style),
        ],
        [
            Paragraph("Windows Defender flags<br/><code>Disha.exe</code> as unrecognized", table_cell_bold),
            Paragraph("Heuristic false-positive common to PyInstaller / Electron binaries.", table_cell_style),
            Paragraph("Click <b>'More info'</b> on the SmartScreen dialog, then click <b>'Run anyway'</b>. Alternatively, add an exclusion in Windows Security for the Disha directory.", table_cell_style),
        ],
    ]
    t_faq = Table(faq_data, colWidths=[120, 110, 290])
    t_faq.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_faq)
    story.append(Spacer(1, 4))

    story.extend(section_header("11", "Quick Reference & Shortcuts Cheat Sheet"))

    shortcuts_data = [
        [
            Paragraph("Action / Workflow", table_header_style),
            Paragraph("macOS Shortcut", table_header_style),
            Paragraph("Windows / Linux Shortcut", table_header_style),
            Paragraph("Mouse / Canvas Gesture", table_header_style),
        ],
        [
            Paragraph("Open Workspace Folder", table_cell_bold),
            Paragraph("Cmd + O", table_cell_code),
            Paragraph("Ctrl + O", table_cell_code),
            Paragraph("Click folder icon in Title Bar", table_cell_style),
        ],
        [
            Paragraph("Box Zoom to Area", table_cell_bold),
            Paragraph("Shift + Drag", table_cell_code),
            Paragraph("Shift + Drag", table_cell_code),
            Paragraph("Draw rectangle with left-click held", table_cell_style),
        ],
        [
            Paragraph("Tilt Pitch &amp; Rotate Bearing", table_cell_bold),
            Paragraph("Right-Click + Drag", table_cell_code),
            Paragraph("Right-Click + Drag", table_cell_code),
            Paragraph("Move mouse vertically/horizontally", table_cell_style),
        ],
        [
            Paragraph("Drop Pin / Street View / Inspect", table_cell_bold),
            Paragraph("Right-Click canvas", table_cell_code),
            Paragraph("Right-Click canvas", table_cell_code),
            Paragraph("Opens context menu at cursor coordinates", table_cell_style),
        ],
        [
            Paragraph("Reset North Bearing", table_cell_bold),
            Paragraph("Click Compass", table_cell_style),
            Paragraph("Click Compass", table_cell_style),
            Paragraph("Resets 3D pitch and rotates north up", table_cell_style),
        ],
        [
            Paragraph("Switch Basemap", table_cell_bold),
            Paragraph("Title Bar Dropdown", table_cell_style),
            Paragraph("Title Bar Dropdown", table_cell_style),
            Paragraph("Cycle through 7 free raster basemaps", table_cell_style),
        ],
        [
            Paragraph("Export Publication Map", table_cell_bold),
            Paragraph("Export Tab", table_cell_style),
            Paragraph("Export Tab", table_cell_style),
            Paragraph("Opens cartographic figure export modal", table_cell_style),
        ],
    ]
    t_short = Table(shortcuts_data, colWidths=[130, 95, 115, 180])
    t_short.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_short)
    story.append(Spacer(1, 4))

    # Concluding note
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#666666"), spaceBefore=2, spaceAfter=2))
    story.append(Paragraph(
        "<b>Need Community Support or Found an Issue?</b> Visit the official Disha GitHub repository at "
        "<code>https://github.com/geoailabs/disha</code> to file issues, review API documentation, or contribute new domain tools.",
        ParagraphStyle("FootNote", parent=body_style, fontSize=7.5, leading=10, textColor=colors.HexColor("#444444"), alignment=1)
    ))

    # Build PDF using NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated PDF: {output_path}")


if __name__ == "__main__":
    out_file = "disha-setup-guide.pdf"
    if len(sys.argv) > 1:
        out_file = sys.argv[1]
    build_setup_guide_pdf(out_file)
