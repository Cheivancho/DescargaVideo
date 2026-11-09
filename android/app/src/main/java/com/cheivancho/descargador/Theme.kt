package com.cheivancho.descargador

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Misma paleta que la versión de escritorio
val Bg = Color(0xFF0E0E13)
val Panel = Color(0xFF16161D)
val Field = Color(0xFF1F1F29)
val Border = Color(0xFF2D2D3A)
val Coral = Color(0xFFF22E62)
val CoralSoft = Color(0xFFFF7A9B)
val TextMain = Color(0xFFECECF2)
val Muted = Color(0xFF8B8B9E)
val Disabled = Color(0xFF555566)
val Ok = Color(0xFF4CC38A)

private val Scheme = darkColorScheme(
    primary = Coral,
    onPrimary = Color.White,
    background = Bg,
    onBackground = TextMain,
    surface = Panel,
    onSurface = TextMain,
    surfaceVariant = Field,
    onSurfaceVariant = Muted,
    outline = Border,
    error = Color(0xFFFF6B6B),
)

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Scheme, content = content)
}
