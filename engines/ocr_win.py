#!/usr/bin/env python3
"""ocr_win.py — Windows port of engines/ocr (Swift/Vision/PDFKit).

Uses Windows AI OCR (winsdk's projection of Windows.Media.Ocr) — the on-device,
NPU-accelerated peer to Apple Vision on Copilot+ hardware — for recognition, and
PyMuPDF for PDF page rasterization / embedded-text-layer extraction.

    ocr_win.py <input.pdf|input.png/jpg/tiff/heic> [-o out.txt] [--dpi N]
               [--lang a,b] [--fast] [--page-sep] [--force-vision]
               [--pages a-b] [--quiet]

Output is PLAIN TEXT (not JSON), matching the macOS binary exactly. All
progress/log lines go to stderr; stdout stays clean for piping.
"""
import argparse, asyncio, io, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import pymupdf
from PIL import Image
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

from winsdk.windows.globalization import Language
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter

IMG_EXT = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".heif"}
PAGE_SEP = "\f===== PAGE {n} =====\n"


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def log(quiet, msg):
    if not quiet:
        print(msg, file=sys.stderr)


def make_engine(langs):
    """langs: comma-separated BCP-47 tags, or None for the user's profile languages."""
    if langs:
        for tag in langs.split(","):
            tag = tag.strip()
            if not tag:
                continue
            try:
                lang = Language(tag)
                if OcrEngine.is_language_supported(lang):
                    eng = OcrEngine.try_create_from_language(lang)
                    if eng:
                        return eng
            except Exception:
                continue
    eng = OcrEngine.try_create_from_user_profile_languages()
    if eng is None:
        die("no OCR language available on this system (Settings > Time & Language > "
            "Language & region > add a language with the 'Optical character recognition' "
            "component)", 3)
    return eng


async def png_bytes_to_softwarebitmap(png_bytes):
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    return await decoder.get_software_bitmap_async()


def normalize_to_png(pil_img):
    """Mirrors the macOS binary's device-RGB normalization (fixes recognizers
    returning 0 results on unusual color profiles)."""
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()


async def ocr_bitmap(engine, png_bytes):
    bmp = await png_bytes_to_softwarebitmap(png_bytes)
    result = await engine.recognize_async(bmp)
    return result.text or ""


def parse_pages_arg(pages_arg, total):
    if not pages_arg:
        return list(range(1, total + 1))
    if "-" in pages_arg:
        lo, hi = pages_arg.split("-", 1)
        lo, hi = int(lo), int(hi)
    else:
        lo = hi = int(pages_arg)
    return [n for n in range(lo, hi + 1) if 1 <= n <= total]


async def run_pdf(engine, path, args):
    doc = pymupdf.open(path)
    total = doc.page_count
    targets = parse_pages_arg(args.pages, total)
    out_parts = []
    for n in targets:
        page = doc[n - 1]
        text = ""
        if not args.force_vision:
            embedded = (page.get_text() or "").strip()
            if len(embedded) > 20:
                text = embedded
        if not text:
            log(args.quiet, f"OCR: page {n}/{total} @ {args.dpi} DPI")
            pix = page.get_pixmap(dpi=args.dpi)
            png_bytes = normalize_to_png(Image.frombytes(
                "RGB" if pix.n < 4 else "RGBA", (pix.width, pix.height), pix.samples))
            text = await ocr_bitmap(engine, png_bytes)
        out_parts.append((n, text))
    doc.close()
    if args.page_sep:
        return "".join(PAGE_SEP.format(n=n) + t for n, t in out_parts)
    return "\n\n".join(t for _, t in out_parts)


async def run_image(engine, path, args):
    log(args.quiet, f"OCR: {path.name}")
    img = Image.open(path)
    png_bytes = normalize_to_png(img)
    text = await ocr_bitmap(engine, png_bytes)
    if args.page_sep:
        return PAGE_SEP.format(n=1) + text
    return text


async def amain(args, path):
    engine = make_engine(args.lang)
    if path.suffix.lower() == ".pdf":
        return await run_pdf(engine, path, args)
    return await run_image(engine, path, args)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("input", nargs="?")
    ap.add_argument("-o", "--out")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--lang", default="")
    ap.add_argument("--fast", action="store_true",
                     help="accepted for CLI parity; Windows AI OCR has no accuracy/speed "
                          "toggle like Vision's .fast/.accurate, so this is a no-op")
    ap.add_argument("--page-sep", action="store_true")
    ap.add_argument("--force-vision", action="store_true")
    ap.add_argument("--pages")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.input:
        die("no input file. See --help.")
    path = Path(args.input)
    if not path.exists():
        die(f"no such file: {path}")
    if path.suffix.lower() != ".pdf" and path.suffix.lower() not in IMG_EXT:
        die(f"unsupported file type: {path.suffix}")

    text = asyncio.run(amain(args, path))

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
