"""Tests del rate-limiter persistente (FASE 1, lección MIS-9).

Cobertura de las reglas que el incidente 429 exigió:
- 429 con Retry-After → pausa exacta respetada
- 429 sin Retry-After → backoff exponencial con techo
- should_fetch rechaza antes del próximo viable
- estado sobrevive a reinstanciación (persistencia real)
- éxito resetea el contador
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fetch_ratelimit import (  # noqa: E402
    PersistentRateLimiter,
    RateLimitState,
    _with_backoff,
    MAX_BACKOFF_S,
    BASE_BACKOFF_S,
    QUOTA_EXHAUSTION_THRESHOLD,
    QUOTA_PAUSE_S,
)


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class TestBackoff(unittest.TestCase):
    def test_exponential_growth(self):
        import random
        rng = random.Random(42)
        b1 = _with_backoff(1, rng)
        b2 = _with_backoff(2, rng)
        b3 = _with_backoff(3, rng)
        # crecimiento (el jitter ±25% no invierte el orden a estas escalas)
        self.assertGreater(b1, 0)
        self.assertGreater(b2, b1 * 0.9)
        self.assertGreater(b3, b2 * 0.9)

    def test_cap(self):
        import random
        rng = random.Random(1)
        for n in (10, 20, 50):
            self.assertLessEqual(_with_backoff(n, rng), MAX_BACKOFF_S * 1.25 + 1)

    def test_base_scale(self):
        import random
        rng = random.Random(7)
        b = _with_backoff(1, rng)
        self.assertGreaterEqual(b, BASE_BACKOFF_S * 0.75)
        self.assertLessEqual(b, BASE_BACKOFF_S * 1.25)


class TestPersistentRateLimiter(unittest.TestCase):
    def _mk(self, tmp: Path, clock: FakeClock) -> PersistentRateLimiter:
        return PersistentRateLimiter(tmp / "state.json", now_fn=clock)

    def test_429_with_retry_after_respected(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            clock = FakeClock()
            rl = self._mk(tmp, clock)
            self.assertTrue(rl.should_fetch())
            pause = rl.record_429(retry_after_s=60)
            self.assertGreaterEqual(pause, 60)  # respeta el Retry-After
            self.assertFalse(rl.should_fetch())
            self.assertGreater(rl.wait_seconds(), 0)
            # el jitter del backoff puede superar a 60: avanzar la pausa exacta
            # (+epsilon para el borde de punto flotante)
            clock.advance(rl.wait_seconds() + 1e-9)
            self.assertTrue(rl.should_fetch())
            self.assertEqual(rl.wait_seconds(), 0.0)

    def test_429_without_retry_after_uses_backoff(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            clock = FakeClock()
            rl = self._mk(tmp, clock)
            p1 = rl.record_429(retry_after_s=None)
            self.assertGreaterEqual(p1, BASE_BACKOFF_S * 0.75)
            clock.advance(p1)
            self.assertTrue(rl.should_fetch())
            p2 = rl.record_429(retry_after_s=None)
            # segundo 429 consecutivo: backoff mayor (2x base, ±25%)
            self.assertGreater(p2, BASE_BACKOFF_S * 1.0)

    def test_state_persists_across_reinstantiation(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            clock = FakeClock()
            rl1 = self._mk(tmp, clock)
            rl1.record_429(retry_after_s=120)
            nxt = rl1.next_viable_at()
            # nuevo proceso (misma ruta de estado)
            rl2 = self._mk(tmp, clock)
            self.assertEqual(rl2.next_viable_at(), nxt)
            self.assertFalse(rl2.should_fetch())
            self.assertEqual(rl2.state.consecutive_429, 1)

    def test_success_resets_counter(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            clock = FakeClock()
            rl = self._mk(tmp, clock)
            rl.record_429(retry_after_s=60)
            clock.advance(61)
            rl.record_success()
            self.assertEqual(rl.state.consecutive_429, 0)
            self.assertTrue(rl.should_fetch())
            # el siguiente 429 vuelve al backoff base, no al escalado
            p = rl.record_429(retry_after_s=None)
            self.assertLessEqual(p, BASE_BACKOFF_S * 1.25 + 1)

    def test_corrupt_state_falls_back_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            p.write_text("no-json{{{", encoding="utf-8")
            clock = FakeClock()
            rl = PersistentRateLimiter(p, now_fn=clock)
            self.assertTrue(rl.should_fetch())
            self.assertEqual(rl.state.total_429, 0)


class TestQuotaExhaustion(unittest.TestCase):
    """Cuota sostenida del proxy saliente: 429 que persiste >90 min tras el
    último 200 (evidencia 2026-10-24). El backoff con techo de 900 s no se
    recupera; tras N fallos consecutivos la pausa debe ser larga y acotada.
    """

    def _mk(self, tmp: Path, clock: FakeClock) -> PersistentRateLimiter:
        return PersistentRateLimiter(tmp / "state.json", now_fn=clock)

    def test_n_failures_still_exponential_backoff(self):
        with tempfile.TemporaryDirectory() as d:
            clock = FakeClock()
            rl = self._mk(Path(d), clock)
            for _ in range(QUOTA_EXHAUSTION_THRESHOLD - 1):
                rl.record_429(retry_after_s=None)
            self.assertEqual(rl.state.pause_reason, "backoff")
            self.assertLessEqual(rl.state.next_viable_at,
                                 clock.t + MAX_BACKOFF_S * 1.25 + 1)

    def test_quota_threshold_triggers_long_pause(self):
        with tempfile.TemporaryDirectory() as d:
            clock = FakeClock()
            rl = self._mk(Path(d), clock)
            for _ in range(QUOTA_EXHAUSTION_THRESHOLD - 1):
                rl.record_429(retry_after_s=None)
                clock.advance(rl.wait_seconds() + 1e-9)
            pause = rl.record_429(retry_after_s=None)  # el N-ésimo fallo
            self.assertEqual(pause, QUOTA_PAUSE_S, "pausa larga exacta (acotada)")
            self.assertEqual(rl.state.pause_reason, "quota_exhaustion")
            self.assertFalse(rl.should_fetch())

    def test_long_pause_does_not_grow_unbounded(self):
        with tempfile.TemporaryDirectory() as d:
            clock = FakeClock()
            rl = self._mk(Path(d), clock)
            for _ in range(QUOTA_EXHAUSTION_THRESHOLD + 1):
                rl.record_429(retry_after_s=None)
                clock.advance(QUOTA_PAUSE_S + 1e-9)  # viable de nuevo…
            # …y el fallo posterior sigue dando exactamente 6 h (no 12, 24…)
            pause = rl.record_429(retry_after_s=None)
            self.assertEqual(pause, QUOTA_PAUSE_S, "la pausa no crece sin límite")
            self.assertEqual(rl.state.next_viable_at,
                             clock.t + QUOTA_PAUSE_S)
            self.assertEqual(rl.state.pause_reason, "quota_exhaustion")

    def test_success_resets_quota_pause(self):
        with tempfile.TemporaryDirectory() as d:
            clock = FakeClock()
            rl = self._mk(Path(d), clock)
            for _ in range(QUOTA_EXHAUSTION_THRESHOLD):
                rl.record_429(retry_after_s=None)
                clock.advance(QUOTA_PAUSE_S + 1e-9)
            self.assertEqual(rl.state.pause_reason, "quota_exhaustion")
            rl.record_success()
            self.assertEqual(rl.state.consecutive_429, 0)
            self.assertIsNone(rl.state.pause_reason)
            self.assertTrue(rl.should_fetch())

    def test_quota_pause_with_retry_after(self):
        # Con Retry-After corto (60) el umbral de cuota sigue imponiendo 6 h
        # (solo a partir del N-ésimo fallo; antes manda el backoff/retry-after).
        with tempfile.TemporaryDirectory() as d:
            clock = FakeClock()
            rl = self._mk(Path(d), clock)
            for i in range(QUOTA_EXHAUSTION_THRESHOLD):
                pause = rl.record_429(retry_after_s=60)
                if i + 1 >= QUOTA_EXHAUSTION_THRESHOLD:
                    self.assertEqual(pause, QUOTA_PAUSE_S)
                clock.advance(pause + 1e-9)
            self.assertEqual(rl.state.pause_reason, "quota_exhaustion")


class TestRateLimitState(unittest.TestCase):
    def test_roundtrip(self):
        s = RateLimitState(next_viable_at=123.5, consecutive_429=3,
                           last_429_at=100.0, total_429=5, total_success=2)
        s2 = RateLimitState.from_json(s.to_json())
        self.assertEqual(s2, s)

    def test_roundtrip_with_pause_reason(self):
        s = RateLimitState(next_viable_at=123.5, consecutive_429=3,
                           pause_reason="quota_exhaustion")
        s2 = RateLimitState.from_json(s.to_json())
        self.assertEqual(s2, s)
        self.assertEqual(s2.pause_reason, "quota_exhaustion")


if __name__ == "__main__":
    unittest.main()
