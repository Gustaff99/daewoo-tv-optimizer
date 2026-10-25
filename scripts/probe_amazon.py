#!/usr/bin/env python3
"""Probe Amazon.es for a Daewoo model: robust fetch (retry until real content),
extract product ASINs + titles. NO OS inferred here — only records what the page
returns. Used to verify Amazon.es is a usable *other source* for OS evidence."""
from __future__ import annotations
import re
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def robust_get(url: str, tries: int = 4, minbytes: int = 100000):
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
    q = f"Daewoo {model}"
    url = "https://www.amazon.es/s?k=" + urllib.parse.quote(q)
    body, n, tries = robust_get(url)
    print(f"search {model}: bytes={n} tries={tries}")
    asins = list(dict.fromkeys(re.findall(r"/dp/([A-Z0-9]{10})", body)))
    print(f"ASINs: {len(asins)} -> {asins[:8]}")
    titles = re.findall(
        r'<span class="a-size-base[^"]*">([^<]{10,120})</span>', body)
    for t in titles[:10]:
        print("  TITLE:", t.strip()[:100])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
