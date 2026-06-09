; ============================================================================
; Chat Mode Assistant — Inno Setup Installer Script
; Build: iscc setup.iss  (run from the installer/ directory)
; Output: C:\Intel\Chat_Mode_Assistant_Setup.exe
; ============================================================================

#define MyAppName      "Chat Mode Assistant"
#define MyAppVersion   "0.1.0"
#define MyAppPublisher "Intel"
#define MyNmName       "com.chat_mode_assistant.bridge"

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
OutputBaseFilename=Chat_Mode_Assistant_Setup

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
FinishedLabel=Setup has finished installing [name].%n%nNext: run "Configure Extension ID" to link your Chrome extension.

; ── Optional tasks ────────────────────────────────────────────────────────────
[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut for 'Configure Extension ID'"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

; ── Files ─────────────────────────────────────────────────────────────────────
[Files]
; Bridge server (standalone exe, no Python needed)
Source: "dist\bridge_server.exe"; DestDir: "{app}"; Flags: ignoreversion

; Native Messaging host launcher
Source: "dist\native_host.exe";   DestDir: "{app}"; Flags: ignoreversion

; Extension ID configurator GUI
Source: "dist\configure.exe";     DestDir: "{app}"; Flags: ignoreversion

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
Name: "{group}\Configure Extension ID";      Filename: "{app}\configure.exe"
Name: "{group}\Uninstall {#MyAppName}";      Filename: "{uninstallexe}"
Name: "{userdesktop}\Configure Chat Mode Assistant"; \
    Filename: "{app}\configure.exe"; Tasks: desktopicon

; ── Post-install: launch Configure wizard ────────────────────────────────────
[Run]
Filename: "{app}\configure.exe"; \
    Description: "Configure Chrome Extension ID (recommended)"; \
    Flags: nowait postinstall skipifsilent

; ── Uninstall cleanup ─────────────────────────────────────────────────────────
[UninstallDelete]
Type: files;           Name: "{app}\nm_manifest.json"
Type: files;           Name: "{app}\bridge.pid"
Type: files;           Name: "{app}\bridge_debug.log"
Type: filesandordirs;  Name: "{app}\log"
; Remove the install dir itself if empty after uninstall
Type: dirifempty;      Name: "{app}"

; ── Pascal code: generate nm_manifest.json at install time ───────────────────
[Code]

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
    '  "allowed_origins": ["chrome-extension://PLACEHOLDER_EXTENSION_ID/"]' + #13#10 +
    '}';

  SaveStringToFile(ManifestPath, Content, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteNativeHostManifest(ExpandConstant('{app}'));
end;
