"""Rate-limit persistente para el fetcher de fichas (FASE 1, lección MIS-9).

Problema real sufrido: el proxy saliente devolvió 429 con
`Retry-After: 60` y luego 429 sin cabecera durante todo el intervalo de
trabajo. Reintentos ciegos agotaron el intervalo sin un solo 200.

Reglas (código, no promesa):
1. Estado persistente en `ratelimit-state.json` (sobrevive entre runs).
2. Ante 429 con Retry-After → pausa exacta.
3. Ante 429 sin Retry-After → backoff exponencial con jitter, con techo.
4. `should_fetch(now)` rechaza el fetch si todavía no es viable.
5. `next_viable_at` es la única fuente de verdad para "¿puedo fetchear?".

Solo stdlib. Determinista si se inyecta `now`/`rng`.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Union

# Backoff exponencial: base * 2^intentos, con techo.
BASE_BACKOFF_S = 60          # 1 min tras el primer 429 sin Retry-After
MAX_BACKOFF_S = 900          # 15 min: techo duro (nunca martillear)
JITTER_FRACTION = 0.25       # ±25% de jitter para no sincronizar reintentos

# Agotamiento de cuota sostenida del proxy saliente (lección 2026-10-24):
# el limitador local siguió devolviendo 429 >90 min tras el último 200,
# incluso con separaciones de 240-300 s. El backoff con techo de 900 s no
# se recupera de una cuota sostenida. Tras N fallos consecutivos: pausa
# larga y ACOTADA (no crece sin límite). Mismo umbral/pausa que fetch_page.py.
QUOTA_EXHAUSTION_THRESHOLD = 3
QUOTA_PAUSE_S = 6 * 3600     # 6 h

@dataclass
class RateLimitState:
    """Estado serializable del rate-limiter."""
    next_viable_at: float = 0.0     # epoch: cuándo se puede volver a fetchear
    consecutive_429: int = 0        # 429 consecutivos sin éxito
    last_429_at: Optional[float] = None
    last_success_at: Optional[float] = None
    total_429: int = 0
    total_success: int = 0
    pause_reason: Optional[str] = None  # "backoff" | "quota_exhaustion" | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "RateLimitState":
        d = json.loads(raw)
        # Compatibilidad con el formato antiguo de fetch_page.py
        # (last_attempt/consecutive_failures/next_viable/last_retry_after).
        # FAIL-SAFE crítico: si existe una pausa futura en el formato
        # antiguo y no la leemos, asumiríamos 0.0 (viable de inmediato)
        # y volveríamos a martillear el limitador del sitio.
        next_viable_at = d.get("next_viable_at")
        if next_viable_at is None:
            next_viable_at = d.get("next_viable", 0.0)
        consecutive = d.get("consecutive_429")
        if consecutive is None:
            consecutive = d.get("consecutive_failures", 0)
        last_429_at = d.get("last_429_at", d.get("last_attempt"))
        return cls(
            next_viable_at=float(next_viable_at or 0.0),
            consecutive_429=int(consecutive or 0),
            last_429_at=last_429_at,
            last_success_at=d.get("last_success_at"),
            total_429=int(d.get("total_429", 0)),
            total_success=int(d.get("total_success", 0)),
            pause_reason=d.get("pause_reason"),
        )


def _with_backoff(consecutive: int, rng: Optional[random.Random] = None) -> float:
    """Backoff exponencial con jitter: base * 2^n, ±JITTER, con techo."""
    rng = rng or random.Random()
    raw = BASE_BACKOFF_S * (2 ** max(0, consecutive - 1))
    capped = min(raw, MAX_BACKOFF_S)
    jitter = capped * JITTER_FRACTION * rng.uniform(-1.0, 1.0)
    return max(1.0, capped + jitter)


class PersistentRateLimiter:
    """Rate-limiter con estado en disco.

    Uso:
        rl = PersistentRateLimiter(state_path)
        if not rl.should_fetch(now):
            raise RefusedBeforeViable(rl.next_viable_at)
        ... fetch ...
        if status == 429:
            rl.record_429(retry_after_s, now=now)
        else:
            rl.record_success(now=now)
    """

    def __init__(self, state_path: Union[str, Path],
                 now_fn=time.time,
                 rng: Optional[random.Random] = None):
        self.state_path = Path(state_path)
        self._now = now_fn
        self._rng = rng or random.Random()
        self.state = self._load()

    def _load(self) -> RateLimitState:
        if self.state_path.is_file():
            try:
                return RateLimitState.from_json(
                    self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError, OSError):
                # Estado corrupto: empezar limpio pero conservando cautela.
                pass
        return RateLimitState()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(self.state.to_json(), encoding="utf-8")
        tmp.replace(self.state_path)  # atómico

    # -- consultas ---------------------------------------------------------

    def should_fetch(self, now: Optional[float] = None) -> bool:
        """True solo si el próximo fetch es viable ahora."""
        now = self._now() if now is None else now
        return now >= self.state.next_viable_at

    def next_viable_at(self) -> float:
        return self.state.next_viable_at

    def wait_seconds(self, now: Optional[float] = None) -> float:
        """Segundos que quedan hasta que el fetch sea viable (>= 0)."""
        now = self._now() if now is None else now
        return max(0.0, self.state.next_viable_at - now)

    # -- eventos -----------------------------------------------------------

    def record_429(self, retry_after_s: Optional[float],
                   now: Optional[float] = None) -> float:
        """Registra un 429 y devuelve los segundos de pausa acordada.

        - Con Retry-After: se respeta el valor del servidor (mínimo backoff).
        - Sin Retry-After: backoff exponencial según 429 consecutivos.
        """
        now = self._now() if now is None else now
        s = self.state
        s.consecutive_429 += 1
        s.total_429 += 1
        s.last_429_at = now
        if retry_after_s is not None and retry_after_s > 0:
            pause = max(float(retry_after_s), _with_backoff(1, self._rng))
        else:
            pause = _with_backoff(s.consecutive_429, self._rng)
        # Cuota sostenida agotada: el backoff no se recupera → pausa larga
        # acotada (mismo criterio que fetch_page.py).
        if s.consecutive_429 >= QUOTA_EXHAUSTION_THRESHOLD:
            pause = max(pause, QUOTA_PAUSE_S)
            s.pause_reason = "quota_exhaustion"
        else:
            s.pause_reason = "backoff"
        s.next_viable_at = now + pause
        self._save()
        return pause

    def record_success(self, now: Optional[float] = None) -> None:
        now = self._now() if now is None else now
        s = self.state
        s.consecutive_429 = 0
        s.total_success += 1
        s.last_success_at = now
        s.pause_reason = None
        s.next_viable_at = 0.0  # listo de inmediato
        self._save()
