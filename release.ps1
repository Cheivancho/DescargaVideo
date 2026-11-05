# Publica una versión nueva:  .\release.ps1 -Notas "Qué cambió"
# Antes: sube VERSION en updater.py y haz commit + push de los cambios.
param([Parameter(Mandatory)][string]$Notas)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = (Select-String -Path updater.py -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
$tag = "v$version"
if (gh release view $tag 2>$null) { throw "La release $tag ya existe. Sube VERSION en updater.py." }

& "$PSScriptRoot\build.ps1"
if ($LASTEXITCODE) { throw "Falló la compilación" }

# ZIP descargable: instalador + Leeme.txt
$stage = Join-Path $env:TEMP "DescargadorYouTube-zip"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $stage | Out-Null
Copy-Item output\DescargadorYouTube-Setup.exe, Leeme.txt $stage
$zip = "output\DescargadorYouTube.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path "$stage\*" -DestinationPath $zip

gh release create $tag output\DescargadorYouTube-Setup.exe $zip --title "Descargador de YouTube $version" --notes $Notas
if ($LASTEXITCODE) { throw "Falló la publicación" }
Write-Host "Publicada $tag" -ForegroundColor Green
