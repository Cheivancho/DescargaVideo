# Changelog

## Android 0.1.2 — 2026-11-09

- Aviso de actualización: al abrir la app avisa si hay una versión nueva en GitHub y permite descargarla e instalarla (con comprobación de SHA-256). Incluye un botón «Buscar actualización de la app» en «Acerca de».

## [2.1.1] — 2026-11-10 (Android 0.2.1)

### Cambiado
- El repositorio de GitHub pasó a llamarse **DescargaVideo** (github.com/Cheivancho/DescargaVideo) y la app ya apunta a la
  dirección nueva (`REPO` en `branding.py` y en `Updater.kt` de Android). Se actualizaron README, Leeme y docs.
- Las versiones ya instaladas siguen encontrando las actualizaciones: GitHub redirige el nombre anterior del repositorio
  (comprobado con el actualizador de la 2.0.1 y 2.0.2 y con la conexión de Java que usa Android).

## [2.1.0] — 2026-11-09 — Nuevo nombre: DescargaVideo (Android 0.2.0)

### Cambiado
- **La app pasa a llamarse DescargaVideo** (antes «Descargador de YouTube»), en PC y en Android: ventana, instalador,
  accesos directos, ejecutable (`DescargaVideo.exe`), nombres de los archivos de la Release (`DescargaVideo-Setup.exe`,
  `DescargaVideo.zip`, `DescargaVideo-portable.zip`), documentación y textos de Android.
- El nombre vive en un solo archivo, `branding.py`; `tests/test_branding.py` comprueba que el instalador, los scripts y el CI
  coincidan.
- Android: cambia el nombre visible y la carpeta de descargas (`Descargas/DescargaVideo`). El identificador del paquete y la
  clave de firma **no cambian**, así que se actualiza encima de la versión anterior.

### Añadido
- **Migración de datos:** la primera vez que arranca, copia `%LOCALAPPDATA%\DescargadorYouTube` a
  `%LOCALAPPDATA%\DescargaVideo` (ajustes, presets, log y motor yt-dlp). Copia, no mueve: la carpeta vieja queda intacta. Si
  falla, la app arranca igual y lo reintenta. La versión portable no migra.
- El instalador, al actualizar desde la versión con el nombre anterior, borra el ejecutable y los accesos directos viejos.

### Decisiones tomadas
- El `AppId` del instalador no cambia: el instalador nuevo reemplaza al viejo en vez de instalarse al lado.
- Quien ya tenía la app conserva su carpeta de instalación anterior (Inno Setup reutiliza la ruta por `AppId`); las
  instalaciones nuevas usan `%LOCALAPPDATA%\Programs\DescargaVideo`.
- El repositorio de GitHub se mantuvo con su nombre anterior en esta versión para no cortar las actualizaciones; se renombró en la 2.1.1.
- El actualizador sigue buscando el instalador por `endswith("setup.exe")`, por lo que sirve con ambos nombres.

### Pendiente / no verificado
- La actualización automática desde una app **ya instalada con el nombre viejo** se probó con una copia de prueba del
  instalador (otro `AppId`, otra carpeta) y con el actualizador de la 2.0.2 leyendo la nueva Release; no sobre una
  instalación real distinta de esa copia.

## [2.0.2] — 2026-11-09

### Corregido
- Videos verticales (Shorts, 9:16): la calidad se cuenta por el lado corto, como YouTube. Un Short de 1080x1920 aparece como «1080p» (antes «1920p») y al elegir «1080p» —también con los presets— baja el 1080x1920 en H.264 en vez de una versión de 608x1080 en AV1.
- La miniatura de un video vertical se muestra entera, con barras, en lugar de recortarse.

### Añadido
- **Orientación del video, pensada para quien no sabe de resoluciones.** Al analizar, un aviso dice «Video VERTICAL (9:16, como un Short o Reel)» o «Video horizontal (16:9)». Nueva opción «Orientación del video»: «Como el original» (por defecto), «Vertical» u «Horizontal», con una frase que explica qué se va a descargar.
- **Protección contra videos horizontales por error:** si el video es vertical y hay una escala horizontal elegida (p. ej. el preset «Resolume 1080p»), se da vuelta sola (1920x1080 pasa a 1080x1920) y la app avisa. Con «Vertical» u «Horizontal» se adapta el video a esa orientación con el «Modo» de Escala/corte (barras, recorte o estirado).
- Las resoluciones se muestran con nombre corriente y tamaño real («1080p Full HD · 1080×1920») y viene marcada la recomendada: la mejor hasta Full HD (antes se marcaba la más alta).
- Android: mismo aviso de orientación y mismas etiquetas de calidad. No convierte entre orientaciones (descarga siempre en la orientación original).
- Escalas verticales para pantallas en retrato: 1080x1920, 2160x3840 y 720x1280.
- El estado y «Mejor calidad» indican cuando el video es vertical.
- Android: el mismo arreglo de calidad vertical (probado con un Short real).

## [2.0.1] — 2026-11-09

### Cambiado
- Rediseño visual: paleta unificada, pestañas nuevas y controles más parejos (ver «Cambiado (diseño)» más abajo).

## [2.0.0] — 2026-11-09 (desde 1.2.0)

### Añadido

**Funciones (Fase 2)**
- **Comodidad:** botón «Abrir carpeta», ajustes recordados en `state.json` (carpeta, formato, audio, tamaño de ventana y
  el resto de opciones), enlace de YouTube pegado desde el portapapeles al abrir/enfocar la ventana, menú **Ayuda**
  (abrir log, versiones, buscar actualizaciones ahora, restaurar motor incluido, detectar la GPU de nuevo).
- **Audio y extras:** MP3, M4A, Opus, WAV y FLAC (calidad en kbps cuando aplica); subtítulos (idiomas configurables,
  incrustar en MP4 o guardar `.srt`); incrustar miniatura y metadatos (MP4, MP3, M4A; se ignora en MOV sin romper).
- **Recorte y escala:** tramo Inicio/Fin (`mm:ss`/`hh:mm:ss`, validado, corte exacto opcional) con `download_ranges`;
  resolución exacta (1920x1080, 3840x2160, 1280x720, `AxB`) con barras / recortar / estirar; HAP en múltiplos de 4;
  FPS máximos (`[fps<=?N]`). El nombre del archivo incluye tramo, escala y FPS.
- **Presets:** `presets.json` en la carpeta de datos (guardar/cargar/borrar) y 4 de fábrica (Resolume 1080p HAP, Premiere
  1080p ProRes 422, Web ligero 720p H.264, Solo audio MP3 320).
- **GPU:** «H.264 (GPU)» y «H.265 (GPU)» (NVENC/QSV/AMF) solo si `ffmpeg -encoders` los lista y una codificación de prueba
  de 1 s funciona (resultado cacheado por ffmpeg); si la GPU falla se reintenta con CPU. Nota al convertir VP9/AV1 a
  ProRes/DNxHR/HAP.
- **Cola, pausa, log y cookies:** botón «+ Cola» y pestaña Cola; **Pausar/Reanudar** (conserva los `.part`); log rotativo
  (`log.txt`, ~1 MB × 3) con tracebacks, «Abrir log» y «Copiar error»; cookies del navegador (Firefox/Chrome/Edge/Brave)
  con mensajes de error comprensibles.

**Distribución y calidad (Fases 3 y 4)**
- **Versión portable:** `DescargadorYouTube-portable.zip` (carpeta de `dist\` + ffmpeg [+ deno] + `portable.flag`); con ese
  archivo junto al ejecutable, los datos (ajustes, presets, log, motor yt-dlp) van a `data\` de al lado. No se actualiza sola
  (avisa de la versión nueva). Incluida en `release.ps1` y en `release.yml`.
- **Firma digital opcional:** `installer.iss` (`/DSign=1`), `build.ps1` (variable `SIGN_COMMAND`) y paso opcional en
  `release.yml` (solo con los secretos `SIGN_PFX_BASE64`/`SIGN_PFX_PASSWORD`). Guía en `docs/FIRMA.md`.
- `docs/WINGET.md`: pasos para publicar el manifiesto con `wingetcreate` (trámite manual).
- **Tests** (`pytest`, 194): `fmt_*`, `parse_version` y `check_app_update` con respuestas simuladas (incluido el rechazo sin
  hash), descarga del instalador verificada, extracción segura de wheels, reintento del motor tras un fallo, selector de
  formato (video individual, playlist y FPS), filtros de ffmpeg (escala/pad/crop), parser de tiempos del recorte, detección
  de `&list=`, progreso global, mensajes de error, consistencia `OUT_FORMATS`/`RECODE_SPECS`, migración de
  `state.json`/`presets.json` viejos o corruptos y resolución del modo portable.
- `requirements.txt` (versiones fijas), `requirements-dev.txt` (pytest, ruff) y `pyproject.toml` (ruff, línea de 120).
- **CI** (`.github/workflows`): `ci.yml` (ruff + pytest en cada push/PR) y `release.yml` (al empujar un tag `v*`: comprueba
  que coincide con `VERSION`, instala Inno Setup con Chocolatey, descarga **ffmpeg 9.0.2 (gyan.dev, full_build)** y
  **deno 2.9.8** con SHA-256 fijado, compila con `build.ps1` y crea la Release con instalador, `.sha256`, `.zip` y portable).
- **Dependencia de ejecución `yt-dlp-ejs`** (`==0.8.0` para yt-dlp 2026.10.26; la versión la fija cada yt-dlp): scripts JS que
  yt-dlp necesita para YouTube. Al actualizar yt-dlp, el actualizador descarga también la versión exacta de `yt-dlp-ejs` que
  pide el wheel nuevo.
- `--selftest` informa de `yt_dlp_ejs`, runtime JS y ffmpeg.

### Corregido (Fase 1)
- **Arranque no bloqueante:** ya no se consulta PyPI antes de abrir la ventana. Al iniciar solo se aplica en local una
  actualización ya descargada (`yt-dlp.next` → `yt-dlp`); la consulta/descarga va en un hilo en segundo plano tras mostrar la
  ventana y deja el motor nuevo en `yt-dlp.next` (se aplica al reiniciar). `ytdlp_last_check` se guarda también si falla,
  con reintento a la hora (`ytdlp_last_ok`). Se mantiene el SHA-256 del wheel y se endurece la comprobación de rutas del zip.
- **Hash obligatorio** en la actualización de la app (campo `digest` o asset `.sha256`); sin hash se rechaza y no se ejecuta
  el instalador. `release.ps1` genera y sube el `.sha256`.
- **Cancelar durante la conversión:** `ffmpeg` corre con `Popen`; al cancelar se termina (y se mata si no responde), se borra
  el archivo parcial y se conserva el MP4 original. La consulta `ffmpeg -i` tiene `timeout`.
- **URL analizada:** la descarga usa la URL analizada; si se edita el campo, DESCARGAR se bloquea hasta volver a analizar.
- **Enlaces `watch?v=…&list=…`:** diálogo «solo este video / toda la lista», usado en análisis y descarga.
- **Progreso global monótono** (trabajos × videos de la lista × pistas) con texto
  `[2/3] 1080p · video 4 de 40 · 12.3 MiB/s · ETA 00:41`.
- **Sin trabajo repetido:** en videos individuales se reutiliza el `info` del análisis (`process_ie_result`) si tiene menos de
  20 min; si falla, se vuelve a extraer.
- **Archivos existentes:** se salta lo que ya existe con su nombre final (`match_filter`) y se avisa; se limpian los
  `*.compat.mp4` huérfanos al iniciar una descarga.
- **Diagnóstico de formatos:** logger propio de yt-dlp (registra en `log.txt`, recuerda la última advertencia) y mensaje útil
  cuando hay pocas/ninguna resolución.
- **Motor JavaScript:** verificado en el yt-dlp instalado (2026.10.26) que YouTube necesita un runtime JS (solo `deno` activo
  por defecto; `node`/`bun`/`quickjs` con la opción `js_runtimes`) y el paquete `yt-dlp-ejs`. La app detecta el runtime y lo
  pasa a yt-dlp; `build.ps1`/`installer.iss` incluyen `vendor\deno.exe` si existe.
- **DPI:** `SetProcessDpiAwareness` y tamaños de ventana/miniatura/`wraplength` escalados.

### Corregido tras la revisión de código
- Un MP4 sin convertir (conversión cancelada o fallida) ya no se da por terminado al repetir la descarga: se comprueba el códec.
- La interfaz ya no se congela si un evento interno falla; el error va al log.
- La cola conserva los elementos que fallaron para poder reintentarlos.
- Un preset ya no impone sus resoluciones a todos los análisis posteriores.
- La opción de GPU guardada se recupera cuando termina la detección; las opciones de GPU que dejan de funcionar se quitan.
- El mensaje final indica "terminada con errores" si algún trabajo falló.
- "Copiar error" incluye el detalle de todos los fallos, no solo el último.
- Pausar también congela ffmpeg durante la conversión (antes seguía hasta terminar); probado con una codificación real.
- Una carpeta de destino inválida muestra un mensaje en lugar de no hacer nada.
- "Buscar actualizaciones" busca el motor aunque falle la consulta de la app, y avisa si una versión se rechaza por no tener SHA-256.
- Si se corta la descarga de una actualización de la app, se borra la carpeta temporal parcial.
- Al decidir si hay un yt-dlp más nuevo se compara con la versión más alta entre incluida, instalada y pendiente.

### Cambiado (diseño)
- Interfaz unificada: nueva paleta oscura con texto claro y coral solo como acento, bordes y campos coherentes, botones con efecto al pasar el ratón.
- Pestañas nuevas (Video, Escala/corte, Extras, Cola) del mismo ancho con subrayado coral en la activa.
- Ventana algo más alta y textos de ayuda más legibles.

### Cambiado
- **`app.py` dividido** sin cambios de comportamiento (extracción mecánica por AST y comprobación con descargas reales):
  `config.py` (rutas, `state.json`, presets, log), `formats.py` (formatos de salida, selector de yt-dlp, filtros de ffmpeg,
  recorte/escala), `convert.py` (`Converter`: ffmpeg, GPU), `downloader.py` (`Downloader`: trabajos, progreso, cancelación,
  pausa), `util.py` (formato de texto), `ui.py` (ventana) y `updater.py`. `app.py` queda como punto de entrada (PyInstaller,
  `--selftest`, DPI).
- Panel izquierdo de la interfaz reorganizado en pestañas (Video / Escala-corte / Extras / Cola) y ventana algo más alta.
- `build.ps1` ya no depende de una ruta fija de Python (`$env:PYTHON` → `py -3.12` → `python`) y busca `ISCC.exe` en el PATH.
- `.gitignore`: `vendor\*.exe`, `selftest.txt`, cachés de pytest/ruff y `data\` (versión portable).
- Type hints en las funciones públicas de cada módulo.
- README y Leeme reescritos con todas las funciones nuevas, la versión portable y una nota sobre reclamos de retirada
  (takedown).
- `VERSION` sube a `2.0.0`.

### Decisiones tomadas
- Un MP4 intermedio sin convertir (p. ej. tras cancelar la conversión a H.265/H.264) tiene el mismo nombre que el final, así
  que una descarga posterior lo contará como «ya existía». Se conserva el original como pide el plan.
- Si el instalador no trae hash, `check_app_update` devuelve `None` (no se ofrece la actualización) y además
  `download_installer` se niega a ejecutarse: doble barrera.
- `remote_components` (`ejs:github`) **no** se activa: ejecutaría código descargado de GitHub; se usa solo el `yt-dlp-ejs`
  empaquetado o verificado desde PyPI.
- Si no hay runtime JS se deja el comportamiento por defecto de yt-dlp (que avisa) en lugar de desactivarlo.
- La carátula de MP3/M4A/MP4 la incrusta la propia app con ffmpeg: `EmbedThumbnail` de yt-dlp exige `ffprobe`, que el
  instalador no incluye.
- Con una cola, DESCARGAR procesa solo la cola (no el ítem configurado en ese momento); la cola se vacía al terminar (salvo
  cancelación).
- Pausar actúa al llegar el siguiente bloque de datos; durante una conversión con ffmpeg la pausa se aplica al terminar esa
  conversión. Reanudar usa los `.part` de yt-dlp (`continuedl`); en listas se vuelve a extraer la lista y se saltan los
  videos ya completos.
- La nota «mejora la compatibilidad, no la calidad» solo se muestra si el origen es VP9/AV1.
- Subtítulos: se piden también los automáticos (`writeautomaticsub`) limitados a los idiomas elegidos.
- El tiempo del recorte solo admite `mm:ss` / `hh:mm:ss` (no segundos sueltos), para evitar ambigüedades.
- La versión portable no usa el actualizador de instalador (no tendría dónde instalarse): avisa de la versión nueva y el
  usuario descarga el `.zip`; el motor yt-dlp sí se actualiza en su carpeta `data\`.
- El paso de firma de la CI y `SIGN_COMMAND` solo cubren certificados `.pfx` con `signtool`; SignPath y Azure Trusted
  Signing requieren sus propias acciones (ver `docs/FIRMA.md`). El ejecutable de dentro del instalador no se firma.

### Pendiente / no verificado
- **Los workflows de GitHub Actions no se han ejecutado** (no pueden probarse en local): solo se validó su sintaxis YAML. Las
  URLs y los SHA-256 de ffmpeg y deno se tomaron de las Releases oficiales con la API de GitHub. El paso de firma con `.pfx`
  tampoco se ha probado (no hay certificado); solo se comprobó que Inno Setup recibe y ejecuta el comando de `SIGN_COMMAND`.
- `build.ps1` se ejecutó en copias temporales del repositorio (para no tocar `dist\`, `build\`, `output\`): genera el
  instalador (~81 MB) y el `.exe` compilado arranca (`--selftest`) con `yt_dlp_ejs` incluido. Esas compilaciones fueron sin
  `vendor\deno.exe` (no está en el equipo de desarrollo), así que el runtime JS empaquetado no se ha probado. La versión
  portable se comprobó repitiendo a mano los pasos de `release.ps1` sobre esa compilación (zip → descomprimir → `--selftest`
  da `portable=True` y `data\` junto al ejecutable); `release.ps1` completo no se ejecutó porque publica.
- **Cookies del navegador:** no se verificó una lectura real. El único intento, con Brave, llegó a abrir la base de cookies del
  equipo y falló al descifrar (DPAPI); el mensaje de error comprensible sí está probado.
- Encoders QSV y AMF: la prueba de 1 s los acepta o descarta correctamente, pero solo se pudo comprobar NVENC (GPU NVIDIA del
  equipo de desarrollo); los argumentos de QSV/AMF no se han probado con hardware real.
- Reutilizar el análisis para descargar (`process_ie_result`) falla con HTTP 403 en algunos casos (p. ej. el trabajo de audio);
  está previsto y se vuelve a extraer, pero la descarga tarda más.
- No se ha comprobado un yt-dlp descargado de PyPI de extremo a extremo en el `.exe` empaquetado (solo la lógica y sus tests).
- Firma digital, winget y los secretos de la CI son trámites manuales del usuario (ver `docs/`).
