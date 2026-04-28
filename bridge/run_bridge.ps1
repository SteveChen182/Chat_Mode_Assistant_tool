# Run Chat Mode Bridge Server
# Port 8776 (not 8775 which is the old ask-mode bridge)
Set-Location $PSScriptRoot
$env:BRIDGE_PORT = "8776"
$env:BRIDGE_DEBUG = "1"
python bridge_server.py
