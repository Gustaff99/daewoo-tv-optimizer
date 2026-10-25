"""Tests del pipeline fetch→parse→matriz (scripts/fetch_and_merge.py).

Ningún test toca la red: transport inyectable + rutas patcheadas a tmp.
Cobertura:
- fetch exitoso → cache + matriz con SO verificado (evidencia real)
- 429 → para en el primer fallo (no martillear)
- not_viable → para sin llamar al transport
- cache hit → no toca la red
- limit respeta el máximo de fichas por run
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.fetch_and_merge as fam  # noqa: E402
from scripts.fetch_page import FetchResult  # noqa: E402

HTML_ANDROID = ("<html><body><table>"
                "<tr><td>Sistema operativo</td><td>Android TV 11</td></tr>"
                "</table><p>Smart TV de 50 pulgadas.</p></body></html>")
HTML_VIDAA = ("<html><body><p>Plataforma VIDAA con apps incluidas.</p>"
              "</body></html>")

CATALOG = (
    "32de15hl-dled-tv\thttps://x.test/es/products/daewoo-32de15hl-dled-tv\n"
    "50dm65qv-50uhd-qled-tv\thttps://x.test/es/products/daewoo-50dm65qv-50uhd-qled-tv\n"
)


class FakeTransport:
    def __init__(self, responses):
        # responses: dict url → (status, headers, body) o lista ordenada
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if isinstance(self.responses, dict):
            return self.responses[url]
        return self.responses.pop(0)


class AdvancingClock:
    """Reloj fake que avanza `step` s por llamada (respetar MIN_GAP=30s)."""

    def __init__(self, t: float = 1_000_000.0, step: float = 31.0):
        self.t = t
        self.step = step

    def __call__(self) -> float:
        v = self.t
        self.t += self.step
        return v


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pages = self.tmp / "pages"
        self.pages.mkdir()
        self.catalog = self.tmp / "catalog.tsv"
        self.catalog.write_text(CATALOG, encoding="utf-8")
        self.matrix_path = self.tmp / "matrix.json"
        self.state = self.tmp / "ratelimit-state.json"

        # Patcheamos los nombres bindados en fetch_and_merge.
        self._orig = (fam.CATALOG_TSV, fam.PAGES_DIR, fam.MATRIX_PATH)
        fam.CATALOG_TSV = self.catalog
        fam.PAGES_DIR = self.pages
        fam.MATRIX_PATH = self.matrix_path
        # Aisla el directorio de evidencia SO real: este test mide la
        # mecánica del pipeline (HTML fetch → parse → matriz), no la
        # evidencia oficial .es (que verifica los 32 modelos de verdad).
        import scripts.build_matrix as bm
        self._evdir = self.tmp / "os-evidence"
        self._evdir.mkdir()
        self._orig_evdir = bm.OS_EVIDENCE_DIR
        bm.OS_EVIDENCE_DIR = self._evdir

    def tearDown(self):
        fam.CATALOG_TSV, fam.PAGES_DIR, fam.MATRIX_PATH = self._orig
        import scripts.build_matrix as bm
        bm.OS_EVIDENCE_DIR = self._orig_evdir

    def _run(self, transport, limit=3, **kw):
        kw.setdefault("now_fn", AdvancingClock())
        return fam.run_pipeline(limit=limit, state_path=self.state,
                                transport=transport, **kw)

    def test_success_fetches_caches_and_verifies_os(self):
        t = FakeTransport({
            "https://x.test/es/products/daewoo-32de15hl-dled-tv":
                (200, {}, HTML_ANDROID),
            "https://x.test/es/products/daewoo-50dm65qv-50uhd-qled-tv":
                (200, {}, HTML_VIDAA),
        })
        rep = self._run(t)
        self.assertEqual(len(rep.fetched), 2)
        self.assertEqual(len(t.calls), 2)
        # HTML cacheado en disco
        self.assertTrue((self.pages / "32de15hl-dled-tv.html").is_file())
        # Matriz reconstruida con SO verificado (evidencia real, no inventada)
        self.assertIsNotNone(rep.matrix_path)
        self.assertEqual(rep.os_total, 2)
        self.assertEqual(rep.os_verified, 2)
        import json
        m = json.loads(self.matrix_path.read_text(encoding="utf-8"))
        a = next(x for x in m["models"] if x["slug"] == "32de15hl-dled-tv")
        self.assertEqual(a["os"]["value"], "android_tv")
        self.assertEqual(a["os"]["confidence"], "high")
        v = next(x for x in m["models"] if x["slug"] == "50dm65qv-50uhd-qled-tv")
        self.assertEqual(v["os"]["value"], "vidaa")

    def test_429_stops_immediately(self):
        t = FakeTransport([
            (200, {}, HTML_ANDROID),
            (429, {"retry-after": "60"}, "local_rate_limited"),
            (200, {}, HTML_VIDAA),  # NUNCA debe consumirse
        ])
        rep = self._run(t)
        self.assertEqual(len(rep.fetched), 1)
        self.assertIsNotNone(rep.rate_limited)
        self.assertEqual(len(t.calls), 2, "para tras el 429: no martillear")

    def test_not_viable_stops_without_network(self):
        # Estado con pausa futura (1h) → fetch devuelve not_viable sin red.
        clock = AdvancingClock(t=1_000_000.0, step=0.0)
        self.state.write_text(
            '{"last_attempt": %d, "consecutive_failures": 1, '
            '"next_viable": %d, "last_retry_after": 60}'
            % (1_000_000, 1_000_000 + 3600),
            encoding="utf-8",
        )
        t = FakeTransport([(200, {}, HTML_ANDROID)])
        rep = fam.run_pipeline(limit=3, state_path=self.state,
                               transport=t, now_fn=clock)
        self.assertIsNotNone(rep.not_viable_at)
        self.assertEqual(t.calls, [], "sin red si no es viable")
        self.assertEqual(len(rep.fetched), 0)

    def test_cache_hit_avoids_network(self):
        (self.pages / "32de15hl-dled-tv.html").write_text(HTML_ANDROID,
                                                          encoding="utf-8")
        (self.pages / "50dm65qv-50uhd-qled-tv.html").write_text(HTML_VIDAA,
                                                                encoding="utf-8")
        t = FakeTransport([(200, {}, "NO-USAR")])
        rep = self._run(t)
        self.assertEqual(len(rep.cache_hits), 2)
        self.assertEqual(t.calls, [])
        self.assertEqual(rep.os_verified, 2)

    def test_limit_respected(self):
        t = FakeTransport({
            "https://x.test/es/products/daewoo-32de15hl-dled-tv":
                (200, {}, HTML_ANDROID),
            "https://x.test/es/products/daewoo-50dm65qv-50uhd-qled-tv":
                (200, {}, HTML_VIDAA),
        })
        rep = self._run(t, limit=1)
        self.assertEqual(len(rep.fetched), 1)
        self.assertEqual(len(t.calls), 1)

    def test_completed_cached_pages_do_not_starve_the_next_download(self):
        (self.pages / "32de15hl-dled-tv.html").write_text(HTML_ANDROID, encoding="utf-8")
        t = FakeTransport({"https://x.test/es/products/daewoo-50dm65qv-50uhd-qled-tv":
                           (200, {}, HTML_VIDAA)})
        rep = self._run(t, limit=1)
        self.assertEqual(rep.cache_hits, ["32de15hl-dled-tv"])
        self.assertEqual(rep.fetched, ["50dm65qv-50uhd-qled-tv"])
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(rep.os_verified, 2)

    def test_no_matrix_skips_rebuild(self):
        t = FakeTransport({
            "https://x.test/es/products/daewoo-32de15hl-dled-tv":
                (200, {}, HTML_ANDROID),
        })
        rep = self._run(t, limit=1, rebuild_matrix=False)
        self.assertIsNone(rep.matrix_path)
        self.assertFalse(self.matrix_path.is_file())


class TestOldStateFormatMigration(unittest.TestCase):
    """El rate-limiter nuevo DEBE leer el estado antiguo de fetch_page.py."""

    def test_old_format_future_pause_respected(self):
        from scripts.fetch_ratelimit import PersistentRateLimiter
        import time

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            # Formato antiguo con pausa 1h en el futuro.
            p.write_text(
                '{"last_attempt": %d, "consecutive_failures": 2, '
                '"next_viable": %d, "last_retry_after": 60}'
                % (time.time(), time.time() + 3600),
                encoding="utf-8",
            )
            rl = PersistentRateLimiter(p)
            self.assertFalse(rl.should_fetch(),
                             "fail-safe: la pausa futura del formato antiguo "
                             "debe respetarse, no asumirse 0")
            self.assertGreater(rl.next_viable_at(), time.time())
            self.assertEqual(rl.state.consecutive_429, 2)

    def test_new_format_still_works(self):
        from scripts.fetch_ratelimit import PersistentRateLimiter
        import time

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            p.write_text(
                '{"next_viable_at": %d, "consecutive_429": 1, '
                '"last_429_at": %d, "total_429": 3, "total_success": 1}'
                % (time.time() + 600, time.time()),
                encoding="utf-8",
            )
            rl = PersistentRateLimiter(p)
            self.assertFalse(rl.should_fetch())
            self.assertEqual(rl.state.total_429, 3)


if __name__ == "__main__":
    unittest.main()
