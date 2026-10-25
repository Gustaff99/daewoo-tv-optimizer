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
3. Doble clic en el ejecutable. En Windows se abre una **ventana gráfica**
   (sin consola) con un campo para la dirección de la TV y botones:
   - **Detectar** → te dice el modelo, el sistema y qué se puede optimizar.
   - **Optimizar** → te muestra el plan y un diálogo SI/NO; solo si dices
     que sí se aplica.
   - **Restaurar** → muestra la lista y pide confirmación explícita.
   - **Ver registro** → muestra las operaciones realizadas.
   En Linux el ejecutable abre el mismo menú por consola (las opciones y la
   seguridad son idénticas: `0` sale, y se exige teclear `SI` para aplicar).
4. Listo. Cada operación queda registrada en `~/.daewoo-optimizer/ops.jsonl`
   (en el ejecutable; en modo fuente, `daewoo-optimizer-ops.jsonl`).

¿Tu modelo no está en la matriz? La herramienta lo detecta por ADB y usa un
perfil genérico conservador para su familia de sistema.

## Seguridad

Solo deshabilita apps con `pm disable-user` (nunca las borra), exige
confirmación explícita (diálogo SI/NO en la ventana, teclar `SI` en la
consola) y deja registro de todo. Sin root y sin tocar el firmware.
Detalle técnico en [`docs/`](docs/).

## Para desarrolladores

- Fuente: `cli.py` (Python 3.8+, solo stdlib) + `detect/`, `engine/`,
  `profiles/` + `ui_tk.py` (ventana gráfica, tkinter stdlib).
- Sin argumentos: se abre la GUI si hay display; si no, el menú de
  terminal; si es .exe windowed sin display, avisa y escribe
  `~/.daewoo-optimizer/gui-error.txt`.
- Tests: `python3 -m unittest discover -s tests` (316 tests).
- Construir el ejecutable: `pip install pyinstaller && python3 scripts/build_exe.py`
  (Linux, consola). Windows: `python3 scripts/build_exe.py --gui`
  (build `--windowed`, sin consola; lo hace la CI en `.github/workflows/build-exe.yml`).
  Descarga el `adb` oficial de Google si no está.
- Matriz de compatibilidad (32 modelos):
  [`docs/research/compatibility-matrix.json`](docs/research/compatibility-matrix.json).
- Validación en TV real: [`docs/validation/`](docs/validation/).
