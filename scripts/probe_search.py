#!/usr/bin/env python3
"""Re-probe search engines for a Daewoo model. The prior run found them
IP-blocked (botnet 202/403/429); re-test in case the block cleared."""
from __future__ import annotations
import re
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
UA_FIREFOX = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
              "Gecko/20100101 Firefox/128.0")


def get(url, ua, timeout=18):
    req = urllib.request.Request(url, headers={"User-Agent": ua,
                                               "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), r.read().decode("utf-8", "replace")


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "40DM62FA"
    q = f"{model} Daewoo TV sistema operativo"
    qe = urllib.parse.quote(q)
    candidates = [
        ("ddg-html", "https://html.duckduckgo.com/html/?q=" + qe, UA_FIREFOX),
        ("ddg-lite", "https://lite.duckduckgo.com/lite/?q=" + qe, UA_FIREFOX),
        ("bing", "https://www.bing.com/search?q=" + qe, UA),
        ("mojeek", "https://www.mojeek.com/search?q=" + qe, UA),
        ("searx-be", "https://searx.be/search?q=" + qe, UA_FIREFOX),
        ("searx-pub", "https://search.inetol.net/search?q=" + qe, UA_FIREFOX),
        ("qwant", "https://www.qwant.com/?q=" + qe, UA),
    ]
    for name, url, ua in candidates:
        t0 = time.time()
        try:
            code, body = get(url, ua)
            low = body.lower()
            has_model = model.lower() in low
            blocked = ("anomaly" in low and "challenge" in low) \
                or ("please enable js" in low) or ("captcha" in low) \
                or ("are you a robot" in low)
            # count result-ish links
            nres = len(re.findall(r'result__a|b_algo|result-title', body))
            print(f"{name:10s} HTTP {code} bytes={len(body):7d} "
                  f"t={time.time()-t0:4.1f}s model={has_model} "
                  f"blocked={blocked} results~{nres}")
        except Exception as e:
            code = getattr(e, "code", "")
            print(f"{name:10s} ERR {type(e).__name__} code={code} "
                  f"t={time.time()-t0:4.1f}s")
        time.sleep(1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
