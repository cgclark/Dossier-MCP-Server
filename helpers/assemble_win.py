#!/usr/bin/env python3
"""assemble_win.py — Windows port of helpers/assemble (Swift/PDFKit).

    assemble_win.py <spec.json> <out.pdf>

spec.json: {"title":"...","exhibits":[{"ex":"A","date":"..","desc":"..",
            "source":"C:\\...\\abs.pdf","pages":"all"|"1"|"1-3","sha":"..."}]}

Builds a schedule cover page + each exhibit's original PDF pages, full fidelity
(pulled straight from source, not the OCR'd copy) — chain of custody preserved.

Deliberate improvement over the macOS binary: the cover schedule paginates onto
additional cover pages instead of silently dropping rows that don't fit.
"""
import io, json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = letter  # 612 x 792 pt, matches the Mac binary's US-Letter cover


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def build_cover_pages(title, exhibits):
    """Yields one or more single-page PDF byte blobs for the schedule cover."""
    rows_per_page_start_y = PAGE_H - 130
    row_height = 18
    bottom_margin = 54

    i = 0
    first_page = True
    while i < len(exhibits) or first_page:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        if first_page:
            c.setFont("Helvetica-Bold", 18)
            c.drawString(54, PAGE_H - 70, title)
            c.setFont("Helvetica", 13)
            c.drawString(54, PAGE_H - 96, "Exhibit Schedule")
            first_page = False
        y = rows_per_page_start_y
        while i < len(exhibits) and y >= bottom_margin:
            e = exhibits[i]
            row = f"{e.get('ex', '')}.  {e.get('date') or ''}   {(e.get('desc') or '')[:60]}"
            c.setFont("Helvetica", 10)
            c.drawString(54, y, row)
            sha = e.get("sha")
            if sha:
                c.setFont("Helvetica", 8)
                c.drawString(360, y, f"SHA-256 {sha[:12]}\u2026")
            y -= row_height
            i += 1
        c.showPage()
        c.save()
        yield buf.getvalue()
        if i >= len(exhibits):
            break


def page_range(spec, count):
    if not spec or spec == "all":
        return list(range(count))
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        lo, hi = int(lo), int(hi)
        return list(range(lo - 1, min(hi, count)))
    return [int(spec) - 1]


def main():
    if len(sys.argv) != 3:
        die("usage: assemble_win.py <spec.json> <out.pdf>")
    spec_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:
        die("bad spec.json")

    writer = PdfWriter()
    idx = 0
    for cover_bytes in build_cover_pages(spec.get("title", ""), spec.get("exhibits", [])):
        for page in PdfReader(io.BytesIO(cover_bytes)).pages:
            writer.add_page(page)
            idx += 1

    for e in spec.get("exhibits", []):
        src_path = e.get("source", "")
        try:
            reader = PdfReader(src_path)
        except Exception:
            print(f"  ! skip {e.get('ex')}: cannot open {src_path}", file=sys.stderr)
            continue
        for p in page_range(e.get("pages"), len(reader.pages)):
            if 0 <= p < len(reader.pages):
                writer.add_page(reader.pages[p])
                idx += 1

    try:
        with open(out_path, "wb") as f:
            writer.write(f)
    except Exception:
        die("write failed")

    print(f"assembled {idx} pages \u2192 {out_path}")


if __name__ == "__main__":
    main()
