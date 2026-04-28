# -- Kerberos ticket check ---------------------------------------------------
$klistOutput = & klist 2>&1
$klistStr = $klistOutput -join "`n"
if ($klistStr -match "Cached Tickets" -or $klistStr -match "krbtgt") {
    Write-Host "[bridge] Kerberos ticket OK"
} else {
    Write-Warning "[bridge] No valid Kerberos ticket found."
    Write-Warning "[bridge] This will cause authentication errors when calling dt gnai."
    Write-Warning "[bridge] To refresh your Kerberos ticket, try one of the following:"
    Write-Warning "[bridge]   Option 1: Lock your Windows screen (Win+L) and unlock it to re-authenticate."
    Write-Warning "[bridge]   Option 2: If MIT Kerberos for Windows is installed, run kinit.exe from its install folder."
    Write-Warning "[bridge]             Common path: C:\Program Files\MIT\Kerberos\bin\kinit.exe"
    Write-Warning "[bridge]   Option 3: Run 'dt auth login' if your dt CLI has an auth command."
    Write-Warning "[bridge] Note: if your ticket was obtained in an admin PowerShell, it is NOT shared with this session."
    $confirm = Read-Host "[bridge] Continue anyway? (y/N)"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        exit 1
    }
}
# -----------------------------------------------------------------------------

# -- Kill any existing bridge on port 8775 ----------------------------------
$existingPid = (netstat -ano | Select-String ":8775\s.*LISTENING") -replace ".*\s(\d+)$", '$1' | Select-Object -First 1
if ($existingPid) {
    $proc = Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue
    $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$existingPid" -ErrorAction SilentlyContinue).CommandLine
    if ($proc -and $proc.Name -match "python" -and $cmdLine -match "bridge_server") {
        Write-Host "[bridge] found existing bridge_server (PID $existingPid), stopping it..."
        Stop-Process -Id ([int]$existingPid) -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        Write-Host "[bridge] old bridge stopped"
    } else {
        Write-Warning "[bridge] port 8775 is in use by another process (PID $existingPid, '$($proc.Name)') - not killing it. Please free the port manually."
        exit 1
    }
}
# -----------------------------------------------------------------------------

# -- Sync toolkit to C:\dt_sighting (no-spaces path required by dt gnai) -----
# $PSScriptRoot = .../GNAI_AssisChatter/bridge -> two levels up = repo root
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$toolkitSrc = Join-Path $repoRoot "SightingAssistantTool_latest"
$toolkitDst = "C:\dt_sighting"
if (Test-Path $toolkitSrc) {
    Write-Host "[bridge] syncing toolkit $toolkitSrc -> $toolkitDst"
    New-Item -ItemType Directory -Path $toolkitDst -Force | Out-Null
    foreach ($item in @("toolkit.yaml", "tools", "assistants", "src")) {
        $s = Join-Path $toolkitSrc $item
        $d = Join-Path $toolkitDst $item
        if (Test-Path $s) {
            if (Test-Path $d) { Remove-Item $d -Recurse -Force }
            Copy-Item $s $d -Recurse -Force
        }
    }
    Write-Host "[bridge] toolkit sync done"
} else {
    Write-Warning "[bridge] toolkit source not found: $toolkitSrc"
    Write-Warning "[bridge] Please do a fresh git clone (git pull may not work for first-time setup):"
    Write-Warning "[bridge]   git clone https://github.com/SteveChen182/GNAI_GCD_AssistChatter.git"
    Write-Warning "[bridge] Skipping toolkit sync - dt may fail if C:\dt_sighting does not exist."
}

# -- Ensure ~/.gnai/config.yaml points sighting toolkit to C:\dt_sighting ---
$gnaiConfig = "$env:USERPROFILE\.gnai\config.yaml"
if (Test-Path $gnaiConfig) {
    $lines = Get-Content $gnaiConfig
    $inSighting = $false
    $changed = $false
    $newLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $lines) {
        if ($line -match "^\s*-\s*name:\s*sighting\s*$") {
            $inSighting = $true
        } elseif ($line -match "^\s*-\s*name:") {
            $inSighting = $false
        }
        if ($inSighting -and $line -match "^\s*path:" -and $line -notmatch "dt_sighting") {
            $newLines.Add('    path: "C:\\dt_sighting"')
            Write-Host "[bridge] config.yaml: updating sighting path -> C:\dt_sighting"
            $changed = $true
        } else {
            $newLines.Add($line)
        }
    }
    if ($changed) {
        $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllLines($gnaiConfig, $newLines, $utf8NoBom)
        Write-Host "[bridge] config.yaml updated"
    } else {
        Write-Host "[bridge] config.yaml sighting path OK"
    }
} else {
    Write-Warning "[bridge] ~/.gnai/config.yaml not found -- skipping path check"
}
# -----------------------------------------------------------------------------

$env:GNAI_BRIDGE_HOST = "127.0.0.1"
$env:GNAI_BRIDGE_PORT = "8775"
$env:GNAI_BRIDGE_TIMEOUT = "360"
$env:GNAI_BRIDGE_DEFAULT_ASSISTANT = "sighting_assistant"
$env:GNAI_BRIDGE_DEBUG = "1"
$env:GNAI_BRIDGE_ECHO_RESPONSE = "1"
$env:GNAI_BRIDGE_MAX_FOLLOWUP_ROUNDS = "0"
$env:GNAI_BRIDGE_STREAM_EMIT_INTERVAL_SECONDS = "0.5"
$env:GNAI_BRIDGE_STREAM_READ_CHARS = "1024"
$env:GNAI_HIDE_THOUGHTS = "1"  # suppress AI internal reasoning/thinking output
# Optional:
# $env:GNAI_BRIDGE_API_KEY = "your-local-bridge-token"

# Optional: manually set full dt.exe path if needed.
# Example:
# $manualDtPath = "C:\Tools\dt\dt.exe"
$manualDtPath = ""  # Leave empty to auto-detect from PATH

if ($manualDtPath -and (Test-Path $manualDtPath)) {
	$env:GNAI_BRIDGE_DT_PATH = $manualDtPath
	Write-Host "[bridge] using manual dt path: $manualDtPath"
} else {
	# Clear stale override so bridge can still try PATH lookup.
	Remove-Item Env:GNAI_BRIDGE_DT_PATH -ErrorAction SilentlyContinue
	$dtCmd = Get-Command dt -ErrorAction SilentlyContinue
	if ($dtCmd) {
		$env:GNAI_BRIDGE_DT_PATH = $dtCmd.Source
		Write-Host "[bridge] using dt from PATH: $($dtCmd.Source)"
	} else {
		Write-Warning "dt not found. Please install dt CLI or set manualDtPath in run_bridge.ps1"
	}
}

python .\bridge_server.py
