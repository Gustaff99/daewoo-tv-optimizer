#!/usr/bin/env python3
"""Fetch Amazon.es search for a Daewoo model, locate the exact-model product
card, print its title + ASIN + surrounding text (to spot the OS). Evidence only."""
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
    q = f"Daewoo {model}"
    url = "https://www.amazon.es/s?k=" + urllib.parse.quote(q)
    body, n, tries = robust_get(url)
    print(f"search {model}: bytes={n} tries={tries}")
    low = body.lower()
    # Find occurrences of the model number and show nearby title-ish text.
    model_low = model.lower()
    seen = set()
    for m in re.finditer(re.escape(model_low), low):
        i = m.start()
        # Grab a window and strip tags to readable text.
        window = body[i-300:i+300]
        text = re.sub(r"<[^>]+>", " ", window)
        text = re.sub(r"\s+", " ", text).strip()
        key = text[:80]
        if key in seen:
            continue
        seen.add(key)
        print(f"CTX: ...{text}...")
        if len(seen) >= 6:
            break
    # ASINs near the model
    asins = list(dict.fromkeys(re.findall(r"/dp/([A-Z0-9]{10})", body)))
    print("ASINs:", asins[:10])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
