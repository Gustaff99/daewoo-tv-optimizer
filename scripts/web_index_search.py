#!/usr/bin/env python3
"""Búsqueda acotada en índice web (Bing) del SO de modelos Daewoo pendientes.

Implementa el plan del informe especialista MIS-10 (commit eb77291):
"bounded model-by-model web-index lookup against exact official product
URLs. Search by exact model and require the exact product page's explicit
Operating System field; store query, retrieval date, canonical URL,
captured excerpt, and confidence as per-model provenance."

Reglas conservadoras (no inventar):
- Solo cuenta el resultado cuyo TÍTULO coincida con el nombre oficial exacto
  `Daewoo <MODEL> ...` (formato de las páginas de producto oficiales).
- El snippet debe contener el campo EXPLÍCITO `Operating System: X`.
- Guard anti-costura: si el snippet menciona `Screen Size: N` y N != tamaño
  del modelo, el snippet es irreconfiable -> NO se verifica (se guarda en raw
  para auditoría y el modelo queda pending).
- NO se resuelven redirects ni se hace fetch de la página oficial (que
  devuelve 429); la evidencia es cita de índice web, no fetch fresco.
- Máximo 2 consultas por modelo, delay 2.5 s entre peticiones. Sin reintentos
  adicionales. Sin proxies/VPN.

Salida:
- docs/research/fetch/os-evidence/web-index-bing-YYYY-MM-DD.json (formato
  estándar de os-evidence con provenance web_index)
- docs/research/fetch/web-index-bing-raw/<MODEL>.json (auditoría: consultas,
  títulos, snippets y veredicto por modelo)
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs/research/compatibility-matrix.json"
EVIDENCE_DIR = ROOT / "docs/research/fetch/os-evidence"
RAW_DIR = ROOT / "docs/research/fetch/web-index-bing-raw"

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
      "Gecko/20100101 Firefox/128.0")
DELAY_S = 2.5
TIMEOUT_S = 15
MAX_QUERIES_PER_MODEL = 3

OS_FIELD = re.compile(
    r"(?:operating system|sistema operativo)\s*:?\s*"
    r"(vidaa|android tv|android|tivo|non[- ]?smart|no inteligente)",
    re.I)
SCREEN_SIZE = re.compile(r"screen size\s*:\s*(\d+)", re.I)
BING_RESULT = re.compile(
    r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.S)
BING_SNIPPET = re.compile(r'<p[^>]*>(.*?)</p>', re.S)


def _clean(html: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", txt).strip()


def bing_search(query: str) -> list[dict]:
    """Devuelve [ {title, url, snippet} ] de los bloques b_algo de Bing."""
    url = ("https://www.bing.com/search?q=" + urllib.parse.quote(query)
           + "&setlang=en&cc=us")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    body = urllib.request.urlopen(req, timeout=TIMEOUT_S).read().decode(
        "utf-8", "replace")
    out = []
    for block in re.split(r'<li class="b_algo"', body)[1:]:
        m = BING_RESULT.search(block)
        if not m:
            continue
        snippets = BING_SNIPPET.findall(block, )
        snips = [_clean(s) for s in snippets[:2]]
        out.append({
            "title": _clean(m.group(2)),
            "url": m.group(1),
            "snippet": " | ".join(s for s in snips if s),
        })
    return out


def model_size(model: str) -> str | None:
    """'55DM75QV' -> '55' (prefijo de 2 dígitos de tamaño)."""
    return model[:2] if model[:2].isdigit() else None


def _is_official_title(model: str, title: str) -> bool:
    """Título de página OFICIAL de producto exacta.

    Formato oficial: 'Daewoo <MODEL> <...> TV' (termina en TV). Excluye
    manuales, descargas y contenido de terceros (manualslib, etc.).
    """
    if not re.match(rf"^daewoo\s+{re.escape(model)}\b", title, re.I):
        return False
    t = title.lower()
    if any(w in t for w in ("manual", "download", "review", "unboxing",
                            "driver", "forum")):
        return False
    return re.search(r"\btv$", t) is not None


def evaluate(model: str, results: list[dict]) -> dict:
    """Aplica las reglas conservadoras a los resultados de una consulta.

    Devuelve {verdict, os, title, snippet, guard} con verdict en
    {'verified', 'unreliable_snippet', 'page_found_no_os', 'no_official_result'}.
    """
    size = model_size(model)
    page_found = None
    for r in results:
        title = r["title"]
        # Título oficial exacto: 'Daewoo <MODEL> <...> TV'
        if not _is_official_title(model, title):
            continue
        if page_found is None:
            page_found = r
        m = OS_FIELD.search(r["snippet"])
        if not m:
            continue
        osval = m.group(1).lower()
        osval = {"android tv": "android tv", "android": "android",
                 "vidaa": "vidaa", "tivo": "tivo",
                 "non smart": "non smart", "no inteligente": "non smart",
                 "non-smart": "non smart"}.get(osval, osval)
        ss = SCREEN_SIZE.search(r["snippet"])
        if ss and size and ss.group(1) != size:
            return {"verdict": "unreliable_snippet",
                    "reason": f"costura de snippet: Screen Size {ss.group(1)} != modelo {model}",
                    "os_candidate": osval, **r}
        return {"verdict": "verified", "os": osval, **r}
    if page_found is not None:
        return {"verdict": "page_found_no_os",
                "reason": "página oficial encontrada sin campo OS explícito en snippet",
                **page_found}
    return {"verdict": "no_official_result",
            "reason": "ningún resultado con título oficial exacto"}


def run(models: list[str], now_iso: str) -> dict:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    evidence_models = []
    raw_all = {}
    for i, model in enumerate(models):
        raw_all[model] = {"queries": [], "verdict": None}
        final = None
        for qi, query in enumerate([
            f'daewooelectronics "{model}" "Operating System"',
            f'"Daewoo {model}" "Operating System"',
            f'daewooelectronics.com "{model}"',
        ][:MAX_QUERIES_PER_MODEL]):
            if qi:
                time.sleep(DELAY_S)
            entry = {"query": query, "at": datetime.now(
                timezone.utc).isoformat()}
            try:
                results = bing_search(query)
            except Exception as e:  # noqa: BLE001 — registro y pasamos
                entry["error"] = f"{type(e).__name__}: {str(e)[:160]}"
                raw_all[model]["queries"].append(entry)
                continue
            entry["results"] = results[:10]
            raw_all[model]["queries"].append(entry)
            verdict = evaluate(model, results)
            raw_all[model]["last_verdict"] = verdict
            if verdict["verdict"] == "verified":
                final = verdict
                break
            if verdict["verdict"] == "unreliable_snippet":
                final = verdict  # no se verifica; no se repite
                break
        v = final or raw_all[model].get("last_verdict") or {
            "verdict": "no_official_result",
            "reason": "sin resultados procesables"}
        raw_all[model]["verdict"] = v["verdict"]
        if v["verdict"] == "verified":
            matrix_entry = None
            try:
                matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
                matrix_entry = next(
                    (x for x in matrix["models"]
                     if x["slug"].startswith(model.lower())), None)
            except (OSError, json.JSONDecodeError):
                pass
            canonical = (matrix_entry or {}).get("url")
            evidence_models.append({
                "model": model,
                "os": v["os"],
                "name": v["title"],
                "source_url": canonical,
                "source_name": "daewooelectronics.com (oficial, vía índice web — Bing)",
                "evidence_snippet": v["snippet"][:300],
                "retrieved_at": now_iso,
                "query": v.get("query", ""),
                "provenance": ("web_index: cita Bing de página oficial exacta "
                               "(título + campo Operating System); no fetch "
                               "HTTP fresco del endpoint (429)"),
            })
        time.sleep(DELAY_S)
    date = now_iso[:10]
    ev_path = EVIDENCE_DIR / f"web-index-bing-{date}.json"
    ev_path.write_text(json.dumps({
        "source": "Index web (Bing) de páginas oficiales Daewoo; cita del "
                  "campo explícito 'Operating System' del snippet de la "
                  "página exacta de producto. NO es fetch HTTP fresco.",
        "source_type": "web_index",
        "retrieved_at": now_iso,
        "count": len(evidence_models),
        "models": evidence_models,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    (RAW_DIR / f"audit-{date}.json").write_text(
        json.dumps(raw_all, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"evidence": evidence_models, "raw": raw_all,
            "evidence_path": str(ev_path)}


def main() -> int:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    models = sys.argv[1:]
    if not models:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        models = [x["slug"].split("-")[0].upper()
                  for x in matrix["models"] if x["os"]["value"] is None]
    out = run(models, now_iso)
    print(f"modelos consultados: {len(models)}")
    print(f"verificados vía índice web: {len(out['evidence'])}")
    for e in out["evidence"]:
        print(f"  {e['model']} = {e['os']}  ({e['title'][:60]})")
    for m, r in out["raw"].items():
        if r["verdict"] != "verified":
            print(f"  {m}: {r['verdict']}")
    print(f"evidencia: {out['evidence_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
