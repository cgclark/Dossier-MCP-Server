#!/usr/bin/env python3
"""webcapture_win.py — Windows port of helpers/webcapture (Swift/WKWebView).

    webcapture_win.py <url> <out-base>

Writes <out-base>.pdf and <out-base>.html; prints metadata JSON to stdout:
{url, final_url, retrieved (UTC now), title, published, modified, author}.
Exit codes match the macOS binary: 2 usage, 3 load failure, 4 timeout.

Uses Playwright driving the system-installed Edge (falling back to Chrome) in
place of WKWebView — no separate browser download needed.
"""
import json, sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

META_JS = """
() => {
  function m(s) { const e = document.querySelector(s); return e ? (e.content || e.getAttribute('datetime')) : null; }
  return {
    title: document.title,
    published: m('meta[property="article:published_time"]') || m('meta[itemprop="datePublished"]') || m('meta[name="datePublished"]'),
    modified: m('meta[property="article:modified_time"]') || m('meta[name="dateModified"]'),
    author: m('meta[name="author"]') || m('meta[property="article:author"]'),
    final_url: location.href,
  };
}
"""


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def main():
    if len(sys.argv) < 3:
        die("usage: webcapture_win.py <url> <out-base>", 2)
    url, out_base = sys.argv[1], sys.argv[2]
    if "://" not in url:
        die("usage: webcapture_win.py <url> <out-base>", 2)

    retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge")
            except Exception:
                browser = p.chromium.launch(channel="chrome")
            page = browser.new_page(viewport={"width": 1200, "height": 1600})
            try:
                page.goto(url, timeout=28000, wait_until="load")
            except PWTimeout:
                die("timeout", 4)
            except Exception as e:
                die(f"load failed: {e}", 3)

            page.wait_for_timeout(1200)  # settle late-rendering JS, same as the Mac binary

            meta = {"url": url, "retrieved": retrieved}
            try:
                scraped = page.evaluate(META_JS)
                for k, v in (scraped or {}).items():
                    if v is not None:
                        meta[k] = v
            except Exception:
                pass

            html = page.content()
            with open(out_base + ".html", "w", encoding="utf-8") as f:
                f.write(html)
            page.pdf(path=out_base + ".pdf")
            browser.close()
    except SystemExit:
        raise
    except Exception as e:
        die(f"load failed: {e}", 3)

    print(json.dumps(meta, sort_keys=True))


if __name__ == "__main__":
    main()
