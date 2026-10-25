"""Interfaz gráfica (tkinter) para doble clic en Windows (FASE 5.6).

El usuario final no sabe qué es una consola: al hacer doble clic en el
.exe debe verse una VENTANA con botones, no una consola que parpadea y
cierra. Esta GUI reutiliza EXACTAMENTE las mismas funciones del menú de
terminal (ui.py): la misma detección, el mismo plan dry-run, la misma
whitelist de escritura, el mismo fail-safe y el mismo log de auditoría.
La única diferencia es la capa de presentación.

Seguridad (idéntica a la CLI):
- Detectar: solo lectura.
- Optimizar: SIEMPRE muestra el plan antes y pide confirmación EXPLICITA
  (diálogo SI/NO) antes de tocar la TV.
- Restaurar: muestra la lista y pide confirmación explícita.
- Identidad no concluyente o perfil default-deny -> no se modifica nada
  (el fail-safe vive en el planner/executor, no en la interfaz).

Sin dependencias externas: tkinter es stdlib.
"""
from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable, List, Optional

import cli
import ui
from detect.adb_probe import list_adb_devices
from detect._paths import default_log_path, state_dir


def has_display() -> bool:
    """True si tkinter puede abrir una ventana (hay display disponible).

    En servidores headless o CI sin X/wayland esto devuelve False y la
    entrada cae al menú de terminal (o al fallo elegante si no hay
    consola).
    """
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def fallback_log_path() -> str:
    """Donde escribir errores cuando no hay consola ni display.

    En el home (state_dir): en .exe windowed el CWD no es fiable.
    """
    return str(state_dir() / "gui-error.txt")


def _answer_to_input(confirmed: bool) -> str:
    """Mapeo diálogo -> valor del input_fn compatible con ui.confirm_si."""
    return "si" if confirmed else ""


class ConfirmBridge:
    """Puente worker-thread -> main-thread para confirmaciones.

    ui.do_optimize / ui.do_restore piden confirmación llamando a un
    input_fn() DESDE EL HILo de trabajo. tkinter solo puede mostrarse
    desde el hilo principal, por lo que el worker deposita la petición
    en una cola y bloquea; el bucle de la UI (root.after) muestra el
    diálogo SI/NO y desbloquea con la respuesta.
    """

    def __init__(self, root) -> None:
        self._root = root
        self._requests: "queue.Queue[None]" = queue.Queue()
        self._answer: Optional[bool] = None
        self._gate = threading.Event()

    def input_fn(self) -> str:
        """Se pasa como input_fn a las funciones de ui.py (desde worker)."""
        self._answer = None
        self._gate.clear()
        self._requests.put(None)
        self._gate.wait()
        return _answer_to_input(self._answer is True)

    def poll(self) -> None:
        """Se invoca desde el bucle de la UI (hilo principal)."""
        try:
            while True:
                self._requests.get_nowait()
                import tkinter.messagebox as mb

                ok = mb.askyesno(
                    "Confirmación",
                    "¿Confirmas esta operación en la TV?\n\n"
                    "Es reversible con 'Restaurar', pero afecta a la TV\n"
                    "hasta que la reviertas.",
                )
                self._answer = ok
                self._gate.set()
        except queue.Empty:
            pass


class _TextBuffer:
    """Captura stdout/stderr del worker y lo volca al widget de texto."""

    def __init__(self, root, text_widget) -> None:
        self._root = root
        self._text = text_widget
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._tail = ""

    def write(self, s: str) -> int:
        if s:
            self._pending.put(s)
        return len(s)

    def flush(self) -> None:  # compatible con io.TextIOBase
        pass

    def poll(self) -> None:
        chunks: List[str] = []
        try:
            while True:
                chunks.append(self._pending.get_nowait())
        except queue.Empty:
            pass
        if not chunks:
            return
        joined = "".join(chunks)
        # Mantener solo el final: no queremos crecer sin límite.
        self._tail = (self._tail + joined)[-20000:]
        self._text.configure(state="normal")
        self._text.insert("end", joined)
        self._text.see("end")
        self._text.configure(state="disabled")


class App:
    """Ventana principal: campo de dispositivo + botones + registro."""

    def __init__(self, root) -> None:
        # tkinter solo se importa aquí: has_display() ya garantizó que
        # hay display (el import en cabecera rompería entornos headless).
        import tkinter as tk
        from tkinter import ttk

        self._root = root
        root.title("Daewoo TV Optimizer")
        root.geometry("760x540")
        self._log = default_log_path()

        top = root
        top.grid_columnconfigure(0, weight=1)
        top.grid_rowconfigure(2, weight=1)

        row_dev = tk.Frame(top)
        row_dev.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        row_dev.grid_columnconfigure(1, weight=1)

        ttk.Label(row_dev, text="TV (IP:puerto):").grid(row=0, column=0, sticky="w")
        self._dev_var = tk.StringVar()
        self._dev_entry = ttk.Entry(row_dev, textvariable=self._dev_var, width=30)
        self._dev_entry.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(row_dev, text="Detectar TVs", command=self._detect_devices).grid(
            row=0, column=2
        )

        row_btn = ttk.Frame(top)
        row_btn.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        self._btn_detect = ttk.Button(row_btn, text="1) Detectar la tele")
        self._btn_detect.grid(row=0, column=0, padx=4)
        self._btn_opt = ttk.Button(row_btn, text="2) Optimizar")
        self._btn_opt.grid(row=0, column=1, padx=4)
        self._btn_restore = ttk.Button(row_btn, text="3) Restaurar")
        self._btn_restore.grid(row=0, column=2, padx=4)
        self._btn_status = ttk.Button(row_btn, text="4) Ver registro")
        self._btn_status.grid(row=0, column=3, padx=4)
        ttk.Button(row_btn, text="Salir", command=root.destroy).grid(
            row=0, column=4, padx=4
        )

        self._text = tk.Text(top, state="disabled", wrap="word",
                             font=("TkFixedFont",))
        self._text.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 8))
        sb = ttk.Scrollbar(top, command=self._text.yview)
        sb.grid(row=2, column=1, sticky="ns", pady=(4, 8), padx=(0, 8))
        self._text.configure(yscrollcommand=sb.set)

        self._bridge = ConfirmBridge(root)
        self._buffer = _TextBuffer(root, self._text)
        self._busy = False

        self._btn_detect.configure(command=self._run_detect)
        self._btn_opt.configure(command=self._run_optimize)
        self._btn_restore.configure(command=self._run_restore)
        self._btn_status.configure(command=self._run_status)

        self.log("Daewoo TV Optimizer — escribe la IP:puerto de la TV "
                 "(o pulsa 'Detectar TVs') y elige una opción.")
        self._root.after(100, self._poll)

    # ------------------------------------------------------------- helpers
    def log(self, msg: str) -> None:
        self._buffer.write(msg + "\n")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self._btn_detect, self._btn_opt, self._btn_restore,
                  self._btn_status):
            b.configure(state=state)

    def _poll(self) -> None:
        if not self._busy:
            self._buffer.poll()
            self._bridge.poll()
        self._root.after(100, self._poll)

    def _resolve_device(self) -> Optional[str]:
        raw = self._dev_var.get().strip()
        if raw:
            return raw
        devices = list_adb_devices()
        if len(devices) == 1:
            self.log(f"TV encontrada automáticamente: {devices[0]}")
            self._dev_var.set(devices[0])
            return devices[0]
        if devices:
            self.log("Varias TVs conectadas; escribe la IP:puerto a usar:")
            for d in devices:
                self.log(f"  - {d}")
        else:
            self.log(
                "No se ha encontrado ninguna TV por ADB.\n"
                "  1. TV: Ajustes > Sistema > Información > pulsar 7 veces "
                "'Número de versión'.\n"
                "  2. TV: Opciones de desarrollador > 'Depuración ADB' = ON.\n"
                "  3. TV y PC en la misma red WiFi.\n"
                "  4. Escribe aquí la IP de la TV (Ajustes > Red) y "
                "pulsa 'Detectar la tele'."
            )
        return None

    # --------------------------------------------------------------- acciones
    def _spawn(self, fn: Callable[[], int]) -> None:
        """Ejecuta fn en un worker con stdout/stderr redirigidos al widget."""
        self._set_busy(True)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = self._buffer
        sys.stderr = self._buffer

        def _worker() -> None:
            code = 0
            try:
                code = fn()
            except Exception:
                # Fail-safe: nunca crashear la ventana; mostrar el error.
                self._buffer.write("\nERROR: " + traceback.format_exc() + "\n")
                code = 1
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                # Vuelta al hilo principal para desbloquear la UI.
                self._root.after(0, self._set_busy, False)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_detect(self) -> None:
        device = self._resolve_device()
        if not device:
            return
        probe = cli.ReadProbeRunner()

        def _fn() -> int:
            return ui.do_detect(device, probe, out=self.log)

        self._spawn(_fn)

    def _run_optimize(self) -> None:
        device = self._resolve_device()
        if not device:
            return
        probe = cli.ReadProbeRunner()
        runner = cli.AdbActionRunner()

        def _fn() -> int:
            return ui.do_optimize(
                device, probe, runner,
                input_fn=self._bridge.input_fn,
                log=self._log, out=self.log,
            )

        self._spawn(_fn)

    def _run_restore(self) -> None:
        device = self._resolve_device()
        if not device:
            return
        runner = cli.AdbActionRunner()

        def _fn() -> int:
            return ui.do_restore(
                device, runner,
                input_fn=self._bridge.input_fn,
                log=self._log, out=self.log,
            )

        self._spawn(_fn)

    def _run_status(self) -> None:
        def _fn() -> int:
            return ui.do_status(log=self._log, out=self.log)

        self._spawn(_fn)

    def _detect_devices(self) -> None:
        devices = list_adb_devices()
        if not devices:
            self.log("No hay TVs conectadas por ADB ahora mismo.")
            return
        self.log("TVs conectadas por ADB:")
        for d in devices:
            self.log(f"  - {d}")
        self._dev_var.set(devices[0])


def run() -> int:
    """Punto de entrada de la GUI. Devuelve el exit code del proceso."""
    import tkinter as tk

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
