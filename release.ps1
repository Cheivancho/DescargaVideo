# Publica una versión nueva:  .\release.ps1 -Notas "Qué cambió"
# Antes: sube VERSION en updater.py y haz commit + push de los cambios.
param([Parameter(Mandatory)][string]$Notas)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = (Select-String -Path updater.py -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
$tag = "v$version"
cmd /c "gh release view $tag >nul 2>nul"
if ($LASTEXITCODE -eq 0) { throw "La release $tag ya existe. Sube VERSION en updater.py." }

& "$PSScriptRoot\build.ps1"
if ($LASTEXITCODE) { throw "Falló la compilación" }

# ZIP descargable: instalador + Leeme.txt
$stage = Join-Path $env:TEMP "DescargadorYouTube-zip"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $stage | Out-Null
Copy-Item output\DescargadorYouTube-Setup.exe, Leeme.txt $stage
# SHA-256 del instalador: la app lo exige para actualizarse (formato "hash  archivo", como sha256sum)
$setup = "output\DescargadorYouTube-Setup.exe"
$sha = "$setup.sha256"
$hash = (Get-FileHash -Algorithm SHA256 $setup).Hash.ToLower()
[IO.File]::WriteAllText((Join-Path $PWD $sha), "$hash  DescargadorYouTube-Setup.exe`n", (New-Object Text.UTF8Encoding $false))

$zip = "output\DescargadorYouTube.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path "$stage\*" -DestinationPath $zip

# Versión portable: la carpeta de dist\ + ffmpeg (+ deno) + portable.flag. Guarda sus datos en .\data
$portable = "output\DescargadorYouTube-portable.zip"
$pstage = Join-Path $env:TEMP "DescargadorYouTube-portable"
Remove-Item $pstage -Recurse -Force -ErrorAction SilentlyContinue
$papp = Join-Path $pstage "DescargadorYouTube"
New-Item -ItemType Directory $papp | Out-Null
Copy-Item "dist\DescargadorYouTube\*" $papp -Recurse
Copy-Item "vendor\ffmpeg.exe" $papp
if (Test-Path "vendor\deno.exe") { Copy-Item "vendor\deno.exe" $papp }
Copy-Item Leeme.txt $papp
New-Item -ItemType File (Join-Path $papp "portable.flag") | Out-Null
Remove-Item $portable -ErrorAction SilentlyContinue
Compress-Archive -Path $papp -DestinationPath $portable

$notesFile = Join-Path $env:TEMP "release-notes.md"
[IO.File]::WriteAllText($notesFile, $Notas, (New-Object Text.UTF8Encoding $false))
gh release create $tag $setup $sha $zip $portable --title "Descargador de YouTube $version" --notes-file $notesFile
if ($LASTEXITCODE) { throw "Falló la publicación" }
Write-Host "Publicada $tag" -ForegroundColor Green
