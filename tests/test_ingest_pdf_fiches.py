"""Tests de la ingesta de fichas EPREL (PDF) del operador — FASE 1.

Cubre:
- parse_eprel_text: formatos EN (shopify) y ES (eprel), normalización de
  resolución con espacios, panel anclado (no absorbe la siguiente línea),
  campos ausentes.
- load_catalog_model_map: modelo → slug.
- ingest: os SIEMPRE pending_verification (no se inventa SO), modelo
  PENDIENTE sin PDF, modelo no presente en catálogo.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingest_pdf_fiches import (  # noqa: E402
    parse_eprel_text, load_catalog_model_map, ingest,
)

# Fichas EPREL de muestra (texto extraído, formatos reales observados).
EN_LCD = """
SUPPLIER'S MODEL IDENTIFIER                                    32DE73HLI
SCREEN RESOLUTION (PIXELS)                                     1366x768                   pixels
PANEL TECHNOLOGY USED                                          LCD
AUTOMATIC BRIGHTNESS CONTROL (ABC) AVAILABLE                   No
SCREEN DIAGONAL                                                80.0                       cm
SCREEN DIAGONAL                                                32                         inches
ENERGY EFFICIENCY CLASS FOR STANDARD DYNAMIC                   E
RANGE (SDR)
IMAGE REFRESH FREQUENCY RATE                                   50                         Hz
"""

ES_QLED = """
 2.   Identificador del modelo                                43DM65QV
12.   Resolución de pantalla                                   3 840   x       2 160      pixels
16.   Tecnología usada en el panel                             QLED LCD
14.   Diagonal de la pantalla                                  108,0    cm
14.   Diagonal de la pantalla                                   43   pulga-
 3.   Clase de eficiencia energética para el rango dinámi-     F
      co normal (SDR)
20.   Frecuencia de refresco de la imagen (por defecto)        50     Hz
"""


class TestParseEprelText(unittest.TestCase):
    def test_english_lcd(self):
        s = parse_eprel_text(EN_LCD)
        self.assertEqual(s["model"], "32DE73HLI")
        self.assertEqual(s["resolution"], "1366x768")
        # El panel NO absorbe la línea siguiente («AUTOMATIC…»).
        self.assertEqual(s["panel"], "LCD")
        self.assertEqual(s["screen_inch"], 32)
        self.assertEqual(s["screen_cm"], 80.0)
        self.assertEqual(s["energy_class_sdr"], "E")
        self.assertEqual(s["refresh_hz"], 50)

    def test_spanish_qled(self):
        s = parse_eprel_text(ES_QLED)
        self.assertEqual(s["model"], "43DM65QV")
        # Resolución con espacios internos normalizada.
        self.assertEqual(s["resolution"], "3840x2160")
        self.assertEqual(s["panel"], "QLED LCD")
        self.assertEqual(s["screen_inch"], 43)
        self.assertEqual(s["screen_cm"], 108.0)
        self.assertEqual(s["energy_class_sdr"], "F")
        self.assertEqual(s["refresh_hz"], 50)

    def test_missing_fields_absent(self):
        s = parse_eprel_text("texto sin campos reconocibles")
        self.assertEqual(s, {})

    def test_panel_anchored_not_greedy(self):
        # «QLED LCD» seguido de otra palabra no debe engullirla.
        txt = "PANEL TECHNOLOGY USED   QLED LCD   SOME OTHER FIELD"
        s = parse_eprel_text(txt)
        self.assertEqual(s["panel"], "QLED LCD")


class TestCatalogModelMap(unittest.TestCase):
    def test_model_to_slug(self):
        with tempfile.TemporaryDirectory() as td:
            cat = Path(td) / "cat.tsv"
            cat.write_text(
                "32de73hli-32hd-dled-tv\thttp://x/32de73hli\n"
                "50dm56qv-43-uhd-dled-tv\thttp://x/50dm56qv\n",
                encoding="utf-8",
            )
            m = load_catalog_model_map(cat)
            self.assertEqual(m["32DE73HLI"]["slug"], "32de73hli-32hd-dled-tv")
            self.assertEqual(m["50DM56QV"]["slug"], "50dm56qv-43-uhd-dled-tv")
            self.assertNotIn("99ZZZZZZ", m)


class TestIngest(unittest.TestCase):
    def _make_env(self, rows, catalog_lines):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        fuentes = root / "FUENTES.csv"
        with fuentes.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["N", "Modelo", "Estado", "Origen",
                        "URL_producto", "URL_ficha", "Archivo", "SHA256", "Detalle"])
            for r in rows:
                w.writerow(r)
        cat = root / "cat.tsv"
        cat.write_text("\n".join(catalog_lines) + "\n", encoding="utf-8")
        return root, fuentes, cat

    def test_os_never_invented_and_pending(self):
        root, fuentes, cat = self._make_env(
            rows=[
                ["1", "32DE73HLI", "OK", "shopify", "u1", "f1",
                 "Fichas/01.pdf", "abc123", "2 páginas"],
                ["2", "50DM56QV", "PENDIENTE", "missing", "u2", "", "", "",
                 "ficha incorrecta del fabricante"],
            ],
            catalog_lines=[
                "32de73hli-32hd-dled-tv\thttp://x/32de73hli",
                "50dm56qv-43-uhd-dled-tv\thttp://x/50dm56qv",
            ],
        )
        data = ingest(fuentes_csv=fuentes, pdf_dir=root, catalog_path=cat)
        # El modelo OK existe aunque el PDF no esté (extracción no disponible),
        # y su os SIEMPRE es pending_verification (no se inventa).
        ok = data["models"]["32de73hli-32hd-dled-tv"]
        self.assertEqual(ok["os"]["status"], "pending_verification")
        self.assertIsNone(ok["os"]["value"])
        # El modelo PENDIENTE aparece en pending con su causa.
        pend = [p for p in data["pending"] if p["model"] == "50DM56QV"]
        self.assertEqual(len(pend), 1)
        self.assertIn("ficha incorrecta", pend[0]["reason"])

    def test_model_not_in_catalog(self):
        root, fuentes, cat = self._make_env(
            rows=[["1", "99ZZZZZZ", "OK", "shopify", "u", "f",
                   "Fichas/x.pdf", "sha", ""]],
            catalog_lines=["32de73hli-32hd-dled-tv\thttp://x/32de73hli"],
        )
        data = ingest(fuentes_csv=fuentes, pdf_dir=root, catalog_path=cat)
        self.assertNotIn("99zzzzzz", data["models"])
        self.assertTrue(any(p["model"] == "99ZZZZZZ" for p in data["pending"]))


if __name__ == "__main__":
    unittest.main()
