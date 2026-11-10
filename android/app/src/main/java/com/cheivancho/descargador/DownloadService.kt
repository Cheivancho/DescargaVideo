package com.cheivancho.descargador

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * Servicio en primer plano: mantiene viva la descarga cuando la app se minimiza o se apaga la pantalla.
 * Muestra el progreso en una notificación y se detiene solo cuando la cola queda vacía.
 */
class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var watcher: kotlinx.coroutines.Job? = null
    private var alreadyFinished: Set<Long> = emptySet() // terminadas antes de esta tanda: no se vuelven a anunciar

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        createChannel()
        ServiceCompat.startForeground(
            this, NOTIF_ID, buildNotification("Preparando descarga…", 0f, indeterminate = true),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
        )
        if (watcher == null) {
            alreadyFinished = Downloads.jobs.value
                .filter { it.status != Status.WAITING && it.status != Status.RUNNING }.map { it.id }.toSet()
        }
        watcher?.cancel()
        watcher = scope.launch {
            Downloads.jobs.collectLatest { jobs ->
                val running = jobs.firstOrNull { it.status == Status.RUNNING }
                val waiting = jobs.count { it.status == Status.WAITING }
                if (running == null && waiting == 0) {
                    announceResult(jobs)
                    ServiceCompat.stopForeground(this@DownloadService, ServiceCompat.STOP_FOREGROUND_REMOVE)
                    stopSelf()
                } else {
                    val title = running?.meta?.title ?: "Descargas en espera"
                    val extra = if (waiting > 0) " (+$waiting en cola)" else ""
                    val n = buildNotification(title + extra, running?.progress ?: 0f, running == null)
                    getSystemService(NotificationManager::class.java).notify(NOTIF_ID, n)
                }
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun announceResult(jobs: List<Job>) {
        val fresh = jobs.filter { it.id !in alreadyFinished }
        val done = fresh.count { it.status == Status.DONE }
        val failed = fresh.count { it.status == Status.ERROR }
        if (done == 0 && failed == 0) return
        val text = buildString {
            if (done > 0) append("$done descarga${if (done > 1) "s" else ""} lista${if (done > 1) "s" else ""}")
            if (failed > 0) append(if (isNotEmpty()) " · " else "").append("$failed con error")
        }
        val n = NotificationCompat.Builder(this, CHANNEL_DONE)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle("DescargaVideo")
            .setContentText(text)
            .setContentIntent(openAppIntent())
            .setAutoCancel(true)
            .build()
        getSystemService(NotificationManager::class.java).notify(NOTIF_DONE_ID, n)
    }

    private fun buildNotification(text: String, progress: Float, indeterminate: Boolean): Notification =
        NotificationCompat.Builder(this, CHANNEL_PROGRESS)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle("Descargando")
            .setContentText(text)
            .setContentIntent(openAppIntent())
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .setProgress(100, (progress * 100).toInt(), indeterminate)
            .build()

    private fun openAppIntent(): PendingIntent = PendingIntent.getActivity(
        this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun createChannel() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_PROGRESS, "Descargas en curso", NotificationManager.IMPORTANCE_LOW),
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_DONE, "Descargas terminadas", NotificationManager.IMPORTANCE_DEFAULT),
        )
    }

    companion object {
        private const val CHANNEL_PROGRESS = "progreso"
        private const val CHANNEL_DONE = "terminadas"
        private const val NOTIF_ID = 1
        private const val NOTIF_DONE_ID = 2

        fun start(ctx: Context) {
            ContextCompat.startForegroundService(ctx, Intent(ctx, DownloadService::class.java))
        }
    }
}
