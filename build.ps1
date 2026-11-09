# Compila la app y genera el instalador:  .\build.ps1
# Requisitos: Python 3.12 con yt-dlp, pillow y pyinstaller; Inno Setup 6; vendor\ffmpeg.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py   = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path "vendor\ffmpeg.exe")) { throw "Falta vendor\ffmpeg.exe" }
if (-not (Test-Path "vendor\deno.exe")) {
    Write-Warning "Falta vendor\deno.exe: sin un runtime de JavaScript YouTube puede ocultar resoluciones (ver README)."
}

$version = (Select-String -Path updater.py -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Compilando versión $version" -ForegroundColor Cyan

& $py -m PyInstaller --noconfirm --onedir --windowed --name DescargadorYouTube `
    --icon icon.ico --add-data "icon.ico;." --collect-all yt_dlp --copy-metadata yt-dlp `
    --collect-all yt_dlp_ejs --copy-metadata yt-dlp-ejs app.py
if ($LASTEXITCODE) { throw "PyInstaller falló" }

& $iscc "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE) { throw "Inno Setup falló" }

Write-Host "Listo: output\DescargadorYouTube-Setup.exe" -ForegroundColor Green
