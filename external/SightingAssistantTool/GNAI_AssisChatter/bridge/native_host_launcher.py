import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
import urllib.error


def _read_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        return None
    if len(raw_length) != 4:
        raise RuntimeError("Invalid native message length header")
    message_length = struct.unpack("=I", raw_length)[0]
    payload = sys.stdin.buffer.read(message_length).decode("utf-8")
    return json.loads(payload)


def _write_message(message):
    encoded = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _health_candidates(base_url):
    normalized = str(base_url or "").strip().rstrip("/")
    if not normalized:
        return []

    root = normalized
    if root.lower().endswith("/v1"):
        root = root[:-3]

    return [
        f"{normalized}/health",
        f"{normalized}/v1/health",
        f"{root}/health",
        f"{root}/v1/health",
    ]


def _probe_health(base_url):
    for url in _health_candidates(base_url):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read(256).decode("utf-8", errors="replace")
                if 200 <= int(status) < 300:
                    return {
                        "ok": True,
                        "url": url,
                        "status": int(status),
                        "bodySnippet": body,
                    }
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            continue

    return {"ok": False}


def _start_bridge_process(bridge_dir, show_window=False):
    script_path = os.path.join(bridge_dir, "run_bridge.ps1")
    if not os.path.isfile(script_path):
        return {"ok": False, "error": f"run_bridge.ps1 not found at {script_path}"}

    kwargs = {
        "cwd": bridge_dir,
        "shell": False,
    }

    if show_window:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
        ]

        if os.name == "nt":
            create_new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            if create_new_console:
                kwargs["creationflags"] = create_new_console
    else:
        kwargs.update(
            {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
        )

        if os.name == "nt":
            create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if create_no_window:
                kwargs["creationflags"] = create_no_window

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
        ]

    process = subprocess.Popen(command, **kwargs)
    return {"ok": True, "pid": process.pid}


def _handle_start_bridge(message):
    bridge_base_url = message.get("bridgeBaseUrl", "http://127.0.0.1:8775/v1")
    wait_ms = int(message.get("waitMs", 12000))
    show_window = bool(message.get("showWindow", False))
    interval_ms = 500

    healthy = _probe_health(bridge_base_url)
    if healthy.get("ok"):
        return {
            "ok": True,
            "started": False,
            "connected": True,
            "health": healthy,
        }

    bridge_dir = os.path.dirname(os.path.abspath(__file__))
    started = _start_bridge_process(bridge_dir, show_window=show_window)
    if not started.get("ok"):
        return {
            "ok": False,
            "started": False,
            "connected": False,
            "error": started.get("error", "Failed to start bridge process"),
        }

    deadline = time.time() + max(1.0, wait_ms / 1000.0)
    latest = {"ok": False}
    while time.time() < deadline:
        latest = _probe_health(bridge_base_url)
        if latest.get("ok"):
            return {
                "ok": True,
                "started": True,
                "connected": True,
                "pid": started.get("pid"),
                "health": latest,
            }
        time.sleep(interval_ms / 1000.0)

    return {
        "ok": False,
        "started": True,
        "connected": False,
        "pid": started.get("pid"),
        "error": "Bridge started but health check did not pass within timeout",
        "health": latest,
    }


def _handle_message(message):
    action = str(message.get("action", "")).strip().lower()

    if action == "start_bridge":
        return _handle_start_bridge(message)

    if action == "ping":
        return {"ok": True, "message": "native host alive"}

    return {"ok": False, "error": f"Unsupported action: {action}"}


def main():
    try:
        message = _read_message()
        if message is None:
            return
        response = _handle_message(message)
    except Exception as exc:
        response = {
            "ok": False,
            "error": str(exc),
        }

    _write_message(response)


if __name__ == "__main__":
    main()
