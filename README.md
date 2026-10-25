# Daewoo TV Optimizer

Herramienta de identificación y optimización **segura y reversible** para
televisores Daewoo (Europa/España). Pensada para un usuario sin conocimientos
técnicos avanzados: detecta el modelo y el sistema, propone una lista
conservadora de aplicaciones preinstaladas que se pueden deshabilitar, y todo
es **reversible** con un solo comando.

## Principios no negociables

1. **Fail-safe:** ante incertidumbre, no se modifica nada. Sin
   identificación concluyente → perfil `unsupported/default` → 0 acciones.
2. **Dry-run por defecto.** Toda acción requiere confirmación explícita.
3. **Reversible:** solo deshabilitación (`pm disable-user --user 0`), nunca
   eliminación; inventario inicial + restauración garantizada.
4. **Sin root, sin exploits, sin flash de firmware, sin bypass de bootlock.**
5. **El USB no es un dispositivo de firmware:** no contiene ni imita
   actualizaciones de sistema.
6. **Nunca por marca:** "Daewoo" no implica plataforma. La gama europea usa
   Android TV, Google TV, Android TV AOSP (sin certificar Google), VIDAA y TiVO.
7. **Whitelist estricto de escritura:** la única capa que toca un TV solo
   entiende `pm disable-user --user 0 <pkg>` y `pm enable --user 0 <pkg>`;
   sin shell (argv fijo).

## Requisitos

- **Python 3.8+** (solo biblioteca estándar, sin dependencias externas).
- **ADB** para hablar con el TV. Dos opciones:
  - Tu PC ya tiene `adb` en el `PATH` (la herramienta lo detecta), o
  - Descarga [Android platform-tools](https://developer.android.com/tools/releases/platform-tools)
    de Google y añade `adb` a tu `PATH`. Este repositorio **no** distribuye
    binarios de terceros.
- El TV con **Depuración USB / ADB** activada (modo desarrollador) y en la
  misma red que el PC.

> Nota: la construcción de la memoria USB autocontenida (`scripts/build_usb.py`)
> sí empaqueta `adb` en `vendor/platform-tools/adb`; esa carpeta es salida de
> build y no se versiona en este repositorio.

## Uso

```bash
# Tests (no tocan ningún dispositivo)
python3 -m unittest discover -s tests          # 303 tests (8 se saltan sin el binario adb descargable)

# RECOMENDADO: menu interactivo en español (detectar/optimizar/restaurar)
python3 cli.py gui
# → detecta modelo, SO y bloatware por ti; muestra el plan ANTES de
#   confirmar; para optimizar/restaurar hay que teclear "SI".

# Identificar sin dispositivo
python3 cli.py identify --model 55DM75QV --os "VIDAA"
# → perfil proprietary/vidaa, actions_allowed=false, no concluyente

# Identificar con ADB (solo lectura)
python3 cli.py probe --device 192.168.1.50:5555

# Dry-run: qué SE HARÍA (no toca nada). La lista de candidatos se detecta
# sola contra los paquetes reales del TV (modelos nuevos incluidos).
python3 cli.py plan --device 192.168.1.50:5555

# Ejecutar (ÚNICO path de modificación: exige --confirm + identidad concluyente).
python3 cli.py apply --device 192.168.1.50:5555 --confirm

# Restaurar todo / ver el registro
python3 cli.py restore --device 192.168.1.50:5555
python3 cli.py report
```

`apply` sin `--confirm` → exit 2. Con perfil sin acciones → 0 acciones.
Con identidad no concluyente → 0 acciones. Todo verificado por tests.

### Modelos nuevos (fuera de la matriz de 32)

La herramienta los admite sin nombres de paquetes manuales: detecta la
familia de SO por ADB, usa el perfil genérico de esa familia y propone una
lista conservadora de bloatware filtrada contra los paquetes reales del
dispositivo. Los componentes esenciales (launcher, ajustes, red, framework)
protege una red dura en el código (`CORE_EXCLUSIONS`), independiente de
perfiles. El plan siempre se muestra antes de confirmar y todo es
reversible con `restaurar`.

## Estructura

```
cli.py             # CLI (solo stdlib): identify/probe/plan/apply/restore/report/gui
ui.py              # menú interactivo en español (doble confirmación)
detect/            # identidad SO-primero + ADB solo lectura + entrada manual + perfiles
engine/            # planner (dry-run) + executor (whitelist) + inventory + audit log
profiles/          # android-tv/ google-tv/ aosp-tv/ proprietary/ unsupported/
scripts/           # investigación (fetch/parse/matriz) + build de USB
docs/              # investigación, matriz de compatibilidad, validación
tests/             # 303 tests
```

## Investigación y matriz de compatibilidad

La gama Daewoo europea se investigó contra fuentes oficiales. La matriz
resultante (32 modelos DE/DM, SO por modelo) vive en
`docs/research/compatibility-matrix.json` y se documenta en
`docs/research/01-models-and-os.md`. Los scripts de `scripts/` reproducen el
proceso (fetch incremental con limitador de cuota, parser de fichas, ingesta
local sin red, reconstrucción de matriz). La evidencia cruda de las capturas
de web no se publica en este repositorio.

## Validación en TV física

El ciclo completo se validó sobre un TV real (D43DM55UQPMS, Android 11 AOSP,
Vestel/MediaTek, familia `aosp-uncertified`): `apply --confirm` 7/7, métricas
antes/después, `restore` 7/7 verificado contra el backup, y re-aplicación
permanente. Comparativa en `docs/validation/FASE7-comparativa-2026-10-25.md`.

## Seguridad

Ver `docs/validation-checklist.md` para el modelo de seguridad completo.
Resumen: whitelist estricto de escritura (argv fijo, sin shell), dry-run por
defecto, reversibilidad garantizada, sin root ni firmware, y fail-safe ante
cualquier incertidumbre.
