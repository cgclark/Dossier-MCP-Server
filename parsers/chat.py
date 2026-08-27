#!/usr/bin/env python3
"""chat.py — band-1 deterministic chat-export parser (Dossier).

Detects WhatsApp (.txt) and imessage-exporter (.txt) exports and emits provenance-
tagged events as JSON. Chat exports carry NO timezone (local wall clock), so per the
four rules we emit value_wall + zone_status="unknown" and NEVER invent a UTC. The
conversation is a range, so we emit its endpoints whole (chat_start + chat_end).
Ambiguous numeric dates (D/M vs M/D) get an order inferred from the whole file.

Prints {"platform": null} for anything that isn't a recognised chat export, so the
caller can fall back to plain-text indexing.

    chat.py <file.txt>
"""
import sys, json, re

# [2025-05-09, 2:32:07 PM] Sender: msg   |   [09/05/2025, 14:32:07] Sender: msg
WA_IOS = re.compile(r"^\[(?P<d>[^,\]]+),\s*(?P<t>\d{1,2}:\d{2}(?::\d{2})?\s*[APap]?\.?[Mm]?\.?)\]\s*(?:(?P<sender>[^:]{1,60}):\s)?")
# 09/05/2025, 14:32 - Sender: msg   |   5/9/25, 2:32 PM - Sender: msg
WA_ANDROID = re.compile(r"^(?P<d>\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),\s*(?P<t>\d{1,2}:\d{2}(?::\d{2})?\s*[APap]?\.?[Mm]?\.?)\s*-\s*(?:(?P<sender>[^:]{1,60}):\s)?")
# imessage-exporter:  May 9, 2025  2:32:07 PM   (date/time on its own line, sender next line)
IMSG = re.compile(r"^(?P<mon>[A-Z][a-z]{2,8}) (?P<day>\d{1,2}), (?P<year>\d{4})\s+(?P<t>\d{1,2}:\d{2}:\d{2}\s*[APap][Mm])")
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _hhmmss(t):
    t = t.strip().replace(".", "").upper()
    ampm = None
    m = re.search(r"([AP])M$", t)
    if m:
        ampm = m.group(1); t = t[:m.start()].strip()
    parts = [int(x) for x in t.split(":")]
    h = parts[0]; mi = parts[1]; s = parts[2] if len(parts) > 2 else 0
    if ampm == "P" and h != 12: h += 12
    if ampm == "A" and h == 12: h = 0
    gran = "second" if len(parts) > 2 else "minute"
    return h, mi, s, gran


def _split_ymd(d):
    """Return (a, b, y) integer fields for a numeric date, plus whether year is 4-digit."""
    parts = re.split(r"[./-]", d.strip())
    if len(parts) != 3:
        return None
    nums = [int(p) for p in parts]
    # ISO YYYY-MM-DD → unambiguous
    if len(parts[0]) == 4:
        return ("iso", nums[0], nums[1], nums[2])
    yr = nums[2] + (2000 if nums[2] < 100 else 0)
    return ("ambig", nums[0], nums[1], yr)


def _infer_order(dates):
    """From all numeric dates decide day/month field order: 'mdy' or 'dmy'."""
    first_gt12 = second_gt12 = False
    for d in dates:
        sp = _split_ymd(d)
        if not sp or sp[0] == "iso":
            continue
        a, b = sp[1], sp[2]
        if a > 12: first_gt12 = True
        if b > 12: second_gt12 = True
    if first_gt12 and not second_gt12:
        return "dmy"
    if second_gt12 and not first_gt12:
        return "mdy"
    return None  # inconclusive


def _wall(dobj, tstr, order):
    """Build (value_wall, granularity, ambiguous) for a numeric date + time string."""
    sp = _split_ymd(dobj)
    if not sp:
        return None
    ambiguous = False
    if sp[0] == "iso":
        y, mo, da = sp[1], sp[2], sp[3]
    else:
        a, b, y = sp[1], sp[2], sp[3]
        use = order or "mdy"
        ambiguous = order is None
        mo, da = (a, b) if use == "mdy" else (b, a)
    try:
        h, mi, s, gran = _hhmmss(tstr)
        return (f"{y:04d}-{mo:02d}-{da:02d}T{h:02d}:{mi:02d}:{s:02d}", gran, ambiguous)
    except Exception:
        return None


def parse(path):
    text = open(path, encoding="utf-8", errors="ignore").read()
    lines = text.splitlines()
    nonblank = sum(1 for ln in lines if ln.strip())

    # --- WhatsApp (iOS or Android) ---
    for rx, plat in ((WA_IOS, "whatsapp-ios"), (WA_ANDROID, "whatsapp-android")):
        hits = [(m, ln) for ln in lines for m in [rx.match(ln.lstrip("‎‏ "))] if m]
        if len(hits) >= 3 and len(hits) / max(nonblank, 1) > 0.2:
            dates = [m.group("d") for m, _ in hits]
            order = _infer_order(dates)
            senders, stamps = set(), []
            for m, _ in hits:
                if m.groupdict().get("sender"):
                    senders.add(m.group("sender").strip())
                w = _wall(m.group("d"), m.group("t"), order)
                if w: stamps.append(w)
            return _result("whatsapp", plat, senders, stamps, len(hits), order)

    # --- imessage-exporter ---
    hits, senders, stamps = [], set(), []
    for i, ln in enumerate(lines):
        m = IMSG.match(ln.strip())
        if not m:
            continue
        hits.append(m)
        mo = MONTHS.get(m.group("mon")[:3])
        if not mo:
            continue
        try:
            h, mi, s, gran = _hhmmss(m.group("t"))
        except Exception:
            continue
        stamps.append((f"{int(m.group('year')):04d}-{mo:02d}-{int(m.group('day')):02d}"
                       f"T{h:02d}:{mi:02d}:{s:02d}", gran, False))
        nxt = next((lines[j].strip() for j in range(i + 1, min(i + 3, len(lines))) if lines[j].strip()), "")
        if nxt and len(nxt) < 60:
            senders.add(nxt)
    if len(hits) >= 3:
        return _result("imessage", "imessage-exporter", senders, stamps, len(hits), "unambiguous")

    return {"platform": None}


def _result(platform, variant, senders, stamps, count, order):
    stamps = [s for s in stamps if s]
    events = []
    if stamps:
        walls = sorted(stamps, key=lambda s: s[0])
        lo, hi = walls[0], walls[-1]
        ambiguous = any(s[2] for s in stamps)
        rel = "wall-clock, zone-unknown" + ("; date-order ambiguous" if ambiguous else "")
        for kind, w in (("chat_start", lo), ("chat_end", hi)):
            events.append({
                "kind": kind, "source": f"{variant}.{kind}",
                "value_raw": w[0], "value_wall": w[0], "value_utc": None,
                "granularity": w[1], "zone_status": "unknown",
                "provenance": "document-backed", "reliability": rel,
                "flag": "ambiguous-date-order" if ambiguous else None,
            })
    return {
        "platform": platform, "variant": variant,
        "participants": sorted(p for p in senders if p),
        "message_count": count, "date_order": order or "inconclusive",
        "events": events,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: chat.py <file.txt>")
    print(json.dumps(parse(sys.argv[1]), indent=2, ensure_ascii=False))
