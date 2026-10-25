"""Tests para scripts/parse_spec_page.py y scripts/build_matrix.py.

Sin red: se inyecta HTML de fixture. Cubren detección de SO (alta/media
confianza), no-inventar SO, specs con evidencia, y generador de matriz.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parse_spec_page import (  # noqa: E402
    merge_into_model_matrix_entry,
    parse_spec_page,
)
from scripts.build_matrix import build_matrix, parse_slug  # noqa: E402

HTML_ANDROID_FIELD = """
<html><body>
<table>
<tr><td>Sistema operativo</td><td>Android TV 11</td></tr>
<tr><td>Memoria</td><td>2 GB de memoria RAM</td></tr>
<tr><td>Almacenamiento</td><td>16 GB de almacenamiento</td></tr>
</table>
<p>Televisor Smart TV de 50 pulgadas.</p>
</body></html>
"""

HTML_VIDAA_TEXT = """
<html><body>
<p>Disfruta de tu contenido con VIDAA U, la plataforma de smart tv.</p>
</body></html>
"""

HTML_GOOGLE_TV = """
<html><body>
<p>Controla tu tele con Google TV. Compatible con asistentes de voz.</p>
</body></html>
"""

HTML_NO_OS = """
<html><body>
<p>Televisor LED de 32 pulgadas con sintonizador DVB-T2.</p>
<p>No es smart tv: solo reproducción USB.</p>
</body></html>
"""

HTML_UNKNOWN_OS_VALUE = """
<html><body>
<table>
<tr><td>Sistema operativo</td><td>Propietario-X 3.0</td></tr>
</table>
</body></html>
"""

HTML_429_BODY = "local_rate_limited"


class TestParseSpecPage(unittest.TestCase):
    def test_android_tv_explicit_field_high_confidence(self):
        p = parse_spec_page(HTML_ANDROID_FIELD)
        self.assertEqual(p.os_value, "android_tv")
        self.assertEqual(p.os_status, "verified")
        self.assertEqual(p.os_confidence, "high")
        self.assertIn("Android TV 11", p.os_evidence)

    def test_vidaa_mention_medium_confidence(self):
        p = parse_spec_page(HTML_VIDAA_TEXT)
        self.assertEqual(p.os_value, "vidaa")
        self.assertEqual(p.os_status, "verified")
        self.assertEqual(p.os_confidence, "medium")

    def test_google_tv(self):
        p = parse_spec_page(HTML_GOOGLE_TV)
        self.assertEqual(p.os_value, "google_tv")
        self.assertEqual(p.os_confidence, "medium")

    def test_no_os_never_invented(self):
        p = parse_spec_page(HTML_NO_OS)
        self.assertIsNone(p.os_value)
        self.assertEqual(p.os_status, "pending_verification")
        self.assertEqual(p.os_confidence, "none")

    def test_unknown_os_value_not_invented(self):
        p = parse_spec_page(HTML_UNKNOWN_OS_VALUE)
        self.assertIsNone(p.os_value)
        self.assertEqual(p.os_status, "pending_verification")
        self.assertIn("Propietario-X", p.os_evidence)

    def test_rate_limit_body_is_not_a_page(self):
        p = parse_spec_page(HTML_429_BODY)
        self.assertIsNone(p.os_value)
        self.assertEqual(p.os_status, "pending_verification")

    def test_specs_with_evidence(self):
        p = parse_spec_page(HTML_ANDROID_FIELD)
        keys = {s.key: s.value for s in p.specs}
        self.assertEqual(keys.get("ram_gb"), "2.0")
        self.assertEqual(keys.get("storage_gb"), "16.0")
        for s in p.specs:
            self.assertTrue(s.evidence)
            self.assertEqual(s.confidence, "medium")

    def test_smart_tv_flag(self):
        self.assertTrue(parse_spec_page(HTML_ANDROID_FIELD).has_smart_tv)
        self.assertFalse(parse_spec_page(HTML_NO_OS).has_smart_tv)

    def test_smart_tv_negation_with_copula(self):
        # «is not a smart tv» también es negación (copula intermedia)
        html_doc = "<p>This set is not a smart tv, only USB playback.</p>"
        self.assertFalse(parse_spec_page(html_doc).has_smart_tv)

    def test_smart_tv_affirmative_still_detected(self):
        html_doc = "<p>It is a smart tv with built-in apps.</p>"
        self.assertTrue(parse_spec_page(html_doc).has_smart_tv)

    def test_empty_html_safe(self):
        p = parse_spec_page("")
        self.assertIsNone(p.os_value)
        self.assertEqual(p.os_status, "pending_verification")

    def test_merge_into_model_entry(self):
        entry = {"slug": "50dm65qv-50uhd-qled-tv", "os": {"value": None}}
        out = merge_into_model_matrix_entry(entry, HTML_ANDROID_FIELD)
        self.assertEqual(out["os"]["value"], "android_tv")
        self.assertEqual(out["os"]["status"], "verified")
        self.assertIn("parsed_from_page", out["specs"])
        # la entrada original no muta
        self.assertIsNone(entry["os"]["value"])


class TestParseSlug(unittest.TestCase):
    def test_qled_50_uhd(self):
        d = parse_slug("50dm65qv-50uhd-qled-tv")
        self.assertEqual(d["size_inch"], 50)
        self.assertEqual(d["panel"], "qled")
        self.assertEqual(d["res_class"], "uhd")

    def test_dled_32_hd(self):
        d = parse_slug("32dm64ha-hd-dled-tv")
        self.assertEqual(d["size_inch"], 32)
        self.assertEqual(d["panel"], "dled")
        self.assertEqual(d["res_class"], "hd")

    def test_fhd_40(self):
        d = parse_slug("40dm63fa-40fhd-dled-tv")
        self.assertEqual(d["size_inch"], 40)
        self.assertEqual(d["res_class"], "fhd")
        self.assertEqual(d["panel"], "dled")

    def test_qled_priority_over_dled(self):
        d = parse_slug("40dm95qv-40-fhd-qled-tv")
        self.assertEqual(d["panel"], "qled")

    def test_unparseable_safe(self):
        d = parse_slug("televisor-x")
        self.assertIsNone(d["size_inch"])
        self.assertIsNone(d["panel"])
        self.assertIsNone(d["res_class"])


HTML_SHOP_NAV_NONSMART = """
<html><body>
<nav>Productos TELEVISION SMART TV Android TV Google TV VIDAA TiVO NON-SMART TV</nav>
<div class="accordion__content rte">
<p><ul>
<li><strong>Tamaño de pantalla:</strong> 32</li>
<li><strong>Resolución:</strong> HD</li>
<li><strong>Tecnología de pantalla:</strong> DLED</li>
<li><strong>Sistema operativo:</strong> No inteligente</li>
</ul></p>
</div>
</body></html>
"""

HTML_SHOP_NAV_ANDROID = """
<html><body>
<nav>Productos SMART TV Android TV Google TV VIDAA TiVO</nav>
<div class="accordion__content rte">
<p><ul>
<li><strong>Tamaño de pantalla:</strong> 43</li>
<li><strong>Resolución:</strong> UHD</li>
<li><strong>Sistema operativo:</strong> Android TV</li>
</ul></p>
</div>
</body></html>
"""

HTML_SHOP_NAV_UNKNOWN = """
<html><body>
<nav>Productos SMART TV Android TV Google TV VIDAA TiVO</nav>
<div class="accordion__content rte">
<p><ul>
<li><strong>Tamaño de pantalla:</strong> 32</li>
<li><strong>Sistema operativo:</strong> Propietario-X</li>
</ul></p>
</div>
</body></html>
"""


class TestShopPagePitfalls(unittest.TestCase):
    """Trampas de la tienda real (Shopify): navegación con nombres de SO,
    diccionario de etiquetas JS, y valores de negación del campo de SO."""

    def test_nav_mention_does_not_override_non_smart_field(self):
        # La navegación menciona «Android TV» pero la ficha dice «No inteligente»
        p = parse_spec_page(HTML_SHOP_NAV_NONSMART)
        self.assertEqual(p.os_value, "non_smart")
        self.assertEqual(p.os_status, "verified")
        self.assertEqual(p.os_confidence, "high")
        self.assertFalse(p.has_smart_tv)
        self.assertIn("No inteligente", p.os_evidence)

    def test_field_beats_nav_for_smart_os(self):
        p = parse_spec_page(HTML_SHOP_NAV_ANDROID)
        self.assertEqual(p.os_value, "android_tv")
        self.assertEqual(p.os_confidence, "high")
        self.assertTrue(p.has_smart_tv)

    def test_unrecognized_field_not_overridden_by_nav(self):
        p = parse_spec_page(HTML_SHOP_NAV_UNKNOWN)
        self.assertIsNone(p.os_value)
        self.assertEqual(p.os_status, "pending_verification")
        self.assertIn("Propietario-X", p.os_evidence)

    def test_merge_non_smart_marks_optimization_not_applicable(self):
        entry = merge_into_model_matrix_entry(
            {"slug": "32de15hl-dled-tv", "specs": {}}, HTML_SHOP_NAV_NONSMART
        )
        self.assertEqual(entry["os"]["value"], "non_smart")
        self.assertFalse(entry["smart_tv"]["value"])
        self.assertEqual(entry["optimization"]["status"], "not_applicable")
        self.assertEqual(entry["specs"]["parsed_from_page"]["resolution"]["value"], "HD")
        self.assertEqual(entry["specs"]["parsed_from_page"]["panel"]["value"], "DLED")


class TestGoldenRealPage(unittest.TestCase):
    """Golden-file de regresión contra la PRIMERA página real descargada
    (daewooelectronics.com, Shopify; commit a22a5e8). Es la prueba de fuego
    del parser: HTML de 300 KB con navegación que menciona TODOS los SO que
    la tienda vende (Android TV, Google TV, VIDAA, TiVO) + diccionario JS de
    etiquetas. El campo de la ficha dice «Sistema operativo: No inteligente»
    → el resultado debe ser non_smart/verified/high, NUNCA un SO inventado.
    """

    REAL_PAGE = Path(__file__).resolve().parent.parent / \
        "docs/research/fetch/pages/32de15hl-dled-tv.html"

    @unittest.skipIf(
        not REAL_PAGE.is_file(),
        "ficha real no presente en este checkout",
    )
    def _parse(self):
        return parse_spec_page(self.REAL_PAGE.read_text(encoding="utf-8"))

    def test_os_is_non_smart_verified_high(self):
        p = self._parse()
        self.assertEqual(p.os_value, "non_smart")
        self.assertEqual(p.os_status, "verified")
        self.assertEqual(p.os_confidence, "high")
        self.assertIn("No inteligente", p.os_evidence)

    def test_smart_tv_is_false_not_none(self):
        p = self._parse()
        self.assertIs(p.has_smart_tv, False)

    def test_navigation_os_names_do_not_leak(self):
        # La navegación menciona Android TV / Google TV / VIDAA / TiVO.
        # Ninguno de ellos puede aparecer como SO del modelo.
        p = self._parse()
        self.assertNotIn(p.os_value, ("android_tv", "google_tv", "vidaa", "tizen", "linux"))

    def test_spec_fields_extracted_with_evidence(self):
        p = self._parse()
        self.assertEqual(p.fields["os"].value, "No inteligente")
        self.assertEqual(p.fields["screen_size"].value, "32")
        self.assertEqual(p.fields["resolution"].value, "HD")
        self.assertEqual(p.fields["panel"].value, "DLED")
        for f in p.fields.values():
            self.assertEqual(f.confidence, "high")
            self.assertTrue(f.evidence, "cada campo debe llevar evidencia")

    def test_merge_into_matrix_entry_not_applicable(self):
        entry = merge_into_model_matrix_entry(
            {"slug": "32de15hl-dled-tv", "specs": {}},
            self.REAL_PAGE.read_text(encoding="utf-8"),
        )
        self.assertEqual(entry["os"]["value"], "non_smart")
        self.assertEqual(entry["os"]["status"], "verified")
        self.assertFalse(entry["smart_tv"]["value"])
        self.assertEqual(entry["optimization"]["status"], "not_applicable")


class TestBuildMatrix(unittest.TestCase):
    def test_matrix_structure_and_no_invented_os(self):
        m = build_matrix(now_iso="2026-10-24T15:00:00Z")
        self.assertEqual(m["model_count"], 32)
        self.assertEqual(len(m["models"]), 32)
        for entry in m["models"]:
            # Invariante «no inventar»: sin evidencia no hay valor; con valor
            # hay que haberlo verificado con evidencia.
            if entry["os"]["value"] is not None:
                self.assertEqual(entry["os"]["status"], "verified")
                self.assertTrue(entry["os"]["evidence"])
            else:
                self.assertIn(
                    entry["os"]["status"],
                    ("pending_verification", "pending_parse"),
                )
            self.assertTrue(entry["verified_in_sitemap"],
                            "cada URL del catálogo debe estar en el sitemap")
            self.assertIn(entry["specs"]["provenance"],
                          ("derived_from_slug", "eprel_fiche+slug"))
            # Invariante: specs EPREL (si existen) conservan provenance propia
            # y el SO sigue sin inventarse.
            if "eprel_fiche" in entry["specs"]:
                self.assertEqual(
                    entry["specs"]["eprel_fiche"]["provenance"], "eprel_fiche")
        self.assertEqual(m["generated_at"], "2026-10-24T15:00:00Z")

    def test_matrix_json_serializable(self):
        m = build_matrix()
        s = json.dumps(m, ensure_ascii=False)
        self.assertIsInstance(s, str)

    def test_merge_cached_page_into_matrix(self):
        import tempfile
        import scripts.build_matrix as bm

        fixture = ("<html><body><table><tr><td>Sistema operativo</td>"
                   "<td>Android TV 11</td></tr></table>"
                   "<p>Smart TV de 50 pulgadas.</p></body></html>")
        with tempfile.TemporaryDirectory() as d:
            pages = Path(d)
            pages.mkdir(exist_ok=True)
            (pages / "50dm65qv-50uhd-qled-tv.html").write_text(fixture, encoding="utf-8")
            original = bm.PAGES_DIR
            bm.PAGES_DIR = pages
            try:
                # os_evidence={} aísla el comportamiento de cache/merge del de
                # fuentes fetchables (que ahora verifica 55DM75QV, etc.).
                m = build_matrix(merge_cached=True, os_evidence={})
            finally:
                bm.PAGES_DIR = original

        target = next(x for x in m["models"] if x["slug"] == "50dm65qv-50uhd-qled-tv")
        self.assertEqual(target["os"]["value"], "android_tv")
        self.assertEqual(target["os"]["status"], "verified")
        self.assertEqual(target["os"]["confidence"], "high")
        self.assertTrue(target["smart_tv"]["value"])
        # los demás modelos siguen pendientes (no se inventa)
        others = [x for x in m["models"] if x["slug"] != "50dm65qv-50uhd-qled-tv"]
        self.assertTrue(all(x["os"]["status"] == "pending_verification" for x in others))

    def test_no_merge_keeps_all_pending(self):
        # os_evidence={} aísla: sin cache ni fuentes, todo os.value es None.
        m = build_matrix(merge_cached=False, os_evidence={})
        self.assertTrue(all(x["os"]["value"] is None for x in m["models"]))

    def test_os_evidence_direct_verified(self):
        # Coincidencia de modelo EXACTO con fuente explícita -> verified.
        ev = {"55DM75QV": [{"os": "vidaa", "source_name": "markandbuy",
                            "source_url": "https://x/55dm75qv",
                            "evidence_snippet": "Smart TV, Vidaa", "retrieved_at": "t"}]}
        m = build_matrix(merge_cached=False, os_evidence=ev)
        t = next(x for x in m["models"] if x["slug"].startswith("55dm75qv"))
        self.assertEqual(t["os"]["value"], "vidaa")
        self.assertEqual(t["os"]["status"], "verified")
        self.assertEqual(t["os"]["confidence"], "high")
        self.assertIn("markandbuy", t["os"]["source"])

    def test_os_evidence_sibling_is_hypothesis_not_assigned(self):
        # Hermano de la MISMA serie -> solo series_hypothesis (no os.value).
        ev = {"32DM65QV": [{"os": "android", "source_name": "markandbuy",
                            "source_url": "https://x/32dm65qv",
                            "evidence_snippet": "Android", "retrieved_at": "t"}]}
        m = build_matrix(merge_cached=False, os_evidence=ev)
        t = next(x for x in m["models"] if x["slug"].startswith("43dm65qv"))
        # no se asigna el SO del hermano
        self.assertIsNone(t["os"]["value"])
        self.assertEqual(t["os"]["status"], "pending_verification")
        self.assertEqual(t["os"]["series_hypothesis"]["value"], "android")
        self.assertEqual(t["os"]["series_hypothesis"]["based_on_models"], ["32DM65QV"])

    def test_os_evidence_web_index_normalization_and_provenance(self):
        # Evidencia de índice web: 'Android TV' se normaliza a 'android_tv'
        # y la provenance de cita (no fetch fresco) se conserva.
        ev = {"32DM64HA": [{"os": "android tv", "source_name": "daewooelectronics.com (oficial, vía índice web)",
                            "source_url": "https://www.daewooelectronics.com/x/daewoo-32dm64ha-hd-dled-tv",
                            "evidence_snippet": "Operating System: Android TV",
                            "retrieved_at": "2026-10-25",
                            "provenance": "web_index: cita de página oficial exacta; no fetch HTTP fresco"}]}
        m = build_matrix(merge_cached=False, os_evidence=ev)
        t = next(x for x in m["models"] if x["slug"].startswith("32dm64ha"))
        self.assertEqual(t["os"]["value"], "android_tv")
        self.assertEqual(t["os"]["status"], "verified")
        self.assertEqual(t["os"]["confidence"], "high")
        self.assertIn("web_index", t["os"]["provenance"])
        self.assertIn("32dm64ha", t["os"]["source_urls"][0])

    def test_os_evidence_non_smart_hyphen_normalization(self):
        # La tienda oficial .es usa product_type='Non-smart' (guión).
        ev = {"32DE15HL": [{"os": "Non-smart", "source_name": "daewooelectronics.es (oficial, products.json)",
                            "source_url": "https://www.daewooelectronics.es/products/x",
                            "evidence_snippet": 'product_type="Non-smart"',
                            "retrieved_at": "2026-10-25",
                            "provenance": "official: fetch HTTP 200 fresco de products.json"}]}
        m = build_matrix(merge_cached=False, os_evidence=ev)
        t = next(x for x in m["models"] if x["slug"].startswith("32de15hl"))
        self.assertEqual(t["os"]["value"], "non_smart")
        self.assertEqual(t["os"]["status"], "verified")

    def test_os_evidence_series_contradiction_not_hypothesis(self):
        # Misma serie con SOs distintos verificados (32DM65QV=android,
        # 43DM65QV=vidaa) -> la serie NO es clasificador: sin hipótesis,
        # se registra series_contradiction en los hermanos pendientes.
        ev = {
            "32DM65QV": [{"os": "android", "source_name": "markandbuy",
                          "source_url": "https://x/32dm65qv",
                          "evidence_snippet": "Android", "retrieved_at": "t"}],
            "43DM65QV": [{"os": "vidaa", "source_name": "daewooelectronics.com (oficial, vía índice web)",
                          "source_url": "https://www.daewooelectronics.com/x/daewoo-43dm65qv-uhd-qled-tv",
                          "evidence_snippet": "Operating System: VIDAA",
                          "retrieved_at": "t",
                          "provenance": "web_index: cita de página oficial exacta; no fetch HTTP fresco"}],
        }
        m = build_matrix(merge_cached=False, os_evidence=ev)
        t43 = next(x for x in m["models"] if x["slug"].startswith("43dm65qv"))
        self.assertEqual(t43["os"]["value"], "vidaa")
        self.assertEqual(t43["os"]["status"], "verified")
        for pref in ("50dm65qv", "55dm65qv"):
            sib = next(x for x in m["models"] if x["slug"].startswith(pref))
            self.assertIsNone(sib["os"]["value"])
            self.assertEqual(sib["os"]["status"], "pending_verification")
            self.assertNotIn("series_hypothesis", sib["os"])
            self.assertIn("series_contradiction", sib["os"])
            self.assertEqual(sib["os"]["series_contradiction"]["values"],
                             ["android", "vidaa"])
            self.assertIn("32DM65QV", sib["os"]["series_contradiction"]["based_on_models"])
            self.assertIn("43DM65QV", sib["os"]["series_contradiction"]["based_on_models"])

    def test_os_evidence_single_series_still_hypothesis(self):
        # Serie con UN solo SO verificado -> hipótesis (comportamiento previo).
        ev = {"55DM75QV": [{"os": "vidaa", "source_name": "markandbuy",
                           "source_url": "https://x/55dm75qv",
                           "evidence_snippet": "Vidaa", "retrieved_at": "t"}]}
        m = build_matrix(merge_cached=False, os_evidence=ev)
        t = next(x for x in m["models"] if x["slug"].startswith("43dm75qv"))
        self.assertIsNone(t["os"]["value"])
        self.assertEqual(t["os"]["series_hypothesis"]["value"], "vidaa")

    def test_os_evidence_no_cross_series_leak(self):
        # VB56QV no debe heredar el SO de DM65QV (series distintas).
        ev = {"32DM65QV": [{"os": "android", "source_name": "markandbuy",
                            "source_url": "https://x/32dm65qv",
                            "evidence_snippet": "Android", "retrieved_at": "t"}]}
        m = build_matrix(merge_cached=False, os_evidence=ev)
        t = next(x for x in m["models"] if x["slug"].startswith("43dm56qv"))
        self.assertNotIn("series_hypothesis", t["os"])
        self.assertIsNone(t["os"]["value"])

    def test_merged_real_pages_only_verify_with_evidence(self):
        # Con las fichas cacheadas reales: los modelos verificados (smart o
        # non_smart) tienen evidencia; el resto sigue pending.
        m = build_matrix(merge_cached=True)
        verified = [x for x in m["models"] if x["os"]["value"] is not None]
        for x in verified:
            self.assertEqual(x["os"]["status"], "verified")
            self.assertTrue(x["os"]["evidence"])
            self.assertIn(x["os"]["value"],
                          ("android_tv", "android", "google_tv", "vidaa",
                           "tivo", "tizen", "webos", "linux", "non_smart"))
        pending = [x for x in m["models"] if x["os"]["value"] is None]
        self.assertTrue(all(x["os"]["status"] == "pending_verification"
                            for x in pending))
        # 1 ficha descargada en este entorno → al menos 1 verificado
        self.assertGreaterEqual(len(verified), 1)


if __name__ == "__main__":
    unittest.main()
