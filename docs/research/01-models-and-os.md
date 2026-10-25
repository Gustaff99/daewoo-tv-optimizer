# FASE 1 — Modelos y SO (investigación, reconstrucción tras pérdida de workspace)

> Reescrito el 2026-10-24 tras la 3ª pérdida del workspace en tmpfs.
> Todos los hechos proceden del registro de la sesión de Paperclip (issue MIS-9).
> Lo que no se pueda verificar vuelve a marcarse como pendiente, no se inventa.

## Operador de la marca en Europa

- La marca "Daewoo" en Europa **no** es el antiguo fabricante coreano (hoy Winia Electronics).
- Operador EU identificado en la tienda oficial: "Daewoo Electronics SA Ltd".
- **Pendiente:** verificación en registro mercantil (sin acceso verificado todavía).

## Plataformas / SO de la gama europea (fuente: tienda oficial daewooelectronics.com)

La gama europea vende **4 SO distintos**: **Android TV, Google TV, VIDAA y TiVO**.
Conclusión de arquitectura: la marca no implica plataforma; el detector debe
resolver el SO antes que el modelo.

## Modelos verificados (iteración 1, fuentes retail/ficha)

| Modelo | SO | Fuente | Confianza |
|---|---|---|---|
| 55DM75QV | VIDAA | Ficha oficial (55" QLED, sin BT, USB×2, DVB-T2/C/S2) | Alta |
| D55DM54UAMSX | Android TV | Retail | Media (pendiente ficha oficial; gama anterior) |
| 24DM54HA2K | Android TV | Retail | Media (id.) |
| 50DM60UA | Android TV | Retail | Media (id.) |
| DW32S / DW43S (India) | "Android 11.1" AOSP custom sin certificación Google | Retail India | Media (no es Android TV) |

## Catálogo activo (iteración 3, re-verificado vía sitemap ES, 2026-10-24)

- **32 modelos de TV** en el catálogo activo español (familias **DE/DM**, 32–65").
  Lista completa recuperada y cacheada a disco (sobrevive al tmpfs):
  - `docs/research/fetch/daewoo-tv-models.txt` (32 handles)
  - `docs/research/fetch/daewoo-tv-models-urls.tsv` (handle → URL oficial ES)
  - `docs/research/fetch/sitemap-2026-10-24.xml`, `sitemap-es-products-2026-10-24.xml`
    (evidencia cruda)
- Catálogo ES = 316 productos de todas las categorías (lavadoras, lavavajillas,
  TVs…); los 32 se filtran por el patrón de modelo `[2-7][0-9](DE|DM)`.
- Rate-limit: hay un **limitador LOCAL del entorno** (cuerpo de respuesta de
  18 bytes: `local_rate_limited`), NO del servidor Daewoo. Modelo empírico
  (evidencia en `docs/research/fetch/pages/32de15hl-dled-tv.429.txt`):
  - 235 s entre peticiones exitosas → OK.
  - 284–318 s entre intentos (contando los fallidos) → 429.
  - La ventana se reinicia en **cada intento** (exito o fallo); ventana
    efectiva ≥318 s (no descartable 600 s).
  - **Regla de run: 1 fetch/run, solo si han pasado ≥600 s desde el último
    intento**; registrar cada intento en el archivo de evidencia.
- Los modelos de la iteración 1 (D55DM54UAMSX, 24DM54HA2K, 50DM60UA) **no** están
  en el catálogo activo = gama anterior.
- 55DM75QV (VIDAA, verificado ficha oficial) **sí** está en el catálogo activo
  (`55dm75qv-55uhd-qled-tv`) → coherencia entre iteraciones.

## SO por modelo — evidencia de fuentes fetchables (2026-10-24)

Directiva del operador (21:25Z): **sin esperas de cuota; usar otras fuentes**.
Se probó el panorama de fuentes desde esta IP (evidencia en `docs/research/fetch/`):

| Fuente | Estado | Aportación |
|---|---|---|
| **markandbuy.com** | ✅ fetchable (API de catálogo, sin Cloudflare) | 7 modelos Daewoo con SO explícito |
| daewooelectronics.com | ❌ rate-limit local (18 B `local_rate_limited`) | solo 1 ficha cacheada (32DE15HL) |
| EPREL (api.ec.europa.eu) | ❌ búsqueda exige token; PDF sin campo SO ni nº registro | specs físicas solo |
| buscadores (DDG/Bing/Mojeek/Brave/Qwant/Searx) | ❌ IP marcada como botnet (202/403/429) | no sirven para descubrir fichas |
| retailers (pccomponentes/carrefour/kitele/…) | ❌ Cloudflare 403 / SSL / 404 | inaccesibles |
| daewooelectronics.pt/.it/.fr | ❌ DNS no resuelve | no existen |

**Fuente productiva: markandbuy.com** (`POST /api/catalog/brand/get-products`,
brand=6232 + página de producto directa). Dato explícito de SO en la descripción.
Evidencia cruda: `docs/research/fetch/os-evidence/markandbuy.json`.

### Estado del SO para los 32 modelos (matriz `compatibility-matrix.json`)

- **Verificado (2/32):**
  - `32DE15HL` = **non_smart** (ficha HTML parseada, no es Smart TV).
  - `55DM75QV` = **VIDAA** (markandbuy, dato explícito + ficha oficial).
- **Hipótesis por serie (5, NO asignadas — requieren ficha del modelo exacto):**
  - `43DM65QV`, `50DM65QV`, `55DM65QV` → **Android** (hermano `32DM65QV`=Android en markandbuy).
  - `43DM75QV`, `50DM75QV` → **VIDAA** (hermano `55DM75QV`=VIDAA, verificado).
- **Pendiente (25/32):** sin fuente explícita alcanzable desde esta IP.

> Regla de integridad: un SO heredado de un hermano de la serie se registra como
> `series_hypothesis` (no como `os.value`). Solo una ficha del modelo exacto con
> dato explícito lo convierte en `verified`. No se infiere ni se inventa.

## Pendientes FASE 1

1. **SO de los 25 modelos pendientes**: requieren una fuente fetchable (no
   Cloudflare, no bloqueada por IP). El operador puede indicar una (retailer,
   manual, ficha) o desbloquear la IP en DuckDuckGo; entonces el batch
   (`scripts/research_os_search.py`) recoge el dato por modelo.
2. Confirmar las 5 hipótesis por serie con la ficha del modelo exacto.
3. Enumeración de la colección `android-tv` (URL de colección pendiente).
4. Registro mercantil del operador EU.
