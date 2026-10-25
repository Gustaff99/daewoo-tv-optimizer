"""Ingesta local de fichas Daewoo proporcionadas por el operador (FASE 1).

Cuando el sitio daewooelectronics.com devuelve 429 (rate-limit) y no se puede
descargar desde esta máquina, el operador descarga las fichas desde su
navegador (Ctrl+S → «Página web, solo HTML», nombrando el archivo con el
**slug** + `.html`) y las entrega como carpeta o `.zip`. Este script las
integra en `docs/research/fetch/pages/` y reconstruye la matriz, **sin tocar
la red**. Es el bypass legítimo del rate-limit para completar la FASE 1.

Principios (coherentes con el resto del pipeline FASE 1):
- **No se toca la red.** Solo se leen/copian archivos locales y se llama a
  `build_matrix` (también local). No hay transport, no hay urllib.
- **No se inventa.** Cada ficha pasa por el mismo `parse_spec_page` que las
  descargadas por red; el SO solo se marca `verified` con evidencia real.
- **No se sobreescribe trabajo ya completado por defecto.** Si la página ya
  está cacheada se omite (a menos que se pase `--force`): una ficha buena
  descargada antes no se pierde por un re-entregado.
- **Guardas contra basura.** Se rechazan cuerpos de rate-limit
  (`local_rate_limited`), archivos demasiado pequeños (shells JS / páginas de
  error) y archivos que no son HTML. Un mal guardado no ensucia la matriz; el
  operador recibe el motivo para re-guardar.

Uso (desarrollo, desde daewoo-tv-optimizer/):
    # carpeta con los HTMLs
    python3 scripts/ingest_local_pages.py /ruta/a/fichas
    # o un .zip con esos HTMLs
    python3 scripts/ingest_local_pages.py /ruta/a/fichas.zip
    # reemplazar páginas ya cacheadas
    python3 scripts/ingest_local_pages.py /ruta/a/fichas --force

Solo stdlib. Determinista. Sin red. Testable con archivos en tmp.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Permite ejecutar como script o como paquete.
try:
    from scripts.build_matrix import build_matrix, CATALOG_TSV, PAGES_DIR, MATRIX_PATH
except ImportError:
    from build_matrix import build_matrix, CATALOG_TSV, PAGES_DIR, MATRIX_PATH


# Umbral mínimo de bytes para considerar una página HTML válida. Una ficha
# real de la tienda pesa ~300 KB; un cuerpo de 429 pesa 18 bytes y un shell
# de error, unos cientos. 512 separa limpiamente «página» de «basura» sin
# rechazar una ficha legítimamente mínima.
MIN_PAGE_BYTES = 512

_HTML_START_RE = re.compile(r"<!doctype|<html", re.I)


@dataclass
class IngestReport:
    drop: str = ""
    ingested: List[str] = field(default_factory=list)       # slugs copiados a pages/
    already_present: List[str] = field(default_factory=list)  # slugs ya cacheados (omitidos)
    rejected: Dict[str, str] = field(default_factory=dict)    # slug -> motivo
    matrix_path: Optional[str] = None
    os_verified: int = 0
    os_total: int = 0

    def to_dict(self) -> dict:
        return {
            "drop": self.drop,
            "ingested": self.ingested,
            "already_present": self.already_present,
            "rejected": self.rejected,
            "matrix_path": self.matrix_path,
            "os_verified": self.os_verified,
            "os_total": self.os_total,
        }


def slug_from_filename(name: str) -> str:
    """Deriva el slug del nombre de archivo entregado.

    '32de73hli-32hd-dled-tv.html' → '32de73hli-32hd-dled-tv'
    '32de73hli-32hd-dled-tv.htm'  → '32de73hli-32hd-dled-tv'
    '32de73hli-32hd-dled-tv'      → '32de73hli-32hd-dled-tv'
    """
    stem = name
    low = stem.lower()
    if low.endswith(".html"):
        stem = stem[:-5]
    elif low.endswith(".htm"):
        stem = stem[:-4]
    return stem


def classify_content(text: str) -> Optional[str]:
    """Devuelve un motivo de rechazo si el contenido NO es una ficha HTML
    válida, o None si parece legítima.

    Conservador: mejor rechazar que ensuciar la matriz con basura. El orden
    importa: primero la firma inequívoca de rate-limit, luego el tamaño, y al
    final la presencia de un documento HTML.
    """
    if "local_rate_limited" in text:
        return "rate_limited_body (es una respuesta 429, no una ficha)"
    nbytes = len(text.encode("utf-8", "ignore"))
    if nbytes < MIN_PAGE_BYTES:
        return (f"too_small ({nbytes} bytes < {MIN_PAGE_BYTES}): "
                f"guarda la página completa (Ctrl+S → «Página web, solo HTML»)")
    if not _HTML_START_RE.search(text):
        return "not_html (sin <!doctype ni <html>): no parece una página web"
    return None


def load_catalog_slugs(catalog_path: Path) -> Dict[str, str]:
    """Devuelve {slug: url} del catálogo TSV (fuente de verdad de slugs)."""
    out: Dict[str, str] = {}
    for line in catalog_path.read_text(encoding="utf-8").strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0].strip():
            out[parts[0].strip()] = parts[1].strip()
    return out


def _resolve_drop(drop: Path) -> Tuple[Path, Optional[Path]]:
    """Si `drop` es un .zip, lo extrae a un tmp y devuelve (dir, tmpdir|None).

    El tmpdir (si lo hay) debe ser limpiado por el llamador con rmtree.
    """
    if drop.is_file() and drop.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="ingest-zip-"))
        with zipfile.ZipFile(drop) as zf:
            zf.extractall(tmp)
        return tmp, tmp
    return drop, None


def ingest_local_pages(
    drop,
    pages_dir: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    matrix_path: Optional[Path] = None,
    rebuild_matrix: bool = True,
    force: bool = False,
) -> IngestReport:
    """Integra fichas HTML locales en `pages_dir` y reconstruye la matriz.

    - `drop`: directorio con los HTMLs (recursivo) o un archivo `.zip`.
    - **Sin red**: solo lectura/copia de archivos locales + build_matrix local.
    - No sobreescribe páginas ya cacheadas salvo `force=True`.
    """
    drop = Path(drop)
    pages_dir = Path(pages_dir) if pages_dir else PAGES_DIR
    catalog_path = Path(catalog_path) if catalog_path else CATALOG_TSV
    matrix_path = Path(matrix_path) if matrix_path else MATRIX_PATH

    rep = IngestReport(drop=str(drop))
    catalog = load_catalog_slugs(catalog_path)

    work_dir, tmp_dir = _resolve_drop(drop)
    try:
        # Recoge todos los .html/.htm (recursivo, por si hay subcarpetas).
        files = sorted(
            list(work_dir.rglob("*.html")) + list(work_dir.rglob("*.htm"))
        )
        seen: set = set()
        for f in files:
            slug = slug_from_filename(f.name)
            if not slug:
                continue
            if slug in seen:
                rep.rejected[slug] = "duplicate_slug (varios archivos con el mismo slug)"
                continue
            seen.add(slug)

            if slug not in catalog:
                rep.rejected[slug] = (
                    f"unknown_slug (no está en el catálogo; archivo {f.name})"
                )
                continue

            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                rep.rejected[slug] = f"read_error ({e})"
                continue

            reason = classify_content(text)
            if reason:
                rep.rejected[slug] = reason
                continue

            target = pages_dir / f"{slug}.html"
            if target.is_file() and not force:
                rep.already_present.append(slug)
                continue

            pages_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, target)
            rep.ingested.append(slug)
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if rebuild_matrix:
        matrix = build_matrix(merge_cached=True,
                              catalog_path=catalog_path, pages_dir=pages_dir)
        matrix_path.parent.mkdir(parents=True, exist_ok=True)
        matrix_path.write_text(
            json.dumps(matrix, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rep.matrix_path = str(matrix_path)
        rep.os_total = matrix["model_count"]
        rep.os_verified = sum(
            1 for m in matrix["models"] if m["os"]["status"] == "verified"
        )
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Integra fichas HTML locales (del operador) en la matriz, sin red.")
    ap.add_argument("drop",
                    help="directorio con los HTMLs o un .zip con ellos")
    ap.add_argument("--force", action="store_true",
                    help="reemplazar páginas ya cacheadas")
    ap.add_argument("--no-matrix", action="store_true",
                    help="no reconstruir la matriz al final")
    ap.add_argument("--pages-dir", default=None,
                    help="directorio de páginas (default: docs/research/fetch/pages)")
    ap.add_argument("--catalog", default=None,
                    help="catálogo TSV (default: docs/research/fetch/daewoo-tv-models-urls.tsv)")
    ap.add_argument("--matrix", default=None,
                    help="ruta de la matriz (default: docs/research/compatibility-matrix.json)")
    args = ap.parse_args(argv)

    drop = Path(args.drop)
    if not drop.exists():
        print(f"ERROR: no existe {drop}")
        return 2

    rep = ingest_local_pages(
        drop,
        pages_dir=Path(args.pages_dir) if args.pages_dir else None,
        catalog_path=Path(args.catalog) if args.catalog else None,
        matrix_path=Path(args.matrix) if args.matrix else None,
        rebuild_matrix=not args.no_matrix,
        force=args.force,
    )
    print(f"integradas:   {len(rep.ingested)} {rep.ingested}")
    print(f"ya presentes: {len(rep.already_present)} {rep.already_present}")
    if rep.rejected:
        print(f"rechazadas:   {len(rep.rejected)}")
        for slug, reason in sorted(rep.rejected.items()):
            print(f"  - {slug}: {reason}")
    if rep.matrix_path:
        print(f"matriz: {rep.matrix_path} (OS verificado {rep.os_verified}/{rep.os_total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
