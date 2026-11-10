; Instalador de DescargaVideo (Inno Setup 6)
; La versión se pasa desde build.ps1:  ISCC /DAppVersion=1.0.0 installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B6F1D6C2-5C1E-4D0B-9E57-7A2C6F0E1D41}
AppName=DescargaVideo
AppVersion={#AppVersion}
AppPublisher=Cheivancho
; Instalaciones nuevas: carpeta DescargaVideo. Quien ya tenía la app (mismo AppId) conserva SU carpeta anterior:
; Inno Setup reutiliza la ruta instalada (UsePreviousAppDir=yes por defecto), así que no se duplica nada.
DefaultDirName={localappdata}\Programs\DescargaVideo
DefaultGroupName=DescargaVideo
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=DescargaVideo-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\DescargaVideo.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
#ifdef Sign
; Firma opcional: build.ps1 pasa /DSign=1 y /Ssigntool=<comando> solo si existe SIGN_COMMAND (docs\FIRMA.md)
SignTool=signtool
SignedUninstaller=yes
#endif
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\DescargaVideo\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "vendor\ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion
; Runtime de JavaScript para YouTube (opcional al compilar; ver README)
Source: "vendor\deno.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[InstallDelete]
; Al actualizar desde la versión con el nombre anterior: quitar el ejecutable y los accesos directos viejos
Type: files; Name: "{app}\DescargadorYouTube.exe"
Type: files; Name: "{autoprograms}\Descargador de YouTube.lnk"
Type: files; Name: "{autodesktop}\Descargador de YouTube.lnk"

[Icons]
Name: "{autoprograms}\DescargaVideo"; Filename: "{app}\DescargaVideo.exe"
Name: "{autodesktop}\DescargaVideo"; Filename: "{app}\DescargaVideo.exe"; Tasks: desktopicon

[Run]
; Instalación normal: casilla "Abrir ahora"
Filename: "{app}\DescargaVideo.exe"; Description: "Abrir DescargaVideo"; Flags: nowait postinstall skipifsilent
; Actualización automática (silenciosa): se reabre sola
Filename: "{app}\DescargaVideo.exe"; Flags: nowait; Check: WizardSilent
