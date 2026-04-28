param(
    [Parameter(Mandatory = $true)]
    [string]$ExtensionId,

    [ValidateSet("chrome", "edge")]
    [string]$Browser = "chrome"
)

$ErrorActionPreference = "Stop"

if (-not $ExtensionId -or $ExtensionId.Length -lt 10) {
    throw "Please provide a valid extension ID."
}

$bridgeDir = $PSScriptRoot
$hostScript = Join-Path $bridgeDir "native_host_launcher.py"
if (-not (Test-Path $hostScript)) {
    throw "native_host_launcher.py not found at: $hostScript"
}

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    throw "python is not found in PATH. Please install Python and retry."
}
$pythonExe = $pythonCmd.Source

$launcherCmdPath = Join-Path $bridgeDir "native_host_launcher.cmd"
$launcherCmdContent = "@echo off`r`n"
$launcherCmdContent += '"' + $pythonExe + '" "' + $hostScript + '"' + "`r`n"
Set-Content -Path $launcherCmdPath -Value $launcherCmdContent -Encoding ASCII

$hostName = "com.gnai.bridge_launcher"

if ($Browser -eq "edge") {
    $manifestDir = Join-Path $env:LOCALAPPDATA "Microsoft\Edge\User Data\NativeMessagingHosts"
    $registryPath = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName"
} else {
    $manifestDir = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data\NativeMessagingHosts"
    $registryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName"
}

New-Item -ItemType Directory -Path $manifestDir -Force | Out-Null
$manifestPath = Join-Path $manifestDir "$hostName.json"

$manifest = [ordered]@{
    name = $hostName
    description = "GNAI bridge launcher native host"
    path = $launcherCmdPath
    type = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}

$manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $manifestPath -Encoding ASCII

New-Item -Path $registryPath -Force | Out-Null
Set-ItemProperty -Path $registryPath -Name "(default)" -Value $manifestPath

Write-Host "Native host installed."
Write-Host "Browser: $Browser"
Write-Host "Manifest: $manifestPath"
Write-Host "Registry: $registryPath"
Write-Host "Allowed extension origin: chrome-extension://$ExtensionId/"
Write-Host "Restart browser and reload the extension to apply changes."
