"""Parser de fichas de producto Daewoo: detección de SO y specs clave (FASE 1).

Principio: **solo reporta lo que aparece literalmente en el HTML**, con el
snippet de evidencia. Nunca inventar SO.

Jerarquía de evidencia (importante, aprendida de la página real de
daewooelectronics.com, tienda Shopify):

1. **Campo explícito** «Sistema operativo: X» en la ficha técnica → autoridad
   única.
   - X = SO smart conocido (Android TV, Google TV, VIDAA, …) → `verified` high.
   - X = negación («No inteligente», «non smart», «not a smart tv», …) →
     `verified` high con valor `non_smart` (dato positivo: el TV NO es smart;
     no hay paquetes que deshabilitar).
   - X = valor no reconocido → `pending_verification` (NO se sobreescribe con
     menciones de navegación).
2. **Mención en el texto** (media confianza): solo si NO hay campo
   explícito, y solo dentro de la *región de especificaciones* (ventana que
   cubre los campos tipo «Tamaño de pantalla:», «Resolución:», …). Si no hay
   región identificable, se busca en el texto completo (fixtures minimalistas).
   La navegación del sitio (categorías «SMART TV / Android TV / VIDAA / TiVO»)
   queda fuera de la región → no produce falsos positivos.

`smart_tv` es tri-estado: True / False / None (sin evidencia).

Solo stdlib. Determinista. Testable sin red (se pasa el HTML).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# Nombres de SO/plataforma smart (mayúsculas-insensibles).
OS_PATTERNS = [
    ("android_tv", re.compile(r"android\s*tv", re.I)),
    ("google_tv", re.compile(r"google\s*tv", re.I)),
    ("vidaa", re.compile(r"vidaa", re.I)),
    ("tizen", re.compile(r"tizen", re.I)),
    ("webos", re.compile(r"webos", re.I)),
    ("linux", re.compile(r"\blinux\b", re.I)),
]

# Campos de la ficha técnica que se reconocen (clave → alternancia de nombres).
# El lookbehind (?<![:\"']) descarta el diccionario de etiquetas JS de la
# tienda («"Operating System":"Sistema operativo"») donde la clave va
# precedida por comillas, no por espacio.
SPEC_FIELD_DEFS = [
    ("os", r"sistema\s+operativo|operating\s+system"),
    ("screen_size", r"tamaño\s+de\s+pantalla|screen\s+size"),
    ("resolution", r"resolución|resolution"),
    ("panel", r"tecnología\s+de\s+pantalla|display\s+technology"),
]
_KEYS_ALT = "|".join(key_re for _, key_re in SPEC_FIELD_DEFS)
# La terminación del valor de un campo es: la siguiente clave conocida,
# un salto de línea, o fin de texto.
_NEXT_KEY_LA = r"(?=\s*(?:" + _KEYS_ALT + r")\s*[:\-]?(?:\s|$))"

SMART_TV_RE = re.compile(r"smart\s*tv", re.I)
SMART_TV_NEGATIONS = {"no", "not", "sin", "without", "nein", "non"}
# Palabras que pueden interponerse entre la negación y «smart tv» sin romperla.
SMART_TV_FILLERS = {
    "es", "is", "was", "were", "zijn",            # copulas
    "a", "an", "the", "el", "la", "un", "una", "de", "du",  # artículos/prep.
}

# Otros specs numéricos de interés (clave → patrón con grupo de captura).
SPEC_PATTERNS = {
    "ram_gb": re.compile(
        r"(\d+(?:[.,]\d+)?)\s*(?:gb|gib)\b\s*(?:de\s*)?"
        r"(?:memoria\s*(?:ram|de\s*memoria)?|ram)", re.I),
    "storage_gb": re.compile(
        r"(\d+(?:[.,]\d+)?)\s*(?:gb|gib)\b\s*(?:de\s*)?"
        r"(?:almacenamiento|memoria\s*interna|storage)", re.I),
}


@dataclass
class SpecFinding:
    key: str
    value: str
    evidence: str
    confidence: str  # high | medium


@dataclass
class ParseResult:
    os_value: Optional[str] = None
    os_status: str = "pending_verification"  # verified | pending_verification
    os_confidence: str = "none"
    os_evidence: str = ""
    specs: list = field(default_factory=list)      # ram_gb / storage_gb
    fields: Dict[str, SpecFinding] = field(default_factory=dict)  # ficha técnica
    has_smart_tv: Optional[bool] = None            # True | False | None (sin evidencia)
    smart_tv_evidence: str = ""
    html_len: int = 0


def strip_tags(page_html: str) -> str:
    """Elimina tags HTML y colapsa espacios (conserva el texto visible)."""
    text = re.sub(r"<[^>]+>", " ", page_html)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text)


def _snippet(text: str, start: int, end: int, radius: int = 80) -> str:
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    return text[a:b].strip()


def _find_smart_tv(text: str) -> Optional[re.Match]:
    """Busca «smart tv» descartando menciones negadas («no es smart tv»)."""
    for m in SMART_TV_RE.finditer(text):
        prefix = text[max(0, m.start() - 40):m.start()]
        words = [w.lower() for w in re.findall(r"[\w']+", prefix)]
        # Negación si, en las últimas 4 palabras, hay una negación y todo lo
        # que va después (hasta «smart tv») son palabras de relleno.
        negated = False
        for i in range(len(words) - 1, max(len(words) - 5, -1), -1):
            w = words[i]
            if w in SMART_TV_NEGATIONS:
                negated = True
                break
            if w not in SMART_TV_FILLERS:
                break  # palabra sustantiva de por medio: no es negación
        if negated:
            continue
        return m
    return None


def _is_non_smart(value: str) -> bool:
    """¿El valor del campo de SO es una negación («No inteligente»,
    «non smart tv», «not a smart tv», «sin smart tv»…)?

    Criterio: hay una palabra de negación y, a corta distancia (≤12 chars),
    «smart» o «inteligente». Determinista y conservador.
    """
    v = " " + re.sub(r"[^\w\s]", " ", value.lower()) + " "
    neg = re.search(r"\b(no|non|not|sin)\b", v)
    pos = re.search(r"\b(smart|inteligente)\b", v)
    if not neg or not pos:
        return False
    return neg.start() <= pos.start() and (pos.start() - neg.end()) <= 12


def _find_spec_fields(text: str) -> Dict[str, Tuple[str, int, int]]:
    """Localiza los campos de la ficha técnica en el texto sin tags.

    Devuelve {clave: (valor, start, end)} usando la PRIMERA ocurrencia válida
    de cada clave (con lookbehind anti-diccionario-JS).
    """
    found: Dict[str, Tuple[str, int, int]] = {}
    for key, key_re in SPEC_FIELD_DEFS:
        pat = re.compile(
            r"(?<![:\"'])\s*(?:" + key_re + r")\s*[:\-]?\s*(.+?)(?:"
            + _NEXT_KEY_LA + r"|\n|$)",
            re.I | re.S,
        )
        m = pat.search(text)
        if m:
            found[key] = (m.group(1).strip().strip(".,;: "), m.start(), m.end())
    return found


def parse_spec_page(page_html: str) -> ParseResult:
    """Analiza el HTML de una ficha y extrae SO + specs con evidencia."""
    res = ParseResult(html_len=len(page_html))
    text = strip_tags(page_html)

    fields = _find_spec_fields(text)
    for key, (val, s, e) in fields.items():
        res.fields[key] = SpecFinding(
            key=key, value=val, evidence=_snippet(text, s, e), confidence="high"
        )

    # Región de especificaciones: ventana que cubre todos los campos hallados.
    if fields:
        region = (max(0, min(s for _, s, _ in fields.values()) - 200),
                  min(len(text), max(e for _, _, e in fields.values()) + 100))
        region_text = text[region[0]:region[1]]
    else:
        region_text = text  # sin región identificable → texto completo

    os_field = fields.get("os")
    if os_field:
        raw_val = os_field[0]
        smart = next(
            ((name, pat) for name, pat in OS_PATTERNS if pat.search(raw_val)),
            None,
        )
        if smart:
            res.os_value, res.os_status, res.os_confidence = smart[0], "verified", "high"
            res.has_smart_tv = True
        elif _is_non_smart(raw_val):
            # Dato positivo verificado: el TV NO es smart.
            res.os_value, res.os_status, res.os_confidence = "non_smart", "verified", "high"
            res.has_smart_tv = False
        else:
            # Campo presente con valor no reconocido: NO inventar y NO
            # sobreescribir con menciones de navegación.
            res.os_value = None
            res.os_status = "pending_verification"
            res.os_confidence = "none"
            res.os_evidence = (
                "Campo «sistema operativo» presente con valor no reconocido: "
                + repr(raw_val)
            )
        if not res.os_evidence:
            res.os_evidence = _snippet(text, os_field[1], os_field[2])
    else:
        # 2) Mención en el texto (media confianza): solo sin campo explícito,
        #    y limitada a la región de especificaciones cuando existe.
        best = None
        for os_name, pattern in OS_PATTERNS:
            mm = pattern.search(region_text)
            if mm and (best is None or mm.start() < best[1]):
                best = (os_name, mm.start(), mm.end())
        if best:
            os_name, s, e = best
            res.os_value = os_name
            res.os_status = "verified"
            res.os_confidence = "medium"
            res.os_evidence = _snippet(region_text, s, e)
            res.has_smart_tv = True
        else:
            sm = _find_smart_tv(region_text)
            res.has_smart_tv = bool(sm) if sm else (
                False if SMART_TV_RE.search(region_text) else None
            )
            if sm:
                res.smart_tv_evidence = _snippet(region_text, sm.start(), sm.end())

    if res.has_smart_tv is not None and not res.smart_tv_evidence and os_field:
        res.smart_tv_evidence = _snippet(text, os_field[1], os_field[2])

    # 4) Specs numéricos (RAM/almacenamiento) — solo con evidencia
    for key, pattern in SPEC_PATTERNS.items():
        for mm in pattern.finditer(region_text):
            val = mm.group(1).replace(",", ".")
            try:
                val_f = float(val)
            except ValueError:
                continue
            ok = (0.5 <= val_f <= 64) if key == "ram_gb" else (1 <= val_f <= 512)
            if ok:
                res.specs.append(SpecFinding(
                    key=key,
                    value=str(val_f),
                    evidence=_snippet(region_text, mm.start(), mm.end()),
                    confidence="medium",
                ))
                break  # una vez por spec

    return res


def merge_into_model_matrix_entry(model_entry: dict, page_html: str) -> dict:
    """Actualiza una entrada de la matriz con el parse de su ficha.

    Devuelve la entrada actualizada. Solo toca campos con evidencia real.
    """
    p = parse_spec_page(page_html)
    entry = dict(model_entry)
    entry["os"] = {
        "value": p.os_value,
        "status": p.os_status,
        "source": f"ficha {model_entry.get('slug')} (HTML parseado)",
        "confidence": p.os_confidence,
        "evidence": p.os_evidence[:300] if p.os_evidence else None,
    }
    if p.has_smart_tv is not None:
        entry["smart_tv"] = {
            "value": p.has_smart_tv,
            "evidence": (p.smart_tv_evidence or p.os_evidence or "")[:200],
        }
    if p.os_value == "non_smart":
        entry["optimization"] = {
            "status": "not_applicable",
            "reason": (
                "Televisor no inteligente según ficha oficial: no hay paquetes "
                "que deshabilitar (fuera de alcance del optimizador)."
            ),
        }
    parsed = {
        k: {"value": v.value, "evidence": v.evidence[:200]}
        for k, v in p.fields.items() if k != "os" and v.value
    }
    if parsed:
        entry["specs"] = dict(entry.get("specs", {}))
        entry["specs"]["parsed_from_page"] = parsed
    if p.specs:
        entry["specs"] = dict(entry.get("specs", {}))
        entry["specs"]["parsed_from_page"] = dict(
            entry["specs"].get("parsed_from_page", {})
        )
        entry["specs"]["parsed_from_page"].update(
            {s.key: {"value": s.value, "evidence": s.evidence[:200]}
             for s in p.specs}
        )
    return entry
