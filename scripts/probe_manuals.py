#!/usr/bin/env python3
"""Probe manual-database sites for a Daewoo model (search reachability).
Evidence-only: records HTTP status + whether the model appears. No OS inferred."""
from __future__ import annotations
import re
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def get(url, timeout=18):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), r.read().decode("utf-8", "replace")


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "40DM62FA"
    q = f"Daewoo {model}"
    qe = urllib.parse.quote(q)
    candidates = [
        ("manualslib", f"https://www.manualslib.com/search/?q={qe}"),
        ("manualmind", f"https://www.manualmind.com/search?q={qe}"),
        ("usermanuals", f"https://www.usermanuals.com/search?q={qe}"),
        ("idbsoft", f"https://www.idbsoft.com/en/search/?q={qe}"),
        ("manuals+", f"https://www.manualsplus.com/search?q={qe}"),
        ("everycircuit", f"https://everycircuit.com/search?q={qe}"),
    ]
    for name, url in candidates:
        t0 = time.time()
        try:
            code, body = get(url)
            low = body.lower()
            has_model = model.lower().replace(" ", "") in low.replace(" ", "")
            has_daewoo = "daewoo" in low
            blocked = ("cloudflare" in low) or ("just a moment" in low) \
                or ("cf-browser" in low)
            print(f"{name:12s} HTTP {code} bytes={len(body):7d} "
                  f"t={time.time()-t0:4.1f}s model={has_model} "
                  f"daewoo={has_daewoo} blocked={blocked}")
        except Exception as e:
            code = getattr(e, "code", "")
            print(f"{name:12s} ERR {type(e).__name__} code={code} "
                  f"t={time.time()-t0:4.1f}s")
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
