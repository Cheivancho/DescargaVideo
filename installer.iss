; Instalador de Descargador de YouTube (Inno Setup 6)
; La versión se pasa desde build.ps1:  ISCC /DAppVersion=1.0.0 installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B6F1D6C2-5C1E-4D0B-9E57-7A2C6F0E1D41}
AppName=Descargador de YouTube
AppVersion={#AppVersion}
AppPublisher=Cheivancho
DefaultDirName={localappdata}\Programs\DescargadorYouTube
DefaultGroupName=Descargador de YouTube
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=DescargadorYouTube-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\DescargadorYouTube.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\DescargadorYouTube\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "vendor\ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion
; Runtime de JavaScript para YouTube (opcional al compilar; ver README)
Source: "vendor\deno.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\Descargador de YouTube"; Filename: "{app}\DescargadorYouTube.exe"
Name: "{autodesktop}\Descargador de YouTube"; Filename: "{app}\DescargadorYouTube.exe"; Tasks: desktopicon

[Run]
; Instalación normal: casilla "Abrir ahora"
Filename: "{app}\DescargadorYouTube.exe"; Description: "Abrir Descargador de YouTube"; Flags: nowait postinstall skipifsilent
; Actualización automática (silenciosa): se reabre sola
Filename: "{app}\DescargadorYouTube.exe"; Flags: nowait; Check: WizardSilent
