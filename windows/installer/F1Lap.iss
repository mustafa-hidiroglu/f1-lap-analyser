; Inno Setup script: windows\dist\F1Lap (publish.ps1 + bundle-python.ps1) -> F1Lap-Setup-<ver>.exe.
; Per-user install (no admin prompt) into %LOCALAPPDATA%\Programs\F1Lap. Unsigned.
; Build: iscc /DAppVersion=0.1.0 windows\installer\F1Lap.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F4C2B1E-8A0D-4E5B-9C21-F1A9B0C3D7E2}
AppName=F1 Lap Analyser
AppVersion={#AppVersion}
AppPublisher=Mustafa Can Hidiroglu
DefaultDirName={localappdata}\Programs\F1Lap
DefaultGroupName=F1 Lap Analyser
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=F1Lap-Setup-{#AppVersion}-win-x64
Compression=lzma2/ultra64
SolidCompression=yes
UninstallDisplayIcon={app}\F1Lap.exe
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\F1Lap\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\F1 Lap Analyser"; Filename: "{app}\F1Lap.exe"
Name: "{autodesktop}\F1 Lap Analyser"; Filename: "{app}\F1Lap.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\F1Lap.exe"; Description: "{cm:LaunchProgram,F1 Lap Analyser}"; Flags: nowait postinstall skipifsilent
