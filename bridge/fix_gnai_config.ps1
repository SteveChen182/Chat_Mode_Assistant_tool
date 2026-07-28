# fix_gnai_config.ps1
# Run this script whenever `dt gnai toolkits register/unregister` corrupts ~/.gnai/config.yaml
# Usage: .\bridge\fix_gnai_config.ps1

$gnaiDir = Join-Path $env:USERPROFILE ".gnai"
$toolkitsDir = Join-Path $gnaiDir "toolkits"
$sightingCandidates = @(
  (Join-Path $PSScriptRoot "..\external\SightingAssistantTool"),
  (Join-Path $toolkitsDir "SightingAssistantTool"),
  (Join-Path $toolkitsDir "sighting")
)
$toolkitPath = $sightingCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $toolkitPath) {
  $toolkitPath = $sightingCandidates[1]
}
$sherlogPath = Join-Path $toolkitsDir "drivers.gpu.core.sherlog-toolkit"
$displayDebuggerPath = Join-Path $toolkitsDir "displaydebugger"
$configPath = Join-Path $gnaiDir "config.yaml"

$content = @"
toolkits:
- name: sherlog
  type: github
  path: '$sherlogPath'
  url: https://github.com/intel-innersource/drivers.gpu.core.sherlog-toolkit
- name: displaydebugger
  type: github
  path: '$displayDebuggerPath'
  url: https://github.com/intel-sandbox/displaydebugger
- name: sighting
  type: github
  path: '$toolkitPath'
  url: https://github.com/intel-sandbox/SightingAssistantTool.git
env: {}
"@

# Remove read-only flag before writing (in case it was locked)
New-Item -ItemType Directory -Path $gnaiDir -Force | Out-Null
attrib -R $configPath 2>$null

[System.IO.File]::WriteAllText(
    $configPath,
    $content,
    (New-Object System.Text.UTF8Encoding $false)   # no BOM — dt's Go YAML parser rejects BOM
)

Write-Host "[OK] config.yaml fixed." -ForegroundColor Green
Get-Content $configPath
