"""Rate-limit-aware page fetcher (helper FASE 1).

Codifica las lecciones del limitador local de daewooelectronics.com
(body `local_rate_limited`, header `retry-after: 60`):

- Respetar el header `retry-after` cuando existe.
- Backoff exponencial entre intentos fallidos: base * 2**fallos, con tope.
- Estado persistente (JSON) para que la hora viable exacta sobreviva entre runs.
- **Refusa fetch antes de la hora viable** (no martillear el limitador).
- Cachea el HTML exitoso a disco.
- Transporte inyectable: los tests nunca tocan la red.

Solo stdlib. No ejecuta nada en red si no se inyecta un transport real.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Parámetros de backoff (segundos).
BASE_BACKOFF = 60          # coincide con el retry-after observado
MAX_BACKOFF = 900          # tope: 15 min
MIN_GAP = 30               # separación mínima entre intentos aunque no haya fallo

# Agotamiento de cuota sostenida del proxy saliente (lección de 2026-10-24):
# el limitador local (body `local_rate_limited`) siguió devolviendo 429
# >90 min tras el último 200, incluso con separaciones de 240-300 s. Un
# backoff con tope de 900 s no puede recuperarse de eso. Regla: tras
# N fallos consecutivos asumimos cuota agotada y programamos una pausa
# larga y ACOTADA (no crece sin límite).
QUOTA_EXHAUSTION_THRESHOLD = 3
QUOTA_PAUSE = 6 * 3600     # 6 h


@dataclass
class FetchResult:
    ok: bool
    status: int
    body: str = ""
    retry_after: Optional[int] = None
    cached: bool = False
    reason: str = ""


@dataclass
class RateLimitState:
    """Estado persistente del limitador."""
    last_attempt: Optional[float] = None      # epoch s del último intento
    consecutive_failures: int = 0
    next_viable: Optional[float] = None       # epoch s desde el que se puede fetch
    last_retry_after: Optional[int] = None
    pause_reason: Optional[str] = None        # "backoff" | "quota_exhaustion" | None

    @classmethod
    def load(cls, path: Path) -> "RateLimitState":
        if not path.is_file():
            return cls()
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                last_attempt=d.get("last_attempt"),
                consecutive_failures=int(d.get("consecutive_failures", 0)),
                next_viable=d.get("next_viable"),
                last_retry_after=d.get("last_retry_after"),
                pause_reason=d.get("pause_reason"),
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            # Estado corrupto → empezar limpio (fail-safe: no asumir permiso).
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "last_attempt": self.last_attempt,
                    "consecutive_failures": self.consecutive_failures,
                    "next_viable": self.next_viable,
                    "last_retry_after": self.last_retry_after,
                    "pause_reason": self.pause_reason,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def backoff_delay(consecutive_failures: int) -> float:
    """Delay de backoff exponencial con tope."""
    return min(MAX_BACKOFF, BASE_BACKOFF * (2 ** max(0, consecutive_failures)))


def compute_next_viable(state: RateLimitState, now: float) -> float:
    """Calcula a partir de qué epoch se permite el siguiente intento.

    Usa el mayor de:
      - next_viable ya registrado (si es futuro)
      - last_attempt + retry_after (si hubo retry-after)
      - last_attempt + backoff_delay(fallos)
      - last_attempt + QUOTA_PAUSE (si fallos consecutivos >= umbral)
      - last_attempt + MIN_GAP
    """
    candidates = [now]
    if state.next_viable is not None:
        candidates.append(state.next_viable)
    if state.last_attempt is not None:
        candidates.append(state.last_attempt + MIN_GAP)
        if state.last_retry_after is not None:
            candidates.append(state.last_attempt + state.last_retry_after)
        candidates.append(state.last_attempt + backoff_delay(state.consecutive_failures))
        if state.consecutive_failures >= QUOTA_EXHAUSTION_THRESHOLD:
            candidates.append(state.last_attempt + QUOTA_PAUSE)
    return max(candidates)


def is_viable(state: RateLimitState, now: float) -> bool:
    """True si se permite fetch ahora (fail-safe: sin estado → viable)."""
    if state.next_viable is None:
        return True
    return now >= state.next_viable


def record_success(state: RateLimitState, now: float) -> None:
    state.last_attempt = now
    state.consecutive_failures = 0
    state.last_retry_after = None
    state.pause_reason = None
    state.next_viable = now + MIN_GAP


def record_failure(state: RateLimitState, now: float, retry_after: Optional[int]) -> None:
    state.last_attempt = now
    state.consecutive_failures += 1
    if retry_after is not None:
        state.last_retry_after = int(retry_after)
    state.pause_reason = (
        "quota_exhaustion"
        if state.consecutive_failures >= QUOTA_EXHAUSTION_THRESHOLD
        else "backoff"
    )
    state.next_viable = compute_next_viable(state, now)


# Un transport recibe la URL y devuelve (status, headers_dict, body).
Transport = Callable[[str], "tuple[int, dict, str]"]


def fetch(
    url: str,
    transport: Transport,
    state_path: Path,
    cache_path: Optional[Path] = None,
    now: Optional[float] = None,
    cache: bool = True,
) -> FetchResult:
    """Fetch con respeto al rate-limit.

    - Si no es la hora viable → no llama al transport (reason='not_viable').
    - Éxito → cachea y resetea fallos.
    - 429 → lee retry-after y programa el backoff.
    - Otros fallos → backoff.
    """
    now = time.time() if now is None else now
    state = RateLimitState.load(state_path)

    if not is_viable(state, now):
        return FetchResult(
            ok=False, status=0, cached=False,
            reason=f"not_viable (next={state.next_viable:.0f}, now={now:.0f})",
        )

    # Cache hit: si ya cacheamos esta URL, no tocar la red.
    if cache and cache_path is not None and cache_path.is_file():
        return FetchResult(
            ok=True, status=200,
            body=cache_path.read_text(encoding="utf-8", errors="replace"),
            cached=True, reason="cache_hit",
        )

    status, headers, body = transport(url)
    state.last_attempt = now

    if status == 200:
        record_success(state, now)
        state.save(state_path)
        if cache and cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(body, encoding="utf-8")
        return FetchResult(ok=True, status=200, body=body, cached=False, reason="fetched")

    if status == 429:
        ra = headers.get("retry-after") or headers.get("Retry-After")
        ra_int: Optional[int] = None
        if ra is not None:
            try:
                ra_int = int(ra)
            except ValueError:
                ra_int = None
        record_failure(state, now, ra_int)
        state.save(state_path)
        return FetchResult(
            ok=False, status=429, retry_after=ra_int,
            reason=f"rate_limited (retry_after={ra_int}, next_viable={state.next_viable:.0f})",
        )

    # Otros errores (5xx, timeouts modelados como status!=200)
    record_failure(state, now, None)
    state.save(state_path)
    return FetchResult(ok=False, status=status, reason=f"http_{status}")


def urllib_transport(url: str, timeout: float = 45.0):
    """Transport real (solo stdlib). Devuelve (status, headers, body)."""
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (daewoo-optimizer research; +local)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, headers, body
    except urllib.error.HTTPError as e:
        headers = {k.lower(): v for k, v in (e.headers or {}).items()}
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, headers, body
    except Exception as e:  # timeout, DNS, conexión → modelado como fallo
        return 0, {}, str(e)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Fetch con respeto al rate-limit (retry-after + backoff).")
    ap.add_argument("url")
    ap.add_argument("--state", default="docs/research/fetch/ratelimit-state.json")
    ap.add_argument("--cache", default=None,
                    help="ruta de cache del HTML (default: derivada de la URL)")
    args = ap.parse_args(argv)

    state_path = Path(args.state)
    cache_path = Path(args.cache) if args.cache else None
    if cache_path is None:
        slug = args.url.rstrip("/").rsplit("/", 1)[-1] or "page"
        cache_path = state_path.parent / "pages" / f"{slug}.html"

    r = fetch(args.url, urllib_transport, state_path, cache_path)
    if r.ok:
        print(f"OK status={r.status} cached={r.cached} reason={r.reason}")
        if r.body and not r.cached:
            print(f"body_len={len(r.body)} cache={cache_path}")
        return 0
    print(f"FAIL status={r.status} reason={r.reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
