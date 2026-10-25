# Daewoo TV Optimizer

Detecta tu televisor Daewoo y deshabilita (sin borrar) los programas que lo
ralentizan. Todo es **reversible**: con un paso devuelves el TV a como estaba.
Si la herramienta no reconoce tu TV, no hace nada.

## Uso (2 minutos)

1. Descarga el ejecutable desde [Releases](https://github.com/Gustaff99/daewoo-tv-optimizer/releases)
   (`daewoo-tv-optimizer.exe` en Windows, `daewoo-tv-optimizer` en Linux)
   y cópialo a una memoria USB. No instala nada y no necesita Python.
2. En el TV: activa **"Depuración USB"** (modo desarrollador) y ponlo en la
   misma red WiFi que tu PC.
3. Doble clic en el ejecutable. Se abre un menú en español:
   - **Detectar** → te dice el modelo, el sistema y qué se puede optimizar.
   - **Optimizar** → te muestra el plan; para aplicar hay que teclear `SI`.
   - **Restaurar** → devuelve todo a como estaba.
4. Listo. Cada operación queda registrada en `daewoo-optimizer-ops.jsonl`
   (se crea junto al ejecutable).

¿Tu modelo no está en la matriz? La herramienta lo detecta por ADB y usa un
perfil genérico conservador para su familia de sistema.

## Seguridad

Solo deshabilita apps con `pm disable-user` (nunca las borra), exige
confirmación y deja registro de todo. Sin root y sin tocar el firmware.
Detalle técnico en [`docs/`](docs/).

## Para desarrolladores

- Fuente: `cli.py` (Python 3.8+, solo stdlib) + `detect/`, `engine/`, `profiles/`.
- Tests: `python3 -m unittest discover -s tests` (303 tests).
- Construir el ejecutable: `pip install pyinstaller && python3 scripts/build_exe.py`
  (descarga el `adb` oficial de Google si no está).
- Matriz de compatibilidad (32 modelos):
  [`docs/research/compatibility-matrix.json`](docs/research/compatibility-matrix.json).
- Validación en TV real: [`docs/validation/`](docs/validation/).
