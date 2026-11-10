package com.cheivancho.descargador

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/** Una versión nueva de la app encontrada en GitHub. */
data class UpdateInfo(
    val version: String,
    val notes: String,
    val apkName: String,
    val apkUrl: String,
    val sha256: String,
    val size: Long,
)

/**
 * Busca versiones nuevas de ESTA app en las Releases de GitHub (etiquetas «android-vX.Y.Z»), las descarga,
 * comprueba su SHA-256 y abre el instalador de Android.
 *
 * Una versión sin SHA-256 publicado se rechaza. Además, Android solo deja actualizar si la nueva APK está firmada
 * con la misma clave que la instalada, así que una APK ajena no se puede instalar encima.
 */
object Updater {
    private const val REPO = "Cheivancho/descargador-youtube"
    private const val TAG_PREFIX = "android-v"
    private const val SUMS_NAME = "SHA256SUMS.txt"

    fun installedVersion(ctx: Context): String =
        runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull() ?: "0"

    private fun parts(v: String): List<Int> = Regex("\\d+").findAll(v).map { it.value.toInt() }.toList()

    /** ¿La versión [a] es más nueva que [b]? Compara número a número (0.1.10 > 0.1.9). */
    fun isNewer(a: String, b: String): Boolean {
        val x = parts(a)
        val y = parts(b)
        for (i in 0 until maxOf(x.size, y.size)) {
            val p = x.getOrElse(i) { 0 }
            val q = y.getOrElse(i) { 0 }
            if (p != q) return p > q
        }
        return false
    }

    private fun open(url: String, timeoutMs: Int): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            setRequestProperty("User-Agent", "DescargaVideo-Android")
            setRequestProperty("Accept", "application/vnd.github+json")
            connectTimeout = timeoutMs
            readTimeout = timeoutMs * 2
        }

    private fun readText(url: String): String {
        val c = open(url, 10_000)
        try {
            if (c.responseCode != 200) throw IOException("GitHub respondió ${c.responseCode}")
            return c.inputStream.bufferedReader().use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    private class Asset(val name: String, val url: String, val size: Long)

    /** Devuelve la versión nueva más reciente, o null si ya tienes la última (o la nueva no se puede verificar). */
    suspend fun check(ctx: Context): UpdateInfo? = withContext(Dispatchers.IO) {
        val releases = JSONArray(readText("https://api.github.com/repos/$REPO/releases?per_page=30"))
        var bestVersion = installedVersion(ctx)
        var best: org.json.JSONObject? = null
        for (i in 0 until releases.length()) {
            val r = releases.getJSONObject(i)
            val tag = r.optString("tag_name")
            if (r.optBoolean("draft") || !tag.startsWith(TAG_PREFIX)) continue
            val v = tag.removePrefix(TAG_PREFIX)
            if (isNewer(v, bestVersion)) {
                best = r
                bestVersion = v
            }
        }
        val rel = best ?: return@withContext null

        val arr = rel.optJSONArray("assets") ?: return@withContext null
        val assets = (0 until arr.length()).map {
            val a = arr.getJSONObject(it)
            Asset(a.getString("name"), a.getString("browser_download_url"), a.optLong("size"))
        }
        // El APK de la arquitectura de este teléfono; si no hay, el «universal».
        val apk = Build.SUPPORTED_ABIS.firstNotNullOfOrNull { abi -> assets.firstOrNull { it.name.endsWith("-$abi.apk") } }
            ?: assets.firstOrNull { it.name.endsWith("-universal.apk") }
            ?: return@withContext null
        val sums = assets.firstOrNull { it.name == SUMS_NAME } ?: return@withContext null
        val hash = readText(sums.url).lineSequence().mapNotNull { line ->
            val p = line.trim().split(Regex("\\s+"), limit = 2)
            if (p.size == 2 && p[1].trimStart('*') == apk.name) p[0].lowercase() else null
        }.firstOrNull() ?: return@withContext null

        UpdateInfo(bestVersion, rel.optString("body").trim(), apk.name, apk.url, hash, apk.size)
    }

    private fun sha256(f: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        f.inputStream().use { input ->
            val buf = ByteArray(256 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    /** Descarga la APK y comprueba su SHA-256. Si ya estaba descargada y es correcta, la reutiliza. */
    suspend fun download(ctx: Context, info: UpdateInfo, onProgress: (Float) -> Unit): File =
        withContext(Dispatchers.IO) {
            val dir = File(ctx.cacheDir, "updates").apply { mkdirs() }
            dir.listFiles()?.filter { it.name != info.apkName }?.forEach { it.delete() }
            val out = File(dir, info.apkName)
            if (out.exists() && sha256(out) == info.sha256) {
                onProgress(1f)
                return@withContext out
            }
            val tmp = File(dir, info.apkName + ".part")
            val c = open(info.apkUrl, 20_000)
            try {
                if (c.responseCode != 200) throw IOException("No se pudo descargar (${c.responseCode}).")
                val total = c.contentLengthLong.takeIf { it > 0 } ?: info.size
                val md = MessageDigest.getInstance("SHA-256")
                var done = 0L
                c.inputStream.use { input ->
                    tmp.outputStream().use { output ->
                        val buf = ByteArray(256 * 1024)
                        while (true) {
                            val n = input.read(buf)
                            if (n < 0) break
                            output.write(buf, 0, n)
                            md.update(buf, 0, n)
                            done += n
                            if (total > 0) onProgress((done.toFloat() / total).coerceAtMost(1f))
                        }
                    }
                }
                val got = md.digest().joinToString("") { "%02x".format(it) }
                if (got != info.sha256) {
                    tmp.delete()
                    throw IOException("El archivo descargado está dañado. Vuelve a intentarlo.")
                }
                out.delete()
                tmp.renameTo(out)
                out
            } catch (e: Throwable) {
                tmp.delete()
                throw e
            } finally {
                c.disconnect()
            }
        }

    /**
     * Abre el instalador de Android. Devuelve false si falta el permiso «instalar apps de esta fuente»: en ese caso
     * abre la pantalla de ajustes para activarlo y hay que volver a tocar «Actualizar ahora».
     */
    fun install(ctx: Context, apk: File): Boolean {
        if (!ctx.packageManager.canRequestPackageInstalls()) {
            ctx.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${ctx.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            return false
        }
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", apk)
        ctx.startActivity(
            Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        return true
    }
}
