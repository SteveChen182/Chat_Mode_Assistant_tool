"""
Chat Mode Bridge Server
=======================
Manages a persistent `dt gnai chat --json --assistant sighting_assistant` process.
Extension communicates via HTTP endpoints. The bridge translates between
HTTP/SSE and the stdin/stdout pipe of the chat process.

Endpoints:
    POST /session/start     → Start a new chat session
    POST /session/send      → Send a message to the active session
    GET  /session/stream    → SSE stream of events from the chat process
    POST /session/stop      → Terminate the active session
    GET  /health            → Health check

Architecture:
    Chrome Extension ←→ HTTP ←→ Bridge Server ←→ stdin/stdout ←→ dt gnai chat --json
"""

import json
import os
import re
import queue
import subprocess
import sys
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from winpty import PtyProcess
    HAS_WINPTY = True
except ImportError:
    HAS_WINPTY = False

# ── Configuration ───────────────────────────────────────────────────────────
HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("BRIDGE_PORT", "8776"))       # NOTE: 8776 to avoid conflict with old bridge (8775)
REQUIRE_API_KEY = os.environ.get("BRIDGE_API_KEY", "").strip()
DEFAULT_ASSISTANT = os.environ.get("BRIDGE_ASSISTANT", "sighting_assistant")
DT_PATH_OVERRIDE = os.environ.get("BRIDGE_DT_PATH", "").strip()
DEBUG_LOG = os.environ.get("BRIDGE_DEBUG", "1").strip().lower() in {"1", "true", "yes"}
AUTO_CLOSE_PAUSE_WINDOWS = os.environ.get("BRIDGE_AUTO_CLOSE_PAUSE", "1").strip().lower() in {"1", "true", "yes"}
PAUSE_SCAN_INTERVAL = int(os.environ.get("BRIDGE_PAUSE_SCAN_INTERVAL", "3"))


def _debug(msg):
    if DEBUG_LOG:
        line = f"[bridge] {msg}\n"
        try:
            sys.stdout.write(line)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass  # stdout may be DEVNULL when launched via NM
        # Also write to log file for NM-launched debugging
        _debug_to_file(line)


def _debug_to_file(line):
    """Append to bridge_debug.log in the same directory as this script."""
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge_debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {line}")
    except Exception:
        pass


# ── Utility ─────────────────────────────────────────────────────────────────
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b[^[\x1b]|\[[0-9;]+m", re.I)


def _strip_ansi(text):
    return _ANSI_RE.sub("", text)


def _resolve_dt():
    if DT_PATH_OVERRIDE and os.path.isfile(DT_PATH_OVERRIDE):
        return DT_PATH_OVERRIDE
    found = shutil.which("dt")
    if found:
        return found
    return None


def _is_disconnect(err):
    if isinstance(err, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    if isinstance(err, OSError):
        w = getattr(err, "winerror", None)
        if w in {10053, 10054, 995}:
            return True
    return False


# ── Child Window Auto-Close (pause windows) ────────────────────────────────
def _collect_descendants_win(root_pid):
    """Get all descendant processes of root_pid on Windows."""
    if os.name != "nt":
        return []
    script = (
        "$items = Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine; "
        "$items | ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=6,
        )
    except Exception:
        return []
    if r.returncode != 0 or not r.stdout.strip():
        return []
    try:
        data = json.loads(r.stdout)
    except Exception:
        return []

    rows = data if isinstance(data, list) else [data]
    by_parent = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        parent = row.get("ParentProcessId")
        if parent is not None:
            by_parent.setdefault(int(parent), []).append(row)

    descendants = []
    stack = [int(root_pid)]
    seen = set(stack)
    while stack:
        pid = stack.pop()
        for child in by_parent.get(pid, []):
            cpid = int(child.get("ProcessId", 0) or 0)
            if cpid > 0 and cpid not in seen:
                seen.add(cpid)
                descendants.append(child)
                stack.append(cpid)
    return descendants


def _close_paused_children(root_pid):
    """Kill descendant cmd.exe windows that contain 'pause' in command line."""
    if os.name != "nt" or not AUTO_CLOSE_PAUSE_WINDOWS:
        return
    for row in _collect_descendants_win(root_pid):
        name = str(row.get("Name", "")).lower()
        cmdline = str(row.get("CommandLine", "")).lower()
        pid = int(row.get("ProcessId", 0) or 0)
        if pid <= 0 or name not in {"cmd.exe", "powershell.exe", "pwsh.exe"}:
            continue
        if " pause" in cmdline or "&& pause" in cmdline or " /k " in cmdline:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    capture_output=True, text=True, timeout=6,
                )
                _debug(f"auto-closed paused child pid={pid}")
            except Exception as e:
                _debug(f"failed to close paused child pid={pid}: {e}")


# ── ChatSession: manages one dt gnai chat --json process ────────────────────
class ChatSession:
    """
    Wraps a persistent ``dt gnai chat --json`` process using ConPTY (pywinpty).

    ConPTY is required because ``dt`` (a Go binary) uses block-buffered stdout
    when connected to a plain pipe, which prevents real-time streaming of JSON
    answer events. ConPTY makes the process behave as if connected to a terminal,
    forcing line-buffered output.
    """

    def __init__(self, assistant=None):
        self.assistant = assistant or DEFAULT_ASSISTANT
        self._pty = None                         # PtyProcess instance
        self.event_queue = queue.Queue()
        self._reader_thread = None
        self._pause_thread = None
        self._stop_event = threading.Event()
        self._ready = threading.Event()          # set when '> ' prompt first seen
        self._waiting_input = threading.Event()  # set when '> ' prompt appears
        self._lock = threading.Lock()
        self.session_id = None                   # GNAI conversation_id from first request event
        self.accumulated_answer = ""             # full answer text for current turn
        self._ignore_prompt = False              # ignore '> ' prompt until usage event (avoids echo)

    def start(self):
        if not HAS_WINPTY:
            raise RuntimeError("pywinpty is required. Install: pip install pywinpty")

        dt_cmd = _resolve_dt()
        if not dt_cmd:
            raise RuntimeError("dt command not found in PATH")

        cmd = f'{dt_cmd} gnai chat --json --assistant {self.assistant}'
        _debug(f"starting via ConPTY: {cmd}")

        self._pty = PtyProcess.spawn(cmd)
        _debug(f"pty pid={self._pty.pid}")

        self._reader_thread = threading.Thread(
            target=self._read_pty, daemon=True, name="pty-reader"
        )
        self._reader_thread.start()

        # Pause window scanner
        if AUTO_CLOSE_PAUSE_WINDOWS and os.name == "nt":
            self._pause_thread = threading.Thread(
                target=self._scan_pause_windows, daemon=True, name="pause-scanner"
            )
            self._pause_thread.start()

        # NOTE: We do NOT block here. The pty-reader thread will set _ready
        # when the '> ' prompt appears. The HTTP handler returns immediately.
        _debug("session spawned, waiting for prompt in background...")

    def send(self, text):
        """Send user input to the chat process via PTY."""
        with self._lock:
            if not self._pty or not self._pty.isalive():
                raise RuntimeError("Chat process not running")
            self._waiting_input.clear()
            self._ignore_prompt = True           # ignore echo'd prompts until usage
            self.accumulated_answer = ""
            self._pty.write(text + "\r")
            _debug(f"sent: {text[:100]}...")

    def stop(self):
        """Terminate the chat session."""
        self._stop_event.set()
        with self._lock:
            if self._pty and self._pty.isalive():
                try:
                    self._pty.write("/exit\r")
                    time.sleep(0.5)
                except Exception:
                    pass
                try:
                    self._pty.terminate()
                except Exception:
                    pass
        _debug("session stopped")

    @property
    def is_alive(self):
        return self._pty is not None and self._pty.isalive()

    @property
    def is_waiting_input(self):
        return self._waiting_input.is_set()

    @property
    def pid(self):
        return self._pty.pid if self._pty else None

    def _read_pty(self):
        """Background thread: read from ConPTY, split into lines, parse & enqueue.

        ConPTY gives us raw terminal output which may include partial reads.
        We accumulate a line buffer and process complete lines.

        NOTE: ConPTY redraws the prompt line repeatedly when idle. We handle
        this by sleeping longer when in waiting state and suppressing duplicate
        prompt log messages.
        """
        buf = ""
        try:
            while not self._stop_event.is_set():
                if not self._pty.isalive():
                    # Process remaining buffer
                    if buf.strip():
                        self._process_line(buf.strip())
                    break

                # When idle (waiting for user input), sleep longer to avoid
                # burning CPU on ConPTY prompt redraws
                if self._waiting_input.is_set():
                    time.sleep(0.5)

                try:
                    data = self._pty.read(4096)
                except EOFError:
                    break

                if not data:
                    time.sleep(0.05)
                    continue

                buf += data

                # Process complete lines
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = _strip_ansi(line).strip()
                    if line:
                        self._process_line(line)

                # Check for prompt in remaining buffer (may not end with \n)
                # Only check if we're NOT already in waiting state (avoid redraw spam)
                if not self._waiting_input.is_set():
                    clean_buf = _strip_ansi(buf).strip()
                    if clean_buf.startswith("> ") or clean_buf == ">":
                        self._process_line(clean_buf)
                        buf = ""

        except Exception as e:
            if not self._stop_event.is_set():
                _debug(f"pty reader error: {e}")
        finally:
            _debug("pty reader exiting")
            self.event_queue.put({"type": "end"})

    def _process_line(self, line):
        """Process a single cleaned line from the PTY output."""

        # Detect '> ' prompt → ready for input
        # Only emit ready event on state transition (not on ConPTY redraws)
        # Also skip prompt echoes right after send (before usage event)
        if line.startswith("> ") or line == ">":
            if self._ignore_prompt:
                return  # echo'd prompt right after send, ignore
            self._ready.set()
            if not self._waiting_input.is_set():
                _debug(f"[pty] prompt detected → ready")
                self._waiting_input.set()
                self.event_queue.put({
                    "type": "ready",
                    "accumulated_answer": self.accumulated_answer,
                })
            # Don't log repeated prompt redraws
            return

        _debug(f"[pty] {line[:200]}")

        # Skip non-JSON lines
        if not line.startswith("{"):
            _debug(f"[pty] (skipped non-JSON)")
            return

        # Skip echo of user input (PTY echoes back what we write)
        # User input won't be valid JSON, so json.loads will catch most cases

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            _debug(f"[pty] (bad JSON)")
            return

        event = self._classify_event(data)
        if event:
            _debug(f"[event] type={event['type']}")
            self.event_queue.put(event)

    def _classify_event(self, data):
        """Parse a JSON line from dt gnai chat --json into a typed event."""

        # Answer chunk: {"answer": "text", ...}
        if "answer" in data:
            text = data["answer"]
            self.accumulated_answer += text
            return {"type": "answer", "text": text}

        # Tool steps: {"steps": [...], ...}
        if "steps" in data:
            steps = data["steps"]
            if isinstance(steps, list) and steps:
                step = steps[0]
                return {
                    "type": "tool_start",
                    "name": step.get("name", ""),
                    "tool_type": step.get("type", ""),
                    "args": step.get("args", {}),
                }

        # Tool request (detailed): {"request": {...}, ...}
        if "request" in data:
            req = data["request"]
            meta = req.get("meta", {})
            config = meta.get("config", {})
            conv_id = config.get("conversation_id")
            if conv_id and not self.session_id:
                self.session_id = conv_id
            return {
                "type": "tool_request",
                "name": req.get("name", ""),
                "operation": req.get("operation", ""),
                "request_id": req.get("request_id", ""),
            }

        # Usage (response complete): {"usage": {...}, ...}
        if "usage" in data:
            self._ignore_prompt = False   # next '> ' prompt is the real one
            return {"type": "usage", "usage": data["usage"]}

        # Error from gnai (e.g. tool execution failure, connection abort)
        # Reset _ignore_prompt so the next '> ' prompt is detected
        if data.get("level") == "error":
            self._ignore_prompt = False
            error_msg = data.get("msg", "Unknown error")
            _debug(f"[event] gnai error detected, resetting ignore_prompt: {error_msg[:200]}")
            return {"type": "error", "text": error_msg}

        # Goodbye
        if data.get("msg") == "Goodbye!":
            return {"type": "goodbye"}

        # Info messages (welcome, loading, etc)
        if "msg" in data and data["msg"]:
            return {"type": "info", "text": data["msg"]}

        return None

    def _scan_pause_windows(self):
        """Periodically scan and close paused child cmd windows."""
        while not self._stop_event.is_set():
            self._stop_event.wait(PAUSE_SCAN_INTERVAL)
            if self._stop_event.is_set():
                break
            if self._pty and self._pty.isalive():
                _close_paused_children(self._pty.pid)


# ── Global Session Manager ──────────────────────────────────────────────────
_current_session = None
_session_lock = threading.Lock()


def _get_session():
    global _current_session
    return _current_session


def _start_session(assistant=None):
    global _current_session
    with _session_lock:
        if _current_session and _current_session.is_alive:
            _current_session.stop()
        session = ChatSession(assistant)
        session.start()
        _current_session = session
        return session


def _stop_session():
    global _current_session
    with _session_lock:
        if _current_session:
            _current_session.stop()
            _current_session = None


# ── HTTP Handler ────────────────────────────────────────────────────────────
class BridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        if DEBUG_LOG:
            sys.stdout.write(f"[http] {fmt % args}\n")

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _json_response(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _check_auth(self):
        if not REQUIRE_API_KEY:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() == REQUIRE_API_KEY
        return False

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def do_GET(self):
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/session/stream":
            self._handle_stream()
        else:
            self._json_response(404, {"error": "not_found"})

    def do_POST(self):
        if not self._check_auth():
            self._json_response(401, {"error": "unauthorized"})
            return

        if self.path == "/session/start":
            self._handle_start()
        elif self.path == "/session/send":
            self._handle_send()
        elif self.path == "/session/stop":
            self._handle_stop()
        else:
            self._json_response(404, {"error": "not_found"})

    # ── Endpoint Handlers ───────────────────────────────────────────────

    def _handle_health(self):
        session = _get_session()
        self._json_response(200, {
            "status": "ok",
            "session_active": session is not None and session.is_alive,
            "session_waiting_input": session.is_waiting_input if session else False,
            "session_id": session.session_id if session else None,
        })

    def _handle_start(self):
        body = self._read_json_body()
        assistant = body.get("assistant", DEFAULT_ASSISTANT)
        # If session already active, return it instead of killing
        existing = _get_session()
        if existing and existing.is_alive:
            self._json_response(200, {
                "status": "already_active",
                "assistant": existing.assistant,
                "session_waiting_input": existing.is_waiting_input,
                "message": "Session already running.",
            })
            return
        try:
            session = _start_session(assistant)
            self._json_response(200, {
                "status": "starting",
                "assistant": session.assistant,
                "message": "Session spawned. Connect to /session/stream for events.",
            })
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _handle_send(self):
        session = _get_session()
        if not session or not session.is_alive:
            self._json_response(400, {"error": "no_active_session"})
            return

        body = self._read_json_body()
        message = body.get("message", "").strip()
        if not message:
            self._json_response(400, {"error": "empty_message"})
            return

        try:
            session.send(message)
            self._json_response(200, {"status": "sent"})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _handle_stop(self):
        _stop_session()
        self._json_response(200, {"status": "stopped"})

    def _handle_stream(self):
        """SSE endpoint: streams events from the chat process."""
        session = _get_session()
        if not session or not session.is_alive:
            self._json_response(400, {"error": "no_active_session"})
            return

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self._cors_headers()
            self.end_headers()
        except Exception:
            return

        try:
            while session.is_alive or not session.event_queue.empty():
                try:
                    event = session.event_queue.get(timeout=2)
                except queue.Empty:
                    # Heartbeat to keep connection alive
                    try:
                        self.wfile.write(": heartbeat\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        break
                    continue

                event_type = event.get("type", "unknown")
                payload = json.dumps(event, ensure_ascii=False)

                try:
                    self.wfile.write(f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    break

                if event_type in ("end", "goodbye"):
                    break

        except Exception as e:
            if not _is_disconnect(e):
                _debug(f"stream error: {e}")


# ── Server Setup ────────────────────────────────────────────────────────────
class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        _, exc, _ = sys.exc_info()
        if exc and _is_disconnect(exc):
            return
        super().handle_error(request, client_address)


def main():
    if not HAS_WINPTY:
        sys.stderr.write(
            "[bridge] ERROR: pywinpty is required.\n"
            "  Install: pip install pywinpty\n"
        )
        sys.exit(1)

    dt_cmd = _resolve_dt()
    if not dt_cmd:
        sys.stderr.write(
            "[bridge] ERROR: 'dt' command not found.\n"
            "  Install Intel Developer Toolkit or set BRIDGE_DT_PATH.\n"
        )
        sys.exit(1)

    _debug(f"dt found at: {dt_cmd}")
    _debug(f"default assistant: {DEFAULT_ASSISTANT}")
    _debug(f"listening on port: {PORT}")
    _debug(f"auto-close pause windows: {AUTO_CLOSE_PAUSE_WINDOWS}")

    server = BridgeServer((HOST, PORT), BridgeHandler)
    print(f"[bridge] Chat Mode Bridge Server running on http://{HOST}:{PORT}")
    print(f"[bridge] Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] Shutting down...")
        _stop_session()
        server.shutdown()


if __name__ == "__main__":
    main()
