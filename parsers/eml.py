#!/usr/bin/env python3
"""eml.py — band-1 deterministic email parser (Dossier).

Emit provenance-tagged events + threading from an .eml, as JSON. No LLM.
Records Date (sender-claimed) and the Received chain (server-stamped) SEPARATELY,
per SPEC §3.4 — agreement is corroboration, divergence is a flag (Claude adjudicates).

    eml.py <file.eml>
"""
import sys, json
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, getaddresses


def iso_utc(dt):
    if dt is None:
        return None, "unknown"
    if dt.tzinfo is None:
        return None, "unknown"            # naive datetime → never invent a zone
    from datetime import timezone
    return dt.astimezone(timezone.utc).isoformat(), "explicit"


def parse_date(raw):
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def main(path):
    with open(path, "rb") as f:
        msg = BytesParser().parse(f)

    events = []

    # Date: — sender-claimed send time
    draw = msg.get("Date")
    if draw:
        dt = parse_date(draw)
        utc, zs = iso_utc(dt)
        events.append({
            "kind": "sent", "source": "email.Date", "value_raw": draw,
            "value_utc": utc, "zone_status": zs,
            "provenance": "document-backed", "reliability": "sender-claimed",
        })

    # Received: — server-stamped hops (header order is newest→oldest)
    for i, rcv in enumerate(msg.get_all("Received", [])):
        tail = rcv.rsplit(";", 1)
        if len(tail) != 2:
            continue
        dt = parse_date(tail[1].strip())
        if not dt:
            continue
        utc, zs = iso_utc(dt)
        events.append({
            "kind": "received", "source": f"email.Received[{i}]",
            "value_raw": tail[1].strip(), "value_utc": utc, "zone_status": zs,
            "provenance": "document-backed", "reliability": "server-stamped",
        })

    refs = (msg.get("References") or "").split()
    headers = {
        "from": getaddresses([msg.get("From", "")]),
        "to": getaddresses(msg.get_all("To", [])),
        "cc": getaddresses(msg.get_all("Cc", [])),
        "subject": msg.get("Subject"),
        "message_id": msg.get("Message-ID"),
    }
    threading = {
        "in_reply_to": msg.get("In-Reply-To"),
        "references": refs,
    }

    print(json.dumps({
        "kind": "email", "headers": headers,
        "events": events, "threading": threading,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: eml.py <file.eml>")
    main(sys.argv[1])
