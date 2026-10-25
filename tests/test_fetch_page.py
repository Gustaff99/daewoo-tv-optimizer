"""Tests para scripts/fetch_page.py (rate-limit aware fetcher).

Ningún test toca la red: el transport es inyectable (función de Python).
Cubren: backoff, hora viable, fail-safe, cache, 429/retry-after, persistencia.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.fetch_page import (  # noqa: E402
    BASE_BACKOFF,
    MAX_BACKOFF,
    MIN_GAP,
    QUOTA_EXHAUSTION_THRESHOLD,
    QUOTA_PAUSE,
    FetchResult,
    RateLimitState,
    backoff_delay,
    compute_next_viable,
    fetch,
    is_viable,
    record_failure,
    record_success,
)

NOW = 1_000_000.0  # epoch fijo para tests deterministas


class TestBackoff(unittest.TestCase):
    def test_exponential(self):
        self.assertEqual(backoff_delay(0), BASE_BACKOFF)          # 60
        self.assertEqual(backoff_delay(1), 120)
        self.assertEqual(backoff_delay(2), 240)
        self.assertEqual(backoff_delay(3), 480)

    def test_capped(self):
        self.assertEqual(backoff_delay(10), MAX_BACKOFF)
        self.assertEqual(backoff_delay(100), MAX_BACKOFF)

    def test_negative_safe(self):
        self.assertEqual(backoff_delay(-3), BASE_BACKOFF)


class TestComputeNextViable(unittest.TestCase):
    def test_no_state_returns_now(self):
        s = RateLimitState()
        self.assertEqual(compute_next_viable(s, NOW), NOW)

    def test_uses_retry_after(self):
        s = RateLimitState(last_attempt=NOW, last_retry_after=60,
                           consecutive_failures=0)
        self.assertEqual(compute_next_viable(s, NOW), NOW + 60)

    def test_uses_backoff_over_mingap(self):
        s = RateLimitState(last_attempt=NOW, consecutive_failures=2)  # 240
        self.assertEqual(compute_next_viable(s, NOW), NOW + 240)

    def test_preserves_future_next_viable(self):
        s = RateLimitState(last_attempt=NOW, next_viable=NOW + 500)
        self.assertEqual(compute_next_viable(s, NOW), NOW + 500)

    def test_takes_max(self):
        s = RateLimitState(last_attempt=NOW, last_retry_after=60,
                           consecutive_failures=2)  # backoff 240
        self.assertEqual(compute_next_viable(s, NOW), NOW + 240)

    def test_quota_exhaustion_uses_long_pause(self):
        # 3+ fallos consecutivos: la pausa es la larga (6 h), no el backoff.
        s = RateLimitState(last_attempt=NOW, last_retry_after=60,
                           consecutive_failures=QUOTA_EXHAUSTION_THRESHOLD)
        self.assertEqual(compute_next_viable(s, NOW), NOW + QUOTA_PAUSE)

    def test_below_quota_threshold_uses_backoff(self):
        s = RateLimitState(last_attempt=NOW, last_retry_after=60,
                           consecutive_failures=QUOTA_EXHAUSTION_THRESHOLD - 1)
        self.assertEqual(compute_next_viable(s, NOW), NOW + 240)


class TestIsViable(unittest.TestCase):
    def test_no_state_viable(self):
        self.assertTrue(is_viable(RateLimitState(), NOW))

    def test_not_viable_before(self):
        s = RateLimitState(next_viable=NOW + 100)
        self.assertFalse(is_viable(s, NOW))

    def test_viable_at_or_after(self):
        s = RateLimitState(next_viable=NOW)
        self.assertTrue(is_viable(s, NOW))
        self.assertTrue(is_viable(s, NOW + 1))


class TestRecord(unittest.TestCase):
    def test_success_resets(self):
        s = RateLimitState(consecutive_failures=5, next_viable=NOW + 900)
        record_success(s, NOW)
        self.assertEqual(s.consecutive_failures, 0)
        self.assertIsNone(s.last_retry_after)
        self.assertEqual(s.next_viable, NOW + MIN_GAP)
        self.assertIsNone(s.pause_reason)

    def test_failure_increments_and_programs(self):
        s = RateLimitState()
        record_failure(s, NOW, retry_after=60)
        self.assertEqual(s.consecutive_failures, 1)
        self.assertEqual(s.last_retry_after, 60)
        self.assertEqual(s.pause_reason, "backoff")
        self.assertGreater(s.next_viable, NOW)

    def test_failure_at_quota_threshold_marks_quota_exhaustion(self):
        s = RateLimitState(consecutive_failures=QUOTA_EXHAUSTION_THRESHOLD - 1)
        record_failure(s, NOW, retry_after=60)
        self.assertEqual(s.consecutive_failures, QUOTA_EXHAUSTION_THRESHOLD)
        self.assertEqual(s.pause_reason, "quota_exhaustion")
        self.assertEqual(s.next_viable, NOW + QUOTA_PAUSE, "pausa larga acotada")

    def test_success_clears_quota_pause(self):
        s = RateLimitState(consecutive_failures=QUOTA_EXHAUSTION_THRESHOLD,
                           pause_reason="quota_exhaustion", next_viable=NOW + QUOTA_PAUSE)
        record_success(s, NOW)
        self.assertIsNone(s.pause_reason)
        self.assertEqual(s.consecutive_failures, 0)
        self.assertTrue(is_viable(s, NOW + MIN_GAP))


class TestStatePersistence(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            s = RateLimitState(last_attempt=NOW, consecutive_failures=3,
                               next_viable=NOW + 480, last_retry_after=60)
            s.save(p)
            loaded = RateLimitState.load(p)
            self.assertEqual(loaded.last_attempt, NOW)
            self.assertEqual(loaded.consecutive_failures, 3)
            self.assertEqual(loaded.next_viable, NOW + 480)
            self.assertEqual(loaded.last_retry_after, 60)

    def test_roundtrip_with_pause_reason(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            s = RateLimitState(last_attempt=NOW, consecutive_failures=3,
                               next_viable=NOW + QUOTA_PAUSE,
                               pause_reason="quota_exhaustion")
            s.save(p)
            loaded = RateLimitState.load(p)
            self.assertEqual(loaded.pause_reason, "quota_exhaustion")

    def test_old_state_file_without_pause_reason_loads(self):
        # Compatibilidad: estados escritos antes del campo pause_reason.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            p.write_text(
                '{"last_attempt": %d, "consecutive_failures": 1, '
                '"next_viable": %d, "last_retry_after": 60}' % (NOW, NOW + 100),
                encoding="utf-8",
            )
            s = RateLimitState.load(p)
            self.assertEqual(s.consecutive_failures, 1)
            self.assertIsNone(s.pause_reason)

    def test_missing_file_clean(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(RateLimitState.load(Path(d) / "nope.json").consecutive_failures, 0)

    def test_corrupt_file_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            p.write_text("{no json", encoding="utf-8")
            self.assertEqual(RateLimitState.load(p).consecutive_failures, 0)


class FakeTransport:
    """Transport inyectable con secuencia de respuestas."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, url):
        self.calls += 1
        return self.responses.pop(0)


class TestFetch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state.json"
        self.cache = self.tmp / "page.html"
        self.url = "https://example.com/x"

    def test_not_viable_does_not_call_transport(self):
        self.state.write_text(
            '{"last_attempt": %d, "consecutive_failures": 1, '
            '"next_viable": %d, "last_retry_after": 60}' % (NOW, NOW + 500),
            encoding="utf-8",
        )
        t = FakeTransport([(200, {}, "ok")])
        r = fetch(self.url, t, self.state, self.cache, now=NOW)
        self.assertFalse(r.ok)
        self.assertIn("not_viable", r.reason)
        self.assertEqual(t.calls, 0, "no debe llamar al transport si no es viable")

    def test_success_fetches_and_caches(self):
        t = FakeTransport([(200, {}, "HTML-OK")])
        r = fetch(self.url, t, self.state, self.cache, now=NOW)
        self.assertTrue(r.ok)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body, "HTML-OK")
        self.assertFalse(r.cached)
        self.assertTrue(self.cache.is_file())
        self.assertEqual(self.cache.read_text(encoding="utf-8"), "HTML-OK")
        # estado reseteado
        self.assertEqual(RateLimitState.load(self.state).consecutive_failures, 0)

    def test_cache_hit_avoids_network(self):
        self.cache.write_text("CACHED", encoding="utf-8")
        t = FakeTransport([(200, {}, "SHOULD-NOT-RUN")])
        r = fetch(self.url, t, self.state, self.cache, now=NOW)
        self.assertTrue(r.ok)
        self.assertTrue(r.cached)
        self.assertEqual(r.body, "CACHED")
        self.assertEqual(t.calls, 0)

    def test_429_reads_retry_after_and_programs(self):
        t = FakeTransport([(429, {"retry-after": "60"}, "local_rate_limited")])
        r = fetch(self.url, t, self.state, self.cache, now=NOW)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, 429)
        self.assertEqual(r.retry_after, 60)
        s = RateLimitState.load(self.state)
        self.assertEqual(s.consecutive_failures, 1)
        self.assertEqual(s.last_retry_after, 60)
        self.assertGreaterEqual(s.next_viable, NOW + 60)

    def test_429_without_retry_after_uses_backoff(self):
        t = FakeTransport([(429, {}, "local_rate_limited")])
        r = fetch(self.url, t, self.state, self.cache, now=NOW)
        self.assertFalse(r.ok)
        self.assertIsNone(r.retry_after)
        s = RateLimitState.load(self.state)
        self.assertGreaterEqual(s.next_viable, NOW + BASE_BACKOFF)

    def test_500_uses_backoff(self):
        t = FakeTransport([(503, {}, "unavailable")])
        r = fetch(self.url, t, self.state, self.cache, now=NOW)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, 503)
        s = RateLimitState.load(self.state)
        self.assertEqual(s.consecutive_failures, 1)
        self.assertGreaterEqual(s.next_viable, NOW + BASE_BACKOFF)

    def test_repeated_429_widens_window(self):
        # Tres 429 seguidos: los INCREMENTOS entre intentos se ensanchan
        # exponencialmente (120 → 240 → 480), no un offset absoluto.
        s = RateLimitState()
        t0 = NOW
        record_failure(s, t0, 60)                       # inc 1 → 120
        t1 = s.next_viable
        record_failure(s, t1, 60)                       # inc 2 → 240
        t2 = s.next_viable
        record_failure(s, t2, 60)                       # inc 3 → 480
        inc1 = t1 - t0
        inc2 = t2 - t1
        self.assertGreaterEqual(inc1, 120)
        self.assertGreater(inc2, inc1, "el incremento debe ensancharse")
        self.assertGreaterEqual(inc2, 240)

    def test_case_insensitive_retry_after(self):
        t = FakeTransport([(429, {"Retry-After": "90"}, "x")])
        r = fetch(self.url, t, self.state, self.cache, now=NOW)
        self.assertEqual(r.retry_after, 90)


if __name__ == "__main__":
    unittest.main()
