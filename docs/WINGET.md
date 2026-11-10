# Publicar en winget

Con un manifiesto en el repositorio de la comunidad, cualquiera podrá instalar la app con
`winget install Cheivancho.DescargaVideo`. **Es un trámite manual tuyo** (una pull request a
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs)); nada del proyecto lo hace por ti.

## Requisitos

- Una Release publicada en GitHub (`vX.Y.Z`) con `DescargaVideo-Setup.exe`. La URL del instalador debe ser
  **estable y versionada**: `https://github.com/Cheivancho/descargador-youtube/releases/download/vX.Y.Z/DescargaVideo-Setup.exe`.
- [`wingetcreate`](https://github.com/microsoft/winget-create): `winget install wingetcreate`.
- Una cuenta de GitHub con `gh` configurado, o un token con permisos para abrir la PR.
- Recomendado: instalador **firmado** (ver `FIRMA.md`); sin firma, la validación automática puede mostrar advertencias de
  SmartScreen y algunos revisores lo cuestionan.

## Primera publicación

1. Publica la Release (`release.ps1` o la CI) y comprueba que la URL del instalador funciona.
2. Crea el manifiesto:

   ```powershell
   wingetcreate new https://github.com/Cheivancho/descargador-youtube/releases/download/v2.1.0/DescargaVideo-Setup.exe
   ```

   `wingetcreate` descarga el instalador, calcula su **SHA-256** y te pregunta los datos. Valores sugeridos:

   | Campo | Valor |
   |---|---|
   | `PackageIdentifier` | `Cheivancho.DescargaVideo` |
   | `PackageName` | `DescargaVideo` |
   | `Publisher` | `Cheivancho` |
   | `License` | `MIT` |
   | `ShortDescription` | DescargaVideo para Windows con interfaz oscura (todas las resoluciones, audio, ProRes/HAP…). |
   | `InstallerType` | `inno` (Inno Setup) |
   | `Scope` | `user` (se instala por usuario, sin permisos de administrador) |
   | `InstallerSwitches` → `Silent` / `SilentWithProgress` | `/SILENT /SUPPRESSMSGBOXES /NORESTART` / `/SILENT /SUPPRESSMSGBOXES /NORESTART` |
   | `Tags` | `youtube`, `downloader`, `yt-dlp`, `video` |

3. Valida y prueba el manifiesto en local (necesita habilitar manifiestos locales:
   `winget settings --enable LocalManifestFiles`):

   ```powershell
   winget validate --manifest .\manifests\c\Cheivancho\DescargaVideo\2.0.0
   winget install --manifest .\manifests\c\Cheivancho\DescargaVideo\2.0.0
   ```

4. Envíalo: `wingetcreate submit <carpeta del manifiesto>` abre la pull request. Un bot la valida (instalación,
   antivirus, hash) y un moderador la aprueba; puede tardar unos días y pedir cambios.

## Nuevas versiones

Cada versión nueva necesita su propia PR, pero es una sola orden:

```powershell
wingetcreate update Cheivancho.DescargaVideo --version 2.1.0 `
  --urls https://github.com/Cheivancho/descargador-youtube/releases/download/v2.1.0/DescargaVideo-Setup.exe `
  --submit
```

(Se puede automatizar con la acción [`vedantmgoyal9/winget-releaser`](https://github.com/vedantmgoyal9/winget-releaser) tras
publicar la Release, con un token personal guardado como secreto; es opcional y no está configurada.)

## Notas

- El hash del manifiesto debe coincidir con el instalador publicado: si vuelves a subir el `.exe` de una Release ya enviada
  a winget, el hash cambia y la validación falla. Publica siempre una versión nueva en vez de reemplazar archivos.
- La app se actualiza sola por su cuenta (ver README); winget y la actualización interna conviven sin problema, porque el
  instalador es el mismo.
- La versión **portable** no se publica en winget con este manifiesto.
