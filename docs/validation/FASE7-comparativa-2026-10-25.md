# FASE 7 — COMPARATIVA ANTES / DESPUÉS DEL APPLY

Fecha: 2026-10-25 · Dispositivo: Daewoo D43DM55UQPMS (Android 11 AOSP, RTM3.211215.317)
ADB: 192.168.1.130:5555 · Perfil: aosp-tv/daewoo-d43dm55uqpms

## Acciones aplicadas (7 deshabilitaciones reversibles, `pm disable-user --user 0`)

| Paquete | Función | Estado |
|---|---|---|
| com.android.cts.ctsshim | Shim de pruebas CTS | deshabilitado |
| com.android.cts.priv.ctsshim | Shim de pruebas CTS privado | deshabilitado |
| com.apgsolutionsllc.APGSOLUTIONSLLC0007 | App OEM no identificada | deshabilitado |
| com.google.android.feedback | App de feedback de Google | deshabilitado |
| com.google.android.katniss | Reportador de errores (telemetría) | deshabilitado |
| com.google.android.play.games | Google Play Games | deshabilitado |
| fusion.android.tv.demo | App demo del OEM | deshabilitado |

Resultado apply: 7/7 ejecutados, 0 fallos (dry_run=false).
Verificación: `pm list packages -d` confirma los 7 en estado deshabilitado.

## Métricas (dumpsys meminfo + top + df)

| Métrica | ANTES (12:04, 6 min boot) | DESPUÉS (12:09, 11 min boot, post-apply) | Δ |
|---|---|---|---|
| CPU idle (top, 4 núcleos) | 361/400 (90.3 %) | 362/400 (90.5 %) | +0.2 pts (ruido) |
| RAM libre (dumpsys) | 646,515 K | 715,123 K | **+68,608 K (+67 MB)** |
| RAM usada (dumpsys) | 1,313,537 K | 1,219,751 K | **−93,786 K (−92 MB)** |
| PSS usado (apps) | 1,050,253 K | 958,583 K | **−91,670 K (−90 MB)** |
| Swap usada | 246,528 K / 511,996 K | 233,472 K / 511,996 K | **−13,056 K (−13 MB)** |
| ZRAM (físico) | 43,288 K | 39,240 K | −4,048 K |
| /data (df) | 3.8G/4.0G (99 %, 68M libres) | 3.8G/4.0G (99 %, 67M libres) | sin cambio (esperado) |
| Tareas (top) | 372 | 372 | igual |

## Interpretación

- **Mejora real y medible**: ~90 MB de PSS liberados y 13 MB menos de
  swap tras deshabilitar 7 paquetes. La RAM libre pasa de 632 a 698 MB.
- **CPU sin cambio**: los 7 paquetes no consumían CPU en reposo; la
  mejora es de memoria, no de CPU. Coherente con el tipo de bloat
  (apps inactivas en segundo plano).
- **/data sin cambio**: `pm disable-user` no borra datos ni APK; solo
  desactiva el paquete para el usuario 0. Para liberar almacenamiento
  haría falta `pm uninstall -k` (no ejecutado: fuera de alcance
  reversible simple y /data sigue al 99 % por uso general, no por
  estos paquetes).
- **Anomalía loadavg persiste** (59/53/31 en ambos capturas con CPU al
  90 % idle): confirmada como artefacto de kernel/build, no métrica
  fiable. Se usa %idle de top.
- **Estabilidad**: sin crash, sin zombies, sin OOM visible en top;
  el sistema opera en "status normal" (dumpsys).

## Limitaciones

- Ventana de medición corta (5 min entre capturas); no incluye
  tiempo de arranque ni apertura de apps (requiere medición manual
  en TV).
- La causa raíz del /data al 99 % no está en estos 7 paquetes;
  requiere análisis de ocupación (`du` en /data, apps con caches
  grandes) si el operador quiere liberar almacenamiento.
- No se ha medido tiempo de respuesta del launcher (métrica de
  FASE 7 pendiente; exige cronometrado manual en el televisor).

## Fichas de evidencia

- ANTES: `docs/validation/FASE7-before-postreboot-2026-10-25.txt`
- DESPUÉS: `docs/validation/FASE7-after-2026-10-25.txt`
- Log de auditoría: `logs/` (audit_log del apply)
