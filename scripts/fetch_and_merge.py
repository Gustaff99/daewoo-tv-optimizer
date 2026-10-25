"""Pipeline FASE 1: fetch de fichas → parse → matriz (un solo comando).

Flujo:
1. Lee el catálogo (docs/research/fetch/daewoo-tv-models-urls.tsv).
2. Para cada slug (hasta --limit), fetch con respeto al rate-limit
   (scripts/fetch_page.py: retry-after + backoff + estado persistente).
   - Éxito → cachea el HTML en docs/research/fetch/pages/{slug}.html.
   - 429 / not_viable → PARA (no martillear; el próximo run continúa).
   - Cache hit → no toca la red.
3. Reconstruye la matriz (scripts/build_matrix.py con --merge) integrando
   todas las fichas cacheadas con su SO/specs y evidencia.

Uso (desarrollo, desde daewoo-tv-optimizer/):
    python3 scripts/fetch_and_merge.py --limit 3

Solo stdlib. El transport es inyectable → los tests no tocan la red.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

# Permite ejecutar como script o como paquete.
try:
    from scripts.fetch_page import (
        fetch, urllib_transport, FetchResult, RateLimitState,
        QUOTA_EXHAUSTION_THRESHOLD,
    )
    from scripts.build_matrix import build_matrix, CATALOG_TSV, PAGES_DIR, MATRIX_PATH
except ImportError:
    from fetch_page import (
        fetch, urllib_transport, FetchResult, RateLimitState,
        QUOTA_EXHAUSTION_THRESHOLD,
    )
    from build_matrix import build_matrix, CATALOG_TSV, PAGES_DIR, MATRIX_PATH

import json  # noqa: E402

Transport = Callable[[str], "tuple[int, dict, str]"]


@dataclass
class PipelineReport:
    fetched: List[str] = field(default_factory=list)      # slugs descargados (200)
    cache_hits: List[str] = field(default_factory=list)   # slugs ya cacheados
    rate_limited: Optional[str] = None                    # slug que dio 429
    not_viable_at: Optional[str] = None                   # slug que no era viable
    other_failures: dict = field(default_factory=dict)    # slug → reason
    matrix_path: Optional[str] = None
    os_verified: int = 0
    os_total: int = 0
    next_viable: Optional[float] = None      # epoch (del estado de rate-limit)
    pause_reason: Optional[str] = None       # "backoff" | "quota_exhaustion"

    def to_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "cache_hits": self.cache_hits,
            "rate_limited": self.rate_limited,
            "not_viable_at": self.not_viable_at,
            "other_failures": self.other_failures,
            "matrix_path": self.matrix_path,
            "os_verified": self.os_verified,
            "os_total": self.os_total,
            "next_viable": self.next_viable,
            "pause_reason": self.pause_reason,
        }


def run_pipeline(
    limit: int = 3,
    state_path: Optional[Path] = None,
    transport: Optional[Transport] = None,
    now_fn: Optional[Callable[[], float]] = None,
    rebuild_matrix: bool = True,
) -> PipelineReport:
    """Ejecuta fetch+merge para hasta `limit` fichas del catálogo.

    - `transport`: inyectable para tests (default: urllib real).
    - `now_fn`: reloj inyectable (default: time.time) — se consulta en cada
      fetch para respetar el MIN_GAP entre intentos.
    - Para en el primer 429/not_viable (el rate-limiter programa la pausa;
      el próximo run continúa donde este se detuvo).
    """
    import time
    state_path = state_path or (PAGES_DIR.parent / "ratelimit-state.json")
    transport = transport or urllib_transport
    now_fn = now_fn or time.time

    lines = CATALOG_TSV.read_text(encoding="utf-8").strip().splitlines()
    entries = [ln.split("\t") for ln in lines]

    rep = PipelineReport()
    for slug, url in entries:
        # Cached pages are already completed work. Counting them against the
        # download budget would revisit the first `limit` files forever.
        if len(rep.fetched) >= limit:
            break
        cache_path = PAGES_DIR / f"{slug}.html"
        r: FetchResult = fetch(url, transport, state_path, cache_path,
                               now=now_fn())
        if r.ok and r.cached:
            rep.cache_hits.append(slug)
        elif r.ok:
            rep.fetched.append(slug)
        elif r.status == 429:
            rep.rate_limited = slug
            break  # el site está limitando: respetar y parar
        elif "not_viable" in r.reason:
            rep.not_viable_at = slug
            break  # aún no es la hora: parar sin tocar la red
        else:
            rep.other_failures[slug] = r.reason
            break  # fallo desconocido: fail-safe, parar

    # Observabilidad del estado de rate-limit (sin tocar la red).
    try:
        st = RateLimitState.load(state_path)
        rep.next_viable = st.next_viable
        rep.pause_reason = st.pause_reason
    except (OSError, ValueError):
        pass

    if rebuild_matrix:
        matrix = build_matrix(merge_cached=True,
                              catalog_path=CATALOG_TSV, pages_dir=PAGES_DIR)
        MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
        MATRIX_PATH.write_text(
            json.dumps(matrix, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rep.matrix_path = str(MATRIX_PATH)
        rep.os_total = matrix["model_count"]
        rep.os_verified = sum(
            1 for m in matrix["models"] if m["os"]["status"] == "verified")
    return rep


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Pipeline FASE 1: fetch de fichas + parse + matriz.")
    ap.add_argument("--limit", type=int, default=3,
                    help="máximo de fichas a descargar en este run (default 3)")
    ap.add_argument("--state", default=None,
                    help="ruta del estado de rate-limit (default: docs/research/fetch/)")
    ap.add_argument("--no-matrix", action="store_true",
                    help="no reconstruir la matriz al final")
    args = ap.parse_args(argv)

    state_path = Path(args.state) if args.state else None
    rep = run_pipeline(limit=args.limit, state_path=state_path,
                       rebuild_matrix=not args.no_matrix)
    print(f"descargadas: {len(rep.fetched)} {rep.fetched}")
    print(f"cache hits: {len(rep.cache_hits)}")
    if rep.rate_limited:
        if rep.pause_reason == "quota_exhaustion" and rep.next_viable:
            import datetime
            t = datetime.datetime.fromtimestamp(
                rep.next_viable, datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%SZ")
            print(
                f"429 en: {rep.rate_limited} → COTA AGOTADA ("
                f">={QUOTA_EXHAUSTION_THRESHOLD} fallos consecutivos): "
                f"pausa larga hasta {t}"
            )
        else:
            print(f"429 en: {rep.rate_limited} → pausa programada, el próximo run continúa")
    if rep.not_viable_at:
        print(f"no viable en: {rep.not_viable_at} → esperar al next_viable del estado")
    if rep.other_failures:
        print(f"fallos: {rep.other_failures}")
    if rep.matrix_path:
        print(f"matriz: {rep.matrix_path} (OS verificado {rep.os_verified}/{rep.os_total})")
    # Exit 0 incluso con 429: es un resultado esperado y gestionado.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
