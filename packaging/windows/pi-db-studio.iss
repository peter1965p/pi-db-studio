; Inno-Setup-Skript für Pi DB Studio (Windows). Erwartet dist\PiDBStudio aus PyInstaller.
; Aufruf: iscc /DVersion=0.5.1 packaging\windows\pi-db-studio.iss
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6E2B4C7A-3F1D-4C55-9B7E-1D0A5C2F9E31}
AppName=Pi DB Studio
AppVersion={#Version}
AppPublisher=Päffgen IT
AppPublisherURL=https://github.com/peter1965p/pi-db-studio
DefaultDirName={autopf}\Pi DB Studio
DefaultGroupName=Pi DB Studio
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=PiDBStudio-{#Version}-Windows-Setup
SetupIconFile=pi-db-studio.ico
UninstallDisplayIcon={app}\PiDBStudio.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktop"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\PiDBStudio\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Pi DB Studio"; Filename: "{app}\PiDBStudio.exe"
Name: "{autodesktop}\Pi DB Studio"; Filename: "{app}\PiDBStudio.exe"; Tasks: desktop

[Run]
Filename: "{app}\PiDBStudio.exe"; Description: "{cm:LaunchProgram,Pi DB Studio}"; Flags: nowait postinstall skipifsilent
