; DigMart Windows installer (roadmap #3). Built by CI with Inno Setup 6:
;   iscc /DAppName=DigMart /DAppVersion=0.7.2.123 /DSourceDir=dist\DigMart packaging\windows_installer.iss
;
; Installs per user into %LOCALAPPDATA%\Programs\DigMart (no admin prompt). That is deliberate: the
; auto-updater swaps the app folder in place, which Program Files would only allow with admin rights on
; every update. Firewall: the app's own one-step "Allow" (core/firewall.py) still covers the engine.
; Unsigned until the code-signing certificate exists (SmartScreen shows "More info -> Run anyway").

#ifndef AppName
  #define AppName "DigMart"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\" + AppName
#endif

[Setup]
AppId={{6C1E2B7A-3D4F-4E8B-9A51-D16A7F0C2E93}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile=..\build\app.ico
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the updater's old-copy backup sits beside the app; your music and the data folder are never touched
Type: filesandordirs; Name: "{app}.previous"
