package com.cheivancho.descargador

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.URL

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val dark = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT) // iconos claros sobre fondo oscuro
        enableEdgeToEdge(statusBarStyle = dark, navigationBarStyle = dark)
        askNotificationPermission()
        handleIntent(intent)
        setContent { AppTheme { Screen(vm) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    /** «Compartir» un enlace desde YouTube hacia esta app: lo pega y lo analiza. */
    private fun handleIntent(intent: Intent?) {
        if (intent?.action == Intent.ACTION_SEND && intent.type == "text/plain") {
            intent.getStringExtra(Intent.EXTRA_TEXT)?.let { vm.onSharedText(it) }
            intent.action = null // no repetir al rotar la pantalla
        }
    }

    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) {}
                .launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}

// ---------------------------------------------------------------- pantalla

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Screen(vm: MainViewModel) {
    val ctx = LocalContext.current
    val jobs by Downloads.jobs.collectAsState()
    var showAbout by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    var lastCount by remember { mutableStateOf(jobs.size) }
    // Al añadir una descarga, baja sola hasta la lista para que se vea el progreso.
    val headerIndex = 3 + if (vm.notice != null) 1 else 0 // cabecera, URL, (aviso), análisis, → «DESCARGAS»
    LaunchedEffect(jobs.size) {
        if (jobs.size > lastCount) listState.animateScrollToItem(headerIndex)
        lastCount = jobs.size
    }

    Box(Modifier.fillMaxSize().background(Bg).systemBarsPadding().imePadding()) {
        LazyColumn(
            Modifier.fillMaxSize(),
            state = listState,
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            item { Header(onAbout = { showAbout = true }) }
            item { UrlBar(vm, ctx) }
            vm.notice?.let { item { Text(it, color = CoralSoft, fontSize = 13.sp) } }

            item {
                when (val a = vm.analysis) {
                    Analysis.Idle -> Text(
                        "Pega un enlace de YouTube, o compártelo desde la app de YouTube con «Compartir → Descargador».",
                        color = Muted, fontSize = 13.sp,
                    )
                    Analysis.Loading -> Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(Modifier.size(22.dp), color = Coral, strokeWidth = 2.5.dp)
                        Spacer(Modifier.size(12.dp))
                        Text("Analizando el video…", color = Muted)
                    }
                    is Analysis.Failed -> Card { Text(a.message, color = MaterialColorError) }
                    is Analysis.Ready -> VideoCard(vm, a.meta)
                }
            }

            item {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Section("DESCARGAS", Modifier.weight(1f))
                    if (jobs.any { it.status != Status.RUNNING && it.status != Status.WAITING }) {
                        TextButton(onClick = { Downloads.clearFinished() }) { Text("Limpiar", color = Muted) }
                    }
                }
            }
            if (jobs.isEmpty()) {
                item { Text("Todavía no hay descargas.", color = Muted, fontSize = 13.sp) }
            } else {
                items(jobs.asReversed(), key = { it.id }) { JobCard(it, ctx) }
            }
        }
    }

    if (showAbout) AboutDialog(onClose = { showAbout = false })
}

private val MaterialColorError = Color(0xFFFF6B6B)

@Composable
private fun Header(onAbout: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text("▶", color = Coral, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Text(
            "  Descargador de YouTube", color = TextMain, fontSize = 19.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis,
        )
        TextButton(onClick = onAbout) { Text("Acerca de", color = Muted) }
    }
}

@Composable
private fun UrlBar(vm: MainViewModel, ctx: Context) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        OutlinedTextField(
            value = vm.url,
            onValueChange = vm::onUrlChange,
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("https://youtube.com/watch?v=…", color = Disabled) },
            singleLine = true,
            shape = RoundedCornerShape(10.dp),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
            keyboardActions = KeyboardActions(onGo = { vm.analyze() }),
            colors = OutlinedTextFieldDefaults.colors(
                focusedTextColor = TextMain, unfocusedTextColor = TextMain,
                focusedBorderColor = Coral, unfocusedBorderColor = Border,
                focusedContainerColor = Field, unfocusedContainerColor = Field, cursorColor = Coral,
            ),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            SoftButton("Pegar", Modifier.weight(1f)) {
                val cm = ctx.getSystemService(ClipboardManager::class.java)
                val text = cm?.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(ctx)?.toString()
                if (text.isNullOrBlank()) {
                    Toast.makeText(ctx, "El portapapeles está vacío.", Toast.LENGTH_SHORT).show()
                } else {
                    vm.onUrlChange(extractUrl(text) ?: text.trim())
                }
            }
            SolidButton("Analizar", Modifier.weight(1f), enabled = vm.analysis != Analysis.Loading) { vm.analyze() }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun VideoCard(vm: MainViewModel, meta: VideoMeta) {
    Card {
        Thumb(meta.thumbnail, Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(10.dp)))
        Spacer(Modifier.height(10.dp))
        Text(meta.title, color = TextMain, fontSize = 16.sp, fontWeight = FontWeight.Bold, maxLines = 3,
            overflow = TextOverflow.Ellipsis)
        Text(
            listOfNotNull(
                meta.channel.takeIf { it.isNotBlank() }, fmtDuration(meta.durationSec),
                "vertical".takeIf { meta.vertical },
            ).joinToString("  ·  "),
            color = Muted, fontSize = 13.sp,
        )
        Spacer(Modifier.height(14.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip("Video", !vm.audioOnly, enabled = meta.heights.isNotEmpty()) { vm.chooseAudioOnly(false) }
            Chip("Solo audio", vm.audioOnly) { vm.chooseAudioOnly(true) }
        }
        Spacer(Modifier.height(12.dp))
        if (vm.audioOnly) {
            Section("FORMATO DE AUDIO")
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Chip("MP3", vm.audioFmt == "mp3") { vm.chooseAudioFmt("mp3") }
                Chip("M4A", vm.audioFmt == "m4a") { vm.chooseAudioFmt("m4a") }
            }
        } else {
            Section(if (meta.vertical) "RESOLUCIÓN (VIDEO VERTICAL)" else "RESOLUCIÓN")
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                meta.heights.forEach { h -> Chip(heightLabel(h), vm.height == h) { vm.chooseHeight(h) } }
            }
        }
        Spacer(Modifier.height(16.dp))
        SolidButton(
            if (vm.canDownload) "⬇   DESCARGAR" else "Vuelve a pulsar Analizar",
            Modifier.fillMaxWidth(), enabled = vm.canDownload, tall = true,
        ) { vm.download() }
    }
}

@Composable
private fun JobCard(job: Job, ctx: Context) {
    Card {
        Text(job.meta.title, color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Bold, maxLines = 2,
            overflow = TextOverflow.Ellipsis)
        val what = if (job.audioOnly) "Audio ${job.audioFmt.uppercase()}" else
            "${job.height}p${if (job.meta.vertical) " vertical" else ""} · MP4"
        Text(what, color = Muted, fontSize = 12.sp)
        if (job.status == Status.RUNNING || job.status == Status.WAITING) {
            Spacer(Modifier.height(8.dp))
            if (job.status == Status.RUNNING && job.progress > 0f) {
                LinearProgressIndicator(
                    progress = { job.progress }, modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)),
                    color = Coral, trackColor = Field,
                )
            } else {
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)),
                    color = Coral, trackColor = Field,
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(
            job.text, fontSize = 13.sp,
            color = when (job.status) {
                Status.DONE -> Ok
                Status.ERROR -> MaterialColorError
                else -> Muted
            },
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            when (job.status) {
                Status.RUNNING, Status.WAITING -> TextButton(onClick = { Downloads.cancel(job.id) }) {
                    Text("Cancelar", color = CoralSoft)
                }
                Status.DONE -> {
                    TextButton(onClick = { openFile(ctx, job) }) { Text("Abrir", color = Coral) }
                    TextButton(onClick = { Downloads.remove(job.id) }) { Text("Quitar", color = Muted) }
                }
                else -> TextButton(onClick = { Downloads.remove(job.id) }) { Text("Quitar", color = Muted) }
            }
        }
    }
}

@Composable
private fun AboutDialog(onClose: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var msg by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var engine by remember { mutableStateOf(Engine.ytdlpVersion(ctx)) }
    val appVer = remember {
        runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull() ?: "?"
    }
    AlertDialog(
        onDismissRequest = onClose,
        containerColor = Panel,
        title = { Text("Descargador de YouTube", color = TextMain) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Versión de la app: $appVer", color = TextMain)
                Text("Motor yt-dlp: $engine", color = TextMain)
                Text("Se actualiza solo una vez al día. Si YouTube deja de funcionar, prueba a actualizarlo ahora.",
                    color = Muted, fontSize = 12.sp)
                Text("Las descargas se guardan en Descargas/DescargadorYouTube. Usa la app solo con contenido " +
                    "que tengas derecho a descargar.", color = Muted, fontSize = 12.sp)
                msg?.let { Text(it, color = CoralSoft) }
            }
        },
        confirmButton = {
            TextButton(enabled = !busy, onClick = {
                busy = true
                msg = "Buscando…"
                scope.launch {
                    msg = Engine.updateNow(ctx)
                    engine = Engine.ytdlpVersion(ctx)
                    busy = false
                }
            }) { Text("Actualizar motor", color = Coral) }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Cerrar", color = Muted) } },
    )
}

// ---------------------------------------------------------------- piezas

@Composable
private fun Card(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Panel)
            .border(1.dp, Border, RoundedCornerShape(14.dp)).padding(14.dp),
        content = content,
    )
}

@Composable
private fun Section(text: String, modifier: Modifier = Modifier) {
    Text(text, color = CoralSoft, fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp, modifier = modifier)
}

@Composable
private fun SolidButton(
    text: String, modifier: Modifier = Modifier, enabled: Boolean = true, tall: Boolean = false, onClick: () -> Unit,
) {
    Button(
        onClick = onClick, enabled = enabled, modifier = modifier.height(if (tall) 54.dp else 46.dp),
        shape = RoundedCornerShape(10.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = Coral, contentColor = Color.White, disabledContainerColor = Field, disabledContentColor = Disabled,
        ),
    ) { Text(text, fontWeight = FontWeight.Bold, fontSize = if (tall) 16.sp else 14.sp) }
}

@Composable
private fun SoftButton(text: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, modifier = modifier.height(46.dp), shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, Border),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = Field, contentColor = TextMain),
    ) { Text(text, fontWeight = FontWeight.Bold, fontSize = 14.sp) }
}

@Composable
private fun Chip(text: String, selected: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    val shape = RoundedCornerShape(10.dp)
    Box(
        Modifier.clip(shape)
            .background(if (selected) Coral else Field)
            .border(1.dp, if (selected) Coral else Border, shape)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text, fontWeight = FontWeight.Bold, fontSize = 14.sp,
            color = when {
                !enabled -> Disabled
                selected -> Color.White
                else -> TextMain
            },
        )
    }
}

@Composable
private fun Thumb(url: String?, modifier: Modifier) {
    var bmp by remember(url) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(url) {
        if (url != null) {
            bmp = withContext(Dispatchers.IO) {
                runCatching { URL(url).openStream().use { BitmapFactory.decodeStream(it) }?.asImageBitmap() }.getOrNull()
            }
        }
    }
    Box(modifier.background(Field), contentAlignment = Alignment.Center) {
        val b = bmp
        if (b != null) Image(b, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
        else Text("Vista previa", color = Muted)
    }
}

// ---------------------------------------------------------------- utilidades

private fun heightLabel(h: Int): String = when {
    h >= 4320 -> "${h}p 8K"
    h >= 2160 -> "${h}p 4K"
    h >= 1080 -> "${h}p HD"
    else -> "${h}p"
}

private fun fmtDuration(sec: Int): String? {
    if (sec <= 0) return null
    val h = sec / 3600
    val m = sec % 3600 / 60
    val s = sec % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}

private fun openFile(ctx: Context, job: Job) {
    val uri = job.savedUri?.let(Uri::parse) ?: return
    try {
        ctx.startActivity(
            Intent(Intent.ACTION_VIEW).setDataAndType(uri, job.savedMime ?: "*/*")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    } catch (_: ActivityNotFoundException) {
        Toast.makeText(ctx, "No hay ninguna app para abrir este archivo.", Toast.LENGTH_SHORT).show()
    }
}
