# FASE 1 — Eliminación sistemática de fuentes alternativas para el SO

Fecha: 2026-10-24 (~22:20Z). Run post-adaptador.

## Contexto

El operador (comentario `4d4ae2ca`): **"dejate de delays, no tienes ninguna
pausa de cuota, busca la info de otras fuentes."**

El sitio oficial `daewooelectronics.com` devuelve `HTTP 429` con cuerpo
`local_rate_limited` de forma **sostenida** (>1 h). Ese 429 proviene del
**proxy saliente (egres por dominio)**, no del servidor remoto, y mi
`fetch_ratelimit.py` lo amplificó en una pausa de 6 h (`quota_exhaustion`,
que es una heurística, NO una cuota confirmada). El operador confirma que no
hay pausa de cuota real.

Objetivo de este run: **agotar las fuentes alternativas** que sí pueden dar el
campo de SO para los **30 modelos pendientes**, sin martillear el dominio
oficial.

## Estado de la matriz (antes y después)

- Total: **32** modelos
- Verificados: **2** (32DE15HL=non_smart, 55DM75QV=VIDAA)
- Hipótesis de serie: **5** (DM65QV→Android, DM75QV→VIDAA)
- Pendientes de SO: **30**

Este run **no añade SO verificado** (las fuentes alternativas no llevan estos
modelos concretos con campo de SO). Añade **evidencia negativa** reproducible.

## Fuentes probadas en este run (evidencia)

| Fuente | Resultado | Evidencia |
|---|---|---|
| **Amazon.es** (batch 10 modelos) | 200 real, **0 TV exactas** | `os-search/amazon-*.json`: solo mandos + serie VB56/DM65QV. El modelo concreto NO aparece como TV. |
| **Amazon.de** | 200 pero `bm-verify` (bot-challenge, 2254 B) | `probe_alt_sources.py` |
| **idealo.de** | 404 (no indexa / JS-gated) | `probe_alt_sources.py` |
| **geizhals.de** | 404 | probe inline |
| **pccomponentes.es** | 403 / 404 | probe inline |
| **coolmod.es** | URLError | probe inline |
| **markandbuy.com** | agotado (6 modelos, ninguno pendiente) | `os-evidence/markandbuy.json` |
| **manualslib / manualmind / idbsoft** | 403 / 404 / DNS | `probe_manuals.py` |
| **manualsplus / everycircuit** | 200 pero **no llevan estos modelos** (recientes 2024-26) | `probe_manuals.py` |
| **Bing** | 200 pero **resultados basura** (bot-detection: devuelve Google Maps) | `research_bing.py`, `bing-search/40DM62FA.json` |
| **EPREL (fichas del operador)** | specs de pantalla/energía, **SIN campo de SO** | `eprel-pdf-specs.json` (30 fichas) |
| **Oficial (Shopify)** | **429 `local_rate_limited` sostenido** | 5 sondas este run, todas 429 |

## Conclusión (evidencia, no inferencia)

Ninguna fuente alternativa **fetchable** lleva los 30 modelos pendientes con un
campo de SO explícito. El campo de SO de estos modelos **solo está en el sitio
oficial Shopify**, que está **limitado por egres por dominio** (429 sostenido).

Los mandos de repuesto que SÍ aparecen en Amazon.es (40DM63FA, 32DM85HV, etc.)
**confirman que los modelos son TVs Daewoo reales vendidas en la UE**, pero no
dan el SO.

## Desbloqueo concreto (sin delay)

El camino más rápido, coherente con "sin delays", es el **mismo patrón que el
operador ya usó para las fichas EPREL**:

1. **El operador descarga localmente** (Ctrl+S → "Página web, solo HTML",
   nombrando por **slug**) las **30 páginas de producto** pendientes de
   `daewooelectronics.com` y las entrega como carpeta o `.zip`.
2. Este repo ya tiene el pipeline `scripts/ingest_local_pages.py` (probado con
   las fichas EPREL) que las integra **sin tocar la red**, pasa por
   `parse_spec_page` y marca el SO `verified` **solo con evidencia real**.

Alternativa (sin intervención humana): el límite de egres por dominio del
proxy saliente se despeje. Sonda limpia: `GET /products.json?limit=250`
(1 petición trae los 32 productos con body_html → SO de todos a la vez).

## No se infiere

- No se asigna `os.value` a ninguno de los 30 por patrón de serie, resolución
  (1366x768→"no smart") ni nombre. Todo queda `pending_verification`.
- La heurística "HD 1366x768 → no smart" es plausible pero **no se registra**
  como SO sin evidencia explícita.
