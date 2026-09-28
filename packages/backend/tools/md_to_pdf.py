#!/usr/bin/env python3
"""
md_to_pdf.py — Markdown → PDF / LaTeX converter with a graceful fallback cascade.

Conversion strategy (tried in order):
  1. pypandoc   — uses a bundled pandoc binary (pip install pypandoc_binary).
                  Produces the highest-fidelity PDF/LaTeX output.
  2. xelatex    — uses our own latex_exporter.py (Markdown→LaTeX) and then
                  compiles with the system xelatex/pdflatex if available.
  3. weasyprint  — (PDF only) pure-Python HTML→PDF via WeasyPrint.
                  No LaTeX or pandoc required.
  4. Error      — raises RuntimeError with friendly install instructions.

CLI usage (backward-compatible):
    python md_to_pdf.py input.md                 # → input.pdf
    python md_to_pdf.py input.md -o output.pdf
    python md_to_pdf.py input.md --tex-only      # only produce .tex
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def _title_from_md(md_path: Path) -> str:
    """Grab the first H1 heading as the document title, or use the filename."""
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    except Exception:
        pass
    return md_path.stem.replace("_", " ").title()


# ── Backend 1: pypandoc ───────────────────────────────────────────────────────

def _try_pypandoc(md_path: Path, out_path: Path, tex_only: bool) -> bool:
    """
    Attempt conversion via pypandoc (which bundles its own pandoc binary).
    Returns True on success, False if pypandoc is not installed.
    Raises on conversion errors so the caller can propagate them.
    """
    try:
        import pypandoc  # type: ignore
    except ImportError:
        return False

    extra_args = [
        "--standalone",
        "--toc",
        "-N",
        "-V", "geometry:margin=1in",
        "-V", "fontsize=11pt",
        "--syntax-highlighting=tango",
        "--resource-path", f".:{md_path.parent}",
    ]
    if not tex_only:
        # Choose the best available PDF engine
        for engine in ("xelatex", "pdflatex", "lualatex"):
            if shutil.which(engine):
                extra_args += ["--pdf-engine", engine]
                break

    to_fmt = "latex" if tex_only else "pdf"
    pypandoc.convert_file(
        str(md_path),
        to_fmt,
        outputfile=str(out_path),
        extra_args=extra_args,
    )
    return True


# ── Backend 2: xelatex / pdflatex ────────────────────────────────────────────

def _find_latex_engine() -> str | None:
    for engine in ("xelatex", "pdflatex", "lualatex"):
        path = shutil.which(engine)
        if path:
            return path
    return None


def _try_latex_engine(md_path: Path, out_path: Path, tex_only: bool) -> bool:
    """
    Use latex_exporter.py to produce a .tex file, then (optionally) compile it.
    Returns True on success, False if no LaTeX engine is available.
    """
    engine = _find_latex_engine()
    if engine is None and not tex_only:
        return False

    from tools.latex_exporter import markdown_to_latex  # type: ignore

    title = _title_from_md(md_path)
    latex_src = markdown_to_latex(md_path.read_text(encoding="utf-8"), title=title)

    if tex_only:
        out_path.write_text(latex_src, encoding="utf-8")
        return True

    # Write .tex to a temp dir and compile
    with tempfile.TemporaryDirectory() as tmp:
        tex_file = Path(tmp) / "document.tex"
        tex_file.write_text(latex_src, encoding="utf-8")

        # Run twice so ToC and cross-references resolve
        for _ in range(2):
            result = subprocess.run(
                [engine, "-interaction=nonstopmode", "-output-directory", tmp, str(tex_file)],
                capture_output=True,
                text=True,
            )

        compiled_pdf = Path(tmp) / "document.pdf"
        if not compiled_pdf.exists():
            stderr = result.stderr or result.stdout or "(no output)"
            raise RuntimeError(f"LaTeX compilation failed:\n{stderr[-2000:]}")

        import shutil as _sh
        _sh.copy2(str(compiled_pdf), str(out_path))

    return True


# ── Backend 3: WeasyPrint (PDF only) ─────────────────────────────────────────

def _try_weasyprint(md_path: Path, out_path: Path) -> bool:
    """
    Convert Markdown → HTML → PDF using WeasyPrint.
    Returns True on success, False if WeasyPrint is not installed.
    """
    try:
        import markdown as md_lib  # type: ignore
        from weasyprint import HTML  # type: ignore
    except ImportError:
        return False

    content = md_path.read_text(encoding="utf-8")
    from tools.mermaid_renderer import replace_mermaid_fences
    html_body = md_lib.markdown(replace_mermaid_fences(content), extensions=["tables", "fenced_code", "toc"])
    title = _title_from_md(md_path)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 800px; margin: 2cm auto; font-size: 12pt; line-height: 1.6; color: #1a1a1a; }}
  h1, h2, h3 {{ color: #1E40AF; border-bottom: 1px solid #CBD5E1; padding-bottom: 4px; }}
  code {{ background: #F1F5F9; padding: 2px 4px; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #F1F5F9; padding: 12px; border-radius: 6px; overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #CBD5E1; padding: 6px 10px; text-align: left; }}
  th {{ background: #EFF6FF; font-weight: bold; color: #1E40AF; }}
  blockquote {{ border-left: 4px solid #1E40AF; margin: 0; padding: 8px 16px; background: #F8FAFC; color: #475569; }}
  .mermaid-container {{ margin: 22px auto; text-align: center; page-break-inside: avoid; }}
  .mermaid-diagram {{ width: 100%; max-width: 760px; height: auto; }}
  @page {{ margin: 2cm; }}
</style>
</head>
<body>
<h1>{title}</h1>
{html_body}
</body>
</html>"""

    HTML(string=full_html, base_url=str(md_path.parent)).write_pdf(str(out_path))
    return True


# ── Public API ────────────────────────────────────────────────────────────────

def convert(
    md_path: str,
    output: str | None = None,
    tex_only: bool = False,
    engine: str = "xelatex",
    bibliography: str | None = None,
    csl: str | None = None,
) -> None:
    """
    Convert a Markdown file to PDF or LaTeX using the best available backend.

    Priority:
      1. pypandoc (bundled pandoc binary — `pip install pypandoc_binary`)
      2. latex_exporter + system xelatex/pdflatex
      3. WeasyPrint HTML→PDF  (PDF only; ignored for tex_only)
      4. RuntimeError with install guidance
    """
    in_path = Path(md_path)
    if not in_path.exists():
        raise FileNotFoundError(f"Input file not found: {md_path}")

    suffix = ".tex" if tex_only else ".pdf"
    out_path = Path(output) if output else in_path.with_suffix(suffix)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []

    # Mermaid is rendered as inline SVG by the HTML/WeasyPrint path. Prefer it
    # whenever the document contains Mermaid so Pandoc/LaTeX cannot reduce the
    # diagram to an unrendered fenced code block.
    has_mermaid = "```mermaid" in in_path.read_text(encoding="utf-8").lower()
    if has_mermaid and not tex_only:
        try:
            if _try_weasyprint(in_path, out_path):
                return
        except Exception as exc:
            errors.append(f"weasyprint (Mermaid): {exc}")
        try:
            from tools.export_engine import generate_pdf_export
            pdf_bytes = generate_pdf_export(
                _title_from_md(in_path),
                in_path.read_text(encoding="utf-8"),
            )
            if pdf_bytes.startswith(b"%PDF") and len(pdf_bytes) > 2000:
                out_path.write_bytes(pdf_bytes)
                return
        except Exception as exc:
            errors.append(f"ReportLab Mermaid fallback: {exc}")

    # ── Backend 1: pypandoc ────────────────────────────────────────────────────
    try:
        if _try_pypandoc(in_path, out_path, tex_only):
            return
    except Exception as exc:
        errors.append(f"pypandoc: {exc}")

    # ── Backend 2: xelatex ────────────────────────────────────────────────────
    try:
        if _try_latex_engine(in_path, out_path, tex_only):
            return
    except Exception as exc:
        errors.append(f"xelatex: {exc}")

    # ── Backend 3: WeasyPrint (PDF only) ──────────────────────────────────────
    if not tex_only:
        try:
            if _try_weasyprint(in_path, out_path):
                return
        except Exception as exc:
            errors.append(f"weasyprint: {exc}")

    # ── All backends failed ────────────────────────────────────────────────────
    detail = "\n".join(f"  • {e}" for e in errors) if errors else "  (no backends available)"
    kind = "LaTeX" if tex_only else "PDF"
    raise RuntimeError(
        f"{kind} export failed — no working backend found.\n"
        f"Attempted backends:\n{detail}\n\n"
        "To fix, install one of:\n"
        "  pip install pypandoc_binary   # (recommended — self-contained)\n"
        "  brew install pandoc           # + TeX Live for PDF\n"
        "  pip install weasyprint markdown  # (PDF only, no LaTeX)\n"
    )


# ── CLI entry point (backward-compatible) ─────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert Markdown to PDF/LaTeX")
    parser.add_argument("input", help="Path to the .md file")
    parser.add_argument("-o", "--output", help="Output file (.pdf or .tex)")
    parser.add_argument("--tex-only", action="store_true", help="Only generate .tex, skip PDF")
    parser.add_argument("--engine", default="xelatex",
                        choices=["xelatex", "pdflatex", "lualatex"],
                        help="LaTeX engine (default: xelatex)")
    parser.add_argument("--bibliography", help="Path to a .bib file")
    parser.add_argument("--csl", help="Path to a .csl citation style file")
    args = parser.parse_args()

    try:
        convert(args.input, args.output, args.tex_only, args.engine,
                args.bibliography, args.csl)
        print(f"Success → {args.output or Path(args.input).with_suffix('.tex' if args.tex_only else '.pdf')}")
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
