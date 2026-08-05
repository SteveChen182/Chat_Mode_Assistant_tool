; ============================================================================
; Chat Mode Assistant — Inno Setup Installer Script
; Build: iscc setup.iss  (run from the installer/ directory)
; Output: C:\Intel\Chat_Mode_Assistant_Setup.exe
; ============================================================================

#define MyAppName      "Chat Mode Assistant"
; MyAppVersion is normally injected by build.ps1 via /DMyAppVersion=x.y.z
; Fall back to a placeholder when compiling setup.iss directly without build.ps1.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Intel"
#define MyNmName       "com.chat_mode_assistant.bridge"
#define ExtensionId    "pmbnnkfhdkommfpphknjpppmlmbihomi"

; ── Setup ────────────────────────────────────────────────────────────────────
[Setup]
AppId={{A3C7E2F1-B894-4D56-9E12-6F0A8B3C7D4E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppComments=Chrome Extension + Python Bridge for Intel GNAI Sighting Assistant

; Install to user AppData — no admin rights required
DefaultDirName={localappdata}\ChatModeAssistant
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; Output installer to C:\Intel\
OutputDir=C:\Intel
OutputBaseFilename=Chat_Mode_Assistant_Setup_{#MyAppVersion}

; Compression
Compression=lzma2/max
SolidCompression=yes

; No admin required (HKCU registry, user AppData)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Visual
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\bridge_server.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ── Finish page message ───────────────────────────────────────────────────────
[Messages]
FinishedLabel=Installation complete. See instructions below.


; ── Files ─────────────────────────────────────────────────────────────────────
[Files]
; Environment checker — extracted to temp dir for pre-install check only
Source: "dist\check_env.exe"; DestDir: "{tmp}"; Flags: nocompression dontcopy

; Bridge server (standalone exe, no Python needed)
Source: "dist\bridge_server.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\bridge\fix_gnai_config.ps1"; DestDir: "{app}"; Flags: ignoreversion

; Native Messaging host launcher
Source: "dist\native_host.exe";   DestDir: "{app}"; Flags: ignoreversion

; Chrome Extension files (user loads these manually in chrome://extensions/)
Source: "..\extension\*"; DestDir: "{app}\extension"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; ── Upgrade cleanup ──────────────────────────────────────────────────────────
; Recreate the Extension tree so files removed by a newer release cannot remain.
; Runtime identity files are disposable and must never cross an upgrade.
; Logs, driver history, Chrome storage, and ~/.gnai data are intentionally kept.
[InstallDelete]
Type: filesandordirs; Name: "{app}\extension"
Type: files;          Name: "{app}\configure.exe"
Type: files;          Name: "{app}\bridge.pid"
Type: files;          Name: "{app}\bridge.port"
Type: files;          Name: "{app}\bridge.discovery.json"

; ── Registry ──────────────────────────────────────────────────────────────────
; Register Native Messaging host so Chrome can find native_host.exe
[Registry]
Root: HKCU; \
    Subkey: "Software\Google\Chrome\NativeMessagingHosts\{#MyNmName}"; \
    ValueType: string; ValueName: ""; \
    ValueData: "{app}\nm_manifest.json"; \
    Flags: uninsdeletekey

; ── Shortcuts ─────────────────────────────────────────────────────────────────
[Icons]
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

; ── Post-install: launch Configure wizard ────────────────────────────────────
[Run]
; Open extension folder after install
Filename: "{app}\extension"; \
    Description: "Open extension folder (for Chrome 'Load unpacked')"; \
    Flags: shellexec nowait postinstall skipifsilent

; ── Uninstall cleanup ─────────────────────────────────────────────────────────
[UninstallDelete]
Type: files;           Name: "{app}\nm_manifest.json"
Type: files;           Name: "{app}\configure.exe"
Type: files;           Name: "{app}\bridge.pid"
Type: files;           Name: "{app}\bridge.port"
Type: files;           Name: "{app}\bridge.discovery.json"
Type: files;           Name: "{app}\bridge_debug.log"
Type: filesandordirs;  Name: "{app}\log"
; Remove the install dir itself if empty after uninstall
Type: dirifempty;      Name: "{app}"

; ── Pascal code: generate nm_manifest.json at install time ───────────────────
[Code]

var
  EnvCheckPage: TWizardPage;
  EnvCheckButton: TNewButton;
  IsUpgrade: Boolean;

{ Prevent Chrome from relaunching old binaries, then stop the entire Bridge tree. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';

  { Detect upgrade: bridge_server.exe already present means this overwrites }
  { an existing install. App dir is resolved and files not yet copied.      }
  IsUpgrade := FileExists(ExpandConstant('{app}\bridge_server.exe'));

  if IsUpgrade then
  begin
    { Temporarily disable Native Messaging until ssPostInstall recreates it. }
    DeleteFile(ExpandConstant('{app}\nm_manifest.json'));

    Exec('taskkill.exe', '/F /T /IM native_host.exe', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /T /IM bridge_server.exe', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
    { ResultCode 0 = process killed, 128 = process not found — both are fine. }

    DeleteFile(ExpandConstant('{app}\bridge.pid'));
    DeleteFile(ExpandConstant('{app}\bridge.port'));
    DeleteFile(ExpandConstant('{app}\bridge.discovery.json'));
  end;
end;

{ Runs check_env.exe on demand; installation is never gated on its result. }
procedure EnvCheckButtonClick(Sender: TObject);
var
  ResultCode: Integer;
begin
  ExtractTemporaryFile('check_env.exe');

  if not Exec(ExpandConstant('{tmp}\check_env.exe'), '', '',
              SW_SHOW, ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox('Unable to launch the environment checker.', mbError, MB_OK);
  end;
end;

{ Create environment-check page immediately after the Welcome page. }
procedure InitializeWizard;
var
  Lbl: TNewStaticText;
begin
  EnvCheckPage := CreateCustomPage(wpWelcome,
    'Environment Check',
    'Verify system prerequisites before installation (optional)');

  Lbl := TNewStaticText.Create(EnvCheckPage);
  Lbl.Parent := EnvCheckPage.Surface;
  Lbl.AutoSize := True;
  Lbl.WordWrap := True;
  Lbl.Width := EnvCheckPage.SurfaceWidth;
  Lbl.Caption :=
    'Click the button below to check whether required tools (Intel dt CLI, GNAI, ' +
    'toolkits) are installed. This is optional — you can also skip it and click ' +
    'Next to proceed directly to installation.';

  EnvCheckButton := TNewButton.Create(EnvCheckPage);
  EnvCheckButton.Parent := EnvCheckPage.Surface;
  EnvCheckButton.Caption := 'Run Environment Check...';
  EnvCheckButton.Left := 0;
  EnvCheckButton.Top := Lbl.Top + Lbl.Height + 16;
  EnvCheckButton.Width := 180;
  EnvCheckButton.Height := 28;
  EnvCheckButton.OnClick := @EnvCheckButtonClick;
end;

{ Write nm_manifest.json pointing to native_host.exe in the install directory. }
procedure WriteNativeHostManifest(AppDir: String);
var
  NativeHostPath : String;
  ManifestPath   : String;
  Content        : String;
begin
  NativeHostPath := AppDir + '\native_host.exe';
  ManifestPath   := AppDir + '\nm_manifest.json';

  { JSON content — escape backslashes for the "path" field }
  { StringChange is the Inno Setup built-in for in-place string replacement }
  StringChange(NativeHostPath, '\', '\\');
  Content :=
    '{' + #13#10 +
    '  "name": "com.chat_mode_assistant.bridge",' + #13#10 +
    '  "description": "Chat Mode Assistant Bridge Launcher",' + #13#10 +
    '  "path": "' + NativeHostPath + '",' + #13#10 +
    '  "type": "stdio",' + #13#10 +
    '  "allowed_origins": ["chrome-extension://{#ExtensionId}/"]' + #13#10 +
    '}';

  SaveStringToFile(ManifestPath, Content, False);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    if IsUpgrade then
    begin
      WizardForm.FinishedLabel.Caption :=
        'Update complete!' + #13#10 + #13#10 +
        'IMPORTANT: You must reload the extension in Chrome for the' + #13#10 +
        'update to take effect.' + #13#10 + #13#10 +
        '  1. Open Chrome  >>  chrome://extensions/' + #13#10 +
        '  2. Find "Chat Mode Assistant"' + #13#10 +
        '  3. Click the reload icon (circular arrow)';
      WizardForm.FinishedLabel.AutoSize := True;

      { Pop up a reminder so the user does not miss the reload step. }
      MsgBox(
        'Update installed successfully.' + #13#10 + #13#10 +
        'Please reload the extension in Chrome for the changes to take effect:' + #13#10 + #13#10 +
        '  1. Open  chrome://extensions/' + #13#10 +
        '  2. Find "Chat Mode Assistant"' + #13#10 +
        '  3. Click the reload (circular arrow) icon.',
        mbInformation, MB_OK);
    end
    else
    begin
      WizardForm.FinishedLabel.Caption :=
        'Installation complete!' + #13#10 + #13#10 +
        'Last step: load the Chrome extension.' + #13#10 + #13#10 +
        '  1. Open Chrome  >>  chrome://extensions/' + #13#10 +
        '  2. Enable "Developer Mode" (top-right toggle)' + #13#10 +
        '  3. Click "Load unpacked"' + #13#10 +
        '  4. Select this folder:' + #13#10 +
        '     ' + ExpandConstant('{app}\extension');
      WizardForm.FinishedLabel.AutoSize := True;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteNativeHostManifest(ExpandConstant('{app}'));
end;
