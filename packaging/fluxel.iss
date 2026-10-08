#define MyAppName "Fluxel"
#ifndef MyAppVersion
  #define MyAppVersion "0.3.20260801"
#endif
#ifndef MyAppVersionDisplay
  #define MyAppVersionDisplay "v0.3.0-20260801"
#endif
#ifndef MyAppFileVersion
  #define MyAppFileVersion "0.3.0.0"
#endif
#define MyAppPublisher "Fluxel"
#define MyAppExeName "Fluxel.exe"

[Setup]
AppId={{A1F8C3B2-7D04-4E2A-9D77-1C4A2055E8B3}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersionDisplay}
AppPublisher={#MyAppPublisher}
AppCopyright=Copyright (C) {#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=Fluxel_Setup_{#MyAppVersionDisplay}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
AllowRootDirectory=no
UsePreviousAppDir=yes
SetupIconFile=..\fig\ico\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppFileVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppFileVersion}
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
InfoBeforeFile=installer-welcome.txt
ShowLanguageDialog=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Fluxel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Launch {#MyAppName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "Launch {#MyAppName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DatabaseDirPage: TInputDirWizardPage;

function LocatorFileName: String;
begin
  Result := ExpandConstant('{localappdata}\Fluxel\location.ini');
end;

function DefaultDatabaseDirectory: String;
begin
  Result := GetIniString('storage', 'database_dir', '', LocatorFileName);
  if Trim(Result) = '' then
    Result := ExpandConstant('{localappdata}\Fluxel');
end;

function LooksLikeOneDrive(const DirectoryName: String): Boolean;
begin
  Result := Pos('\onedrive', Lowercase(DirectoryName)) > 0;
end;

procedure InitializeWizard;
begin
  DatabaseDirPage := CreateInputDirPage(
    wpSelectDir,
    'Database location',
    'Choose where Fluxel stores its SQLite databases.',
    'Fluxel creates Tasks.db, QuickAccess.db, and Planning.db in this folder. A local folder is recommended.',
    False,
    '');
  DatabaseDirPage.Add('');
  DatabaseDirPage.Values[0] := DefaultDatabaseDirectory;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DatabaseDirPage.ID then
  begin
    if Trim(DatabaseDirPage.Values[0]) = '' then
    begin
      MsgBox('Choose a database folder before continuing.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if LooksLikeOneDrive(DatabaseDirPage.Values[0]) then
    begin
      Result := MsgBox(
        'SQLite files in OneDrive require special care.' + #13#10 + #13#10 +
        'Set the folder to Always keep on this device, never run Fluxel on two computers at once, and wait for sync to finish before switching computers.' + #13#10 + #13#10 +
        'Use this folder anyway?',
        mbConfirmation,
        MB_YESNO) = IDYES;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  LocatorDirectory: String;
begin
  if CurStep = ssPostInstall then
  begin
    LocatorDirectory := ExpandConstant('{localappdata}\Fluxel');
    ForceDirectories(LocatorDirectory);
    SetIniString('storage', 'database_dir', DatabaseDirPage.Values[0], LocatorFileName);
  end;
end;

function DeleteDatabasesRequested: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    if CompareText(ParamStr(I), '/FLUXELDELETEDB=1') = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

procedure DeleteDatabaseFamily(const FileName: String);
begin
  DeleteFile(FileName);
  DeleteFile(FileName + '-journal');
  DeleteFile(FileName + '-wal');
  DeleteFile(FileName + '-shm');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDirectory: String;
begin
  if (CurUninstallStep = usPostUninstall) and DeleteDatabasesRequested then
  begin
    DataDirectory := GetIniString(
      'storage',
      'database_dir',
      ExpandConstant('{localappdata}\Fluxel'),
      LocatorFileName);
    DeleteDatabaseFamily(AddBackslash(DataDirectory) + 'Tasks.db');
    DeleteDatabaseFamily(AddBackslash(DataDirectory) + 'QuickAccess.db');
    DeleteDatabaseFamily(AddBackslash(DataDirectory) + 'Planning.db');
  end;
end;
