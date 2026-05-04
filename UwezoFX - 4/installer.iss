; UWEZO-FX Trading System – Inno Setup Script
; Compatible with Windows 7 SP1, 8, 8.1, 10, and 11
; Version: 3.7
; Save as: UWEZO-FX.iss

[Setup]
AppId={{UWEZO-FX-TRADING-SYSTEM}}
AppName=UWEZO-FX Trading System
AppVersion=3.7
AppPublisher=UWEZO-FX
AppPublisherURL=https://www.uwezofx.com
AppSupportURL=https://www.uwezofx.com/support
AppUpdatesURL=https://www.uwezofx.com/download
DefaultDirName={commonpf}\UWEZO-FX
DefaultGroupName=UWEZO-FX
AllowNoIcons=yes
LicenseFile=LICENSE.txt
OutputDir=installer_output
OutputBaseFilename=UWEZO-FX_Setup_v3.7
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
MinVersion=6.1sp1
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
UsedUserAreasWarning=no
UninstallDisplayIcon={app}\UWEZO-FX.exe
UninstallDisplayName=UWEZO-FX Trading System
VersionInfoVersion=3.7.0.0
VersionInfoCompany=UWEZO-FX
VersionInfoDescription=Professional Trading System for MetaTrader 5
VersionInfoCopyright=© 2026 UWEZO-FX

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a Start Menu icon"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "startupicon"; Description: "Launch at Windows startup"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Main executable – overwrite even if read‑only
Source: "dist\UWEZO-FX.exe"; DestDir: "{app}"; Flags: overwritereadonly

; Data files (static – will not be overwritten if user modified them)
Source: "icon.png"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "my_photo.jpg"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: ".env"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "trading_config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

; Entire modules folder (overwrite all)
Source: "modules\*"; DestDir: "{app}\modules"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\UWEZO-FX"; Filename: "{app}\UWEZO-FX.exe"; IconFilename: "{app}\icon.ico"; IconIndex: 0
Name: "{group}\Uninstall UWEZO-FX"; Filename: "{uninstallexe}"
Name: "{autodesktop}\UWEZO-FX"; Filename: "{app}\UWEZO-FX.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
Name: "{userstartup}\UWEZO-FX"; Filename: "{app}\UWEZO-FX.exe"; IconFilename: "{app}\icon.ico"; Tasks: startupicon

[Run]
Filename: "{app}\UWEZO-FX.exe"; Description: "{cm:LaunchProgram,UWEZO-FX}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\profile_photos"
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeSetup(): Boolean;
var
  Msg: string;
  WinVersion: TWindowsVersion;
begin
  Result := True;

  GetWindowsVersionEx(WinVersion);
  if (WinVersion.Major = 6) and (WinVersion.Minor = 0) then
  begin
    Msg := 'Windows Vista is not officially supported. Some features may not work correctly.' + #13#10 +
           'Do you want to continue installation anyway?';
    if MsgBox(Msg, mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;

  if not RegKeyExists(HKEY_CURRENT_USER, 'Software\MetaQuotes\MT5') and
     not RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\MetaQuotes\MT5') then
  begin
    Msg := 'MetaTrader 5 does not appear to be installed on this computer.' + #13#10 +
           'UWEZO-FX requires MetaTrader 5 to be installed. Do you want to continue installation anyway?';
    if MsgBox(Msg, mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(ExpandConstant('{app}\logs'));
    ForceDirectories(ExpandConstant('{app}\profile_photos'));
    ForceDirectories(ExpandConstant('{app}\cache'));
  end;
end;