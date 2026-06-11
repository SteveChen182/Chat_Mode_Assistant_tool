"""
Native Messaging Host — Chat Mode Assistant Bridge Launcher
============================================================
Chrome extension calls this via Native Messaging to:
  1. Check if bridge_server.py is running
  2. Launch it if not
  3. Return status

Protocol: Chrome NM (4-byte length-prefix + JSON on stdin/stdout)
"""

import json
import os
import struct
import subprocess
import sys
import urllib.request

BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8776"))   # Default 8776; bridge falls back to random if occupied

# When bundled as native_host.exe via PyInstaller, __file__ points to the
# temp extraction dir. Use sys.executable directory to find bridge_server.exe.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
    BRIDGE_SCRIPT = os.path.join(SCRIPT_DIR, "bridge_server.exe")
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    BRIDGE_SCRIPT = os.path.join(SCRIPT_DIR, "bridge_server.py")

PORT_FILE = os.path.join(SCRIPT_DIR, "bridge.port")


def _read_port_file():
    """Return the port written by bridge_server, or None if not found."""
    try:
        with open(PORT_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _bridge_url(port):
    return f"http://127.0.0.1:{port}"


def read_message():
    """Read one NM message from stdin (4-byte LE length + JSON)."""
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    length = struct.unpack("<I", raw)[0]
    data = sys.stdin.buffer.read(length)
    return json.loads(data.decode("utf-8"))


def send_message(obj):
    """Write one NM message to stdout (4-byte LE length + JSON)."""
    encoded = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def is_bridge_running():
    """Check if bridge server responds on /health (port discovered from bridge.port file)."""
    port = _read_port_file()
    if not port:
        return False, None
    try:
        # Use a no-proxy opener so corporate http_proxy doesn't intercept localhost
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{_bridge_url(port)}/health", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "ok":
                return True, port
    except Exception:
        pass
    return False, None


def launch_bridge():
    """Spawn bridge server as a detached background process."""
    env = os.environ.copy()
    # Default to port 8776; if occupied, bridge will fail and caller retries
    env["BRIDGE_PORT"] = str(BRIDGE_PORT)
    env["BRIDGE_DEBUG"] = "1"

    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE
    if getattr(sys, "frozen", False):
        # Bundled exe: launch bridge_server.exe directly (no Python needed)
        cmd = [BRIDGE_SCRIPT]
    else:
        # Dev mode: launch bridge_server.py with the current Python interpreter
        cmd = [sys.executable, BRIDGE_SCRIPT]
    subprocess.Popen(cmd, cwd=SCRIPT_DIR, env=env, creationflags=flags)


def main():
    msg = read_message()
    if not msg:
        return

    action = msg.get("action", "")

    if action == "launch":
        # Check if already running — respond immediately with port.
        running, port = is_bridge_running()
        if running:
            send_message({"status": "already_running", "port": port})
            return
        # Not running: spawn bridge and return IMMEDIATELY (no waiting).
        # background.js will poll with "check" until bridge.port appears.
        try:
            # Remove stale port file so background.js can detect fresh start
            try:
                if os.path.exists(PORT_FILE):
                    os.remove(PORT_FILE)
            except OSError:
                pass
            launch_bridge()
            send_message({"status": "launching"})
        except Exception as e:
            send_message({"status": "error", "message": str(e)})

    elif action == "check":
        # Return current bridge status + port (fast, no waiting).
        running, port = is_bridge_running()
        send_message({
            "status": "running" if running else "not_running",
            "port": port,
        })

    else:
        send_message({"status": "error", "message": f"Unknown action: {action}"})


if __name__ == "__main__":
    main()
