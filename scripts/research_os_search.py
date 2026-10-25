#!/usr/bin/env python3
"""FASE 1 — Research the OS (Sistema operativo) of each Daewoo model from
*other* sources (the official store daewooelectronics.com is rate-limited).

Method: query a search engine (DuckDuckGo HTML, no JS) per model number,
capture the top results (title, decoded URL, snippet) as raw evidence, and
save one JSON file per model. NO OS is inferred here — this only records what
the web returns. A separate pass (build_matrix / review) maps evidence -> OS
with an explicit source + confidence.

Design constraints (from DORAMONSTER / project rules):
  * No paid providers, no VPN/proxy, no credential scraping.
  * Public web search only; every hit is stored as evidence (URL + snippet).
  * Polite spacing between requests; detects the search engine's rate-limit
    page and stops rather than hammering.
  * Never invent an OS: a model with no OS-bearing evidence stays pending.

Usage:
  python3 scripts/research_os_search.py --limit N        # first N models
  python3 scripts/research_os_search.py --only 43DM65QV  # one model
  python3 scripts/research_os_search.py                  # all models
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_TXT = ROOT / "docs/research/fetch/daewoo-tv-models.txt"
OUT_DIR = ROOT / "docs/research/fetch/os-search"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)

# DuckDuckGo HTML endpoint (no JS, parseable).
DDG = "https://html.duckduckgo.com/html/"

# A result anchor looks like:
#   <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=ENCODED&rut=...">Title</a>
_ANCHOR_RE = re.compile(
    r'class="result__a"\s+href="([^"]+)"[^>]*>(.*?)</a>', re.S
)
_SNIPPET_RE = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</a>', re.S
)


def model_number_from_slug(slug: str) -> str:
    """'43dm65qv-uhd-qled-tv' -> '43DM65QV' (first token, uppercased)."""
    return slug.strip().split("-")[0].upper()


def _decode_ddg(href: str) -> str:
    """Decode a //duckduckgo.com/l/?uddg=... redirect to the real URL."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            return qs["uddg"][0]
    return href


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _looks_rate_limited(status: int, body: str) -> bool:
    if status in (403, 429, 202):
        return True
    low = body.lower()
    return ("anomaly" in low and "challenge" in low) or "no results" in low and status == 200 and len(body) < 2000


def search_model(model: str, timeout: int = 25) -> dict:
    """Run one search and return parsed results + raw status."""
    q = f"{model} Daewoo TV"
    url = DDG + "?" + urllib.parse.urlencode({"q": q})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    result = {
        "model": model,
        "query": q,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "http_status": None,
        "rate_limited": False,
        "results": [],
    }
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # noqa: BLE001
        status = e.code
        body = e.read().decode("utf-8", "replace") if e.fp else ""
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    result["http_status"] = status
    if _looks_rate_limited(status, body):
        result["rate_limited"] = True
        result["error"] = f"rate_limited (HTTP {status})"
        return result

    # Walk the document, pairing anchors with the next snippet.
    anchors = list(_ANCHOR_RE.finditer(body))
    snippets = list(_SNIPPET_RE.finditer(body))
    for i, m in enumerate(anchors[:8]):
        href, title = m.group(1), _clean(m.group(2))
        real = _decode_ddg(href)
        # Snippet is the one whose match starts after this anchor.
        snip = ""
        for s in snippets:
            if s.start() > m.start():
                snip = _clean(s.group(1))
                break
        result["results"].append(
            {"title": title, "url": real, "snippet": snip}
        )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="", help="single model number")
    ap.add_argument("--gap", type=float, default=3.0, help="seconds between requests")
    ap.add_argument("--timeout", type=int, default=25)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.only:
        models = [args.only.upper()]
    else:
        slugs = [
            ln.strip()
            for ln in MODELS_TXT.read_text().splitlines()
            if ln.strip()
        ]
        models = [model_number_from_slug(s) for s in slugs]
        if args.limit:
            models = models[: args.limit]

    print(f"researching {len(models)} models from other sources (search)")
    rl = 0
    for i, model in enumerate(models):
        r = search_model(model, timeout=args.timeout)
        out = OUT_DIR / f"{model}.json"
        out.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n")
        n = len(r["results"])
        flag = "RATE-LIMITED" if r["rate_limited"] else ""
        # First-result title as a quick signal.
        top = r["results"][0]["title"] if r["results"] else ""
        print(f"[{i+1:02d}/{len(models)}] {model}: {n} results {flag} | {top[:60]}")
        if r["rate_limited"]:
            rl += 1
            # Back off: stop early to avoid hammering the search engine.
            print("  -> rate limited; stopping to avoid hammering.", file=sys.stderr)
            break
        if i < len(models) - 1:
            time.sleep(args.gap)

    print(f"done. {len(models)} targeted, {rl} rate-limited. evidence in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
