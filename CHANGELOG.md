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

### Cambiado (Fase 3)
- **`app.py` dividido** sin cambios de comportamiento (extracción mecánica por AST y comprobación con descargas reales):
  `config.py` (rutas, `state.json`, presets, log), `formats.py` (formatos de salida, selector de yt-dlp, filtros de
  ffmpeg, recorte/escala), `convert.py` (`Converter`: ffmpeg, GPU), `downloader.py` (`Downloader`: trabajos, progreso,
  cancelación, pausa), `util.py` (formato de texto), `ui.py` (ventana) y `updater.py`. `app.py` queda como punto de
  entrada (PyInstaller, `--selftest`, DPI).
- `build.ps1` ya no depende de una ruta fija de Python (`$env:PYTHON` → `py -3.12` → `python`) y busca `ISCC.exe` en el PATH.
- `.gitignore`: `vendor\*.exe`, `selftest.txt`, cachés de pytest/ruff y `data\` (versión portable).
- Type hints en las funciones públicas de cada módulo; `ruff` configurado en `pyproject.toml` (línea de 120).

### Añadido (Fase 3)
- **Tests** (`pytest`, 191): `fmt_*`, `parse_version` y `check_app_update` con respuestas simuladas (incluido el rechazo sin
  hash), descarga del instalador verificada, extracción segura de wheels, reintento del motor tras un fallo, selector de
  formato (video individual, playlist y FPS), filtros de ffmpeg (escala/pad/crop), parser de tiempos del recorte,
  detección de `&list=`, progreso global, mensajes de error, consistencia `OUT_FORMATS`/`RECODE_SPECS` y migración de
  `state.json`/`presets.json` viejos o corruptos.
- `requirements.txt` (versiones fijas), `requirements-dev.txt` (pytest, ruff) y `pyproject.toml`.
- **CI** (`.github/workflows`): `ci.yml` (ruff + pytest en cada push/PR) y `release.yml` (al empujar un tag `v*`: comprueba que
  coincide con `VERSION`, instala Inno Setup con Chocolatey, descarga **ffmpeg 9.0.2 (gyan.dev, full_build)** y **deno 2.9.8**
  con SHA-256 fijado, compila con `build.ps1` y crea la Release con instalador, `.sha256` y `.zip`).

### Añadido (Fase 2)
- **Comodidad:** botón «Abrir carpeta», ajustes recordados en `state.json` (carpeta, formato, audio, tamaño de
  ventana y el resto de opciones), enlace de YouTube pegado desde el portapapeles al abrir/enfocar, menú **Ayuda**
  (abrir log, versiones, buscar actualizaciones ahora, restaurar motor incluido, detectar GPU de nuevo).
- **Audio y extras:** MP3, M4A, Opus, WAV y FLAC (calidad en kbps cuando aplica); subtítulos (idiomas configurables,
  incrustar en MP4 o guardar `.srt`); incrustar miniatura y metadatos (MP4, MP3, M4A; se ignora en MOV).
- **Recorte y escala:** tramo Inicio/Fin (`mm:ss`/`hh:mm:ss`, validado, corte exacto opcional) con `download_ranges`;
  resolución exacta (1920x1080, 3840x2160, 1280x720, AxB) con barras / recortar / estirar; HAP en múltiplos de 4;
  FPS máximos (`[fps<=?N]`). El nombre del archivo incluye tramo, escala y FPS.
- **Presets:** `presets.json` en `DATA_DIR` (guardar/cargar/borrar) y 4 de fábrica.
- **GPU:** «H.264 (GPU)» y «H.265 (GPU)» (NVENC/QSV/AMF) solo si `ffmpeg -encoders` los lista y una codificación de
  prueba de 1 s funciona (resultado cacheado por ffmpeg); si la GPU falla se reintenta con CPU. Nota al convertir
  VP9/AV1 a ProRes/DNxHR/HAP.
- **Cola, pausa, log y cookies:** botón «+ Cola» y pestaña Cola; **Pausar/Reanudar** (conserva los `.part`);
  log rotativo (`log.txt`, ~1 MB × 3) con tracebacks, «Abrir log» y «Copiar error»; cookies del navegador
  (Firefox/Chrome/Edge/Brave) con mensajes de error comprensibles.

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

- La carátula de MP3/M4A/MP4 la incrusta la propia app con ffmpeg: `EmbedThumbnail` de yt-dlp exige `ffprobe`,
  que el instalador no incluye.
- Con una cola, DESCARGAR procesa solo la cola (no el ítem configurado en ese momento); la cola se vacía al terminar
  (salvo cancelación).
- Pausar actúa al llegar el siguiente bloque de datos; durante una conversión con ffmpeg la pausa se aplica al
  terminar esa conversión.
- Reanudar tras la pausa usa los `.part` de yt-dlp (`continuedl`); en listas se vuelve a extraer la lista y se saltan
  los videos ya completos.
- La nota «mejora la compatibilidad, no la calidad» solo se muestra si el origen es VP9/AV1.
- Subtítulos: se piden también los automáticos (`writeautomaticsub`) limitados a los idiomas elegidos.

### Pendiente / no verificado
- **Los workflows de GitHub Actions no se han ejecutado** (no pueden probarse en local): solo se validó su sintaxis YAML.
  Las URLs y los SHA-256 de ffmpeg y deno se tomaron de las Releases oficiales con la API de GitHub.
- `build.ps1` se ejecutó en una copia temporal del repositorio (para no tocar `dist\`, `build\`, `output\`): genera el
  instalador (80,7 MB) y el `.exe` compilado arranca (`--selftest`) con `yt_dlp_ejs` incluido. Esa compilación fue sin
  `vendor\deno.exe` (no está en el equipo de desarrollo).
- Reutilizar el análisis para descargar (`process_ie_result`) falla con HTTP 403 en algunos casos (p. ej. el trabajo de
  audio); está previsto y se vuelve a extraer, pero la descarga tarda más.- Encoders QSV y AMF: la prueba de 1 s los descarta/acepta correctamente, pero solo se pudo comprobar NVENC (GPU NVIDIA
  del equipo de desarrollo); los argumentos de QSV/AMF no se han probado con hardware real.
- No se probó la lectura real de cookies de Firefox/Chrome/Edge (se evitó acceder a los perfiles del usuario).
- No se ha comprobado un yt-dlp descargado de PyPI de extremo a extremo en el `.exe` empaquetado (solo la lógica).
