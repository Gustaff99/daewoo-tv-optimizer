#!/usr/bin/env python3
"""Search Bing for a Daewoo model and extract result cards (title, URL,
snippet). Evidence-only: records what Bing returns; no OS inferred here.
Bing was IP-blocked in the prior run but works again (2026-10-24 ~22:10Z)."""
from __future__ import annotations
import html as _html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs/research/fetch/bing-search"


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), r.read().decode("utf-8", "replace")


def _clean(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def bing_results(body: str):
    """Bing organic results: <li class="b_algo"> ... <h2><a href=URL>title</a>
    ... snippet in <p> or <div class="b_caption">."""
    out = []
    for li in re.findall(r'<li class="b_algo".*?</li>', body, re.S):
        am = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                       li, re.S)
        if not am:
            continue
        url = am.group(1)
        title = _clean(am.group(2))
        # snippet: first <p> after the anchor, or b_caption
        sm = re.search(r'<p[^>]*>(.*?)</p>', li, re.S)
        snip = _clean(sm.group(1)) if sm else ""
        out.append({"title": title, "url": url, "snippet": snip})
    return out


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "40DM62FA"
    q = f"{model} Daewoo TV"
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(q) \
        + "&setlang=es&count=15"
    code, body = get(url)
    res = bing_results(body)
    print(f"Bing {model}: HTTP {code} bytes={len(body)} results={len(res)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"model": model, "query": q, "http_status": code,
           "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "results": res}
    (OUT_DIR / f"{model}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    for i, r in enumerate(res):
        print(f"[{i}] {r['title'][:80]}")
        print(f"    {r['url'][:100]}")
        if r["snippet"]:
            print(f"    snip: {r['snippet'][:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
