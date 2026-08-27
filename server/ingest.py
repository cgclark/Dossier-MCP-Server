#!/usr/bin/env python3
"""ingest.py — Dossier Milestone 2 (hardened per run1 §15).

For each file under <matter>/sources/ (zips expanded): hash (dedup), `meta` (band-1),
OWN high-quality OCR (never inherited), `datedetect` (band-2, value_wall kept),
`eml.py` (email), plus extract.py band-1.5 (per-doc locale, form-field dates, DocuSign).
Writes ONLY to --work. Idempotent.

    ingest.py <matter_dir> --work <workdir>
"""
import argparse, json, os, re, sqlite3, subprocess, sys, time, zipfile, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import extract
import summarize as summ   # aliased: ingest.py already defines a summarize() (DB-summary) fn

PAGE_RX = re.compile(r"\f===== PAGE (\d+) =====")
FORM_LABELS = ("beginning date", "ending date", "initial term", "commencement",
               "expiration", "date of lease", "effective date")


def parse_web_dt(s):
    """Web meta dates (article:published_time etc.) are usually zoned ISO8601."""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).isoformat(), "explicit"
    except (ValueError, TypeError):
        pass
    return None, "unknown"


def capture_urls(sources, work):
    """Capture public URLs listed in <sources>/urls.txt to immutable PDF snapshots.
    Returns {snapshot_pdf_path: metadata}. Requires network (opt-in via urls.txt)."""
    web = {}
    urls_file = sources / "urls.txt"
    if not urls_file.exists():
        return web
    webdir = work / "web"; webdir.mkdir(parents=True, exist_ok=True)
    for i, line in enumerate(urls_file.read_text().splitlines()):
        u = line.strip()
        if not u or u.startswith("#"):
            continue
        base = webdir / f"page{i:03d}"
        r = run([str(WEBCAP), u, str(base)])
        pdf = base.with_suffix(".pdf")
        if pdf.exists():
            try:
                web[str(pdf)] = json.loads(r.stdout) if r.stdout.strip() else {"url": u}
            except json.JSONDecodeError:
                web[str(pdf)] = {"url": u}
        else:
            print(f"  ! web capture failed: {u} ({r.stderr.strip()[:80]})", file=sys.stderr)
    return web


def r1_pages(body):
    """Map page-number → text from --page-sep output."""
    parts = PAGE_RX.split(body)
    pm = {}
    for k in range(1, len(parts) - 1, 2):
        try:
            pm[int(parts[k])] = parts[k + 1]
        except (ValueError, IndexError):
            pass
    return pm

# Location-independent: resolve everything relative to the dossier root (server/..).
BASE = Path(__file__).resolve().parent.parent
META = BASE / "helpers/meta"
DATEDETECT = BASE / "helpers/datedetect"
EML = BASE / "parsers/eml.py"
CHAT = BASE / "parsers/chat.py"
OCRBIN = BASE / "engines/ocr"
WEBCAP = BASE / "helpers/webcapture"
SCHEMA = BASE / "schema.sql"
IMG = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".heif"}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def log_metric(db, file, rung, ms, model=None, prompt_tok=None, gen_tok=None):
    """Persist a per-op timing (and optional on-device VLM tokens) to the metric table.
    ts defaults to now in-schema; savings.py reads model/prompt_tok/gen_tok for VLM cost."""
    db.execute("INSERT INTO metric(task,file,rung,model,prompt_tok,gen_tok,ms) "
               "VALUES('ingest',?,?,?,?,?,?)", (file, rung, model, prompt_tok, gen_tok, int(ms)))


def _ms(t0):
    return (time.perf_counter() - t0) * 1000


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def expand_zips(sources, work):
    exp = work / "_expanded"
    for z in sources.rglob("*.zip"):
        dest = exp / z.stem
        if dest.exists():
            continue
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(z) as zf:
                zf.extractall(dest)
        except Exception as e:
            print(f"  ! zip {z.name}: {e}", file=sys.stderr)
    return exp


def _xlsx_text(f):
    """Worksheet text from an .xlsx via stdlib only — robust to the openpyxl autofilter bug
    that blocks some workbooks (e.g. the Clark-Park financial summary). Tab-labelled, tab-joined."""
    import zipfile
    from xml.etree import ElementTree as ET
    M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    try:
        z = zipfile.ZipFile(f)
    except Exception:
        return None
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        try:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
                ss.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")))
        except Exception:
            ss = []
    names = {}
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        for s in wb.iter():
            if s.tag.endswith("}sheet"):
                tgt = rels.get(s.get(RID), "")
                names[tgt.split("/")[-1]] = s.get("name")
    except Exception:
        pass
    out = []
    for sf in sorted(n for n in z.namelist()
                     if n.startswith("xl/worksheets/") and n.endswith(".xml")):
        out.append("===== %s =====" % (names.get(sf.split("/")[-1]) or sf.split("/")[-1]))
        try:
            root = ET.fromstring(z.read(sf))
        except Exception:
            continue
        for row in root.iter(M + "row"):
            cells = []
            for c in row.iter(M + "c"):
                v = c.find(M + "v"); val = v.text if v is not None else None
                if c.get("t") == "s" and val is not None:
                    try: val = ss[int(val)]
                    except Exception: pass
                if val is None:
                    isel = c.find(M + "is")
                    if isel is not None:
                        val = "".join(x.text or "" for x in isel.iter() if x.tag.endswith("}t"))
                cells.append("" if val is None else str(val))
            if any(cells):
                out.append("\t".join(cells))
    return "\n".join(out) if len(out) > len(names) else None


def _pptx_text(f):
    """Slide (and notes) text from a .pptx via stdlib — textutil cannot read pptx."""
    from xml.etree import ElementTree as ET
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
    try:
        z = zipfile.ZipFile(f)
    except Exception:
        return None
    def _texts(name):
        try:
            return [t.text for t in ET.fromstring(z.read(name)).iter(A) if t.text]
        except Exception:
            return []
    slides = sorted((n for n in z.namelist()
                     if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
                    key=lambda n: int(re.sub(r"\D", "", n) or 0))
    out = []
    for i, sf in enumerate(slides, 1):
        runs = _texts(sf)
        note = _texts(sf.replace("slides/slide", "notesSlides/notesSlide"))
        if runs or note:
            out.append("----- slide %d -----" % i)
            if runs: out.append(" ".join(runs))
            if note: out.append("[notes] " + " ".join(note))
    return "\n".join(out) if out else None


def _eml_text(f):
    """Plain-text body (+ key headers) of an .eml so email correspondence is searchable."""
    import email
    from email import policy
    try:
        msg = email.message_from_bytes(f.read_bytes(), policy=policy.default)
    except Exception:
        return None
    hdr = [f"{h}: {msg.get(h)}" for h in ("From", "To", "Cc", "Subject", "Date") if msg.get(h)]
    body = ""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            body = part.get_content()
            if part.get_content_type() == "text/html":
                body = re.sub(r"<[^>]+>", " ", body)
    except Exception:
        pass
    text = ("\n".join(hdr) + "\n\n" + (body or "")).strip()
    return text or None


def own_ocr(f, work):
    """Always OCR with OUR engine (don't trust inherited ocr/). --page-sep for sub-doc awareness."""
    ext = f.suffix.lower()
    outdir = work / "ocr"; outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (f.stem + ".txt")
    if out.exists():
        return out
    if ext == ".pdf" or ext in IMG:
        run([str(OCRBIN), str(f), "-o", str(out), "--page-sep", "--quiet"])
    elif ext in (".docx", ".doc", ".rtf"):
        # textutil (macOS) converts legacy .doc/.rtf and the OOXML word format (NOT pptx/xlsx)
        out.write_text(run(["textutil", "-convert", "txt", "-stdout", str(f)]).stdout)
    elif ext == ".txt":
        # plain text (incl. WhatsApp/iMessage chat exports) — index verbatim
        try: out.write_text(f.read_text(errors="ignore"))
        except Exception: return None
    else:
        txt = {".xlsx": _xlsx_text, ".pptx": _pptx_text, ".eml": _eml_text}.get(ext, lambda _: None)(f)
        if not txt:
            return None
        out.write_text(txt)
    return out if out.exists() else None


def _state_dir(work):
    d = Path(work) / ".ingest"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_progress(work, **fields):
    """Merge fields into <work>/.ingest/progress.json (best-effort, never raises)."""
    st = _state_dir(work)
    p = st / "progress.json"
    cur = {}
    if p.exists():
        try:
            cur = json.loads(p.read_text())
        except Exception:
            cur = {}
    cur.update(fields)
    try:
        p.write_text(json.dumps(cur))
    except Exception:
        pass
    return cur


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def summarize(db):
    """Build the ingest summary FROM THE DB, so it is correct no matter how many
    resumed runs produced the manifest (this-run counters would under-report)."""
    q = lambda s, *a: db.execute(s, a).fetchone()[0]
    ingested = q("SELECT COUNT(*) FROM artifact WHERE duplicate_of IS NULL")
    dupes = q("SELECT COUNT(*) FROM artifact WHERE duplicate_of IS NOT NULL")
    by_kind = dict(db.execute("SELECT kind,COUNT(*) FROM artifact WHERE duplicate_of IS NULL "
                              "GROUP BY kind ORDER BY 2 DESC").fetchall())
    pages = q("SELECT COALESCE(SUM(pages),0) FROM artifact WHERE duplicate_of IS NULL")
    chars = q("SELECT COALESCE(SUM(LENGTH(body)),0) FROM doc_fts")
    events = q("SELECT COUNT(*) FROM event")
    by_prov = dict(db.execute("SELECT provenance,COUNT(*) FROM event GROUP BY provenance").fetchall())
    formfield = q("SELECT COUNT(*) FROM event WHERE source LIKE 'formfield@%'")
    docusign = q("SELECT COUNT(*) FROM artifact WHERE flags LIKE '%docusign_envelopes%'")
    zone_unknown = q("SELECT COUNT(*) FROM event WHERE zone_status='unknown'")
    r1_docs = q("SELECT COUNT(DISTINCT artifact_id) FROM event WHERE source LIKE 'formfield-R1%'")
    r1_recovered = q("SELECT COUNT(*) FROM event WHERE source LIKE 'formfield-R1%'")
    sparse = q("SELECT COUNT(*) FROM gap WHERE gap_type='sparse-ocr'")
    raw_image = pages * 1600
    full_text = chars // 4
    actual = events * 25 + 2000
    L = ["=" * 58, "DOSSIER INGEST (hardened) SUMMARY", "=" * 58,
         f"artifacts        : {ingested} (+{dupes} dupes)  {by_kind}",
         f"pages / ocr chars: {pages} / {chars:,}",
         f"events           : {events}  prov={by_prov}",
         f"  formfield dates: {formfield}   docusign docs: {docusign}",
         f"  R1 force-vision: {r1_docs} docs re-OCR'd, {r1_recovered} typed dates recovered",
         f"  zone-unknown   : {zone_unknown}   sparse-ocr flags: {sparse}",
         f"tokens  raw-image~{raw_image:,}  full-text~{full_text:,}  dossier~{actual:,}"]
    if raw_image:
        L.append(f"saved   vs raw {100*(raw_image-actual)//raw_image}%   "
                 f"vs text {100*(full_text-actual)//max(full_text,1)}%")
    # per-stage timings (present once ingest has metered into `metric`)
    tm = db.execute("SELECT rung,COUNT(*),SUM(ms),MAX(ms) FROM metric WHERE task='ingest' "
                    "AND rung!='file-total' GROUP BY rung ORDER BY 3 DESC").fetchall()
    if tm:
        total = q("SELECT COALESCE(SUM(ms),0) FROM metric WHERE task='ingest' AND rung='file-total'")
        slow = db.execute("SELECT file,rung,ms FROM metric WHERE task='ingest' AND rung!='file-total' "
                          "ORDER BY ms DESC LIMIT 1").fetchone()
        L.append(f"timings          : {total/1000:.1f}s processing  ["
                 + "  ".join(f"{r}={ms/1000:.1f}s" for r, n, ms, mx in tm) + "]")
        if slow:
            L.append(f"  slowest op     : {slow[1]} on {slow[0][:40]} = {slow[2]/1000:.1f}s")
    return "\n".join(L)


def cmd_status(work):
    """Report background-job progress, or the final summary once done."""
    st = _state_dir(work)
    prog = {}
    pf = st / "progress.json"
    if pf.exists():
        try:
            prog = json.loads(pf.read_text())
        except Exception:
            prog = {}
    state, done, total = prog.get("state"), prog.get("done", 0), prog.get("total", 0)
    running = _alive(prog.get("pid"))
    if state == "done":
        sumf = st / "summary.txt"
        body = sumf.read_text() if sumf.exists() else summarize(
            sqlite3.connect(Path(work) / "manifest.db"))
        print(f"status: done  ({total}/{total})\n{body}")
    elif running:
        print(f"status: running  ({done}/{total} files)  pid={prog.get('pid')}\n"
              f"OCR+extract still in progress — poll again shortly.")
    elif state == "running":
        # progress says running but the pid is gone → it died/was killed mid-run.
        print(f"status: stalled  ({done}/{total} files; last pid not alive)\n"
              f"Partial work is committed and idempotent. Re-call ingest to resume.")
    else:
        print("status: not started  (no ingest has been run for this work dir)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("matter", nargs="?"); ap.add_argument("--work", required=True)
    ap.add_argument("--status", action="store_true",
                    help="report background-job progress / final summary, then exit")
    ap.add_argument("--summary-only", action="store_true",
                    help="print the DB-derived summary without doing any work")
    ap.add_argument("--summarize", action="store_true",
                    help="also generate on-device summaries per artifact (Apple FM; ~5-6s/doc)")
    a = ap.parse_args()
    if a.status:
        cmd_status(a.work); return
    if a.summary_only:
        print(summarize(sqlite3.connect(Path(a.work) / "manifest.db"))); return
    if not a.matter:
        ap.error("matter is required unless --status/--summary-only")
    matter, work = Path(a.matter), Path(a.work)
    # Accept either a matter dir containing sources/, OR a raw folder of documents.
    sources = matter / "sources" if (matter / "sources").is_dir() else matter
    work.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(work / "manifest.db")
    db.executescript(SCHEMA.read_text())
    summ.ensure_columns(db)   # summary/key_points columns (idempotent migration)

    exp = expand_zips(sources, work)
    web_meta = capture_urls(sources, work)     # <sources>/urls.txt → PDF snapshots (opt-in, needs network)
    files = [p for p in list(sources.rglob("*")) + list(exp.rglob("*"))
             if p.is_file() and p.suffix.lower() != ".zip"
             and p.name not in (".DS_Store", "urls.txt")]
    files += [Path(p) for p in web_meta]        # captured web snapshots join the pipeline

    # Idempotency: skip files already ingested in a prior run into this manifest,
    # so re-running into the same --work never duplicates rows.
    existing = {r[0] for r in db.execute("SELECT sha256 FROM artifact")}
    write_progress(work, total=len(files), done=0, state="running",
                   pid=os.getpid(), matter=str(matter))
    proc = 0
    seen = {}
    c = {"ingested": 0, "dupes": 0, "chars": 0, "pages": 0, "events": 0, "zone_unknown": 0,
         "formfield": 0, "docusign": 0, "sparse": 0, "ambiguous": 0, "r1_docs": 0, "r1_recovered": 0}
    by_kind, by_prov = {}, {}

    def add_event(aid, kind, raw, utc, wall, gran, zs, src, prov, flag=None, resolution="parsed"):
        db.execute("INSERT INTO event(artifact_id,kind,value_raw,value_utc,value_wall,granularity,"
                   "zone_status,source,provenance,resolution) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (aid, kind, raw, utc, wall, gran, zs, src, prov, resolution))
        c["events"] += 1
        if zs == "unknown":
            c["zone_unknown"] += 1
        by_prov[prov] = by_prov.get(prov, 0) + 1
        if flag:
            c["ambiguous"] += 1

    for f in files:
        proc += 1
        write_progress(work, done=proc)
        try:
            t_file = time.perf_counter()
            sha = sha256(f)
            if sha in existing:
                continue                      # already ingested in a prior run → true idempotency
            if sha in seen:
                c["dupes"] += 1
                db.execute("INSERT INTO artifact(sha256,original_path,kind,duplicate_of) VALUES(?,?,?,?)",
                           (sha, str(f), f.suffix.lower().lstrip("."), seen[sha])); continue
            m = {}
            t0 = time.perf_counter(); r = run([str(META), str(f)]); log_metric(db, f.name, "meta", _ms(t0))
            if r.returncode == 0 and r.stdout.strip():
                m = json.loads(r.stdout)
            kind = m.get("kind", f.suffix.lower().lstrip("."))
            pages = (m.get("pdf") or {}).get("pages", 1 if kind == "image" else None)
            aid = db.execute("INSERT INTO artifact(sha256,original_path,kind,pages,bytes,title) "
                             "VALUES(?,?,?,?,?,?)", (sha, str(f), kind, pages, m.get("bytes"),
                             (m.get("pdf") or {}).get("title"))).lastrowid
            seen[sha] = aid; c["ingested"] += 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if pages:
                c["pages"] += pages

            # band-1 from meta
            if (m.get("pdf") or {}).get("created"):
                add_event(aid, "created", m["pdf"]["created"], m["pdf"]["created"], None, "second",
                          "explicit", "pdf./Info", "document-backed")
            if (m.get("fs") or {}).get("birth"):
                add_event(aid, "created", m["fs"]["birth"], m["fs"]["birth"], None, "second",
                          "explicit", "fs.birthtime", "document-backed")
            img = m.get("image") or {}
            if img.get("DateTimeOriginal"):
                add_event(aid, "captured", img["DateTimeOriginal"], None, None, "second",
                          img.get("zone_status", "unknown"), "exif.DateTimeOriginal", "document-backed")

            # web capture: retag as a webpage + record URL and retrieval/published provenance
            if str(f) in web_meta:
                wm = web_meta[str(f)]
                db.execute("UPDATE artifact SET kind='webpage', flags=? WHERE id=?",
                           (json.dumps({k: wm.get(k) for k in ("url", "final_url", "title")}), aid))
                if wm.get("retrieved"):
                    add_event(aid, "retrieved", wm["retrieved"], wm["retrieved"], None, "second",
                              "explicit", "web.retrieved", "document-backed")
                for k in ("published", "modified"):
                    if wm.get(k):
                        utc, zs = parse_web_dt(wm[k])
                        add_event(aid, k, wm[k], utc, None, "second" if utc else "day", zs,
                                  f"web.{k}", "document-backed")

            is_chat = False
            if f.suffix.lower() == ".eml":
                t0 = time.perf_counter(); r = run([sys.executable, str(EML), str(f)]); log_metric(db, f.name, "eml", _ms(t0))
                if r.returncode == 0 and r.stdout.strip():
                    for ev in json.loads(r.stdout).get("events", []):
                        add_event(aid, ev["kind"], ev["value_raw"], ev.get("value_utc"), None,
                                  "second", ev.get("zone_status", "unknown"), ev["source"],
                                  ev.get("provenance", "document-backed"))

            elif f.suffix.lower() == ".txt":
                # chat exports (WhatsApp / imessage-exporter) → conversation-span events;
                # non-chat .txt returns platform:null and is left to plain-text indexing.
                r = run([sys.executable, str(CHAT), str(f)])
                if r.returncode == 0 and r.stdout.strip():
                    ch = json.loads(r.stdout)
                    if ch.get("platform"):
                        is_chat = True
                        db.execute("UPDATE artifact SET kind='chat', flags=? WHERE id=?",
                                   (json.dumps({k: ch.get(k) for k in
                                                ("platform", "variant", "participants", "message_count")}), aid))
                        by_kind["chat"] = by_kind.get("chat", 0) + 1
                        for ev in ch.get("events", []):
                            add_event(aid, ev["kind"], ev["value_raw"], None, ev.get("value_wall"),
                                      ev.get("granularity", "minute"), "unknown", ev["source"],
                                      "document-backed", flag=ev.get("flag"))

            t0 = time.perf_counter(); tp = own_ocr(f, work); log_metric(db, f.name, "ocr", _ms(t0))
            content_events = 0
            if tp and tp.exists():
                body = tp.read_text(errors="ignore")
                c["chars"] += len(body)
                db.execute("INSERT INTO doc_fts(body,artifact_id) VALUES(?,?)", (body, aid))
                db.execute("UPDATE artifact SET ocr_path=? WHERE id=?", (str(tp), aid))
                if a.summarize:      # opt-in on-device gist (Apple FM); reduction only
                    summ.store(db, aid, summ.run_summary(str(tp)))
                locale = extract.infer_locale(body)
                # band-2 content dates — skipped for chat exports (chat.py already gives
                # authoritative, zone-honest span events; NSDataDetector would misread the
                # per-message locale as US MDY and flood the table one date per message)
                if not is_chat:
                    t0 = time.perf_counter(); r = run([str(DATEDETECT), str(tp)]); log_metric(db, f.name, "datedetect", _ms(t0))
                    if r.returncode == 0 and r.stdout.strip():
                        for ev in json.loads(r.stdout):
                            add_event(aid, ev["kind"], ev["value_raw"], ev.get("value_utc"),
                                      ev.get("value_wall"), ev.get("granularity", "day"),
                                      ev.get("zone_status", "unknown"), ev["source"],
                                      ev.get("provenance", "document-backed"))
                            content_events += 1
                # band-1.5 form-field dates (semantically typed)
                doc_ff = 0
                for ev in extract.formfield_dates(body, locale):
                    add_event(aid, ev["kind"], ev["value_raw"], None, ev.get("value_wall"),
                              "day", ev.get("zone_status", "unknown"), ev["source"],
                              "document-backed", ev.get("flag"))
                    c["formfield"] += 1; doc_ff += 1
                # DocuSign
                ds = extract.docusign(body)
                if ds["envelope_ids"]:
                    c["docusign"] += 1
                    db.execute("UPDATE artifact SET flags=? WHERE id=?",
                               (json.dumps({"docusign_envelopes": ds["envelope_ids"]}), aid))
                for ev in ds["signing_events"]:
                    add_event(aid, ev["kind"], ev["value_raw"], None, None, "day", "unknown",
                              ev["source"], "document-backed")

                # R1: cheap-trigger, page-granular force-Vision (bypass text layer) for
                # form/DocuSign/sparse docs whose text layer scrambled label↔value adjacency.
                cpp = (len(body) / pages) if pages else 9999
                if (doc_ff == 0 and ds["envelope_ids"]) or (pages and pages >= 2 and content_events == 0) or cpp < 200:
                    pm = r1_pages(body)
                    if ds["envelope_ids"]:
                        targets = [n for n, t in pm.items()
                                   if "docusign envelope id" in t.lower()
                                   or any(lb in t.lower() for lb in FORM_LABELS)] or [1]
                    else:
                        targets = sorted(pm) or [1]
                    combined = ""
                    t0 = time.perf_counter()
                    for n in sorted(set(targets))[:6]:          # cap pages → bounded cost
                        rr = run([str(OCRBIN), str(f), "--force-vision", "--pages", str(n), "--quiet"])
                        combined += "\n" + rr.stdout
                    log_metric(db, f.name, "R1", _ms(t0))
                    loc2 = extract.infer_locale(combined) or locale
                    rec = 0
                    for ev in extract.formfield_dates(combined, loc2):
                        add_event(aid, ev["kind"], ev["value_raw"], None, ev.get("value_wall"),
                                  "day", ev.get("zone_status", "unknown"),
                                  ev["source"].replace("formfield", "formfield-R1"),
                                  "document-backed", ev.get("flag"), resolution="reinspect")
                        rec += 1
                    if rec:
                        c["r1_recovered"] += rec; c["r1_docs"] += 1
                    else:
                        c["sparse"] += 1
                        db.execute("INSERT INTO gap(artifact_id,gap_type,detail,remediation) VALUES(?,?,?,?)",
                                   (aid, "sparse-ocr", f"{pages}pp, R1 found no typed dates",
                                    "R4a human-assist of key page"))
            log_metric(db, f.name, "file-total", _ms(t_file))
            db.commit()
        except Exception as e:
            print(f"  ! {f.name[:48]}: {e}", file=sys.stderr)
    db.commit()

    # DB-derived summary: correct after any number of resumed runs (this-run
    # counters would under-report a corpus finished across several passes).
    summary = summarize(db)
    print(summary)
    try:
        (_state_dir(work) / "summary.txt").write_text(summary)
    except Exception:
        pass
    write_progress(work, done=len(files), total=len(files), state="done")


if __name__ == "__main__":
    main()
