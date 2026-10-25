"""Generador de la matriz de compatibilidad Daewoo (FASE 1).

Entrada: `docs/research/fetch/daewoo-tv-models-urls.tsv` (catálogo ES verificado
contra el sitemap oficial de daewooelectronics.com).

Salida: `docs/research/compatibility-matrix.json` — matriz estructurada con:
- Datos derivados del slug oficial (tamaño, panel, clase de resolución),
  etiquetados `derived_from_slug` (confianza medium: es la nomenclatura del
  propio vendor, no una espec confirmada de la ficha).
- `os`: SIEMPRE `pending_verification` al generarse. El OS por modelo solo se
  rellena con `parse_spec_page.py` cuando hay HTML de ficha real cacheado.
  **Nunca se inventa el OS.**
- `verified_in_sitemap`: true solo si la URL aparece en el sitemap oficial.
- `optimization`/`risks`: vacíos hasta verificación (fail-safe).

Solo stdlib. Determinista.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
FETCH_DIR = REPO / "docs" / "research" / "fetch"
CATALOG_TSV = FETCH_DIR / "daewoo-tv-models-urls.tsv"
SITEMAPS = [
    FETCH_DIR / "sitemap-es-products-2026-10-24.xml",
    FETCH_DIR / "sitemap-2026-10-24.xml",
]
MATRIX_PATH = REPO / "docs" / "research" / "compatibility-matrix.json"
PAGES_DIR = FETCH_DIR / "pages"
EPREL_SPECS_JSON = FETCH_DIR / "eprel-pdf-specs.json"
OS_EVIDENCE_DIR = FETCH_DIR / "os-evidence"

# Resolución EPREL → clase, para cross-check contra el slug.
_RES_TO_CLASS = {
    "1366x768": "hd", "1280x720": "hd", "720p": "hd",
    "1920x1080": "fhd", "1080p": "fhd",
    "3840x2160": "uhd", "2160p": "uhd", "4k": "uhd",
}


def _load_eprel_specs() -> dict:
    """Carga specs EPREL de las fichas PDF del operador (si existen)."""
    if EPREL_SPECS_JSON.is_file():
        try:
            return json.loads(EPREL_SPECS_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def parse_slug(slug: str) -> dict:
    """Extrae tamaño/panel/resolución del slug oficial del vendor.

    Ej.: '50dm65qv-50uhd-qled-tv' → size_inch=50, panel=qled, res_class=uhd.
    Estos datos son derivados de la nomenclatura del vendor (medium confidence),
    no de la ficha técnica.
    """
    s = slug.lower()
    size_m = re.match(r"^(\d{2})d[me]", s)
    size = int(size_m.group(1)) if size_m else None

    panel = None
    if "qled" in s:
        panel = "qled"
    elif "oled" in s:
        panel = "oled"
    elif "dled" in s:
        panel = "dled"

    res_class = None
    if "uhd" in s:
        res_class = "uhd"
    elif "fhd" in s:
        res_class = "fhd"
    elif re.search(r"(?<![a-z])hd(?![a-z])", s) or "-hd-" in s:
        res_class = "hd"

    return {"size_inch": size, "panel": panel, "res_class": res_class}


def load_sitemap_urls() -> set:
    urls = set()
    for f in SITEMAPS:
        if f.is_file():
            urls.update(re.findall(r"<loc>(.*?)</loc>", f.read_text(encoding="utf-8")))
    return urls


def os_entry_for(slug: str) -> dict:
    """Entrada de OS: pendiente hasta que haya ficha HTML real parseada."""
    cached = PAGES_DIR / f"{slug}.html"
    if cached.is_file():
        # Dejar que parse_spec_page lo llene; aquí solo señalamos que hay cache.
        return {
            "value": None,
            "status": "pending_parse",
            "source": f"docs/research/fetch/pages/{slug}.html (cacheado, sin parsear)",
            "confidence": "none",
        }
    return {
        "value": None,
        "status": "pending_verification",
        "source": None,
        "confidence": "none",
    }


def _model_number(slug: str) -> str:
    """'55dm75qv-55uhd-qled-tv' -> '55DM75QV' (primer token, mayúsculas)."""
    return slug.split("-")[0].upper()


def _series(slug_or_model: str) -> str:
    """'55DM75QV' -> 'DM75QV' (sin el prefijo de 2 dígitos de tamaño)."""
    mn = _model_number(slug_or_model)
    return mn[2:] if len(mn) > 2 else mn


def _canonical_os(osv: str) -> str:
    """Normaliza el valor de SO al canon de la matriz.

    'Android TV' -> 'android_tv', 'No inteligente'/'Non-Smart' -> 'non_smart',
    'TiVo' -> 'tivo', 'VIDAA' -> 'vidaa'. El resto pasa tal cual (minúsculas).
    """
    table = {
        "android tv": "android_tv",
        "android": "android",
        "non smart": "non_smart",
        "non-smart": "non_smart",
        "no inteligente": "non_smart",
        "tivo": "tivo",
        "vidaa": "vidaa",
    }
    return table.get(osv, osv)


def _load_os_evidence() -> dict:
    """Carga evidencia de SO de fuentes fetchables (`os-evidence/*.json`).

    Devuelve {model_number: [ {os, source_name, source_url, evidence_snippet,
    retrieved_at, provenance}, ... ]}. Solo fuentes con dato EXPLÍCITO de SO;
    nunca se infiere. Soporta el formato de `markandbuy.json` (lista
    `models`) y el de `web-index-*.json` (citas de páginas oficiales exactas
    vía índice web, con `provenance` por entrada).
    """
    out: dict = {}
    if not OS_EVIDENCE_DIR.is_dir():
        return out
    for f in sorted(OS_EVIDENCE_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for m in data.get("models", []):
            mn = (m.get("model") or "").upper()
            osv = _canonical_os((m.get("os") or "").lower())
            if not mn or not osv or osv == "unknown":
                continue
            out.setdefault(mn, []).append({
                "os": osv,
                "source_name": m.get("source_name"),
                "source_url": m.get("source_url"),
                "evidence_snippet": m.get("evidence_snippet"),
                "retrieved_at": m.get("retrieved_at"),
                "provenance": m.get("provenance"),
            })
    return out


def apply_os_evidence(entry: dict, slug: str, evidence: dict) -> None:
    """Aplica evidencia de SO sobre la entrada de la matriz.

    - Coincidencia de modelo EXACTO con fuente explícita -> `verified`.
    - Hermano de la MISMA serie con SO conocido -> solo `series_hypothesis`
      (NO se asigna os.value; requiere ficha del modelo exacto). Sin inventar.
    - Si la MISMA serie tiene modelos exactos verificados con SOs DISTINTOS
      (ej. 32DM65QV=android y 43DM65QV=vidaa), la serie NO es clasificador:
      se registra `series_contradiction` en vez de hipótesis (instrucción del
      informe especialista MIS-10: re-evaluar DM65QV→Android ante el resultado
      exacto 43DM65QV=VIDAA).
    """
    mn = _model_number(slug)
    series = _series(slug)
    direct = evidence.get(mn, [])
    if direct:
        srcs = sorted({d["source_name"] for d in direct if d.get("source_name")})
        urls = sorted({d["source_url"] for d in direct if d.get("source_url")})
        prov = {d.get("provenance") for d in direct if d.get("provenance")}
        entry["os"] = {
            "value": _canonical_os(str(direct[0].get("os") or "").lower()),
            "status": "verified",
            "source": "; ".join(srcs) or "os-evidence",
            "source_urls": urls,
            "confidence": "high",
            "evidence": " | ".join(
                (d.get("evidence_snippet") or "")[:160] for d in direct
            ),
            "provenance": sorted(prov)[0] if prov else
                          "fuente fetchable (retailer/otros), dato explícito de SO",
        }
        return
    sib = [(k, v) for k, v in evidence.items()
           if k != mn and _series(k) == series]
    if sib:
        vals = sorted({_canonical_os(str(v[0].get("os") or "").lower())
                      for _, v in sib})
        srcs = sorted({v[0].get("source_name") for _, v in sib
                       if v[0].get("source_name")})
        if len(vals) > 1:
            # Contradicción en la serie: el sufijo no clasifica el SO.
            entry["os"]["series_contradiction"] = {
                "values": vals,
                "based_on_models": sorted(k for k, _ in sib),
                "source": "; ".join(srcs) or "os-evidence",
                "note": ("La serie NO es clasificador de SO: modelos exactos "
                         "verificados de la misma serie tienen SOs distintos. "
                         "Sin hipótesis; se requiere la ficha del modelo exacto."),
            }
            return
        entry["os"]["series_hypothesis"] = {
            "value": vals[0] if len(vals) == 1 else vals,
            "based_on_models": sorted(k for k, _ in sib),
            "source": "; ".join(srcs) or "os-evidence",
            "note": ("Hipótesis por serie (hermano de la misma serie con SO "
                     "conocido). NO asignado: requiere ficha del modelo exacto."),
        }


def build_matrix(now_iso: Optional[str] = None, merge_cached: bool = True,
                 catalog_path: Optional[Path] = None,
                 pages_dir: Optional[Path] = None,
                 eprel_specs: Optional[dict] = None,
                 os_evidence: Optional[dict] = None) -> dict:
    try:
        from scripts.parse_spec_page import merge_into_model_matrix_entry
    except ImportError:  # ejecutado como script, no como paquete
        from parse_spec_page import merge_into_model_matrix_entry

    catalog_path = catalog_path or CATALOG_TSV
    pages_dir = pages_dir or PAGES_DIR
    eprel_specs = eprel_specs if eprel_specs is not None else _load_eprel_specs()
    eprel_by_slug = eprel_specs.get("models", {}) if eprel_specs else {}
    os_evidence = (os_evidence if os_evidence is not None
                   else _load_os_evidence())
    lines = catalog_path.read_text(encoding="utf-8").strip().splitlines()
    sitemap_urls = load_sitemap_urls()

    models = []
    for line in lines:
        slug, url = line.split("\t")
        slug_data = parse_slug(slug)
        entry = {
            "slug": slug,
            "url": url,
            "verified_in_sitemap": url in sitemap_urls,
            "specs": {
                "size_inch": slug_data["size_inch"],
                "panel": slug_data["panel"],
                "res_class": slug_data["res_class"],
                "provenance": "derived_from_slug",
                "provenance_note": (
                    "Nomenclatura del vendor en la URL oficial; no de la ficha"
                ),
            },
            "os": os_entry_for(slug),
            "hardware_platform": {"value": None, "status": "pending_verification"},
            "diagnosis_methods": {
                "adb": "unknown",
                "usb_execution": "unknown",
                "note": "No asumir ADB: depende del SO real (pendiente).",
            },
            "optimization": {"status": "not_assessed", "actions": []},
            "risks": [],
        }
        # Si hay ficha HTML cacheada para este slug, parsear e integrar.
        if merge_cached:
            page = pages_dir / f"{slug}.html"
            if page.is_file():
                entry = merge_into_model_matrix_entry(
                    entry, page.read_text(encoding="utf-8"))
        # Si hay ficha EPREL (PDF del operador), integrar specs + cross-check.
        e = eprel_by_slug.get(slug)
        if e and e.get("specs"):
            entry["specs"] = dict(entry.get("specs", {}))
            entry["specs"]["eprel_fiche"] = {
                **e["specs"],
                "provenance": "eprel_fiche",
                "provenance_note": (
                    "Ficha EPREL de etiquetado energético (UE 2019/2013) "
                    "entregada por el operador; registro oficial UE."
                ),
                "source_pdf": e.get("pdf"),
                "sha256": e.get("sha256"),
                "origin": e.get("origin"),
                "model_match": e.get("model_match"),
            }
            entry["specs"]["provenance"] = "eprel_fiche+slug"
            # Cross-check: resolución EPREL vs clase derivada del slug.
            e_res = e["specs"].get("resolution")
            e_cls = _RES_TO_CLASS.get(e_res) if e_res else None
            if e_cls and slug_data.get("res_class") and e_cls != slug_data["res_class"]:
                entry["specs"]["cross_check"] = {
                    "field": "resolution",
                    "eprel": e_res, "slug_class": slug_data["res_class"],
                    "match": False,
                    "note": "La resolución de la ficha EPREL no coincide con la "
                            "clase derivada del slug; revisar.",
                }
            elif e_cls and slug_data.get("res_class"):
                entry["specs"]["cross_check"] = {
                    "field": "resolution",
                    "eprel": e_res, "slug_class": slug_data["res_class"],
                    "match": True,
                }
        # Evidencia de SO de fuentes fetchables (directo=verified; serie=hipótesis).
        apply_os_evidence(entry, slug, os_evidence)
        models.append(entry)

    n_eprel = sum(1 for m in models if "eprel_fiche" in m.get("specs", {}))
    n_mismatch = sum(
        1 for m in models
        if m.get("specs", {}).get("cross_check", {}).get("match") is False
    )
    n_os_verified = sum(1 for m in models if m["os"].get("status") == "verified")
    n_os_hyp = sum(1 for m in models if "series_hypothesis" in m["os"])
    if n_os_verified < len(models):
        os_status_note = ("Las fichas EPREL no incluyen campo de SO; los modelos "
                          "sin fuente explícita siguen en pending_verification.")
    else:
        os_status_note = ("SO verificado para el 100% de los modelos; no quedan "
                          "pendientes.")
    return {
        "version": 1,
        "generated_at": now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market": "es-europa",
        "source_catalog": "daewooelectronics.com (catálogo ES, verificado contra sitemap oficial)",
        "model_count": len(models),
        "models": models,
        "notes": [
            "os.value=null es intencional: no se inventa el SO sin ficha real.",
            "specs derivados del slug oficial del vendor (medium confidence).",
            (f"specs EPREL integradas de {n_eprel} fichas PDF del operador "
             f"(provenance eprel_fiche, high); {n_mismatch} con cross-check de "
             "resolución no coincidente."),
            os_status_note,
            (f"OS verificado por fuente fetchable (dato explícito): {n_os_verified}; "
             f"hipótesis por serie (no asignadas): {n_os_hyp}. "
             "Los modelos sin fuente explícita siguen en pending_verification."),
            "optimization no evaluado hasta identificar SO real (fail-safe).",
        ],
    }


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Genera la matriz de compatibilidad.")
    ap.add_argument("--no-merge", action="store_true",
                    help="no parsear fichas cacheadas (solo catálogo)")
    args = ap.parse_args(argv)

    matrix = build_matrix(merge_cached=not args.no_merge)
    MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_PATH.write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Matriz generada: {MATRIX_PATH} ({matrix['model_count']} modelos)")
    verified = sum(1 for m in matrix["models"] if m["os"]["status"] == "verified")
    print(f"OS verificado: {verified}/{matrix['model_count']}")
    print(f"OS pendiente de verificación: {matrix['model_count'] - verified}/{matrix['model_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
