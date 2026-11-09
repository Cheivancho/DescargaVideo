package com.cheivancho.descargador

import android.app.Application
import android.content.Context
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** Información de un video ya analizado. */
data class VideoMeta(
    val url: String,
    val title: String,
    val channel: String,
    val durationSec: Int,
    val thumbnail: String?,
    val heights: List<Int>,
)

/** Application: arranca el motor (yt-dlp + Python + ffmpeg) en segundo plano. */
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        instance = this
        Engine.start(this)
    }

    companion object {
        lateinit var instance: App
            private set
    }
}

/**
 * Envuelve a yt-dlp. La primera vez descomprime Python (unos segundos), por eso se inicia en
 * segundo plano y todo lo demás espera con [ensureReady].
 */
object Engine {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val ready = CompletableDeferred<Unit>()

    /** Mientras se actualiza yt-dlp nadie debe usarlo: el archivo se reemplaza y Python lo leería a medias. */
    private val updating = Mutex()

    fun start(app: Application) {
        scope.launch {
            updating.lock() // se toma ANTES de avisar que el motor está listo
            try {
                try {
                    YoutubeDL.init(app)
                    FFmpeg.init(app)
                    ready.complete(Unit)
                } catch (e: Throwable) {
                    ready.completeExceptionally(e)
                }
                autoUpdate(app)
            } finally {
                updating.unlock()
            }
        }
    }

    /** Espera a que el motor esté iniciado y no esté actualizándose. */
    suspend fun ensureReady() {
        ready.await()
        updating.withLock { }
    }

    /** Actualiza yt-dlp como mucho una vez al día (YouTube cambia seguido). Nunca debe romper nada. */
    private fun autoUpdate(ctx: Context) {
        val prefs = ctx.getSharedPreferences("motor", Context.MODE_PRIVATE)
        val last = prefs.getLong("ultima_busqueda", 0L)
        if (System.currentTimeMillis() - last < 24 * 3600 * 1000L) return
        try {
            YoutubeDL.updateYoutubeDL(ctx)
        } catch (_: Throwable) {
            // sin red u otro fallo: se reintenta más tarde
        }
        prefs.edit().putLong("ultima_busqueda", System.currentTimeMillis()).apply()
    }

    /** Búsqueda manual desde «Acerca de». Devuelve un mensaje para mostrar. */
    suspend fun updateNow(ctx: Context): String = withContext(Dispatchers.IO) {
        try {
            ready.await()
            if (Downloads.hasActive()) return@withContext "Hay descargas en curso. Espera a que terminen para actualizar."
            updating.withLock {
                val st = YoutubeDL.updateYoutubeDL(ctx)
                ctx.getSharedPreferences("motor", Context.MODE_PRIVATE).edit()
                    .putLong("ultima_busqueda", System.currentTimeMillis()).apply()
                if (st == YoutubeDL.UpdateStatus.DONE) "Motor actualizado." else "El motor ya está al día."
            }
        } catch (e: Throwable) {
            "No se pudo actualizar: " + friendlyError(e.message)
        }
    }

    fun ytdlpVersion(ctx: Context): String = try {
        YoutubeDL.versionName(ctx) ?: "incluido"
    } catch (_: Throwable) {
        "incluido"
    }

    /** Analiza un enlace de un solo video (nunca la lista completa). */
    suspend fun analyze(url: String): VideoMeta = withContext(Dispatchers.IO) {
        ensureReady()
        val req = YoutubeDLRequest(url)
        req.addOption("--no-playlist")
        val info = YoutubeDL.getInfo(req)
        val heights = info.formats.orEmpty()
            .filter { (it.vcodec ?: "none") != "none" && it.height > 0 }
            .map { it.height }.distinct().sortedDescending()
        VideoMeta(
            url = url,
            title = info.title ?: info.fulltitle ?: "Sin título",
            channel = info.uploader ?: "",
            durationSec = info.duration,
            thumbnail = info.thumbnail,
            heights = heights,
        )
    }
}

/** Convierte el error de yt-dlp en un mensaje que se entienda. */
fun friendlyError(raw: String?): String {
    val msg = raw.orEmpty()
    val low = msg.lowercase()
    return when {
        "not a bot" in low || "sign in to confirm" in low ->
            "YouTube pide comprobar que no eres un robot. Prueba de nuevo en unos minutos o cambia de red (Wi-Fi/datos)."
        "private video" in low -> "El video es privado."
        "video unavailable" in low || "this video is not available" in low -> "El video no está disponible."
        "age" in low && ("restrict" in low || "confirm your age" in low) ->
            "El video tiene restricción de edad y requiere iniciar sesión."
        "urlopen error" in low || "getaddrinfo" in low || "timed out" in low || "unable to download webpage" in low ||
            "network is unreachable" in low -> "No hay conexión a internet."
        "javascript runtime" in low -> "Falta el motor JavaScript de YouTube. Actualiza el motor desde «Acerca de»."
        "no space left" in low -> "No queda espacio en el teléfono."
        else -> msg.lineSequence().map { it.trim() }.lastOrNull { it.isNotEmpty() }?.take(220)
            ?: "Error desconocido."
    }
}

/** ¿Es un enlace de YouTube? Devuelve (es video, es lista pura sin video). */
fun youtubeLinkKind(url: String): Pair<Boolean, Boolean> {
    val u = url.trim()
    val host = Regex("^https?://([^/?#]+)", RegexOption.IGNORE_CASE).find(u)?.groupValues?.get(1)?.lowercase()
        ?: return false to false
    val ok = host == "youtu.be" || host == "youtube.com" || host.endsWith(".youtube.com")
    if (!ok) return false to false
    val hasV = host == "youtu.be" || Regex("[?&]v=[\\w-]+").containsMatchIn(u) ||
        Regex("youtube\\.com/(shorts|live|embed)/[\\w-]+", RegexOption.IGNORE_CASE).containsMatchIn(u)
    val hasList = Regex("[?&]list=").containsMatchIn(u)
    return hasV to (hasList && !hasV)
}

/** Primer enlace http(s) dentro de un texto (lo que llega al «compartir»). */
fun extractUrl(text: String): String? =
    Regex("https?://\\S+").find(text)?.value?.trimEnd(')', ']', '.', ',', ';')
