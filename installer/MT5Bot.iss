; Online installer for MT5Bot.
;
; Version-agnostic: at install time it reads latest.json (the same manifest the running
; bot polls for self-updates), downloads MT5Bot-<ver>.exe from the releases bucket,
; verifies its SHA-256, and installs it per-user. Build this once and it never goes
; stale -- the version lives in latest.json, not in this installer.
;
; Compile with build_installer.py, which supplies ManifestUrl from .env:
;     ISCC.exe /DManifestUrl="https://.../releases/latest.json" installer\MT5Bot.iss

#ifndef ManifestUrl
  #error ManifestUrl is required: build via build_installer.py (passes /DManifestUrl=...)
#endif

[Setup]
AppId={{8F1A7C2E-3B4D-4E6A-9C1F-7A2D5E8B0C31}
AppName=MT5Bot
AppVerName=MT5Bot
AppPublisher=MT5Bot
DefaultDirName={localappdata}\MT5Bot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
CloseApplications=yes
OutputDir=..\dist
OutputBaseFilename=MT5Bot-Setup
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\MT5Bot.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Downloaded to {tmp} by the [Code] section below; `external` means it is taken at
; install time from that path rather than compiled into the installer.
Source: "{tmp}\MT5Bot.exe"; DestDir: "{app}"; Flags: external ignoreversion

[Icons]
Name: "{autoprograms}\MT5Bot"; Filename: "{app}\MT5Bot.exe"
Name: "{autodesktop}\MT5Bot"; Filename: "{app}\MT5Bot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MT5Bot.exe"; Description: "Launch MT5Bot"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadPage: TDownloadWizardPage;
  ExeUrl, ExeSha, ExeVersion: String;

// Inno's Pascal Script has no PosEx, so we walk a shrinking remainder with Pos/Copy.
function JsonString(const Json, Key: String; var Value: String): Boolean;
var
  Rest: String;
  P: Integer;
begin
  Result := False;
  P := Pos('"' + Key + '"', Json);
  if P = 0 then Exit;
  Rest := Copy(Json, P + Length(Key) + 2, Length(Json));
  P := Pos(':', Rest);
  if P = 0 then Exit;
  Rest := Copy(Rest, P + 1, Length(Rest));
  P := Pos('"', Rest);
  if P = 0 then Exit;
  Rest := Copy(Rest, P + 1, Length(Rest));
  P := Pos('"', Rest);
  if P = 0 then Exit;
  Value := Copy(Rest, 1, P - 1);
  Result := True;
end;

function FetchManifest: Boolean;
var
  WinHttp: Variant;
  Body: String;
begin
  Result := False;
  try
    WinHttp := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    WinHttp.Open('GET', '{#ManifestUrl}', False);
    WinHttp.Send;
    if WinHttp.Status <> 200 then Exit;
    Body := WinHttp.ResponseText;
  except
    Exit;
  end;
  if not JsonString(Body, 'url', ExeUrl) then Exit;
  if not JsonString(Body, 'sha256', ExeSha) then Exit;
  JsonString(Body, 'version', ExeVersion);
  Result := True;
end;

function InitializeSetup: Boolean;
begin
  Result := FetchManifest;
  if not Result then
    MsgBox('Could not reach the MT5Bot release server. Check your internet connection and try again.',
      mbCriticalError, MB_OK);
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading MT5Bot', 'Fetching the latest version...', nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  if CurPageID = wpReady then begin
    DownloadPage.Clear;
    // Third arg is the expected SHA-256: Inno verifies it during the download and
    // raises on mismatch, so a corrupt or tampered binary never gets installed.
    DownloadPage.Add(ExeUrl, 'MT5Bot.exe', ExeSha);
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        Result := True;
      except
        if not DownloadPage.AbortedByUser then
          MsgBox('Download failed: ' + AddPeriod(GetExceptionMessage), mbCriticalError, MB_OK);
        Result := False;
      end;
    finally
      DownloadPage.Hide;
    end;
  end else
    Result := True;
end;
