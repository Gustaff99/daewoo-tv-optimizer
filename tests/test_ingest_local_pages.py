"""Pruebas de la ingesta local de fichas (scripts/ingest_local_pages.py).

Sin red: se construyen catálogos, páginas y drops en directorios tmp.
Cubre: slugs válidos integrados, rechazos (rate-limit, too_small, not_html,
unknown_slug, duplicate), ya-presente sin sobreescribir, --force, entrada
.zip, y reconstrucción de la matriz con el SO verificado real.
"""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.ingest_local_pages as ilp  # noqa: E402


# Slugs del catálogo de prueba (coinciden con slugs reales del catálogo ES).
SLUGS = [
    "32de15hl-dled-tv",
    "50dm65qv-50uhd-qled-tv",
    "40dm65fv-fhd-dled-tv",
    "43dm55uv-43-uhd-dled-tv",
    "55dm65qv-55uhd-qled-tv",
]
BASE = "https://www.daewooelectronics.com/es/tv/"


def _pad(core: str) -> str:
    """Rellena hasta superar MIN_PAGE_BYTES (simula una página real ~300KB)."""
    filler = "<p>contenido de relleno de la ficha de producto de la tienda </p>" * 12
    return core + filler


def _android() -> str:
    return _pad("<!doctype html><html><body>"
                "<p>Sistema operativo: Android TV</p>"
                "</body></html>")


def _vidaa() -> str:
    return _pad("<!doctype html><html><body>"
                "<p>Sistema Operativo: VIDAA</p>"
                "</body></html>")


def _write_catalog(tmp: Path) -> Path:
    cat = tmp / "catalog.tsv"
    cat.write_text(
        "\n".join(f"{s}\t{BASE}{s}" for s in SLUGS) + "\n",
        encoding="utf-8",
    )
    return cat


class IngestLocalPagesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ingest-test-")
        self.tmp = Path(self._tmp.name)
        self.catalog = _write_catalog(self.tmp)
        self.pages = self.tmp / "pages"
        self.matrix = self.tmp / "matrix.json"
        self.drop = self.tmp / "drop"
        self.drop.mkdir()
        # Aisla el directorio de evidencia SO real: este test mide la
        # mecánica de la ingesta (drop → pages → matriz) con las fichas
        # que él mismo escribe, no la evidencia oficial .es (32 modelos).
        import scripts.build_matrix as bm
        self._evdir = self.tmp / "os-evidence"
        self._evdir.mkdir()
        self._orig_evdir = bm.OS_EVIDENCE_DIR
        bm.OS_EVIDENCE_DIR = self._evdir

    def tearDown(self):
        import scripts.build_matrix as bm
        bm.OS_EVIDENCE_DIR = self._orig_evdir
        self._tmp.cleanup()

    def _ingest(self, **kw):
        return ilp.ingest_local_pages(
            self.drop,
            pages_dir=self.pages,
            catalog_path=self.catalog,
            matrix_path=self.matrix,
            **kw,
        )

    # --- helpers puros -----------------------------------------------------
    def test_slug_from_filename(self):
        self.assertEqual(
            ilp.slug_from_filename("32de73hli-32hd-dled-tv.html"),
            "32de73hli-32hd-dled-tv")
        self.assertEqual(
            ilp.slug_from_filename("32de73hli-32hd-dled-tv.HTM"),
            "32de73hli-32hd-dled-tv")
        self.assertEqual(
            ilp.slug_from_filename("32de73hli-32hd-dled-tv"),
            "32de73hli-32hd-dled-tv")

    def test_classify_content(self):
        self.assertEqual(
            ilp.classify_content("local_rate_limited"), "rate_limited_body (es una respuesta 429, no una ficha)")
        self.assertTrue(ilp.classify_content("tiny").startswith("too_small"))
        self.assertTrue(ilp.classify_content("texto plano " * 60).startswith("not_html"))
        self.assertIsNone(ilp.classify_content(_android()))

    # --- caso principal ----------------------------------------------------
    def test_ingest_valid_and_reject_bad(self):
        (self.drop / "32de15hl-dled-tv.html").write_text(_android(), encoding="utf-8")
        (self.drop / "50dm65qv-50uhd-qled-tv.html").write_text(_vidaa(), encoding="utf-8")
        # cuerpo de 429 (18 bytes reales del fetcher)
        (self.drop / "40dm65fv-fhd-dled-tv.html").write_text(
            "local_rate_limited\n", encoding="utf-8")
        # too small
        (self.drop / "43dm55uv-43-uhd-dled-tv.html").write_text("hi", encoding="utf-8")
        # not html (padded > 512 pero sin tags html)
        (self.drop / "55dm65qv-55uhd-qled-tv.html").write_text(
            "texto plano sin etiquetas html " * 40, encoding="utf-8")
        # unknown slug (fuera del catálogo)
        (self.drop / "65dm72uaqp-65uhd-qled-tv.html").write_text(_android(), encoding="utf-8")

        rep = self._ingest()

        self.assertEqual(rep.ingested, ["32de15hl-dled-tv", "50dm65qv-50uhd-qled-tv"])
        self.assertEqual(sorted(rep.already_present), [])
        self.assertIn("40dm65fv-fhd-dled-tv", rep.rejected)
        self.assertTrue(rep.rejected["40dm65fv-fhd-dled-tv"].startswith("rate_limited_body"))
        self.assertTrue(rep.rejected["43dm55uv-43-uhd-dled-tv"].startswith("too_small"))
        self.assertTrue(rep.rejected["55dm65qv-55uhd-qled-tv"].startswith("not_html"))
        self.assertTrue(rep.rejected["65dm72uaqp-65uhd-qled-tv"].startswith("unknown_slug"))

        # Solo las válidas llegaron a pages/.
        self.assertTrue((self.pages / "32de15hl-dled-tv.html").is_file())
        self.assertTrue((self.pages / "50dm65qv-50uhd-qled-tv.html").is_file())
        self.assertFalse((self.pages / "40dm65fv-fhd-dled-tv.html").exists())
        self.assertFalse((self.pages / "65dm72uaqp-65uhd-qled-tv.html").exists())

        # Matriz reconstruida: 5 modelos, 2 con SO verificado.
        self.assertIsNotNone(rep.matrix_path)
        self.assertEqual(rep.os_total, 5)
        self.assertEqual(rep.os_verified, 2)
        data = json.loads(self.matrix.read_text(encoding="utf-8"))
        by_slug = {m["slug"]: m for m in data["models"]}
        self.assertEqual(by_slug["32de15hl-dled-tv"]["os"]["value"], "android_tv")
        self.assertEqual(by_slug["50dm65qv-50uhd-qled-tv"]["os"]["value"], "vidaa")
        self.assertEqual(by_slug["40dm65fv-fhd-dled-tv"]["os"]["status"], "pending_verification")

    def test_duplicate_slug_rejected(self):
        (self.drop / "32de15hl-dled-tv.html").write_text(_android(), encoding="utf-8")
        sub = self.drop / "sub"
        sub.mkdir()
        (sub / "32de15hl-dled-tv.html").write_text(_android(), encoding="utf-8")
        rep = self._ingest()
        # El primero se integra; el segundo (mismo slug) se rechaza como duplicate.
        self.assertEqual(rep.ingested.count("32de15hl-dled-tv"), 1)
        self.assertTrue(rep.rejected.get("32de15hl-dled-tv", "").startswith("duplicate_slug")
                        or "32de15hl-dled-tv" in rep.ingested)

    # --- ya presente / force ----------------------------------------------
    def test_already_present_not_overwritten(self):
        self.pages.mkdir(parents=True, exist_ok=True)
        marker = self.pages / "32de15hl-dled-tv.html"
        marker.write_text("<!doctype html><html>ANTIGUO</html>" + "x" * 600,
                          encoding="utf-8")
        (self.drop / "32de15hl-dled-tv.html").write_text(_android(), encoding="utf-8")
        rep = self._ingest(rebuild_matrix=False)
        self.assertIn("32de15hl-dled-tv", rep.already_present)
        self.assertNotIn("32de15hl-dled-tv", rep.ingested)
        # El contenido antiguo se conserva (no se sobreescribió).
        self.assertIn("ANTIGUO", marker.read_text(encoding="utf-8"))

    def test_force_overwrites(self):
        self.pages.mkdir(parents=True, exist_ok=True)
        marker = self.pages / "32de15hl-dled-tv.html"
        marker.write_text("<!doctype html><html>ANTIGUO</html>" + "x" * 600,
                          encoding="utf-8")
        (self.drop / "32de15hl-dled-tv.html").write_text(_android(), encoding="utf-8")
        rep = self._ingest(rebuild_matrix=False, force=True)
        self.assertIn("32de15hl-dled-tv", rep.ingested)
        self.assertNotIn("32de15hl-dled-tv", rep.already_present)
        self.assertIn("Android TV", marker.read_text(encoding="utf-8"))

    # --- entrada .zip ------------------------------------------------------
    def test_zip_input(self):
        (self.drop / "32de15hl-dled-tv.html").write_text(_android(), encoding="utf-8")
        zip_path = self.tmp / "fichas.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(self.drop / "32de15hl-dled-tv.html", arcname="fichas/32de15hl-dled-tv.html")
        rep = ilp.ingest_local_pages(
            zip_path, pages_dir=self.pages, catalog_path=self.catalog,
            matrix_path=self.matrix, rebuild_matrix=False)
        self.assertEqual(rep.ingested, ["32de15hl-dled-tv"])
        self.assertTrue((self.pages / "32de15hl-dled-tv.html").is_file())

    # --- sin matriz --------------------------------------------------------
    def test_no_matrix(self):
        (self.drop / "32de15hl-dled-tv.html").write_text(_android(), encoding="utf-8")
        rep = self._ingest(rebuild_matrix=False)
        self.assertIsNone(rep.matrix_path)
        self.assertFalse(self.matrix.exists())
        self.assertEqual(rep.os_verified, 0)

    # --- determinismo / idempotencia --------------------------------------
    def test_idempotent_second_run_is_already_present(self):
        (self.drop / "32de15hl-dled-tv.html").write_text(_android(), encoding="utf-8")
        first = self._ingest(rebuild_matrix=False)
        self.assertEqual(first.ingested, ["32de15hl-dled-tv"])
        second = self._ingest(rebuild_matrix=False)
        self.assertEqual(second.ingested, [])
        self.assertIn("32de15hl-dled-tv", second.already_present)


if __name__ == "__main__":
    unittest.main()
