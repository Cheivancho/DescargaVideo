# DescargaVideo

> Antes se llamaba «Descargador de YouTube». Es el mismo programa: al actualizar se conservan tus ajustes, presets y el motor descargado (los datos pasan a `%LOCALAPPDATA%\DescargaVideo`; la carpeta vieja no se borra).

Aplicación de escritorio para Windows con interfaz oscura para descargar videos de YouTube en **todas las
resoluciones que el video tenga disponibles** (144p hasta 4K/8K), con salida lista para edición y pantallas LED
(ProRes, DNxHR, HAP), audio, subtítulos, recortes, escala exacta, presets y cola. Muestra una vista previa con las
características del video.

## Instalación

1. Entra en la sección **[Releases](../../releases/latest)** de este repositorio.
2. Elige una de las descargas:
   - **`DescargaVideo.zip`**: trae el instalador y un `Leeme.txt`. Descomprímelo y abre
     `DescargaVideo-Setup.exe` (Siguiente → Instalar). También puedes bajar el `.exe` suelto.
   - **`DescargaVideo-portable.zip`**: sin instalación (ver [Versión portable](#versión-portable)).

> **Aviso de Windows:** como el instalador no está firmado digitalmente, Windows puede mostrar
> *"Windows protegió su PC"*. Pulsa **Más información → Ejecutar de todas formas**. Es normal en programas pequeños e
> independientes (ver [`docs/FIRMA.md`](docs/FIRMA.md)).

## Uso básico

1. Pega el enlace del video o playlist y pulsa **Analizar**. (Si el portapapeles ya tiene un enlace de YouTube, la app lo
   pega sola al abrirse o al volver a enfocar la ventana; no analiza automáticamente.)
2. Elige una, varias o todas las resoluciones. Con un enlace `watch?v=…&list=…` la app pregunta si quieres **solo ese
   video o toda la lista**.
3. Elige el **formato de salida** y las opciones que necesites (pestañas de abajo).
4. Pulsa **DESCARGAR**. Por defecto se guarda en `Videos\YouTube`; al terminar, **Abrir carpeta** la abre.

Si editas la URL después de analizar, DESCARGAR se bloquea hasta que vuelvas a pulsar **Analizar**. Repetir una
descarga **no vuelve a bajar ni convertir** lo que ya existe (avisa «Ya existía»). La barra de progreso es global
(resoluciones × videos de la lista × video/audio) y nunca retrocede; en listas muestra «video N de M».

### Formatos de salida (pestaña *Video*)

Por encima de 1080p YouTube solo ofrece VP9/AV1, que programas como Adobe Media Encoder o Resolume Alley no abren bien.
La app descarga la mejor calidad y la convierte una sola vez:

| Formato | Contenedor | Uso recomendado |
|---|---|---|
| H.264 + AAC (por defecto) | MP4 | Uso general, ligero |
| H.265 / HEVC + AAC | MP4 | Archivos más pequeños |
| H.264 / H.265 (GPU) | MP4 | Igual que los anteriores pero mucho más rápido (solo aparece si tu GPU lo soporta; ver [GPU](#codificación-por-gpu)) |
| ProRes 422 HQ / ProRes 422 | MOV | Media Encoder, edición |
| DNxHR HQ | MOV | Premiere, Avid, DaVinci |
| HAP / HAP Q | MOV | Resolume |
| Motion JPEG | MOV | Intra-frame ligero |
| Original de YouTube | MP4 | Sin convertir (VP9/AV1 + Opus) |

ProRes, DNxHR y HAP generan archivos muy pesados (varios GB por minuto en 4K). Al convertir un origen VP9/AV1 a esos
formatos la app avisa: *la conversión mejora la compatibilidad, no la calidad*.

La pestaña *Video* también permite limitar los **FPS máximos** (Máximo / 30 / 60).

### Escala y corte (pestaña *Escala/corte*)

- **Resolución exacta de salida** (importante para pantallas LED): 1920x1080, 3840x2160, 1280x720 o personalizada `AxB`,
  con tres modos: *ajustar con barras*, *rellenar recortando* o *estirar*. Se aplica con filtros de ffmpeg y
  re-codifica el video (con «Original» se usa H.264). **HAP exige múltiplos de 4**: la app ajusta las dimensiones y avisa.
- **Recortar tramo:** campos *Inicio* y *Fin* en `mm:ss` u `hh:mm:ss` (validados; vacío = sin límite). *Corte exacto*
  re-codifica en los cortes; sin ella se corta en el fotograma clave más cercano. El nombre del archivo indica el tramo,
  p. ej. `Título [1080p] [00m10s-00m20s].mp4` (y también la escala y los FPS si se usan).

### Extras (pestaña *Extras*)

- **Audio:** MP3 (por defecto), M4A, Opus, WAV o FLAC; calidad en kbps en los formatos con pérdida.
- **Subtítulos:** idiomas configurables (por defecto `es,en`); *Incrustar* (solo MP4) o *Guardar .srt*. En MOV se guarda el
  `.srt` aparte.
- **Miniatura y metadatos:** incrusta la carátula y los metadatos en MP4, MP3 y M4A (en MOV, Opus, WAV y FLAC se ignora la
  miniatura sin error).
- **Cookies del navegador:** Ninguno / Firefox / Chrome / Edge / Brave. Útil cuando YouTube pide iniciar sesión.
  Firefox suele ser lo más fiable; **Chrome y Edge recientes pueden fallar al leer las cookies** (cifrado o archivo
  bloqueado: cierra el navegador por completo). Si falla, la app lo explica en español.

### Presets

El selector **Preset** de arriba guarda y recupera combinaciones de resoluciones, formato, audio, FPS, escala,
subtítulos y miniatura (el recorte nunca se guarda). Se almacenan en `presets.json` dentro de la carpeta de datos.
Vienen cuatro de fábrica (de solo lectura):

| Preset | Qué hace |
|---|---|
| Resolume 1080p (HAP) | 1080p → HAP, 1920x1080 con barras |
| Premiere 1080p (ProRes 422) | 1080p → ProRes 422 |
| Web ligero 720p (H.264) | 720p → H.264, máx. 30 FPS |
| Solo audio MP3 320 | Solo audio MP3 a 320 kbps |

Si el video no tiene la resolución exacta del preset, se elige la disponible más cercana por debajo.

### Cola, pausa y cancelación

- **+ Cola** guarda el trabajo configurado (enlace, resoluciones, formato y extras) y permite analizar otro enlace. La
  pestaña **Cola** muestra y quita elementos. **DESCARGAR** procesa toda la cola (o el elemento actual si la cola está
  vacía).
- **Pausar / Reanudar** detiene la descarga conservando los archivos parciales (`.part`) y continúa donde iba.
- **Cancelar** funciona también durante una conversión larga: detiene ffmpeg, borra el archivo parcial y conserva el MP4
  original.

### Codificación por GPU

Al abrir, la app consulta `ffmpeg -encoders` y **prueba con una codificación de 1 segundo** cada encoder de GPU (NVIDIA
NVENC, Intel QSV, AMD AMF). Solo si funciona aparece «H.264 (GPU)» / «H.265 (GPU)». Si la conversión por GPU falla, se
reintenta con CPU y se avisa. Ayuda → *Detectar la GPU de nuevo* repite la prueba.

### Ayuda, log y errores

El menú **Ayuda** ofrece: *Abrir log*, *Acerca de* (versiones y carpeta de datos), *Buscar actualizaciones ahora*,
*Restaurar motor incluido* (borra el yt-dlp descargado; se aplica al reiniciar) y *Detectar la GPU de nuevo*. Los errores
se registran con su traceback en `log.txt` (rotativo, ~1 MB × 3 copias); tras un fallo aparece **Copiar error** para
pegarlo en un informe.

## Versión portable

`DescargaVideo-portable.zip` se descomprime en cualquier carpeta (por ejemplo un USB) y se ejecuta sin instalar. Un
archivo `portable.flag` junto al ejecutable hace que **todos los datos** (ajustes, presets, log y motor yt-dlp) vivan en la
carpeta `data\` de al lado en lugar de `%LOCALAPPDATA%`. Trae `ffmpeg.exe` (y `deno.exe` si la Release lo incluye).
La versión portable **no se actualiza sola**: cuando hay una versión nueva la app lo indica arriba a la derecha y
descargas el `.zip` nuevo (el motor yt-dlp sí se actualiza solo). Para crear tu propio portable basta con copiar la carpeta
de la app y añadir un archivo vacío llamado `portable.flag`.

## Actualizaciones automáticas

- Al abrir la app, si hay una versión nueva aparece una ventana de **actualización disponible**; **Actualizar ahora** la
  instala y reabre sola.
- **yt-dlp** (el motor de descarga) se actualiza en segundo plano, porque YouTube cambia con frecuencia. La ventana nunca
  espera a la red al abrirse: el motor nuevo se descarga y **se aplica al reiniciar la app**.
- Necesita conexión a internet para actualizar; sin ella la app sigue funcionando.
- **Verificación del instalador:** la app solo se actualiza si la Release publica el SHA-256 del instalador (campo `digest`
  del asset o el archivo `DescargaVideo-Setup.exe.sha256`); sin hash, la actualización se **rechaza**. Ojo: el hash
  protege contra descargas **corruptas**, no contra una cuenta de GitHub comprometida (quien publicara un instalador
  malicioso publicaría también su hash). Para eso sirve la firma digital ([`docs/FIRMA.md`](docs/FIRMA.md)).

## Motor JavaScript (Deno) para YouTube

Las versiones actuales de yt-dlp necesitan un *runtime* de JavaScript para resolver los desafíos de YouTube; sin él pueden
faltar resoluciones (`No supported JavaScript runtime could be found`). yt-dlp solo activa **Deno** por defecto y admite
también Node.js, Bun y QuickJS, y además necesita el paquete `yt-dlp-ejs` (ya incluido en la app). La app busca, en este
orden, `deno`, `node`, `bun`, `qjs` (primero junto al ejecutable, luego en el `PATH`). Si no encuentra ninguno y el
análisis devuelve pocas resoluciones, lo indica en la barra de estado.

- Para incluirlo en el instalador: descarga `deno.exe` desde <https://github.com/denoland/deno/releases>
  (`deno-x86_64-pc-windows-msvc.zip`) y colócalo en `vendor\` antes de compilar. `build.ps1` avisa si falta; `installer.iss`
  lo copia si existe. (La CI de Release lo descarga con SHA-256 fijado.)
- Más información: <https://github.com/yt-dlp/yt-dlp/wiki/EJS>.

## Desarrollo

Requisitos: Python 3.12, [Inno Setup 6](https://jrsoftware.org/isinfo.php) y un `ffmpeg.exe` en `vendor\`
(opcional: `deno.exe`). Estructura:

| Archivo | Contenido |
|---|---|
| `app.py` | Punto de entrada (PyInstaller, `--selftest`, DPI) |
| `ui.py` | Ventana, estilos y widgets (tkinter) |
| `downloader.py` | Trabajos de yt-dlp, progreso, cancelación, pausa |
| `convert.py` | ffmpeg: conversión, miniaturas, detección de GPU |
| `formats.py` | Formatos de salida, selector de yt-dlp, filtros de ffmpeg, recorte y escala |
| `config.py` | Rutas, ajustes (`state.json`), presets, log |
| `updater.py` | Actualización de yt-dlp y de la app, modo portable |
| `util.py` | Formato de texto |

```powershell
python -m pip install -r requirements-dev.txt   # dependencias + pytest + ruff
ruff check .
pytest
python -c "import app; a=app.App(); a.after(800, a.destroy); a.mainloop()"   # prueba de arranque
python app.py --selftest selftest.txt                                         # diagnóstico
.\build.ps1                                                                   # compila el instalador
```

`build.ps1` busca Python (variable `PYTHON` → `py -3.12` → `python`) e Inno Setup (`ISCC.exe` en el `PATH` o en las rutas
habituales) y genera `output\DescargaVideo-Setup.exe`.

### Publicar una versión

1. Sube `VERSION` en `updater.py`, actualiza el `CHANGELOG.md` y haz commit + push.
2. **Con la CI (recomendado):** `git tag vX.Y.Z && git push origin vX.Y.Z`. El workflow *Release* comprueba que el tag
   coincide con `VERSION`, ejecuta ruff y pytest, compila (con ffmpeg y deno descargados con SHA-256 fijado) y crea la
   Release con el instalador, su `.sha256`, el `.zip` y el portable.
3. **Desde tu PC (alternativa):** `.\release.ps1 -Notas "qué cambió"` hace lo mismo en local con `gh`.

El workflow *CI* (`ruff` + `pytest`) corre en cada push y pull request.

Más documentación: [`docs/FIRMA.md`](docs/FIRMA.md) (firma digital), [`docs/WINGET.md`](docs/WINGET.md) (publicar en winget),
[`CHANGELOG.md`](CHANGELOG.md).

## Avisos

- **Uso responsable:** descargar contenido de YouTube puede incumplir sus términos de servicio y los derechos de autor.
  Usa esta herramienta solo con contenido propio, con licencia libre o con permiso de su autor. El autor no se hace
  responsable del uso que se le dé.
- **Riesgo de reclamos de retirada (takedown):** los proyectos de este tipo reciben con frecuencia reclamos DMCA o avisos
  de plataformas de alojamiento (incluido GitHub) por «eludir medidas de protección». Este repositorio podría ser retirado
  o limitado sin previo aviso; conviene conservar copias propias del código y no depender de un único alojamiento.
- El instalador incluye [FFmpeg](https://ffmpeg.org/) (build de gyan.dev, licencia GPL v3; código fuente en
  <https://ffmpeg.org/download.html>) y usa [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense). Si se incluye,
  [Deno](https://deno.com/) tiene licencia MIT.
- El código de esta aplicación se publica bajo licencia MIT.
