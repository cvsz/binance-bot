;------------------------------------------------------------------------------
; Binance Spot Trading Bot — Windows Installer Script
; Compiler: Inno Setup 6 (https://jrsoftware.org/isinfo.php)
; Build:    iscc setup-windows.iss
;------------------------------------------------------------------------------

#define MyAppName "Binance Spot Trading Bot"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "ZeaZ Binance Bot"
#define MyAppURL "https://github.com/cvsz/binance-bot"
#define MyAppExeName "run.bat"

[Setup]
AppId={{{8C4A1F2B-3D5E-4F6A-8B9C-0D1E2F3A4B5C}}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=../../LICENSE
InfoBeforeFile=../../README-WINDOWS.md
OutputDir=../../reports/release
OutputFileName=binance-bot-windows-setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=low

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
Source: "../../bot\*"; DestDir: "{app}\bot"; Flags: ignoreversion recursesubdirs
Source: "../../run.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../constraints.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../requirements-dev.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../run.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../setup-windows.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../README-WINDOWS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../AGENTS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "../../Makefile"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\setup-windows.ps1"; Description: "{cm:LaunchProgram,{#StringChange('#MyAppName', ' ', '&')}} Setup"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: dirifempty; Name: "{app}"
Type: dirifempty; Name: "{app}\data"
Type: dirifempty; Name: "{app}\logs"
Type: dirifempty; Name: "{app}\reports"

[UninstallDelete]
Type: files; Name: "{app}\.env"
Type: files; Name: "{app}\config.yaml"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  
  { Check for Python }
  if not FileExists(ExpandConstant('{sys}')) then begin
  end;
  
  { Warn about real-money trading }
  if MsgBox('WARNING: Binance Spot Trading Bot' + #13#13 +
            'This bot trades REAL MONEY on Binance.' + #13#13 +
            'Before using live trading:' + #13 +
            '1. Backtest your strategy on historical data' + #13 +
            '2. Paper trade for 1-2 weeks' + #13 +
            '3. Test on Binance Testnet for 1 week' + #13 +
            '4. Only then use real money with funds you can afford to lose' + #13#13 +
            'Do you want to continue installation?',
            mbConfirmation, MB_YESNO) = idNo then
  begin
    Result := False;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
end;
