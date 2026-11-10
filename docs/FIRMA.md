# Firma digital del instalador

Hoy el instalador **no está firmado**, así que Windows SmartScreen muestra *«Windows protegió su PC»*. Firmarlo
elimina el aviso de «editor desconocido» y, con el tiempo, la advertencia de SmartScreen (la reputación se acumula
con las descargas; un certificado EV la da de inmediato). **Es un trámite manual tuyo**: hace falta una identidad
verificada y, normalmente, dinero o una solicitud aprobada. Nada del proyecto depende de ello: si no hay firma,
todo se compila y publica igual.

> **No confundir con el SHA-256.** El archivo `DescargaVideo-Setup.exe.sha256` protege contra descargas
> **corruptas**, pero no demuestra *quién* publicó el instalador: si alguien tomara el control de la cuenta de
> GitHub, publicaría también su propio hash. Solo una firma de código con un certificado emitido a tu nombre lo
> evita.

## Opciones

| Opción | Coste aproximado | Cuándo conviene |
|---|---|---|
| **SignPath Foundation** | Gratis para proyectos de código abierto que cumplan sus condiciones | Este repositorio es público y con licencia MIT: es la primera opción que vale la pena intentar. Hay que solicitarlo y que lo aprueben; la firma se hace en su servicio (integración con GitHub Actions). |
| **Azure Trusted Signing** (servicio de firma gestionada de Microsoft) | Suscripción mensual baja | No gestionas certificados ni hardware. Exige verificar tu identidad u organización y, según el momento, está limitado por país o tipo de cuenta. |
| **Certificado de una CA (OV / EV)** | Desde algunas decenas hasta cientos de euros al año | Es el camino clásico. Las CA exigen que la clave privada viva en un token/HSM, así que la firma desde CI es más incómoda (se firma en tu PC o con un servicio de firma en la nube de la CA). |
| **Certificado autofirmado** | Gratis | **No sirve para distribuir**: Windows no confía en él y SmartScreen seguirá avisando. Solo vale para probar el flujo de firma. |

Las condiciones, precios y países admitidos de estos servicios cambian con frecuencia: **comprueba la documentación
actual de cada proveedor** antes de decidir.

## Cómo está preparado el proyecto

La firma es **opcional** y solo se activa si defines lo necesario:

- **`installer.iss`**: si se compila con `/DSign=1` usa `SignTool=signtool` y firma también el desinstalador.
- **`build.ps1`**: si existe la variable de entorno `SIGN_COMMAND`, pasa a Inno Setup `/DSign=1` y
  `/Ssigntool=<SIGN_COMMAND>`. Dentro del comando, `$f` es el archivo que Inno Setup quiere firmar. Ejemplo local con
  un certificado `.pfx` (con signtool del Windows SDK):

  ```powershell
  $env:SIGN_COMMAND = '"C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe" sign /fd sha256 /td sha256 /tr http://timestamp.digicert.com /f "C:\ruta\firma.pfx" /p "CONTRASEÑA" $f'
  .\build.ps1
  ```

  Sin `SIGN_COMMAND`, `build.ps1` compila sin firmar, como hasta ahora.
- **`.github/workflows/release.yml`**: el paso *«Preparar la firma (opcional)»* solo se ejecuta si el repositorio tiene
  el secreto `SIGN_PFX_BASE64`. Entonces decodifica el `.pfx`, localiza `signtool.exe` en el runner y define
  `SIGN_COMMAND` para `build.ps1`.

## Pasos manuales para activar la firma en la CI con un `.pfx`

1. Obtén el certificado (`.pfx` con clave privada exportable; solo es posible si la CA lo permite).
2. Conviértelo a Base64: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("firma.pfx")) | Set-Clipboard`.
3. En GitHub: *Settings → Secrets and variables → Actions → New repository secret*:
   - `SIGN_PFX_BASE64`: el Base64 del `.pfx`.
   - `SIGN_PFX_PASSWORD`: su contraseña.
4. Publica una versión con un tag `vX.Y.Z`. El instalador saldrá firmado y el `.sha256` se calcula sobre el instalador
   ya firmado.

Con **SignPath** o **Azure Trusted Signing** el paso 3 cambia: ambos tienen su propia acción de GitHub y no usan un `.pfx`;
habría que sustituir el paso *«Preparar la firma»* por la acción del proveedor (siguiendo su documentación) y firmar
`output\DescargaVideo-Setup.exe` después de compilar.

## Qué falta por firmar

Inno Setup firma el instalador y el desinstalador. El `DescargaVideo.exe` que va **dentro** del instalador (y el de
la versión portable) no se firma con este flujo; si quieres firmarlo también, hay que firmarlo con `signtool` después de
PyInstaller y antes de ejecutar Inno Setup.
