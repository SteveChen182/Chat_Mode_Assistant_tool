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
import time
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
PID_FILE = os.path.join(SCRIPT_DIR, "bridge.pid")
DISCOVERY_FILE = os.path.join(SCRIPT_DIR, "bridge.discovery.json")


def _read_discovery_file():
    """Return validated bridge discovery data, or None for stale/corrupt data."""
    try:
        with open(DISCOVERY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if not isinstance(data.get("port"), int) or not 1 <= data["port"] <= 65535:
            return None
        if not isinstance(data.get("pid"), int) or data["pid"] <= 0:
            return None
        if not isinstance(data.get("instance_id"), str) or not data["instance_id"]:
            return None
        return data
    except (OSError, ValueError):
        return None


def _read_port_file():
    """Return the port written by bridge_server, or None if not found."""
    try:
        with open(PORT_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _read_bridge_identity():
    """Return discovery data, with a protocol-v1 fallback for older bridges."""
    discovery = _read_discovery_file()
    if discovery:
        return discovery
    port = _read_port_file()
    if not port:
        return None
    return {
        "instance_id": None,
        "protocol_version": 1,
        "pid": None,
        "port": port,
    }


def _is_pid_alive(pid):
    """Check if a given PID is still running (Windows).
    Uses GetExitCodeProcess to distinguish zombie handles from live processes."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        # GetExitCodeProcess: if still active, exit_code = 259 (STILL_ACTIVE)
        exit_code = ctypes.c_ulong()
        result = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        if result and exit_code.value == 259:  # STILL_ACTIVE
            return True
        return False
    except Exception:
        pass
    return False


def _is_bridge_launching():
    """Check if bridge was recently spawned but hasn't written port file yet.
    Returns False (and cleans up stale PID file) if the process is dead."""
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        if _is_pid_alive(pid):
            return True
        # PID file exists but process is dead — clean up stale files
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False
    except Exception:
        return False


def _terminate_bridge_process():
    """Terminate the discovered bridge process tree and clear stale discovery."""
    identity = _read_bridge_identity()
    pid = identity.get("pid") if identity else None
    if not pid:
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
        except Exception:
            pid = None

    if pid and _is_pid_alive(pid):
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0 and _is_pid_alive(pid):
            raise RuntimeError(result.stderr.strip() or f"Failed to terminate bridge PID {pid}")

        deadline = time.monotonic() + 5
        while _is_pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _is_pid_alive(pid):
            raise RuntimeError(f"Bridge PID {pid} did not exit after taskkill")

    for path in (DISCOVERY_FILE, PORT_FILE, PID_FILE):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    return pid


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
    """Check that /health matches the discovered bridge instance."""
    identity = _read_bridge_identity()
    if not identity:
        return False, None
    port = identity["port"]
    try:
        # Use a no-proxy opener so corporate http_proxy doesn't intercept localhost
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{_bridge_url(port)}/health", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "ok":
                expected_instance = identity.get("instance_id")
                expected_pid = identity.get("pid")
                if expected_instance and data.get("instance_id") != expected_instance:
                    return False, None
                if expected_pid and data.get("pid") != expected_pid:
                    return False, None
                identity.update({
                    "instance_id": data.get("instance_id") or expected_instance,
                    "protocol_version": data.get("protocol_version", identity.get("protocol_version", 1)),
                })
                return True, identity
    except Exception:
        pass
    return False, None


def launch_bridge(debug_mode=False):
    """Spawn bridge server as a detached background process."""
    env = os.environ.copy()
    # Default to port 8776; if occupied, bridge will fail and caller retries
    env["BRIDGE_PORT"] = str(BRIDGE_PORT)
    env["BRIDGE_DEBUG"] = "1"

    if debug_mode:
        # Debug mode: show console window for troubleshooting
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE
    else:
        # Normal mode: hide console window
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    if getattr(sys, "frozen", False):
        # Bundled exe: launch bridge_server.exe directly (no Python needed)
        cmd = [BRIDGE_SCRIPT]
    else:
        # Dev mode: launch bridge_server.py with the current Python interpreter
        cmd = [sys.executable, BRIDGE_SCRIPT]
    process = subprocess.Popen(cmd, cwd=SCRIPT_DIR, env=env, creationflags=flags)
    temp_path = f"{PID_FILE}.{os.getpid()}.tmp"
    try:
        with open(temp_path, "w", encoding="ascii") as f:
            f.write(str(process.pid))
        os.replace(temp_path, PID_FILE)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
    return process.pid


def main():
    msg = read_message()
    if not msg:
        return

    action = msg.get("action", "")

    if action == "launch":
        # Check if already running — respond immediately with port.
        running, identity = is_bridge_running()
        if running:
            send_message({"status": "already_running", **identity})
            return
        # Check if bridge was already spawned (PID alive but port file not ready yet)
        if _is_bridge_launching():
            send_message({"status": "launching"})
            return
        # Not running: spawn bridge and return IMMEDIATELY (no waiting).
        # background.js will poll with "check" until bridge.port appears.
        try:
            # Remove stale port file so background.js can detect fresh start
            try:
                if os.path.exists(PORT_FILE):
                    os.remove(PORT_FILE)
                if os.path.exists(DISCOVERY_FILE):
                    os.remove(DISCOVERY_FILE)
            except OSError:
                pass
            debug_mode = msg.get("debug_mode", False)
            launch_bridge(debug_mode=debug_mode)
            send_message({"status": "launching"})
        except Exception as e:
            send_message({"status": "error", "message": str(e)})

    elif action == "check":
        # Return current bridge status + port (fast, no waiting).
        running, identity = is_bridge_running()
        send_message({
            "status": "running" if running else "not_running",
            **(identity or {}),
        })

    elif action == "reset":
        try:
            previous_pid = _terminate_bridge_process()
            new_pid = launch_bridge(debug_mode=msg.get("debug_mode", False))
            send_message({
                "status": "launching",
                "previous_pid": previous_pid,
                "pid": new_pid,
            })
        except Exception as e:
            send_message({"status": "error", "message": str(e)})

    else:
        send_message({"status": "error", "message": f"Unknown action: {action}"})


if __name__ == "__main__":
    main()
