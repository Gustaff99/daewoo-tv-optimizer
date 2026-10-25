# Matriz de compatibilidad Daewoo — v1 (reconstrucción)

Regla: solo entra un modelo con fuente. Lo no verificado = `?`.
La marca nunca implica plataforma: cada fila necesita su propia evidencia.

| Modelo | SO | HW/plataforma | Conexión/diagnóstico | Optimización real | Riesgos | Fuente | Confianza |
|---|---|---|---|---|---|---|---|
| 55DM75QV | VIDAA | QLED 55", sin BT, USB×2, DVB-T2/C/S2 | Sin ADB, sin APK | Solo ajustes nativos (sin bloatware deshabilitable) | Bajo (sin modificación) | Ficha oficial | Alta |
| D55DM54UAMSX | Android TV | `?` | ADB (pendiente verificar en hardware) | Deshabilitación reversible de bloatware (FASE 3) | Medio hasta verificar | Retail | Media |
| 24DM54HA2K | Android TV | `?` | ADB (pendiente) | Id. | Id. | Retail | Media |
| 50DM60UA | Android TV | `?` | ADB (pendiente) | Id. | Id. | Retail | Media |
| DW32S / DW43S (India) | AOSP custom "Android 11.1" sin cert. Google | `?` | ADB (pendiente) | Limitada: sin certificación Google, sin perfil Android TV | Alto (plataforma no estándar) | Retail India | Media |
| Resto catálogo activo ES (31 modelos DE/DM, 32–65"; lista cacheada en `docs/research/fetch/daewoo-tv-models.txt`) | `?` (4 SO posibles: Android TV, Google TV, VIDAA, TiVO) | `?` | `?` | `?` | `?` | Sitemap oficial ES re-verificado 2026-10-24 | Baja (pendiente ficha a ficha) |

## Mecanismos de optimización por familia de SO

- **Android TV / Google TV:** ADB solo lectura para detectar; deshabilitación
  reversible (`pm disable-user`) como mecanismo preferido; lista de exclusión de
  paquetes críticos obligatoria (arranque, launcher, ajustes, conectividad,
  remoto, multimedia/DRM/HDMI, updates). **Nada de eliminación** por defecto.
- **VIDAA / TiVO (proprietarios):** solo ajustes nativos documentados. Sin ADB,
  sin APK, sin firmware modificado. El perfil autoriza 0 acciones del motor.
- **AOSP sin certificación:** tratar como propietario hasta evidencia en contrario.

## No verificado (no se asume)

- Compatibilidad ADB real de los modelos Android TV (requiere hardware).
- Versiones de firmware por modelo.
- Hardware/plataforma OEM-ODM por modelo.
