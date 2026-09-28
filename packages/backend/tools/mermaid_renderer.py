"""Small dependency-free Mermaid renderer for report exports.

The desktop app only needs Mermaid diagrams in generated documents. This
renderer intentionally supports the common flowchart/graph and sequence
diagram syntax used by planning reports, and falls back to a readable code
diagram when a less common Mermaid dialect is encountered.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass


@dataclass
class _Node:
    key: str
    label: str


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _strip_direction(source: str) -> tuple[str, str]:
    lines = [line.strip() for line in source.splitlines() if line.strip() and not line.strip().startswith("%%")]
    kind = lines[0].lower() if lines else "flowchart"
    body = "\n".join(lines[1:]) if lines else ""
    direction = "LR" if re.search(r"\b(?:graph|flowchart)\s+LR\b", kind + " " + body, re.I) else "TB"
    if lines and re.match(r"^(?:graph|flowchart)\b", lines[0], re.I):
        parts = lines[0].split()
        direction = parts[1].upper() if len(parts) > 1 and parts[1].upper() in {"TB", "BT", "LR", "RL"} else direction
    return kind, direction


def _flowchart_svg(source: str) -> str:
    _kind, direction = _strip_direction(source)
    body = "\n".join(source.splitlines()[1:])
    nodes: dict[str, _Node] = {}
    edges: list[tuple[str, str, str]] = []

    token = re.compile(r"([A-Za-z0-9_:.\-]+)\s*(?:\[([^\]]+)\]|\(([^)]+)\)|\{([^}]+)\})?")
    edge_re = re.compile(
        r"([A-Za-z0-9_:.\-]+)(?:\s*(?:\[([^\]]+)\]|\(([^)]+)\)|\{([^}]+)\}))?"
        r"\s*[-=.]+(?:>|>[-.]*|\|([^|]+)\|)?\s*"
        r"([A-Za-z0-9_:.\-]+)(?:\s*(?:\[([^\]]+)\]|\(([^)]+)\)|\{([^}]+)\}))?"
    )

    def add_node(key: str, label: str | None) -> None:
        if key not in nodes:
            nodes[key] = _Node(key, (label or key).strip().replace("<br/>", "\n"))

    for raw in body.splitlines():
        line = raw.strip().split("%%", 1)[0].strip()
        if not line or line.startswith("subgraph") or line == "end" or line.startswith("classDef") or line.startswith("class "):
            continue
        for match in edge_re.finditer(line):
            groups = match.groups()
            src, src_a, src_b, src_c, edge_label, dst, dst_a, dst_b, dst_c = groups
            add_node(src, src_a or src_b or src_c)
            add_node(dst, dst_a or dst_b or dst_c)
            edges.append((src, dst, (edge_label or "").strip()))
        if not edges or (edges and edges[-1][0] not in line and edges[-1][1] not in line):
            for match in token.finditer(line):
                key = match.group(1)
                add_node(key, match.group(2) or match.group(3) or match.group(4))

    if not nodes:
        return _fallback_svg(source)

    ordered = list(nodes.values())
    horizontal = direction in {"LR", "RL"}
    cell_w, cell_h = 180, 74
    cols = min(4, len(ordered)) if horizontal else max(1, min(4, int(len(ordered) ** 0.5)))
    rows = (len(ordered) + cols - 1) // cols
    width = max(520, cols * cell_w + 80)
    height = max(180, rows * cell_h + 80)
    positions = {
        node.key: (50 + (i % cols) * cell_w, 30 + (i // cols) * cell_h)
        for i, node in enumerate(ordered)
    }
    if horizontal:
        positions = {node.key: (50 + (i // rows) * cell_w, 30 + (i % rows) * cell_h) for i, node in enumerate(ordered)}
        width, height = max(520, ((len(ordered) + rows - 1) // rows) * cell_w + 80), max(180, rows * cell_h + 80)

    parts = [
        f'<svg class="mermaid-diagram" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Mermaid flowchart">',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#475569"/></marker></defs>',
        '<rect width="100%" height="100%" rx="12" fill="#f8fafc" stroke="#cbd5e1"/>',
    ]
    for src, dst, label in edges:
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        parts.append(f'<line x1="{x1 + 65}" y1="{y1 + 22}" x2="{x2 + 65}" y2="{y2 + 22}" stroke="#64748b" stroke-width="2" marker-end="url(#arrow)"/>')
        if label:
            parts.append(f'<text x="{(x1 + x2) / 2 + 65:.1f}" y="{(y1 + y2) / 2 + 18:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="#475569">{_esc(label)}</text>')
    for node in ordered:
        x, y = positions[node.key]
        lines = node.label.split("\n")[:3]
        parts.append(f'<rect x="{x}" y="{y}" width="130" height="44" rx="8" fill="#ffffff" stroke="#2563eb" stroke-width="2"/>')
        for i, line in enumerate(lines):
            parts.append(f'<text x="{x + 65}" y="{y + 19 + i * 13}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#0f172a">{_esc(line[:30])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _sequence_svg(source: str) -> str:
    lines = [line.strip() for line in source.splitlines()[1:] if line.strip()]
    participants: list[str] = []
    messages: list[tuple[str, str, str]] = []
    for line in lines:
        participant = re.match(r"(?:participant|actor)\s+([^ ]+)", line, re.I)
        if participant:
            participants.append(participant.group(1))
            continue
        match = re.match(r"([^\s:]+)\s*-+>?\s*([^:]+):\s*(.*)", line)
        if match:
            a, b, text = match.groups()
            participants.extend([a.strip(), b.strip()])
            messages.append((a.strip(), b.strip(), text.strip()))
    participants = list(dict.fromkeys(participants)) or ["A", "B"]
    width, height = max(560, len(participants) * 170), max(190, len(messages) * 58 + 100)
    xs = {name: 80 + i * ((width - 160) / max(1, len(participants) - 1)) for i, name in enumerate(participants)}
    parts = [f'<svg class="mermaid-diagram" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Mermaid sequence diagram">', '<defs><marker id="seq-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#475569"/></marker></defs>', '<rect width="100%" height="100%" rx="12" fill="#f8fafc" stroke="#cbd5e1"/>']
    for name, x in xs.items():
        parts.append(f'<rect x="{x - 50}" y="20" width="100" height="30" rx="6" fill="#dbeafe" stroke="#2563eb"/><text x="{x}" y="40" text-anchor="middle" font-family="Arial,sans-serif" font-size="12">{_esc(name)}</text><line x1="{x}" y1="50" x2="{x}" y2="{height - 20}" stroke="#94a3b8" stroke-dasharray="5 5"/>')
    for i, (a, b, text) in enumerate(messages):
        y = 82 + i * 52
        x1, x2 = xs.get(a, 80), xs.get(b, 80)
        parts.append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="#475569" stroke-width="2" marker-end="url(#seq-arrow)"/><text x="{(x1 + x2) / 2}" y="{y - 8}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="#334155">{_esc(text[:48])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _fallback_svg(source: str) -> str:
    lines = [line.strip() for line in source.splitlines() if line.strip()][:18]
    height = max(100, 40 + len(lines) * 20)
    text = "".join(f'<text x="18" y="{28 + i * 20}" font-family="monospace" font-size="12" fill="#334155">{_esc(line[:100])}</text>' for i, line in enumerate(lines))
    return f'<svg class="mermaid-diagram" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 {height}" role="img" aria-label="Mermaid diagram source"><rect width="100%" height="100%" rx="12" fill="#f8fafc" stroke="#cbd5e1"/>{text}</svg>'


def render_mermaid(source: str) -> str:
    first = next((line.strip().lower() for line in source.splitlines() if line.strip()), "")
    if first.startswith("sequencediagram"):
        return _sequence_svg(source)
    if first.startswith(("flowchart", "graph")):
        return _flowchart_svg(source)
    return _fallback_svg(source)


def replace_mermaid_fences(markdown_text: str) -> str:
    pattern = re.compile(r"```mermaid\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
    return pattern.sub(lambda match: f'<div class="mermaid-container">{render_mermaid(match.group(1))}</div>', markdown_text)


def render_mermaid_png(source: str) -> bytes:
    """Render a compact PNG for the ReportLab fallback PDF backend."""
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default()
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    first = lines[0].lower() if lines else ""
    is_sequence = first.startswith("sequencediagram")
    canvas = Image.new("RGB", (900, 420), "#f8fafc")
    draw = ImageDraw.Draw(canvas)

    if is_sequence:
        participants: list[str] = []
        messages: list[tuple[str, str, str]] = []
        for line in lines[1:]:
            p = re.match(r"(?:participant|actor)\s+([^ ]+)", line, re.I)
            m = re.match(r"([^\s:]+)\s*-+>?\s*([^:]+):\s*(.*)", line)
            if p:
                participants.append(p.group(1))
            elif m:
                participants.extend([m.group(1).strip(), m.group(2).strip()])
                messages.append((m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
        participants = list(dict.fromkeys(participants)) or ["A", "B"]
        xs = {name: 90 + i * (720 / max(1, len(participants) - 1)) for i, name in enumerate(participants)}
        for name, x in xs.items():
            draw.rounded_rectangle((x - 55, 20, x + 55, 52), radius=6, fill="#dbeafe", outline="#2563eb", width=2)
            draw.text((x, 36), name[:18], fill="#0f172a", font=font, anchor="mm")
            draw.line((x, 52, x, 390), fill="#94a3b8", width=1)
        for i, (a, b, text) in enumerate(messages[:7]):
            y = 90 + i * 42
            x1, x2 = xs.get(a, 90), xs.get(b, 90)
            draw.line((x1, y, x2, y), fill="#475569", width=2)
            draw.polygon([(x2, y), (x2 - 9 if x2 > x1 else x2 + 9, y - 5), (x2 - 9 if x2 > x1 else x2 + 9, y + 5)], fill="#475569")
            draw.text(((x1 + x2) / 2, y - 12), text[:55], fill="#334155", font=font, anchor="mm")
    else:
        nodes: list[tuple[str, str]] = []
        for line in lines[1:]:
            for key, label in re.findall(r"([A-Za-z0-9_:.\-]+)\s*\[([^\]]+)\]", line):
                if not any(existing == key for existing, _ in nodes):
                    nodes.append((key, label.replace("<br/>", " ")))
        if not nodes:
            nodes = [(str(i + 1), line[:70]) for i, line in enumerate(lines[1:8])]
        positions = {key: (70 + (i % 4) * 210, 42 + (i // 4) * 125) for i, (key, _label) in enumerate(nodes)}
        for line in lines[1:]:
            for src, dst in re.findall(r"([A-Za-z0-9_:.\-]+)\s*[-=.]+>\s*([A-Za-z0-9_:.\-]+)", line):
                if src in positions and dst in positions:
                    x1, y1 = positions[src][0] + 75, positions[src][1] + 24
                    x2, y2 = positions[dst][0] + 75, positions[dst][1] + 24
                    draw.line((x1, y1, x2, y2), fill="#64748b", width=2)
                    draw.polygon([(x2, y2), (x2 - 8, y2 - 5), (x2 - 8, y2 + 5)], fill="#64748b")
        for key, label in nodes:
            x, y = positions[key]
            draw.rounded_rectangle((x, y, x + 150, y + 48), radius=8, fill="#ffffff", outline="#2563eb", width=2)
            draw.text((x + 75, y + 24), label[:28], fill="#0f172a", font=font, anchor="mm")

    output = BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()
