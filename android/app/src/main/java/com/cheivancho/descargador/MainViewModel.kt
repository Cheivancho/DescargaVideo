package com.cheivancho.descargador

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch

sealed interface Analysis {
    data object Idle : Analysis
    data object Loading : Analysis
    data class Ready(val meta: VideoMeta) : Analysis
    data class Failed(val message: String) : Analysis
}

sealed interface UpdateUi {
    data object Idle : UpdateUi
    data class Downloading(val progress: Float) : UpdateUi
    data object NeedsPermission : UpdateUi
    data class Failed(val message: String) : UpdateUi
}

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("ajustes", Context.MODE_PRIVATE)

    var url by mutableStateOf("")
        private set
    var analysis by mutableStateOf<Analysis>(Analysis.Idle)
        private set
    var analyzedUrl by mutableStateOf<String?>(null)
        private set

    var audioOnly by mutableStateOf(prefs.getBoolean("solo_audio", false))
        private set
    var audioFmt by mutableStateOf(prefs.getString("formato_audio", "mp3") ?: "mp3")
        private set
    var height by mutableStateOf(0)
        private set
    private var preferredHeight = prefs.getInt("altura", 1080)

    /** Aviso de un solo uso (p. ej. «el enlace es una lista»). */
    var notice by mutableStateOf<String?>(null)
        private set

    /** Versión nueva de la app encontrada en GitHub (null si no hay o ya se descartó). */
    var update by mutableStateOf<UpdateInfo?>(null)
        private set
    var updateUi by mutableStateOf<UpdateUi>(UpdateUi.Idle)
        private set

    init {
        checkUpdate() // al abrir la app: si hay una versión nueva, se avisa
    }

    /**
     * Busca una versión nueva. Al abrir la app es silencioso si no hay nada o falla la red. En una búsqueda manual
     * se llama a [onResult] con un mensaje, o con null si se encontró una versión nueva (se abre el aviso).
     */
    fun checkUpdate(manual: Boolean = false, onResult: (String?) -> Unit = {}) {
        viewModelScope.launch {
            try {
                val found = Updater.check(getApplication())
                if (found == null) {
                    if (manual) onResult("Ya tienes la última versión (${Updater.installedVersion(getApplication())}).")
                } else {
                    update = found
                    updateUi = UpdateUi.Idle
                    if (manual) onResult(null)
                }
            } catch (e: Throwable) {
                if (manual) onResult("No se pudo comprobar: " + friendlyError(e.message))
            }
        }
    }

    fun dismissUpdate() {
        update = null
        updateUi = UpdateUi.Idle
    }

    /** Descarga la actualización, comprueba que no esté dañada y abre el instalador de Android. */
    fun startUpdate() {
        val info = update ?: return
        if (updateUi is UpdateUi.Downloading) return
        updateUi = UpdateUi.Downloading(0f)
        viewModelScope.launch {
            try {
                val apk = Updater.download(getApplication(), info) { p -> updateUi = UpdateUi.Downloading(p) }
                if (Updater.install(getApplication(), apk)) dismissUpdate() else updateUi = UpdateUi.NeedsPermission
            } catch (e: Throwable) {
                updateUi = UpdateUi.Failed(friendlyError(e.message))
            }
        }
    }

    val canDownload: Boolean
        get() = analysis is Analysis.Ready && analyzedUrl != null && url.trim() == analyzedUrl

    fun onUrlChange(value: String) {
        url = value
        notice = null
    }

    fun clearNotice() {
        notice = null
    }

    fun chooseAudioOnly(v: Boolean) {
        audioOnly = v
        prefs.edit().putBoolean("solo_audio", v).apply()
    }

    fun chooseAudioFmt(v: String) {
        audioFmt = v
        prefs.edit().putString("formato_audio", v).apply()
    }

    fun chooseHeight(h: Int) {
        height = h
        preferredHeight = h
        prefs.edit().putInt("altura", h).apply()
    }

    /** Texto que llega al «compartir» o al pegar: saca el enlace y lo analiza. */
    fun onSharedText(text: String) {
        val link = extractUrl(text) ?: text.trim()
        url = link
        analyze()
    }

    fun analyze() {
        val link = extractUrl(url) ?: url.trim()
        url = link
        val (isVideo, isOnlyList) = youtubeLinkKind(link)
        when {
            link.isEmpty() -> { notice = "Pega primero un enlace de YouTube."; return }
            isOnlyList -> {
                notice = "Este enlace es una lista de reproducción. Por ahora en el celular solo se descargan " +
                    "videos sueltos: abre un video de la lista y comparte su enlace."
                return
            }
            !isVideo -> { notice = "Eso no parece un enlace de video de YouTube."; return }
        }
        notice = null
        analysis = Analysis.Loading
        analyzedUrl = null
        viewModelScope.launch {
            try {
                val meta = Engine.analyze(link)
                if (url.trim() != link) return@launch // el usuario cambió el enlace mientras tanto
                analysis = Analysis.Ready(meta)
                analyzedUrl = link
                // elige la resolución guardada, o la más cercana hacia abajo
                height = meta.heights.firstOrNull { it <= preferredHeight } ?: meta.heights.lastOrNull() ?: 0
                if (meta.heights.isEmpty()) chooseAudioOnly(true)
            } catch (e: Throwable) {
                analysis = Analysis.Failed(friendlyError(e.message))
            }
        }
    }

    fun download() {
        val ready = analysis as? Analysis.Ready ?: return
        if (!canDownload) return
        Downloads.enqueue(getApplication(), ready.meta, audioOnly, height, audioFmt)
        notice = "Añadido a las descargas."
    }
}
