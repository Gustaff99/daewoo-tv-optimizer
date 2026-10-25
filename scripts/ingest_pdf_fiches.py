"""Ingesta de fichas EPREL (PDF) entregadas por el operador — FASE 1.

Contexto: el sitio daewooelectronics.com devuelve HTTP 429 y el operador
entregó un ZIP con 30 fichas técnicas en PDF (fichas de etiquetado energético
EPREL, Reglamento UE 2019/2013) + `FUENTES.csv` (índice modelo→origen→URL→SHA256)
+ `LEEME.txt`.

Principio: **solo reporta lo que aparece literalmente en el PDF**, con
provenance `eprel_fiche`. Estas fichas contienen modelo, resolución, panel,
diagonal, clase energética y refresco — pero **NO el campo de SO**. Por tanto:

- `os` SIEMPRE queda `pending_verification` (no se inventa el SO).
- Las specs EPREL se integran en la matriz como `specs.eprel_fiche`
  (confianza high: registro oficial UE) y se cross-checkean contra las specs
  derivadas del slug.

Fuente de texto: `pdftotext` (poppler) si está disponible; si no, el PDF se
marca `extraction: "unavailable"` (no se inventa). Determinista, solo stdlib
+ pdftotext como herramienta externa opcional.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
FETCH_DIR = REPO / "docs" / "research" / "fetch"
CATALOG_TSV = FETCH_DIR / "daewoo-tv-models-urls.tsv"
EPREL_DIR = FETCH_DIR / "eprel-pdf"
FUENTES_CSV = EPREL_DIR / "FUENTES.csv"
OUT_JSON = FETCH_DIR / "eprel-pdf-specs.json"


# ---------------------------------------------------------------------------
# Extracción de texto PDF (pdftotext opcional)
# ---------------------------------------------------------------------------

def pdf_to_text(pdf_path: Path) -> Optional[str]:
    """Extrae texto con pdftotext -layout. None si no hay pdftotext o falla."""
    if not pdf_path.is_file():
        return None
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        return None
    text = r.stdout
    return text if text.strip() else None


def _norm(text: str) -> str:
    """Colapsa TODO el whitespace a un espacio (el -layout deja columnas
    muy separadas y saltos de línea entre campos)."""
    return re.sub(r"\s+", " ", text)


def _energy_class_sdr(t: str):
    """Clase de eficiencia (SDR) = letra A-G más cercana al marcador (SDR).

    En el formato EN la letra va ANTES de '(SDR)' (mismo renglón); en el ES
    va DESPUÉS. Tomamos la letra A-G más próxima al marcador.
    """
    m = re.search(r"\(SDR\)", t, re.I)
    if not m:
        return None
    before = t[max(0, m.start() - 40):m.start()]
    mb = re.findall(r"\b([A-G])\b", before)
    if mb:
        return mb[-1]
    after = t[m.end():m.end() + 60]
    ma = re.search(r"\b([A-G])\b", after)
    return ma.group(1) if ma else None


# ---------------------------------------------------------------------------
# Parser de campos EPREL (formatos EN shopify y ES eprel)
# ---------------------------------------------------------------------------

# (clave, patrón) — la primera captura es el valor. Se aplican sobre el texto
# normalizado (espacios colapsados). Soportan los dos idiomas observados.
EPREL_FIELDS = [
    ("model",
     r"(?:SUPPLIER’S MODEL IDENTIFIER|SUPPLIER'S MODEL IDENTIFIER|"
     r"Identificador del modelo)\s+([A-Z0-9]{4,})"),
    ("resolution",
     r"(?:SCREEN RESOLUTION \(PIXELS\)|Resolución de pantalla)"
     r"\s+([\d][\d ]*?)\s*x\s*([\d][\d ]*?)\s*pixels"),
    ("panel",
     r"(?:PANEL TECHNOLOGY USED|Tecnología usada en el panel)\s+"
     r"((?:QLED|OLED|VA|IPS|LCD)\s?(?:LCD)?\b)"),
    ("screen_inch",
     r"(?:SCREEN DIAGONAL\s+([\d]+)\s+inches|Diagonal de la pantalla\s+([\d]+)\s+pulga)"),
    ("screen_cm",
     r"(?:SCREEN DIAGONAL\s+([\d]+(?:[.,][\d]+)?)\s+cm|"
     r"Diagonal de la pantalla\s+([\d]+(?:[.,][\d]+)?)\s+cm)"),
    ("refresh_hz",
     r"(?:IMAGE REFRESH FREQUENCY RATE|Frecuencia de refresco de la imagen)"
     r"[^\d]*(\d{2,3})\s*Hz"),
]


def parse_eprel_text(text: str) -> Dict[str, object]:
    """Extrae los campos EPREL del texto de una ficha. Solo lo literal.

    Devuelve {clave: valor} con los campos hallados; los ausentes no aparecen.
    La resolución se normaliza a 'WxH' (sin espacios).
    """
    t = _norm(text)
    out: Dict[str, object] = {}
    for key, pat in EPREL_FIELDS:
        m = re.search(pat, t, re.I)
        if not m:
            continue
        if key == "resolution":
            w = m.group(1).replace(" ", "")
            h = m.group(2).replace(" ", "")
            out[key] = f"{w}x{h}"
        elif key in ("screen_inch", "screen_cm"):
            # Dos grupos alternativos (EN | ES): toma el que coincidió.
            val = m.group(1) if m.group(1) is not None else m.group(2)
            out[key] = int(val) if key == "screen_inch" else float(val.replace(",", "."))
        elif key == "refresh_hz":
            out[key] = int(m.group(1))
        elif key == "panel":
            out[key] = re.sub(r"\s+", " ", m.group(1)).strip()
        else:
            out[key] = m.group(1)
    # La clase de eficiencia se resuelve por proximidad al marcador (SDR)
    # porque el label se parte en líneas de forma distinta en EN y ES.
    ec = _energy_class_sdr(t)
    if ec:
        out["energy_class_sdr"] = ec
    return out


# ---------------------------------------------------------------------------
# Mapeo modelo → slug del catálogo
# ---------------------------------------------------------------------------

def load_catalog_model_map(catalog_path: Path) -> Dict[str, dict]:
    """Devuelve {MODELO_MAYUSC: {slug, url}} usando el primer token del slug."""
    m: Dict[str, dict] = {}
    for line in catalog_path.read_text(encoding="utf-8").strip().splitlines():
        slug, url = line.split("\t")
        model = slug.split("-")[0].upper()
        m[model] = {"slug": slug, "url": url}
    return m


# ---------------------------------------------------------------------------
# Ingesta completa
# ---------------------------------------------------------------------------

def ingest(fuentes_csv: Path = FUENTES_CSV,
           pdf_dir: Path = EPREL_DIR,
           catalog_path: Path = CATALOG_TSV,
           source_label: str = "Fichas_Tecnicas_Daewoo_2026-10-24.zip (operador)") -> dict:
    model_map = load_catalog_model_map(catalog_path)
    models: Dict[str, dict] = {}
    pending: List[dict] = []
    ok_count = 0
    extraction_failures: List[str] = []

    with fuentes_csv.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            model = (row.get("Modelo") or "").strip().upper()
            estado = (row.get("Estado") or "").strip()
            if not model:
                continue
            cmap = model_map.get(model)
            if cmap is None:
                # Modelo del CSV no está en el catálogo: se registra aparte.
                pending.append({
                    "model": model, "slug": None,
                    "reason": "modelo no presente en el catálogo del sitio",
                    "detalle": (row.get("Detalle") or "").strip() or None,
                })
                continue

            entry: Dict[str, object] = {
                "model": model,
                "slug": cmap["slug"],
                "url_producto": (row.get("URL_producto") or "").strip() or None,
                "url_ficha": (row.get("URL_ficha") or "").strip() or None,
                "origin": (row.get("Origen") or "").strip() or None,
                "sha256": (row.get("SHA256") or "").strip() or None,
                "pdf": (row.get("Archivo") or "").strip() or None,
                # Estas fichas EPREL NO tienen campo de SO → nunca se inventa.
                "os": {
                    "value": None,
                    "status": "pending_verification",
                    "note": "La ficha EPREL de etiquetado energético no incluye campo de SO.",
                },
                "specs": {},
                "provenance": "eprel_fiche",
            }

            if estado != "OK":
                entry["state"] = estado.lower()
                entry["specs"] = {}
                entry["extraction"] = "not_available"
                entry["reason"] = (row.get("Detalle") or "").strip() or None
                models[cmap["slug"]] = entry
                pending.append({
                    "model": model, "slug": cmap["slug"],
                    "reason": (row.get("Detalle") or f"estado={estado}").strip(),
                })
                continue

            # OK: localizar PDF y extraer texto.
            pdf_rel = (row.get("Archivo") or "").strip()
            pdf_path = pdf_dir / pdf_rel if pdf_rel else None
            text = pdf_to_text(pdf_path) if pdf_path else None
            if text is None:
                entry["extraction"] = "unavailable"
                extraction_failures.append(cmap["slug"])
            else:
                entry["extraction"] = "pdftotext"
                specs = parse_eprel_text(text)
                # Verificación de integridad: el modelo del PDF debe coincidir.
                pdf_model = specs.get("model")
                entry["model_match"] = (pdf_model == model) if pdf_model else None
                entry["specs"] = {k: v for k, v in specs.items() if k != "model"}
                ok_count += 1

            models[cmap["slug"]] = entry

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO))
        except ValueError:
            return str(p)

    return {
        "source": source_label,
        "fuentes_csv": _rel(fuentes_csv),
        "pdf_dir": _rel(pdf_dir),
        "pdf_count": ok_count,
        "extraction_failures": extraction_failures,
        "pending": pending,
        "note": (
            "Fichas EPREL de etiquetado energético (UE 2019/2013): dan specs de "
            "pantalla pero NO el campo de SO. os.value=null es intencional."
        ),
        "models": models,
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Ingresa fichas EPREL (PDF) del operador.")
    ap.add_argument("--out", default=str(OUT_JSON))
    args = ap.parse_args(argv)

    data = ingest()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"Artifact EPREL: {out}")
    print(f"PDFs con specs extraídas: {data['pdf_count']}")
    print(f"Pendientes: {len(data['pending'])}")
    for p in data["pending"]:
        print(f"  - {p['model']} ({p['slug']}): {p['reason']}")
    if data["extraction_failures"]:
        print(f"Fallos de extracción: {data['extraction_failures']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
