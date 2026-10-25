# Estado de validación (FASE 7) — 2026-10-25

Resumen automatizado (antes de la TV física): 258/258 tests, matriz
32/32 SO verificado con fuente oficial, USB construida con manifiesto
SHA-256 (incluye `adb` en `vendor/platform-tools/adb`).

## 1. TV física — ENTREGADA

- Modelo: **D43DM55UQPMS** (etiqueta; `ro.product.model` es genérico:
  "Android TV"). NO está en el catálogo ES de la matriz (32 modelos);
  queda registrado en `on_device_models` de
  `docs/research/compatibility-matrix.json` y en el perfil
  `profiles/aosp-tv/daewoo-d43dm55uqpms.json`.
- Identidad real (ADB, 2026-10-25): Android 11 (API 30),
  fingerprint `My/EMIR/shandao:11/RTM3.211215.317/8963041:user/release-keys`
  (OEM Vestel, chipset MediaTek). Familia: **aosp-uncertified**
  (Android TV AOSP sin plataforma certificada de Google TV: no hay
  `com.google.tv` ni Play Store).
- Resolución de perfil: `aosp-tv/daewoo-d43dm55uqpms` vía
  `adb_match` (prefix del fingerprint), NO por el nombre comercial:
  el modelo de etiqueta no aparece en getprop.

## 2. Métricas ANTES (colectadas 2026-10-25, solo lectura)

Ver `docs/validation/FASE7-before-2026-10-25.txt`:

- 4 núcleos, 1.8 GB RAM, swap 512 MB **99 % usado**.
- **Load average 72.36** (saturado), 399 tareas, 8 zombis, muchos
  hilos en estado D (E/S).
- `dumpsys meminfo`: "Service dumps disabled due to **hung system
  process**".
- **/data al 99 %** (74 MB libres de 4 GB). Uptime 9 días.

Lectura: el TV tiene un problema de almacenamiento/salud del sistema
que limita el impacto medible de deshabilitar 7 paquetes de usuario.
Para una comparación antes/después justa conviene un reinicio del TV
(acción del operador; la herramienta no reinicia el dispositivo).

## 3. Plan dry-run — VERIFICADO en el TV

`python3 cli.py plan --device 192.168.1.130:5555` genera 7 acciones
reversibles (`pm disable-user --user 0`), cada una con su comando de
restauración y `state_before`. Ninguna acción toca paquetes de
sistema, launcher, framework ni OEM.

## 4. Autorización explícita (bloqueante para `apply`)

- La herramienta **no modifica nada** sin `apply --confirm`.
- Pendiente: autorización del operador, vista la sección 2 (estado
  degradado del TV) y la sección 3 (plan).
- Opcional recomendado antes del `apply`: reinicio del TV para que
  las métricas "después" sean comparables.

## 5. Métricas DESPUÉS (pendientes de `apply` + reinicio)

1. Tiempo de arranque (encendido → launcher listo).
2. Tiempo de respuesta del launcher.
3. Memoria disponible (`adb shell cat /proc/meminfo`).
4. Almacenamiento disponible (`adb shell df /data`).
5. Tiempo de apertura de 2-3 aplicaciones habituales.
6. Estabilidad general (24-48 h de uso normal).

`report` muestra el registro de operaciones y cómo restaurar.

## 6. Criterio de cierre

La misión no se marca `done` sin: (a) `apply` autorizado y ejecutado,
(b) métricas después comparables, (c) restauración probada
(`restore`), o (d) una decisión expresa del operador de cerrar con lo
entregado hasta ahora.
