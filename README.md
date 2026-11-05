# Descargador de YouTube

Aplicación de escritorio para Windows con interfaz oscura para descargar videos de YouTube
en **todas las resoluciones que el video tenga disponibles** (144p hasta 4K/8K), además de
audio en MP3 y playlists completas. Muestra una vista previa con las características del video.

## Instalación (para todo el mundo)

1. Entra en la sección **[Releases](../../releases/latest)** de este repositorio.
2. Descarga **`DescargadorYouTube.zip`** (trae el instalador y un archivo `Leeme.txt` con las instrucciones), descomprímelo
   y abre `DescargadorYouTube-Setup.exe`. También puedes descargar el `.exe` suelto.
3. Haz doble clic y sigue los pasos (Siguiente → Instalar).

> **Aviso de Windows:** como el instalador no está firmado digitalmente, Windows puede mostrar
> *"Windows protegió su PC"*. Pulsa **Más información → Ejecutar de todas formas**.
> Es normal en programas pequeños e independientes.

## Actualizaciones automáticas

- Al abrir la app, si hay una versión nueva aparece una ventana de **actualización disponible**.
  Pulsa **Actualizar ahora** y se instala y reabre sola.
- **yt-dlp** (el motor de descarga) se actualiza solo en segundo plano, porque YouTube cambia
  con frecuencia. No tienes que hacer nada.
- Necesita conexión a internet para actualizar; sin ella la app sigue funcionando.

## Uso

1. Pega el enlace del video o playlist y pulsa **Analizar**.
2. Elige una, varias o todas las resoluciones (y opcionalmente el audio MP3).
3. Elige el **formato de salida** (ver tabla).
4. Pulsa **DESCARGAR**. Se guarda por defecto en `Videos\YouTube`.

### Formatos de salida

Por encima de 1080p YouTube solo ofrece VP9/AV1, que programas como Adobe Media Encoder o
Resolume Alley no abren bien. La app descarga la mejor calidad y la convierte una sola vez:

| Formato | Contenedor | Uso recomendado |
|---|---|---|
| H.264 + AAC (por defecto) | MP4 | Uso general, ligero |
| H.265 / HEVC + AAC | MP4 | Archivos más pequeños |
| ProRes 422 HQ / ProRes 422 | MOV | Media Encoder, edición |
| DNxHR HQ | MOV | Premiere, Avid, DaVinci |
| HAP / HAP Q | MOV | Resolume |
| Motion JPEG | MOV | Intra-frame ligero |
| Original de YouTube | MP4 | Sin convertir (VP9/AV1 + Opus) |

ProRes, DNxHR y HAP generan archivos muy pesados (varios GB por minuto en 4K).

## Compilar desde el código

Requisitos: Python 3.12 (`pip install yt-dlp pillow pyinstaller`), [Inno Setup 6](https://jrsoftware.org/isinfo.php)
y un `ffmpeg.exe` en `vendor\`.

```powershell
.\build.ps1
```

Genera `output\DescargadorYouTube-Setup.exe`. Para publicar una versión nueva: sube el número de
`VERSION` en `updater.py`, haz commit y ejecuta `.
elease.ps1 -Notas "qué cambió"`, que compila, genera el `.zip`
y crea la Release `vX.Y.Z` en GitHub.

## Avisos

- **Uso responsable:** descargar contenido de YouTube puede incumplir sus términos de servicio y los
  derechos de autor. Usa esta herramienta solo con contenido propio, con licencia libre o con permiso
  de su autor. El autor no se hace responsable del uso que se le dé.
- El instalador incluye [FFmpeg](https://ffmpeg.org/) (build de gyan.dev, licencia GPL v3;
  código fuente en <https://ffmpeg.org/download.html>) y usa [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense).
- El código de esta aplicación se publica bajo licencia MIT.
