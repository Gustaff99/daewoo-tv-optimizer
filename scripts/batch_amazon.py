#!/usr/bin/env python3
"""Batch-search Amazon.es for Daewoo TV models (FASE 1, otras fuentes).

Resumible: salta los modelos que ya tienen evidencia en
docs/research/fetch/os-search/amazon-<MODEL>.json.

Evidence-only: guarda ASIN+titulo+URL de cada tarjeta de resultado y marca
si el modelo concreto aparece como TV (no mando). NO infiere el SO aqui;
la extraccion del SO se hace en una segunda pasada sobre la pagina de
producto (fetch_os_from_asin).

Detecta bot-challenge (bm-verify / pagina pequena) y respeta delay entre
peticiones para no disparar el challenge.
"""
from __future__ import annotations
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
OUT_DIR = ROOT / "docs/research/fetch/os-search"
DELAY_S = 3.0          # delay entre peticiones (anti bot-challenge)
BOT_MIN_BYTES = 40000  # por debajo de esto, sospecha de challenge


def robust_get(url: str, tries: int = 3, minbytes: int = 60000):
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


def is_bot_challenge(body: str) -> bool:
    low = body.lower()
    return ("bm-verify" in low) or ("captcha" in low) \
        or ("validatecaptcha" in low) or (len(body) < BOT_MIN_BYTES)


def extract_cards(body: str):
    cards = re.split(r'data-asin="([A-Z0-9]{10})"', body)
    out = []
    for i in range(1, len(cards) - 1, 2):
        asin = cards[i]
        block = cards[i + 1]
        tm = re.search(r'<h2[^>]*aria-label="([^"]+)"', block)
        if not tm:
            tm = re.search(
                r'class="a-size-base[^"]*"[^>]*>([^<]{15,160})<', block)
        title = tm.group(1).strip() if tm else ""
        out.append({"asin": asin, "title": title})
    # dedup by asin keeping first (longest title)
    seen = {}
    for c in out:
        a = c["asin"]
        if a not in seen or len(c["title"]) > len(seen[a]["title"]):
            seen[a] = c
    return list(seen.values())


def classify(model: str, title: str) -> str:
    """'tv' | 'remote' | 'other' — por el modelo concreto en el titulo."""
    t = title.lower()
    m = model.lower()
    if m not in t:
        return "other"
    if any(k in t for k in ("mando", "remote", "control ", "teleguia",
                            "pila", "bater")):
        return "remote"
    if "tv" in t:
        return "tv"
    return "other"


def pending_models() -> list:
    m = json.load(open(ROOT / "docs/research/compatibility-matrix.json"))
    out = []
    for mdl in m["models"]:
        slug = mdl.get("slug") or mdl.get("model")
        if (mdl.get("os") or {}).get("value") is None:
            out.append(slug.split("-")[0].upper())
    return out


def main() -> int:
    only = sys.argv[1:]  # opcional: lista de modelos concreta
    models = only or pending_models()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = 0
    for model in models:
        out = OUT_DIR / f"amazon-{model}.json"
        if out.exists():
            print(f"[skip] {model} (ya tiene evidencia)")
            continue
        url = "https://www.amazon.es/s?k=" + urllib.parse.quote(
            f"Daewoo {model}")
        body, n, tries = robust_get(url)
        challenge = is_bot_challenge(body)
        cards = [] if challenge else extract_cards(body)
        tv = [c for c in cards if classify(model, c["title"]) == "tv"]
        rec = {
            "model": model,
            "source": "amazon.es",
            "query": f"Daewoo {model}",
            "url": url,
            "http_bytes": n,
            "tries": tries,
            "bot_challenge": challenge,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cards": cards,
            "exact_tv_matches": tv,
        }
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        done += 1
        print(f"[{model}] bytes={n} tries={tries} challenge={challenge} "
              f"cards={len(cards)} TV_match={len(tv)}")
        for c in tv:
            print(f"    TV: {c['asin']} {c['title'][:90]}")
        time.sleep(DELAY_S)
        if challenge:
            # backoff mas largo si hay challenge
            time.sleep(15.0)
    print(f"--- batch terminado: {done} nuevos, "
          f"{len(models)-done} skipeados ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
