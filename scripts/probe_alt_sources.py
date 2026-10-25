#!/usr/bin/env python3
"""Time-boxed multi-source probe for Daewoo pending models.
Sources: amazon.de, idealo.de, and one final official-site check.
Evidence-only: records reachability + whether the exact model appears.
No OS inferred here."""
from __future__ import annotations
import re
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
UA_FF = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
         "Gecko/20100101 Firefox/128.0")


def get(url, ua, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": ua,
                                               "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), r.read().decode("utf-8", "replace")


def main() -> int:
    models = sys.argv[1:] or ["40DM62FA", "32DE73HLI", "50DM56QV"]
    for model in models:
        print(f"\n===== {model} =====")
        qe = urllib.parse.quote(f"Daewoo {model}")
        probes = [
            ("amazon.de", "https://www.amazon.de/s?k=" + qe, UA),
            ("idealo.de", "https://www.idealo.de/preisvergleich/Sortiment=1551/Searchtext=" + qe, UA_FF),
            ("idealo-s", "https://www.idealo.de/suchergebnis/?q=" + qe, UA_FF),
        ]
        for name, url, ua in probes:
            t0 = time.time()
            try:
                code, body = get(url, ua)
                low = body.lower()
                has_model = model.lower() in low
                blocked = ("captcha" in low) or ("are you a robot" in low) \
                    or ("just a moment" in low) or ("bm-verify" in low)
                print(f"{name:11s} HTTP {code} bytes={len(body):7d} "
                      f"t={time.time()-t0:4.1f}s model={has_model} "
                      f"blocked={blocked}")
            except Exception as e:
                code = getattr(e, "code", "")
                print(f"{name:11s} ERR {type(e).__name__} code={code} "
                      f"t={time.time()-t0:4.1f}s")
            time.sleep(1.5)
        # one final official check
        t0 = time.time()
        try:
            url = ("https://www.daewooelectronics.com/products/"
                   "daewoo-%s.json" % model.lower())
            code, body = get(url, UA_FF)
            print(f"official    HTTP {code} bytes={len(body):7d} "
                  f"t={time.time()-t0:4.1f}s")
            if code == 200:
                import json
                d = json.loads(body)
                p = d.get("product", {})
                print("   title:", p.get("title"))
        except Exception as e:
            code = getattr(e, "code", "")
            print(f"official    ERR {type(e).__name__} code={code} "
                  f"t={time.time()-t0:4.1f}s")
        time.sleep(1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
