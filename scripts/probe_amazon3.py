#!/usr/bin/env python3
"""Extract title+ASIN pairs from an Amazon.es search page (result cards)."""
from __future__ import annotations
import re
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def robust_get(url, tries=4, minbytes=100000):
    best = ("", 0)
    for t in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA,
                              "Accept": "text/html,application/xhtml+xml"})
            with urllib.request.urlopen(req, timeout=25) as r:
                body = r.read().decode("utf-8", "replace")
            if len(body) > best[1]:
                best = (body, len(body))
            if len(body) >= minbytes:
                return body, len(body), t + 1
        except Exception:
            pass
        time.sleep(2.0)
    return best[0], best[1], tries


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "40DM62FA"
    url = "https://www.amazon.es/s?k=" + urllib.parse.quote(f"Daewoo {model}")
    body, n, tries = robust_get(url)
    print(f"search {model}: bytes={n} tries={tries}")
    # Amazon result cards: data-asin="XXXX" ... and a title in h2/span.
    # Split on data-asin blocks.
    cards = re.split(r'data-asin="([A-Z0-9]{10})"', body)
    # cards = [pre, asin1, block1, asin2, block2, ...]
    for i in range(1, len(cards) - 1, 2):
        asin = cards[i]
        block = cards[i + 1]
        # title: first h2 aria-label or s-line-clamp
        tm = re.search(r'<h2[^>]*aria-label="([^"]+)"', block)
        if not tm:
            tm = re.search(r'class="a-size-base[^"]*"[^>]*>([^<]{15,140})<', block)
        title = tm.group(1).strip() if tm else "(no title)"
        print(f"{asin}  {title[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
