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
