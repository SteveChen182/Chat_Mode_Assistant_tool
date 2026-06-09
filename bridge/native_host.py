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

BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8776"))
BRIDGE_URL = f"http://127.0.0.1:{BRIDGE_PORT}"

# When bundled as native_host.exe via PyInstaller, __file__ points to the
# temp extraction dir. Use sys.executable directory to find bridge_server.exe.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
    BRIDGE_SCRIPT = os.path.join(SCRIPT_DIR, "bridge_server.exe")
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    BRIDGE_SCRIPT = os.path.join(SCRIPT_DIR, "bridge_server.py")


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
    """Check if bridge server responds on /health."""
    try:
        req = urllib.request.Request(f"{BRIDGE_URL}/health")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "ok"
    except Exception:
        return False


def launch_bridge():
    """Spawn bridge server as a detached background process."""
    env = os.environ.copy()
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
        if is_bridge_running():
            send_message({"status": "already_running", "port": BRIDGE_PORT})
            return
        try:
            launch_bridge()
            send_message({"status": "launched", "port": BRIDGE_PORT})
        except Exception as e:
            send_message({"status": "error", "message": str(e)})

    elif action == "check":
        send_message({
            "status": "running" if is_bridge_running() else "not_running",
            "port": BRIDGE_PORT,
        })

    else:
        send_message({"status": "error", "message": f"Unknown action: {action}"})


if __name__ == "__main__":
    main()
