# Compila la app y genera el instalador:  .\build.ps1
# Requisitos: Python 3.12 con las dependencias de requirements.txt, Inno Setup 6 y vendor\ffmpeg.exe
# (opcional pero recomendado: vendor\deno.exe, ver README).
#
# Python: variable de entorno PYTHON (ruta al python.exe) -> "py -3.12" -> "python" del PATH.
# Inno Setup: ISCC.exe del PATH -> carpetas de instalación habituales.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Resolve-Python {
    if ($env:PYTHON -and (Test-Path $env:PYTHON)) { return @($env:PYTHON) }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { return @("py", "-3.12") }
    }
    $p = Get-Command python -ErrorAction SilentlyContinue
    if ($p) { return @($p.Source) }
    throw "No se encontró Python 3.12. Instálalo o define la variable de entorno PYTHON con la ruta al python.exe."
}

function Resolve-Iscc {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidatos = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidatos) { if (Test-Path $c) { return $c } }
    throw "No se encontró ISCC.exe (Inno Setup 6). Instálalo (https://jrsoftware.org/isinfo.php) o añádelo al PATH."
}

$py = Resolve-Python
$pyExe = $py[0]
$pyArgs = @()
if ($py.Count -gt 1) { $pyArgs = $py[1..($py.Count - 1)] }
$iscc = Resolve-Iscc

if (-not (Test-Path "vendor\ffmpeg.exe")) { throw "Falta vendor\ffmpeg.exe" }
if (-not (Test-Path "vendor\deno.exe")) {
    Write-Warning "Falta vendor\deno.exe: sin un runtime de JavaScript YouTube puede ocultar resoluciones (ver README)."
}

$version = (Select-String -Path updater.py -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Compilando versión $version" -ForegroundColor Cyan

& $pyExe @pyArgs -m PyInstaller --noconfirm --onedir --windowed --name DescargadorYouTube `
    --icon icon.ico --add-data "icon.ico;." --collect-all yt_dlp --copy-metadata yt-dlp `
    --collect-all yt_dlp_ejs --copy-metadata yt-dlp-ejs app.py
if ($LASTEXITCODE) { throw "PyInstaller falló" }

# Firma digital OPCIONAL: solo si defines SIGN_COMMAND (ver docs\FIRMA.md). Sin ella se compila sin firmar.
$isccArgs = @("/DAppVersion=$version")
if ($env:SIGN_COMMAND) {
    Write-Host "Firmando el instalador con SIGN_COMMAND" -ForegroundColor Cyan
    $isccArgs += "/DSign=1"
    $isccArgs += "/Ssigntool=$env:SIGN_COMMAND"
}
& $iscc @isccArgs installer.iss
if ($LASTEXITCODE) { throw "Inno Setup falló" }

Write-Host "Listo: output\DescargadorYouTube-Setup.exe" -ForegroundColor Green
