#!/usr/bin/env python3
"""extract.py — Dossier band-1.5 hardening extractors (from benchmark run1 §15).

Pure-Python, deterministic, no LLM:
  • infer_locale / normalize_numeric  — per-document MM/DD vs DD/MM resolution
  • formfield_dates                   — "Label: <date>" pairs → semantically-typed events
  • docusign                          — envelope IDs + certificate signing timestamps

Importable by ingest; also runnable standalone for testing:  extract.py <textfile>
"""
import re, sys, json

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# numeric d/m/y or m/d/y, and common text forms
NUM = r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b"
TEXT_DATE = r"\b(?:\d{1,2}\s+[A-Z][a-z]+\s+\d{4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})\b"
ANY_DATE = rf"(?:{NUM[2:]}|{TEXT_DATE})"  # NUM without the \b duplication when embedded

LABELS = [
    (r"beginning(?:\s+date)?(?:\s+of\s+lease)?", "effective"),
    (r"commencement", "effective"),
    (r"effective(?:\s+date)?", "effective"),
    (r"ending(?:\s+date)?(?:\s+of\s+lease)?", "expires"),
    (r"expiration", "expires"),
    (r"termination(?:\s+date)?", "expires"),
    (r"date\s+signed|signed\s+on|executed(?:\s+on)?", "signed"),
]


def infer_locale(text):
    """Return 'MDY', 'DMY', or None by finding any unambiguous numeric date (a field >12)."""
    mdy = dmy = 0
    for a, b, _ in re.findall(NUM, text):
        a, b = int(a), int(b)
        if a > 12 and b <= 12:
            dmy += 1
        elif b > 12 and a <= 12:
            mdy += 1
    if mdy and not dmy:
        return "MDY"
    if dmy and not mdy:
        return "DMY"
    return None  # conflicting or no disambiguating evidence


def normalize_numeric(a, b, y, locale):
    a, b, y = int(a), int(b), int(y)
    if y < 100:
        y += 2000
    if locale == "MDY":
        mo, da = a, b
    elif locale == "DMY":
        mo, da = b, a
    else:
        return None, "order-ambiguous"
    if 1 <= mo <= 12 and 1 <= da <= 31:
        return f"{y:04d}-{mo:02d}-{da:02d}", "explicit-locale"
    return None, "order-ambiguous"


def formfield_dates(text, locale=None):
    """Find 'Label ... : <date>' pairs → typed events."""
    out = []
    for pat, kind in LABELS:
        # pat must be wrapped in a non-capturing group: several LABELS entries contain a
        # top-level "|" of their own (e.g. "date\s+signed|signed\s+on|executed..."), which —
        # unwrapped — silently splits the WHOLE concatenated regex into separate top-level
        # alternatives, so some branches never include the trailing date group at all and
        # group(1) comes back None even though the match "succeeded".
        for m in re.finditer(r"(?:" + pat + r")[^\n:]{0,30}:?\s*(" + NUM + r"|" + TEXT_DATE + r")",
                             text, re.IGNORECASE):
            raw = m.group(1)
            if raw is None:
                continue
            ev = {"kind": kind, "value_raw": raw, "source": f"formfield@{m.start()}",
                  "provenance": "document-backed", "granularity": "day"}
            nm = re.match(NUM, raw)
            if nm:
                iso, zs = normalize_numeric(*nm.groups(), locale)
                ev["value_wall"] = iso
                ev["zone_status"] = "unknown" if zs == "order-ambiguous" else "unknown"
                if zs == "order-ambiguous":
                    ev["flag"] = "order-ambiguous"
            out.append(ev)
    return out


def docusign(text):
    env = re.findall(r"Docusign\s+Envelope\s+ID:\s*([0-9A-Fa-f-]{36})", text)
    signs = []
    for m in re.finditer(r"(Signed|Sent|Completed|Viewed):\s*([0-9/]{6,10})[^\n]{0,30}",
                        text, re.IGNORECASE):
        signs.append({"kind": "docusign-" + m.group(1).lower(), "value_raw": m.group(2),
                      "source": f"docusign@{m.start()}", "provenance": "document-backed"})
    return {"envelope_ids": list(dict.fromkeys(env)), "signing_events": signs}


if __name__ == "__main__":
    txt = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
    loc = infer_locale(txt)
    print(json.dumps({
        "locale": loc,
        "formfield_dates": formfield_dates(txt, loc),
        "docusign": docusign(txt),
    }, indent=2))
