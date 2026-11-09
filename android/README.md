# Descargador de YouTube — Android

Versión para Android del descargador (carpeta `android/` del repositorio). Usa
[youtubedl-android](https://github.com/yausername/youtubedl-android) (yt-dlp + Python + ffmpeg + QuickJS incluidos), así que no
necesita instalar nada más en el teléfono.

## Qué hace (v0.1.0)

- Pegar un enlace, o **Compartir → Descargador** desde la app de YouTube, y analizarlo (miniatura, título, canal, duración).
- Video en la resolución elegida (prefiere H.264 + AAC) o solo audio en MP3 / M4A con título y artista.
- Cola de descargas (una tras otra), cancelar, y las descargas siguen con la app minimizada (notificación de progreso).
- Se guarda en `Descargas/DescargadorYouTube` (sin pedir permisos de almacenamiento).
- **Avisa cuando hay una versión nueva de la app**: al abrirla consulta las Releases de GitHub y, si hay una más reciente, muestra los cambios y un botón «Actualizar ahora» que la descarga, comprueba su SHA-256 (una versión sin hash se rechaza) y abre el instalador de Android. Android solo permite actualizar con la misma clave de firma, así que una APK ajena no se instala encima. La primera vez pide permiso para «instalar apps de esta fuente». Si Google Play Protect muestra «¿Analizar la app?», se puede elegir «Más detalles → Instalar sin analizar».
- El motor yt-dlp se actualiza solo (como mucho una vez al día) y a mano desde «Acerca de».

- Avisa si el video es **vertical** (Shorts/Reels) u horizontal y lo descarga siempre en su orientación original.

**Límites:** solo videos sueltos (las listas completas no); sin recorte, subtítulos ni escalado; Android 10 o superior.

## Instalar

Descarga el `.apk` de la Release y ábrelo (Android pide permitir «instalar apps de origen desconocido» para el navegador o el
gestor de archivos). Para casi todos los teléfonos modernos sirve `arm64-v8a`; si dudas, usa el `universal` (más pesado).

> Esta app **no puede estar en Google Play** (su política prohíbe descargar de YouTube): se reparte como APK. Avisa sola
> cuando hay una versión nueva (ver arriba); la 0.1.1 y anteriores no tienen ese aviso y se actualizan instalando la APK encima.

## Compilar

Requisitos: JDK 17 o superior y el SDK de Android (Android Studio o solo las herramientas). Crea `android/local.properties`
con `sdk.dir=C:/ruta/al/Android/Sdk`.

```powershell
cd android
.\gradlew.bat :app:assembleDebug      # APK de pruebas (firma de depuración)
.\gradlew.bat :app:assembleRelease    # APK final (usa keystore.properties si existe)
```

Los APK quedan en `app\build\outputs\apk\<debug|release>\` (uno por arquitectura y uno `universal`).

### Firma

`assembleRelease` firma con la clave descrita en `android/keystore.properties` (no se sube a git, igual que el `.jks`):

```
storeFile=descargador-release.jks
storePassword=...
keyAlias=descargador
keyPassword=...
```

**Guarda una copia de `descargador-release.jks` y de `keystore.properties`.** Android solo permite actualizar una app con la
misma clave: si se pierde, quien ya la tenga instalada tendrá que desinstalarla para poner una versión nueva.

## Probar sin teléfono

Con la imagen de sistema x86_64 del SDK y un AVD, `adb install app-x86_64-debug.apk`. El análisis es lento en el emulador
(el motor JavaScript de YouTube corre sin aceleración); en un teléfono real es bastante más rápido.

## Aviso

Úsala solo con contenido que tengas derecho a descargar. Los proyectos de este tipo pueden recibir reclamos de retirada
(takedown).
