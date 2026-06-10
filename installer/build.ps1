<#
.SYNOPSIS
    Builds Chat_Mode_Assistant_Setup.exe -> C:\Intel\

.DESCRIPTION
    1. Checks / installs PyInstaller
    2. Bundles bridge_server.py, native_host.py, configure.py with PyInstaller
    3. Runs Inno Setup Compiler (ISCC) to produce the installer
    Output: C:\Intel\Chat_Mode_Assistant_Setup.exe

.NOTES
    Run from the project root:  .\installer\build.ps1
    Requires:
      - Python 3.10+  with  pip install pywinpty
      - Inno Setup 6  (https://jrsoftware.org/isinfo.php)
#>

$ErrorActionPreference = "Stop"

# Paths
$ProjectRoot  = Split-Path -Parent $PSScriptRoot
$InstallerDir = $PSScriptRoot
$DistDir      = Join-Path $InstallerDir "dist"
$BuildDir     = Join-Path $InstallerDir "build"
$OutputDir    = "C:\Intel"

Write-Host ""
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  Chat Mode Assistant -- Installer Build"       -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host ""

function Step {
    param([string]$msg)
    Write-Host ""
    Write-Host "[STEP] $msg" -ForegroundColor Yellow
}

function OK {
    param([string]$msg)
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Fail {
    param([string]$msg)
    Write-Host ""
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    exit 1
}

# 1. Check Python
Step "Checking Python..."
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Fail "Python not found in PATH. Install Python 3.10+ first." }
$pyVer = (python --version 2>&1).ToString().Trim()
OK $pyVer

# Check pywinpty
$pywinptyOk = python -c "import winpty; print('ok')" 2>$null
if ($pywinptyOk -ne "ok") {
    Write-Host "  Installing pywinpty..." -ForegroundColor Yellow
    pip install pywinpty --quiet
    if ($LASTEXITCODE -ne 0) { Fail "Failed to install pywinpty." }
    OK "pywinpty installed"
} else {
    OK "pywinpty found"
}

# 2. Check / install PyInstaller
Step "Checking PyInstaller..."
$pyinstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
if (-not $pyinstaller) {
    Write-Host "  Installing PyInstaller..." -ForegroundColor Yellow
    pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { Fail "Failed to install PyInstaller." }
    OK "PyInstaller installed"
} else {
    $piVer = (python -m PyInstaller --version 2>&1).ToString().Trim()
    OK "PyInstaller $piVer"
}

# 3. Clean previous build
Step "Cleaning previous build..."
if (Test-Path $DistDir)  { Remove-Item $DistDir  -Recurse -Force }
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
OK "dist/ and build/ cleaned"

# 4. Bundle bridge_server.exe
Step "Bundling bridge_server.exe (includes pywinpty DLLs)..."
$bridgeScript = Join-Path $ProjectRoot "bridge\bridge_server.py"

# Locate pywinpty package directory to manually include native DLLs/EXEs.
# PyInstaller's --collect-all skips these because winpty appears as a module
# rather than a package in newer Python versions.
$winptyDir = python -c "import winpty, os; print(os.path.dirname(winpty.__file__))"
if (-not $winptyDir -or -not (Test-Path $winptyDir)) {
    Fail "Cannot locate pywinpty package directory."
}
Write-Host "  pywinpty dir: $winptyDir" -ForegroundColor DarkGray

# Build --add-binary flags for each native file in the winpty package
$winptyNativeFiles = @("conpty.dll", "winpty.dll", "winpty-agent.exe", "OpenConsole.exe")
$addBinaryArgs = @()
foreach ($f in $winptyNativeFiles) {
    $src = Join-Path $winptyDir $f
    if (Test-Path $src) {
        $addBinaryArgs += "--add-binary"
        $addBinaryArgs += "${src};winpty"
        Write-Host "  + including $f" -ForegroundColor DarkGray
    } else {
        Write-Host "  ! $f not found (skipping)" -ForegroundColor DarkYellow
    }
}

# Also include the .pyd extension module
$pydFiles = Get-ChildItem "$winptyDir\winpty.*.pyd" -ErrorAction SilentlyContinue
foreach ($pyd in $pydFiles) {
    $addBinaryArgs += "--add-binary"
    $addBinaryArgs += "$($pyd.FullName);winpty"
    Write-Host "  + including $($pyd.Name)" -ForegroundColor DarkGray
}

python -m PyInstaller `
    --onefile `
    --name bridge_server `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $InstallerDir `
    --noconfirm `
    @addBinaryArgs `
    $bridgeScript

if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed for bridge_server.py" }
OK "bridge_server.exe built"

# 5. Bundle native_host.exe
Step "Bundling native_host.exe (Native Messaging host)..."
$nmScript = Join-Path $ProjectRoot "bridge\native_host.py"

python -m PyInstaller `
    --onefile `
    --name native_host `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $InstallerDir `
    --noconfirm `
    $nmScript

if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed for native_host.py" }
OK "native_host.exe built"

# 6. Verify all exes exist
Step "Verifying build artifacts..."
@("bridge_server.exe", "native_host.exe") | ForEach-Object {
    $p = Join-Path $DistDir $_
    if (-not (Test-Path $p)) { Fail "Missing: $p" }
    $size = "{0:N0}" -f (Get-Item $p).Length
    OK "$_  ($size bytes)"
}

# 8. Find Inno Setup
Step "Locating Inno Setup Compiler (ISCC)..."
$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    "C:\Program Files\Inno Setup 5\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Host ""
    Write-Host "  Inno Setup not found." -ForegroundColor Red
    Write-Host "  Download: https://jrsoftware.org/isinfo.php" -ForegroundColor Yellow
    Write-Host "  Then re-run this script." -ForegroundColor Yellow
    exit 1
}
OK "Found: $iscc"

# 9. Ensure output dir exists
Step "Ensuring output directory C:\Intel exists..."
if (-not (Test-Path $OutputDir)) {
    New-Item $OutputDir -ItemType Directory | Out-Null
}
OK "$OutputDir ready"

# 10. Run Inno Setup
Step "Running Inno Setup Compiler..."
$issFile = Join-Path $InstallerDir "setup.iss"
& $iscc $issFile

if ($LASTEXITCODE -ne 0) { Fail "Inno Setup compilation failed." }

# 11. Done
$outputExe = Join-Path $OutputDir "Chat_Mode_Assistant_Setup.exe"
if (-not (Test-Path $outputExe)) { Fail "Expected output not found: $outputExe" }
$finalSize = "{0:N0}" -f (Get-Item $outputExe).Length

Write-Host ""
Write-Host "===============================================" -ForegroundColor Green
Write-Host "  BUILD COMPLETE"                               -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green
Write-Host "  Installer : $outputExe"                      -ForegroundColor Cyan
Write-Host "  Size      : $finalSize bytes"                 -ForegroundColor Cyan
Write-Host ""
Write-Host "  Run the installer and follow the wizard."        -ForegroundColor White
Write-Host "  Follow the prompts to load the Chrome extension." -ForegroundColor White
Write-Host ""