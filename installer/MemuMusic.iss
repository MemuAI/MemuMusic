#ifndef AppVersion
  #error AppVersion must be supplied by build-installer.ps1
#endif

[Setup]
AppId=MemuMusic
AppName=MemuMusic
AppVersion={#AppVersion}
AppPublisher=MemuMusic
DefaultDirName={localappdata}\Programs\MemuMusic
DefaultGroupName=MemuMusic
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupMutex=Local\MemuMusic.Setup
CloseApplications=no
RestartApplications=no
AllowCancelDuringInstall=no
UninstallDisplayIcon={app}\MemuMusic.exe
#ifdef TestBuild
OutputDir=..\build\test-installer
OutputBaseFilename=MemuMusic-Setup-test
CreateUninstallRegKey=no
#else
OutputDir=..\dist
OutputBaseFilename=MemuMusic-Setup
#endif
SetupIconFile=..\memumusic\web\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[CustomMessages]
english.CloseMusic=Please close MemuMusic before installing or removing it, then try again.
russian.CloseMusic=Закройте MemuMusic перед установкой или удалением и повторите попытку.
english.WaitFailed=MemuMusic did not close in time. Your previous installation was not changed.
russian.WaitFailed=MemuMusic не закрылся вовремя. Предыдущая установка не изменена.
english.BadPid=The update process identifier is invalid. Your previous installation was not changed.
russian.BadPid=Неверный идентификатор процесса обновления. Предыдущая установка не изменена.
english.BackupFailed=Could not back up the existing application. The previous installation was not changed.
russian.BackupFailed=Не удалось создать резервную копию приложения. Предыдущая установка не изменена.
english.BackupExists=A previous recovery file already exists. It was left untouched; choose another time to retry.
russian.BackupExists=Файл восстановления уже существует. Он сохранён; повторите попытку позднее.
english.RestoreFailed=Could not restore the previous application automatically. Its backup is at: %1
russian.RestoreFailed=Не удалось автоматически восстановить прежнюю версию. Резервная копия: %1
english.LaunchMusic=Launch MemuMusic
russian.LaunchMusic=Запустить MemuMusic

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\MemuMusic.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
#ifdef TestBuild
Name: "{app}\test-shortcuts\MemuMusic"; Filename: "{app}\MemuMusic.exe"; WorkingDir: "{localappdata}"
#else
Name: "{autoprograms}\MemuMusic"; Filename: "{app}\MemuMusic.exe"; WorkingDir: "{localappdata}"
Name: "{autodesktop}\MemuMusic"; Filename: "{app}\MemuMusic.exe"; WorkingDir: "{localappdata}"; Tasks: desktopicon
#endif

#ifndef TestBuild
[Registry]
Root: HKCU; Subkey: "Software\MemuMusic"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty
#endif

[Run]
#ifdef TestBuild
Filename: "{app}\MemuMusic.exe"; Parameters: "--serve --data-dir ""{app}\test-profile"" --ready-file ""{app}\test-relaunch.ready"""; WorkingDir: "{localappdata}"; Flags: nowait skipifdoesntexist; Check: RelaunchRequested
#else
Filename: "{app}\MemuMusic.exe"; WorkingDir: "{localappdata}"; Description: "{cm:LaunchMusic}"; Flags: nowait postinstall skipifsilent; Check: not RelaunchRequested
Filename: "{app}\MemuMusic.exe"; WorkingDir: "{localappdata}"; Flags: nowait skipifdoesntexist; Check: RelaunchRequested
#endif

[Code]
const
  SynchronizeAccess = $00100000;
  WaitObject0 = 0;
  WaitTimeout = 258;
  InvalidHandleValue = -1;
  GenericRead = $80000000;
  GenericWrite = $40000000;
  OpenExisting = 3;
  ErrorInvalidParameter = 87;

var
  BackupPath: String;
  BackupMade: Boolean;
  InstallCompleted: Boolean;

function OpenProcess(DesiredAccess: Cardinal; InheritHandle: Boolean; ProcessId: Cardinal): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(Handle: THandle; Milliseconds: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function GetLastError: Cardinal;
  external 'GetLastError@kernel32.dll stdcall';
function GetCurrentProcessId: Cardinal;
  external 'GetCurrentProcessId@kernel32.dll stdcall';
function CreateFileW(FileName: String; DesiredAccess, ShareMode: Cardinal; SecurityAttributes: Cardinal;
  CreationDisposition, FlagsAndAttributes: Cardinal; TemplateFile: THandle): THandle;
  external 'CreateFileW@kernel32.dll stdcall';

function RelaunchRequested: Boolean;
begin
  Result := ExpandConstant('{param:MMRELAUNCH|0}') = '1';
end;

function IsApplicationFree(const Path: String): Boolean;
var
  Handle: THandle;
begin
  Result := True;
  if not FileExists(Path) then Exit;
  Handle := CreateFileW(Path, GenericRead or GenericWrite, 0, 0, OpenExisting, 0, 0);
  Result := Handle <> InvalidHandleValue;
  if Result then CloseHandle(Handle);
end;

function WaitForApplication: String;
var
  Text: String;
  Pid, I: Integer;
  Handle: THandle;
  WaitResult, ErrorCode: Cardinal;
begin
  Result := '';
  Text := ExpandConstant('{param:MMWAITPID|0}');
  Pid := StrToIntDef(Text, -1);
  if Pid < 0 then begin Result := CustomMessage('BadPid'); Exit; end;
  if Pid > 0 then begin
    Handle := OpenProcess(SynchronizeAccess, False, Cardinal(Pid));
    if Handle = 0 then begin
      ErrorCode := GetLastError;
      if ErrorCode <> ErrorInvalidParameter then begin Result := CustomMessage('WaitFailed'); Exit; end;
    end else begin
      WaitResult := WaitForSingleObject(Handle, 60000);
      CloseHandle(Handle);
      if WaitResult <> WaitObject0 then begin Result := CustomMessage('WaitFailed'); Exit; end;
    end;
  end;
  for I := 0 to 120 do begin
    if IsApplicationFree(ExpandConstant('{app}\MemuMusic.exe')) then Exit;
    if Pid = 0 then begin Result := CustomMessage('CloseMusic'); Exit; end;
    Sleep(250);
  end;
  Result := CustomMessage('WaitFailed');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Target: String;
begin
  Result := WaitForApplication;
  if Result <> '' then Exit;
  Target := ExpandConstant('{app}\MemuMusic.exe');
  if FileExists(Target) then begin
    BackupPath := ExpandConstant('{app}\MemuMusic.restore-') + IntToStr(GetCurrentProcessId) + '.exe';
    if FileExists(BackupPath) then begin Result := CustomMessage('BackupExists'); Exit; end;
    if not CopyFile(Target, BackupPath, True) then begin Result := CustomMessage('BackupFailed'); Exit; end;
    BackupMade := True;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  #ifdef TestBuild
  if (CurStep = ssInstall) and (ExpandConstant('{param:MMFAIL|0}') = '1') then begin
    if not SaveStringToFile(ExpandConstant('{app}\MemuMusic.exe'), 'simulated partial replacement', False) then
      RaiseException('Could not set up simulated failure');
    Abort;
  end;
  #endif
  if CurStep = ssPostInstall then begin
    InstallCompleted := True;
    if BackupMade then begin
      if DeleteFile(BackupPath) then begin
        BackupMade := False;
        Log('Removed backup after successful install: ' + BackupPath);
      end else Log('Could not remove backup after successful install: ' + BackupPath + ', error ' + IntToStr(GetLastError));
    end;
  end;
end;

procedure DeinitializeSetup;
var
  Target, MessageText: String;
begin
  if not BackupMade then Exit;
  if InstallCompleted then begin
    DeleteFile(BackupPath);
    Exit;
  end;
  Target := ExpandConstant('{app}\MemuMusic.exe');
  if CopyFile(BackupPath, Target, False) then DeleteFile(BackupPath)
  else begin
    MessageText := FmtMessage(CustomMessage('RestoreFailed'), [BackupPath]);
    Log(MessageText);
    if not WizardSilent then MsgBox(MessageText, mbError, MB_OK);
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := IsApplicationFree(ExpandConstant('{app}\MemuMusic.exe'));
  if not Result and not UninstallSilent then MsgBox(CustomMessage('CloseMusic'), mbError, MB_OK);
end;
