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
  EnvCheckPage: TInputOptionWizardPage;
  IsUpgrade: Boolean;

{ Force-terminate bridge_server.exe before files are copied (upgrade installs). }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';

  { Detect upgrade: bridge_server.exe already present means this overwrites }
  { an existing install. App dir is resolved and files not yet copied.      }
  IsUpgrade := FileExists(ExpandConstant('{app}\bridge_server.exe'));

  Exec('taskkill.exe', '/F /IM bridge_server.exe', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  { ResultCode 0 = process killed, 128 = process not found — both are fine. }
end;

{ Create environment-check page immediately after the Welcome page. }
procedure InitializeWizard;
begin
  EnvCheckPage := CreateInputOptionPage(wpWelcome,
    'Environment Check',
    'Verify system prerequisites before installation',
    'Would you like to run the environment checker now?',
    False, False);
  EnvCheckPage.Add('Yes — run environment check (recommended)');
  EnvCheckPage.Add('No  — skip and proceed directly to installation');
  EnvCheckPage.Values[0] := True;
end;

{ Gate the Next button on the environment-check page. }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;

  if CurPageID = EnvCheckPage.ID then
  begin
    if EnvCheckPage.SelectedValueIndex = 0 then
    begin
      { Extract check_env.exe to the temp directory, then run it. }
      ExtractTemporaryFile('check_env.exe');

      if not Exec(ExpandConstant('{tmp}\check_env.exe'), '', '',
                  SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      begin
        { Could not launch the checker — allow proceeding with a notice. }
        MsgBox('Unable to launch the environment checker.' + #13#10 +
               'Proceeding with installation.',
               mbInformation, MB_OK);
      end
      else if ResultCode = 1 then
      begin
        { One or more checks failed — ask the user whether to continue. }
        Result := MsgBox(
          'Some environment checks failed.' + #13#10 +
          'It is recommended to resolve the issues before installing.' + #13#10 + #13#10 +
          'Continue installation anyway?',
          mbConfirmation, MB_YESNO) = IDYES;
      end
      else if (ResultCode <> 0) and (ResultCode <> 2) then
      begin
        { Unknown exit code — checker may have crashed; warn and ask. }
        Result := MsgBox(
          'The environment checker exited unexpectedly (code: ' + IntToStr(ResultCode) + ').' + #13#10 +
          'This may indicate a crash. Continue installation anyway?',
          mbConfirmation, MB_YESNO) = IDYES;
      end;
      { ResultCode = 0 → all passed, proceed normally.              }
      { ResultCode = 2 → checker closed before checks ran (treated  }
      {                  as "skip"), proceed normally.               }
    end;
    { SelectedValueIndex = 1 → user chose Skip, proceed normally. }
  end;
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
