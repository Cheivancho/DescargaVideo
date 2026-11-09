package com.cheivancho.descargador

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.File

enum class Status { WAITING, RUNNING, DONE, ERROR, CANCELED }

data class Job(
    val id: Long,
    val meta: VideoMeta,
    val audioOnly: Boolean,
    val height: Int,
    val audioFmt: String,
    val status: Status = Status.WAITING,
    val progress: Float = 0f,
    val text: String = "En espera",
    val savedUri: String? = null,
    val savedMime: String? = null,
)

/** Cola de descargas de toda la app: una tras otra, también con la app en segundo plano. */
object Downloads {
    private val _jobs = MutableStateFlow<List<Job>>(emptyList())
    val jobs: StateFlow<List<Job>> = _jobs.asStateFlow()

    private val lock = Any()
    private var runner: kotlinx.coroutines.Job? = null
    private var nextId = 1L

    fun enqueue(ctx: Context, meta: VideoMeta, audioOnly: Boolean, height: Int, audioFmt: String) {
        val job = synchronized(lock) {
            Job(nextId++, meta, audioOnly, height, audioFmt).also { j -> _jobs.update { it + j } }
        }
        DownloadService.start(ctx)
        pump(job.id)
    }

    fun hasActive(): Boolean = _jobs.value.any { it.status == Status.WAITING || it.status == Status.RUNNING }

    fun cancel(id: Long) {
        val job = _jobs.value.firstOrNull { it.id == id } ?: return
        when (job.status) {
            Status.WAITING -> modify(id) { copy(status = Status.CANCELED, text = "Cancelada") }
            Status.RUNNING -> {
                modify(id) { copy(text = "Cancelando…") }
                YoutubeDL.destroyProcessById(processId(id))
            }
            else -> {}
        }
    }

    fun remove(id: Long) = _jobs.update { list ->
        list.filterNot { it.id == id && it.status != Status.RUNNING && it.status != Status.WAITING }
    }

    fun clearFinished() = _jobs.update { list ->
        list.filter { it.status == Status.RUNNING || it.status == Status.WAITING }
    }

    private fun processId(id: Long) = "job-$id"

    private fun modify(id: Long, f: Job.() -> Job) =
        _jobs.update { list -> list.map { if (it.id == id) it.f() else it } }

    /** Arranca el procesador de la cola si no está corriendo. */
    private fun pump(@Suppress("UNUSED_PARAMETER") hint: Long) {
        synchronized(lock) {
            if (runner?.isActive == true) return
            runner = Engine.scope.launch {
                while (true) {
                    val next = synchronized(lock) {
                        val n = _jobs.value.firstOrNull { it.status == Status.WAITING }
                        if (n == null) runner = null
                        n
                    } ?: break
                    process(next)
                }
            }
        }
    }

    private fun process(job: Job) {
        val ctx = App.instance
        val dir = File(ctx.cacheDir, "dl/${job.id}").apply { deleteRecursively(); mkdirs() }
        modify(job.id) { copy(status = Status.RUNNING, text = "Preparando…", progress = 0f) }
        try {
            kotlinx.coroutines.runBlocking { Engine.ensureReady() }
            val req = buildRequest(job, dir)
            val streams = if (job.audioOnly) 1 else 2
            var stream = 0
            var best = 0f
            YoutubeDL.execute(req, processId(job.id)) { pct, eta, line ->
                if (line.contains("Destination:")) stream++
                val overall = ((stream - 1).coerceAtLeast(0) + pct.coerceIn(0f, 100f) / 100f) / streams
                best = maxOf(best, overall.coerceAtMost(0.99f))
                val etaText = if (eta > 0) " · quedan ${fmtEta(eta)}" else ""
                val what = if (job.audioOnly) "audio" else if (stream <= 1) "video" else "audio"
                modify(job.id) { copy(progress = best, text = "Descargando $what · ${(best * 100).toInt()} %$etaText") }
            }
            modify(job.id) { copy(progress = 0.99f, text = "Guardando en Descargas…") }
            val out = findOutput(dir) ?: error("No se generó ningún archivo.")
            val (uri, mime) = saveToDownloads(ctx, out)
            modify(job.id) {
                copy(status = Status.DONE, progress = 1f, text = "Listo · Descargas/DescargadorYouTube",
                    savedUri = uri.toString(), savedMime = mime)
            }
        } catch (_: YoutubeDL.CanceledException) {
            modify(job.id) { copy(status = Status.CANCELED, text = "Cancelada") }
        } catch (e: Throwable) {
            if (_jobs.value.firstOrNull { it.id == job.id }?.text == "Cancelando…") {
                modify(job.id) { copy(status = Status.CANCELED, text = "Cancelada") }
            } else {
                modify(job.id) { copy(status = Status.ERROR, text = friendlyError(e.message)) }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun buildRequest(job: Job, dir: File): YoutubeDLRequest {
        val req = YoutubeDLRequest(job.meta.url)
        req.addOption("--no-playlist")
        req.addOption("--no-mtime")
        req.addOption("--newline")
        req.addOption("--embed-metadata")
        req.addOption("-o", dir.absolutePath + "/%(title).150B.%(ext)s")
        if (job.audioOnly) {
            val sel = if (job.audioFmt == "m4a") "bestaudio[ext=m4a]/bestaudio/best" else "bestaudio/best"
            req.addOption("-f", sel)
            req.addOption("-x")
            req.addOption("--audio-format", job.audioFmt)
            req.addOption("--audio-quality", "0")
        } else {
            val h = job.height
            // Prefiere H.264 + AAC (se reproduce en cualquier celular); si no hay, lo mejor disponible.
            req.addOption(
                "-f",
                "bv*[height<=$h][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=$h][ext=mp4]+ba[ext=m4a]/" +
                    "bv*[height<=$h]+ba/b[height<=$h]/b",
            )
            req.addOption("--merge-output-format", "mp4")
        }
        return req
    }

    private val outputExts = setOf("mp4", "mkv", "webm", "mp3", "m4a", "opus", "ogg", "wav", "flac", "mov")

    private fun findOutput(dir: File): File? =
        dir.listFiles()?.filter { it.isFile && it.extension.lowercase() in outputExts }?.maxByOrNull { it.length() }

    private fun mimeFor(ext: String) = when (ext.lowercase()) {
        "mp4" -> "video/mp4"
        "mkv" -> "video/x-matroska"
        "webm" -> "video/webm"
        "mov" -> "video/quicktime"
        "mp3" -> "audio/mpeg"
        "m4a" -> "audio/mp4"
        "opus", "ogg" -> "audio/ogg"
        "wav" -> "audio/wav"
        "flac" -> "audio/flac"
        else -> "application/octet-stream"
    }

    /** Copia el archivo a Descargas/DescargadorYouTube (sin pedir permisos de almacenamiento). */
    private fun saveToDownloads(ctx: Context, file: File): Pair<Uri, String> {
        val mime = mimeFor(file.extension)
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, file.name)
            put(MediaStore.Downloads.MIME_TYPE, mime)
            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/DescargadorYouTube")
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val resolver = ctx.contentResolver
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: error("No se pudo crear el archivo en Descargas.")
        try {
            resolver.openOutputStream(uri)!!.use { out -> file.inputStream().use { it.copyTo(out) } }
        } catch (e: Throwable) {
            resolver.delete(uri, null, null)
            throw e
        }
        values.clear()
        values.put(MediaStore.Downloads.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
        return uri to mime
    }

    private fun fmtEta(sec: Long): String {
        val m = sec / 60
        val s = sec % 60
        return if (m > 0) "%d:%02d min".format(m, s) else "$s s"
    }
}
