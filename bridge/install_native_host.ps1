<#
.SYNOPSIS
    One-time setup: registers the Native Messaging Host for Chrome.

.DESCRIPTION
    After loading the Chat Mode Assistant extension in Chrome:
    1. Copy the Extension ID from chrome://extensions/
    2. Run: .\install_native_host.ps1 -ExtensionId <your-id>

    This allows the extension to auto-launch the bridge server.
#>
param(
    [Parameter(Mandatory=$false)]
    [string]$ExtensionId
)

$ErrorActionPreference = "Stop"
$NmName = "com.chat_mode_assistant.bridge"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "=== Chat Mode Assistant - Native Messaging Setup ===" -ForegroundColor Cyan
Write-Host ""

# ── Get Extension ID ────────────────────────────────────────────────────
if (-not $ExtensionId) {
    Write-Host "To find your Extension ID:" -ForegroundColor Yellow
    Write-Host "  1. Go to chrome://extensions/"
    Write-Host "  2. Enable Developer mode (top-right toggle)"
    Write-Host "  3. Find 'Chat Mode Assistant'"
    Write-Host "  4. Copy the ID (32-char lowercase string)"
    Write-Host ""
    $ExtensionId = Read-Host "Enter your Chrome Extension ID"
}

if ($ExtensionId.Length -lt 20) {
    Write-Host "ERROR: Extension ID looks too short. Expected 32-char ID." -ForegroundColor Red
    exit 1
}

Write-Host "  Extension ID: $ExtensionId"

# ── Resolve Python path ─────────────────────────────────────────────────
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "ERROR: python not found in PATH." -ForegroundColor Red
    exit 1
}
$PythonPath = $pythonCmd.Source
Write-Host "  Python: $PythonPath"

# ── Create native_host.cmd wrapper ──────────────────────────────────────
$hostScript = Join-Path $ScriptDir "native_host.py"
$cmdPath = Join-Path $ScriptDir "native_host.cmd"
@"
@echo off
"$PythonPath" "$hostScript"
"@ | Set-Content -Path $cmdPath -Encoding ASCII
Write-Host "  Launcher: $cmdPath"

# ── Create NM manifest JSON ─────────────────────────────────────────────
$manifestPath = Join-Path $ScriptDir "$NmName.json"
$manifest = @{
    name            = $NmName
    description     = "Chat Mode Assistant Bridge Launcher"
    path            = $cmdPath
    type            = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -Path $manifestPath -Encoding UTF8
Write-Host "  Manifest: $manifestPath"

# ── Register in Windows Registry ────────────────────────────────────────
$regPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$NmName"
if (-not (Test-Path $regPath)) {
    New-Item -Path $regPath -Force | Out-Null
}
Set-ItemProperty -Path $regPath -Name "(Default)" -Value $manifestPath
Write-Host "  Registry: $regPath"

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "The extension will now auto-launch the bridge when opened." -ForegroundColor Green
Write-Host ""
