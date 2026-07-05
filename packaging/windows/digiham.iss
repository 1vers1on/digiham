; Inno Setup script for the digiham Windows installer.
;
; Packages the PyInstaller one-folder build (dist\digiham) into a friendly
; setup.exe with Start-Menu and optional desktop shortcuts and an uninstaller.
;
; Build (from the repo root, after running PyInstaller):
;   iscc /DMyAppVersion=1.0.1 packaging\windows\digiham.iss
; The version defaults to 0.0.0 if not passed.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "digiham"
#define MyAppPublisher "Ellie"
#define MyAppURL "https://github.com/1vers1on/digiham"
#define MyAppExeName "digiham.exe"

[Setup]
AppId={{7B1C4E2A-3D5F-4A6B-9C0D-DIGIHAM00001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE.txt
OutputDir=..\..\dist
OutputBaseFilename=digiham-{#MyAppVersion}-windows-setup
SetupIconFile=..\..\assets\digiham.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller one-folder output.
Source: "..\..\dist\digiham\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
