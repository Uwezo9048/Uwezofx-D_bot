; UWEZO-Deriv-Bot Trading Bot – Inno Setup Script
; Compatible with Windows 7 SP1, 8, 8.1, 10, and 11
; Version: 3.0
; Save as: UWEZO-Deriv-Bot.iss

[Setup]
AppId={{UWEZO-DERIV-BOT}}
AppName=UWEZO-Deriv Bot v3
AppVersion=3.0
AppPublisher=UWEZO-FX
AppPublisherURL=https://www.uwezofx.com
AppSupportURL=https://www.uwezofx.com/support
AppUpdatesURL=https://www.uwezofx.com/download
DefaultDirName={commonpf}\UWEZO-Deriv-Bot
DefaultGroupName=UWEZO-Deriv Bot
AllowNoIcons=yes
LicenseFile=LICENSE.txt
OutputDir=installer_output
OutputBaseFilename=UWEZO-Deriv-Bot_Setup_v3.0
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
MinVersion=6.1sp1
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
UsedUserAreasWarning=no
UninstallDisplayIcon={app}\UWEZO-Deriv-Bot.exe
UninstallDisplayName=UWEZO-Deriv Bot
VersionInfoVersion=3.0.0.0
VersionInfoCompany=UWEZO-FX
VersionInfoDescription=Deriv Multi-Strategy Trading Bot
VersionInfoCopyright=© 2026 UWEZO-FX

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a Start Menu icon"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "startupicon"; Description: "Launch at Windows startup"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Main executable
Source: "dist\UWEZO-Deriv-Bot.exe"; DestDir: "{app}"; Flags: overwritereadonly

; Data files (static – will not be overwritten if user modified them)
Source: "icon.png"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: ".env"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

; Entire modules folder (required for the app to run)
Source: "modules\*"; DestDir: "{app}\modules"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\UWEZO-Deriv Bot"; Filename: "{app}\UWEZO-Deriv-Bot.exe"; IconFilename: "{app}\icon.ico"; IconIndex: 0
Name: "{group}\Uninstall UWEZO-Deriv Bot"; Filename: "{uninstallexe}"
Name: "{autodesktop}\UWEZO-Deriv Bot"; Filename: "{app}\UWEZO-Deriv-Bot.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
Name: "{userstartup}\UWEZO-Deriv Bot"; Filename: "{app}\UWEZO-Deriv-Bot.exe"; IconFilename: "{app}\icon.ico"; Tasks: startupicon

[Run]
Filename: "{app}\UWEZO-Deriv-Bot.exe"; Description: "{cm:LaunchProgram,UWEZO-Deriv Bot}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Remove writable directories that the app creates at runtime
Type: filesandordirs; Name: "{userappdata}\UWEZO-Deriv-Bot"
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeSetup(): Boolean;
var
  Msg: string;
  WinVersion: TWindowsVersion;
begin
  Result := True;

  GetWindowsVersionEx(WinVersion);
  // Windows Vista and older warning
  if (WinVersion.Major = 6) and (WinVersion.Minor = 0) then
  begin
    Msg := 'Windows Vista is not officially supported. Some features may not work correctly.' + #13#10 +
           'Do you want to continue installation anyway?';
    if MsgBox(Msg, mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;

  // Check for required Windows version (7 SP1 or newer)
  if (WinVersion.Major < 6) or ((WinVersion.Major = 6) and (WinVersion.Minor < 1)) then
  begin
    Msg := 'Windows 7 SP1 or newer is required to run this application.' + #13#10 +
           'Your Windows version is too old. Installation will now exit.';
    MsgBox(Msg, mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Create writable directories in AppData if they don't exist
    ForceDirectories(ExpandConstant('{userappdata}\UWEZO-Deriv-Bot'));
  end;
end;