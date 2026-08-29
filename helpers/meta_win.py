#!/usr/bin/env python3
"""meta_win.py — Windows port of helpers/meta (Swift/CGImageSource/PDFKit).

    meta_win.py <file>

Emits the same JSON shape as the macOS `meta` binary: path/sha256/bytes/fs/kind,
plus a `pdf` or `image` block. Never fabricates a timezone — zone_status stays
"unknown" unless an explicit EXIF offset is present (SPEC.md 3.2, rule 2).
"""
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

IMG_EXT = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".heif"}


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def sha256_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iso_z(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fs_block(p):
    st = p.stat()
    # On Windows, st_ctime is creation time (unlike POSIX, where it's inode-change time).
    birth = datetime.fromtimestamp(st.st_ctime, tz=timezone.utc)
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
    return {"birth": iso_z(birth), "mtime": iso_z(mtime)}


def pdf_block(p):
    import pymupdf as fitz
    try:
        doc = fitz.open(p)
    except Exception:
        return None
    meta = doc.metadata or {}

    def pdf_date(s):
        # PDF date strings look like D:20260531120000+00'00 or D:20260531120000Z
        if not s or not s.startswith("D:"):
            return None
        s = s[2:]
        try:
            if len(s) >= 14:
                dt = datetime.strptime(s[:14], "%Y%m%d%H%M%S")
                return iso_z(dt)
        except ValueError:
            return None
        return None

    block = {
        "pages": doc.page_count,
        "created": pdf_date(meta.get("creationDate")),
        "modified": pdf_date(meta.get("modDate")),
        "title": meta.get("title") or None,
        "author": meta.get("author") or None,
        "producer": meta.get("producer") or None,
    }
    doc.close()
    return {k: v for k, v in block.items() if v is not None} or {"pages": doc.page_count}


def _rational_to_deg(gps_ref, gps_coord):
    try:
        deg = float(gps_coord[0]) + float(gps_coord[1]) / 60.0 + float(gps_coord[2]) / 3600.0
    except (TypeError, IndexError, ZeroDivisionError):
        return None
    if gps_ref in ("S", "W"):
        deg = -deg
    return deg


def image_block(p):
    from PIL import Image, ExifTags
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        img = Image.open(p)
    except Exception:
        return None
    w, h = img.size
    block = {"pixelW": w, "pixelH": h}
    exif = {}
    try:
        raw = img.getexif()
        for tag_id, val in raw.items():
            tag = ExifTags.TAGS.get(tag_id, tag_id)
            exif[tag] = val
        # EXIF IFD (where DateTimeOriginal/OffsetTimeOriginal live) is a sub-block on Pillow.
        exif_ifd = raw.get_ifd(0x8769) if hasattr(raw, "get_ifd") else {}
        for tag_id, val in exif_ifd.items():
            tag = ExifTags.TAGS.get(tag_id, tag_id)
            exif[tag] = val
    except Exception:
        pass

    dto = exif.get("DateTimeOriginal")
    offset = exif.get("OffsetTimeOriginal")
    if dto:
        block["DateTimeOriginal"] = str(dto)
        block["zone_status"] = "unknown"
        if offset:
            block["OffsetTimeOriginal"] = str(offset)
            block["zone_status"] = "explicit"
    if exif.get("Make"):
        block["make"] = str(exif["Make"]).strip("\x00").strip()
    if exif.get("Model"):
        block["model"] = str(exif["Model"]).strip("\x00").strip()
    if exif.get("Orientation") is not None:
        block["orientation"] = int(exif["Orientation"])
    if exif.get("DateTime"):
        block["DateTime"] = str(exif["DateTime"])

    try:
        gps = raw.get_ifd(0x8825) if hasattr(raw, "get_ifd") else {}
        if gps:
            lat = _rational_to_deg(gps.get(1), gps.get(2))
            lon = _rational_to_deg(gps.get(3), gps.get(4))
            if lat is not None and lon is not None:
                block["gps"] = {"lat": lat, "lon": lon}
    except Exception:
        pass
    return block


def main():
    if len(sys.argv) < 2:
        die("usage: meta_win.py <file>")
    p = Path(sys.argv[1])
    if not p.exists():
        die(f"no such file: {p}")

    out = {
        "path": str(p),
        "sha256": sha256_of(p),
        "bytes": p.stat().st_size,
        "fs": fs_block(p),
    }
    ext = p.suffix.lower()
    kind = None
    if ext == ".pdf":
        pdf = pdf_block(p)
        if pdf:
            out["pdf"] = pdf
            kind = "pdf"
    elif ext in IMG_EXT:
        img = image_block(p)
        if img:
            out["image"] = img
            kind = "image"
    if kind is None:
        kind = "email" if ext == ".eml" else "other"
    out["kind"] = kind

    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
