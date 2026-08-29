#!/usr/bin/env python3
"""datedetect_win.py — Windows port of helpers/datedetect (Swift/NSDataDetector).

    datedetect_win.py <textfile>     (or: datedetect_win.py -   to read stdin)

Rules baked in (SPEC.md 3.2), same as the macOS binary:
  - keep ranges whole — "X to Y" yields BOTH endpoints (content-range-start/end)
  - never invent a timezone — if no explicit offset is found, value_utc is null
    and we report the wall-clock the text actually stated (value_wall)
  - preserve the raw span + character offset (source: content@<offset>)

Field names in each emitted record must match exactly what server/ingest.py
parses by key: kind, value_raw, value_utc, value_wall, granularity, zone_status,
source, provenance.
"""
import json, re, sys
from datetime import timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import dateparser
from dateparser.search import search_dates

MONTH_RX = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)
YEAR_RX = re.compile(r"\b\d{4}\b")
DAY_RX = re.compile(r"\b\d{1,2}\b")
TIME_RX = re.compile(r"\d{1,2}:\d{2}")
RANGE_CONNECTOR_RX = re.compile(r"^\s*(to|-|–|—|through|thru)\s*$", re.I)


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def granularity(span):
    low = span.lower()
    if TIME_RX.search(low) or "am" in low or "pm" in low:
        return "second"
    if DAY_RX.search(low):
        return "day"
    if MONTH_RX.search(low):
        return "month"
    if YEAR_RX.search(low):
        return "year"
    return "day"


def has_explicit_zone(span):
    """Best-effort mirror of NSDataDetector's zone detection: an explicit
    offset (+05:00, Z) or a recognizable zone abbreviation in the raw text."""
    if re.search(r"[+-]\d{2}:?\d{2}\b", span) or re.search(r"\bUTC\b|\bGMT\b|\bZ\b", span):
        return True
    return bool(re.search(r"\b(EST|EDT|CST|CDT|MST|MDT|PST|PDT)\b", span))


def record(kind, dt, span, offset):
    r = {
        "kind": kind,
        "value_raw": span,
        "granularity": granularity(span),
        "source": f"content@{offset}",
        "provenance": "document-backed",
    }
    # Only trust a zone if the span itself contains explicit zone text AND a
    # zone-aware re-parse of just that span actually resolved one — never invent.
    aware = None
    if has_explicit_zone(span):
        aware = dateparser.parse(span, settings={"RETURN_AS_TIMEZONE_AWARE": True})
    if aware is not None and aware.tzinfo is not None:
        r["zone_status"] = "explicit"
        r["value_utc"] = aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        r["zone_status"] = "unknown"
        r["value_utc"] = None
        r["value_wall"] = dt.replace(tzinfo=None).isoformat()
    return r


def main():
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        p = Path(sys.argv[1])
        if not p.exists():
            die(f"no such file: {p}")
        text = p.read_text(encoding="utf-8", errors="ignore")
    else:
        text = sys.stdin.read()

    # languages=["en"] + STRICT_PARSING cuts dateparser's well-known false-positive rate
    # on short ambiguous fragments (street numbers, stray abbreviations) close to zero on
    # real corpus text, without losing genuine dates (verified against test-flat corpus).
    settings = {"RETURN_AS_TIMEZONE_AWARE": False, "STRICT_PARSING": True}
    found = search_dates(text, languages=["en"], settings=settings) or []

    out = []
    used_ranges = set()
    # Detect simple "DATE <connector> DATE" ranges by looking at what sits
    # between two consecutive matches in the original text.
    for i in range(len(found) - 1):
        span_a, dt_a = found[i]
        span_b, dt_b = found[i + 1]
        off_a = text.find(span_a)
        off_b = text.find(span_b, off_a + len(span_a))
        if off_a == -1 or off_b == -1:
            continue
        between = text[off_a + len(span_a):off_b]
        if RANGE_CONNECTOR_RX.match(between):
            out.append(record("content-range-start", dt_a, span_a, off_a))
            out.append(record("content-range-end", dt_b, span_b, off_b))
            used_ranges.add(i)
            used_ranges.add(i + 1)

    for i, (span, dt) in enumerate(found):
        if i in used_ranges:
            continue
        off = text.find(span)
        if off == -1:
            continue
        out.append(record("content", dt, span, off))

    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
