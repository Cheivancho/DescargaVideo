# Changelog

## [Sin publicar] — rama `mejoras-v2` (1.2.0 → 2.0.0)

### Corregido (Fase 1)
- **Arranque no bloqueante:** ya no se consulta PyPI antes de abrir la ventana. Al iniciar solo se aplica en
  local una actualización ya descargada (`yt-dlp.next` → `yt-dlp`); la consulta/descarga va en un hilo
  en segundo plano tras mostrar la ventana y deja el motor nuevo en `yt-dlp.next` (se aplica al reiniciar).
  `ytdlp_last_check` se guarda también si falla, con reintento a la hora (`ytdlp_last_ok`). Se mantiene el
  SHA-256 del wheel y se endurece la comprobación de rutas del zip.
- **Hash obligatorio** en la actualización de la app (campo `digest` o asset `.sha256`); sin hash se rechaza
  y no se ejecuta el instalador. `release.ps1` genera y sube el `.sha256`.
- **Cancelar durante la conversión:** `ffmpeg` corre con `Popen`; al cancelar se termina (y se mata si no
  responde), se borra el archivo parcial y se conserva el MP4 original. La consulta `ffmpeg -i` tiene `timeout`.
- **URL analizada:** la descarga usa la URL analizada; si se edita el campo, DESCARGAR se bloquea hasta
  volver a analizar.
- **Enlaces `watch?v=…&list=…`:** diálogo «solo este video / toda la lista», usado en análisis y descarga.
- **Progreso global monótono** (trabajos × videos de la lista × pistas) con texto
  `[2/3] 1080p · video 4 de 40 · 12.3 MiB/s · ETA 00:41`.
- **Sin trabajo repetido:** en videos individuales se reutiliza el `info` del análisis
  (`process_ie_result`) si tiene menos de 20 min; si falla, se vuelve a extraer.
- **Archivos existentes:** se salta lo que ya existe con su nombre final (`match_filter`) y se avisa; se limpian
  los `*.compat.mp4` huérfanos al iniciar una descarga.
- **Diagnóstico de formatos:** logger propio de yt-dlp (registra en `log.txt`, recuerda la última advertencia) y
  mensaje útil cuando hay pocas/ninguna resolución.
- **Motor JavaScript:** verificado en el yt-dlp instalado (2026.10.26) que YouTube necesita un runtime JS
  (solo `deno` activo por defecto; `node`/`bun`/`quickjs` con la opción `js_runtimes`) y el paquete
  `yt-dlp-ejs`. La app detecta el runtime y lo pasa a yt-dlp; `build.ps1`/`installer.iss` incluyen
  `vendor\deno.exe` si existe.
- **DPI:** `SetProcessDpiAwareness` y tamaños de ventana/miniatura/`wraplength` escalados.

### Añadido (Fase 1)
- Dependencia de ejecución **`yt-dlp-ejs`** (pinned por yt-dlp: `==0.8.0` para yt-dlp 2026.10.26): scripts JS que
  yt-dlp necesita para YouTube. Al actualizar yt-dlp, el actualizador descarga también la versión exacta de
  `yt-dlp-ejs` que pide el wheel nuevo.
- `--selftest` informa de `yt_dlp_ejs`, runtime JS y ffmpeg.

### Decisiones tomadas
- Un MP4 intermedio sin convertir (p. ej. tras cancelar la conversión a H.265/H.264) tiene el mismo nombre que el
  final, así que una descarga posterior lo contará como «ya existía». Se conserva el original como pide el plan.
- Si el instalador no trae hash, `check_app_update` devuelve `None` (no se ofrece la actualización) y además
  `download_installer` se niega a ejecutarse: doble barrera.
- `remote_components` (`ejs:github`) **no** se activa: ejecutaría código descargado de GitHub; se usa solo el
  `yt-dlp-ejs` empaquetado/verificado desde PyPI.
- Si no hay runtime JS se deja el comportamiento por defecto de yt-dlp (que avisa) en lugar de desactivarlo.

### Pendiente / no verificado
- No se ha comprobado un yt-dlp descargado de PyPI de extremo a extremo en el `.exe` empaquetado (solo la lógica).
