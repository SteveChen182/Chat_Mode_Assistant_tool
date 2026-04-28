@echo off
echo Starting Chat Mode Bridge Server (port 8776)...
echo.
cd /d "%~dp0"
set BRIDGE_PORT=8776
set BRIDGE_DEBUG=1
python bridge_server.py
pause
