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
import ctypes
import ctypes.wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── PyInstaller compatibility ─────────────────────────────────────────────────
# When bundled as a standalone exe, __file__ points to the temp extraction dir.
# Use sys.executable directory instead so logs/pid are written next to the exe.
if getattr(sys, "frozen", False):
    _SCRIPT_DIR = os.path.dirname(sys.executable)
    # Add the bundled winpty/ sub-directory to PATH so Windows can find
    # conpty.dll, winpty.dll, winpty-agent.exe, OpenConsole.exe before importing.
    _winpty_bin = os.path.join(sys._MEIPASS, "winpty")
    if os.path.isdir(_winpty_bin):
        os.environ["PATH"] = _winpty_bin + os.pathsep + os.environ.get("PATH", "")
else:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from winpty import PtyProcess
    HAS_WINPTY = True
except ImportError:
    HAS_WINPTY = False

# ── Configuration ───────────────────────────────────────────────────────────
HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
# Port 0 = OS picks a free port automatically (recommended).
# Set BRIDGE_PORT env-var to force a specific port (e.g. for dev/testing).
PORT = int(os.environ.get("BRIDGE_PORT", "8776"))
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
        log_path = os.path.join(_SCRIPT_DIR, "bridge_debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {line}")
    except Exception:
        pass


# ── Session I/O Logger ──────────────────────────────────────────────────────
_session_log_path = None


def _init_session_log():
    """Create a new session log file in bridge/log/ with timestamp-based name."""
    global _session_log_path
    log_dir = os.path.join(_SCRIPT_DIR, "log")
    os.makedirs(log_dir, exist_ok=True)
    filename = f"session_{time.strftime('%Y%m%d_%H%M%S')}.log"
    _session_log_path = os.path.join(log_dir, filename)
    _session_log("SESSION", f"Log started: {filename}")
    return _session_log_path


def _session_log(direction, content):
    """Log a single I/O entry. direction: INPUT, OUTPUT, EVENT, SESSION."""
    if not _session_log_path:
        return
    try:
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(_session_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{direction}] {content}\n")
    except Exception:
        pass


def _close_session_log():
    """Mark session log as closed."""
    global _session_log_path
    if _session_log_path:
        _session_log("SESSION", "Log closed")
        _session_log_path = None


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


# ── Regression module (Check-gfx-driver-regression) ───────────────────────
_REGRESSION_MODULE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "external", "Check-gfx-driver-regression")
)
if os.path.isdir(_REGRESSION_MODULE_DIR) and _REGRESSION_MODULE_DIR not in sys.path:
    sys.path.insert(0, _REGRESSION_MODULE_DIR)

try:
    import regression_checker as _rc
    import regression_bridge as _rb
    _rc._debug = _debug
    _rb._rc = _rc       # share already-imported module so debug injection works
    _HAS_REGRESSION = True
    _debug("regression_checker loaded from " + _REGRESSION_MODULE_DIR)
except ImportError as _e:
    _HAS_REGRESSION = False
    _rb = None
    _debug(f"Warning: regression modules not found at {_REGRESSION_MODULE_DIR}: {_e}")


# ── Driver History Cache + Build Version Cache ────────────────────────────────
# Classes live in external/Check-gfx-driver-regression/regression_cache.py
# so that the standalone server.py can share the same implementation.
try:
    from regression_cache import _DriverHistoryStore, _BuildVersionCache
    _debug("regression_cache loaded from " + _REGRESSION_MODULE_DIR)
except ImportError as _e:
    _debug(f"Warning: regression_cache not found: {_e}")
    # Fallback stubs (should never happen if external/ is present)
    class _DriverHistoryStore:
        def __init__(self, data_dir=None): pass
        def lookup(self, *a): return None
        def save(self, *a): pass
        def list_all(self, bt): return []
        def delete(self, *a): return False
    class _BuildVersionCache:
        def __init__(self, data_dir=None): pass
        def lookup_multi(self, *a): return {}
        def save_multi(self, *a): pass

_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
_driver_history      = _DriverHistoryStore(data_dir=_BRIDGE_DIR)
_build_version_cache = _BuildVersionCache(data_dir=_BRIDGE_DIR)


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
    """Kill descendant cmd.exe that are running a script ending with 'pause'.

    Only matches explicit pause commands at word boundaries to avoid
    false positives (e.g. paths containing 'pause').
    """
    if os.name != "nt" or not AUTO_CLOSE_PAUSE_WINDOWS:
        return
    for row in _collect_descendants_win(root_pid):
        name = str(row.get("Name", "")).lower()
        cmdline = str(row.get("CommandLine", "")).lower()
        pid = int(row.get("ProcessId", 0) or 0)
        if pid <= 0 or name not in {"cmd.exe", "powershell.exe", "pwsh.exe"}:
            continue
        # Match explicit pause commands: "& pause", "&& pause", "& pause>nul", etc.
        if _re.search(r'[&|]\s*pause\s*(>|$|"|\))', cmdline):
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    capture_output=True, text=True, timeout=6,
                )
                _debug(f"auto-closed paused child pid={pid} cmdline={cmdline[:100]}")
            except Exception as e:
                _debug(f"failed to close paused child pid={pid}: {e}")


# ── GDHM Analysis Window Auto-Close ────────────────────────────────────────
_GDHM_TITLE_KEYWORD = "gdhm analysis"
_gdhm_window_first_seen = {}  # {sighting_id: timestamp} — grace period tracking

import re as _re

def _cmd_has_active_children(cmd_pid):
    """Recursively check if a cmd.exe process tree has any active work running.

    Walks down through cmd.exe children until it finds non-cmd/non-conhost
    processes. If any exist → analysis still running. If the entire tree is
    only cmd.exe + conhost.exe → waiting at 'pause'.
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-CimInstance Win32_Process | Where-Object {{ $_.ParentProcessId -eq {cmd_pid} }} | "
             "Select-Object ProcessId, Name | ConvertTo-Json"],
            capture_output=True, text=True, timeout=5,
        )
        data = out.stdout.strip()
        if not data:
            return False
        import json as _json
        children = _json.loads(data)
        if isinstance(children, dict):
            children = [children]

        for child in children:
            name = (child.get("Name") or "").lower()
            child_pid = child.get("ProcessId", 0)
            if name == "conhost.exe":
                continue
            if name == "cmd.exe":
                # Recurse into nested cmd.exe
                if _cmd_has_active_children(child_pid):
                    return True
            else:
                # Found a non-cmd, non-conhost process → still working
                return True
        return False
    except Exception:
        return True  # On error, assume still active (don't close)

def _find_gdhm_cmd_processes():
    """Find cmd.exe processes running GDHM analysis bat files.

    Returns dict: {sighting_id: pid} for cmd.exe processes whose CommandLine
    contains 'gdhm_analysis_<id>'.
    """
    results = {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
             "Select-Object ProcessId, CommandLine | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10,
        )
        import json as _json
        data = _json.loads(out.stdout) if out.stdout.strip() else []
        if isinstance(data, dict):
            data = [data]
        for proc in data:
            cmdline = proc.get("CommandLine") or ""
            match = _re.search(r"gdhm_analysis_(\d+)", cmdline, _re.IGNORECASE)
            if match:
                sid = match.group(1)
                # Prefer the inner cmd (child) — it's the one actually running the bat
                if sid not in results:
                    results[sid] = proc["ProcessId"]
                else:
                    # Keep the higher PID (child spawned later)
                    results[sid] = max(results[sid], proc["ProcessId"])
    except Exception:
        pass
    return results

def _close_gdhm_analysis_windows():
    """Find and close GDHM Analysis windows that are idle (waiting at pause).

    Strategy: Find the cmd.exe running gdhm_analysis_*.bat and check if it has
    any child processes (other than conhost.exe). If no active children exist,
    the bat script has finished and is waiting at 'pause' — safe to kill.
    """
    global _gdhm_window_first_seen
    if os.name != "nt" or not AUTO_CLOSE_PAUSE_WINDOWS:
        return

    import time as _time

    # Step 1: Find cmd.exe processes running gdhm_analysis bat files
    cmd_procs = _find_gdhm_cmd_processes()  # {sighting_id: pid}

    if not cmd_procs:
        _gdhm_window_first_seen.clear()
        return

    # Clean up stale entries
    _gdhm_window_first_seen = {k: v for k, v in _gdhm_window_first_seen.items() if k in cmd_procs}

    # Step 2: For each GDHM cmd process, check if it's idle (no active children)
    for sid, cmd_pid in cmd_procs.items():
        has_children = _cmd_has_active_children(cmd_pid)

        if has_children:
            # Still working — reset/remove from tracking
            _gdhm_window_first_seen.pop(sid, None)
            _debug(f"GDHM {sid} cmd_pid={cmd_pid} still has active children — skipping")
            continue

        # No active children — it's likely at 'pause'
        now = _time.time()
        if sid not in _gdhm_window_first_seen:
            # First time seeing it idle — record timestamp, wait for confirmation
            _gdhm_window_first_seen[sid] = now
            _debug(f"GDHM {sid} cmd_pid={cmd_pid} appears idle — starting grace period")
            continue

        # Check grace period: must be idle for at least 10 seconds
        elapsed = now - _gdhm_window_first_seen[sid]
        if elapsed < 10:
            _debug(f"GDHM {sid} cmd_pid={cmd_pid} idle for {elapsed:.0f}s — waiting (need 10s)")
            continue

        # Confirmed idle for 10+ seconds — kill it
        try:
            subprocess.run(
                ["taskkill", "/PID", str(cmd_pid), "/F", "/T"],
                capture_output=True, text=True, timeout=6,
            )
            _debug(f"auto-closed idle GDHM cmd: sid={sid} (cmd_pid={cmd_pid}, idle={elapsed:.0f}s)")
        except Exception as e:
            _debug(f"failed to close GDHM cmd_pid={cmd_pid}: {e}")
        _gdhm_window_first_seen.pop(sid, None)


# ── ChatSession: manages one dt gnai chat --json process ────────────────────
class ChatSession:
    """
    Wraps a persistent ``dt gnai chat --json`` process using ConPTY (pywinpty).

    ConPTY is required because ``dt`` (a Go binary) uses block-buffered stdout
    when connected to a plain pipe, which prevents real-time streaming of JSON
    answer events. ConPTY makes the process behave as if connected to a terminal,
    forcing line-buffered output.
    """

    def __init__(self, assistant=None, conversation_id=None):
        self.assistant = assistant or DEFAULT_ASSISTANT
        self.conversation_id = conversation_id  # user-specified conversation ID
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
        self._config_error_handled = False       # prevent duplicate auto-fix attempts
        self._idle_timer = None                  # timer to synthesize 'ready' if '> ' prompt is missed
        self._idle_timer_lock = threading.Lock()

    def start(self):
        if not HAS_WINPTY:
            raise RuntimeError("pywinpty is required. Install: pip install pywinpty")

        dt_cmd = _resolve_dt()
        if not dt_cmd:
            raise RuntimeError("dt command not found in PATH")

        cmd = f'{dt_cmd} gnai chat --json --assistant {self.assistant}'
        if self.conversation_id:
            cmd += f' --conversation-id {self.conversation_id}'
        _debug(f"starting via ConPTY: {cmd}")

        # Use a very wide terminal (500 cols) so dt's JSON output lines are never
        # wrapped by ConPTY. At 80 cols, dt inserts ANSI cursor codes mid-JSON,
        # corrupting every answer chunk and causing json.loads() to fail.
        self._pty = PtyProcess.spawn(cmd, dimensions=(50, 500))
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
            # Sanitize: replace newlines with spaces to prevent multi-command injection
            clean_text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()
            self._cancel_idle_timer()
            self._waiting_input.clear()
            self._ignore_prompt = True           # ignore echo'd prompts until usage
            self.accumulated_answer = ""
            self._pty.write(clean_text + "\r")
            _session_log("INPUT", clean_text)
            _debug(f"sent: {clean_text[:100]}...")

    def stop(self):
        """Terminate the chat session."""
        self._stop_event.set()
        self._cancel_idle_timer()
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

    # ── Idle Timer ──────────────────────────────────────────────────────────

    def _reset_idle_timer(self):
        """Reset the 2-second idle timer after each answer chunk.

        If the '> ' prompt is not detected within 2 s of the last answer
        chunk (e.g. displaydebugger does not emit a usage event and the
        prompt is somehow missed), synthesise a 'ready' event so the UI
        is not permanently stuck in the 'not waiting for input' state.
        """
        with self._idle_timer_lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
            self._idle_timer = threading.Timer(2.0, self._on_idle_timeout)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _cancel_idle_timer(self):
        with self._idle_timer_lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None

    def _on_idle_timeout(self):
        """Fired 2 s after the last answer chunk when '> ' was not detected."""
        if self._waiting_input.is_set() or self._stop_event.is_set():
            return  # already handled normally
        _debug("[idle] 2 s elapsed with no prompt — synthesising ready event")
        self._waiting_input.set()
        self.event_queue.put({
            "type": "ready",
            "accumulated_answer": self.accumulated_answer,
        })

    # ── PTY Reader ───────────────────────────────────────────────────────────

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
                        _debug(f"pty exited, remaining buf: {repr(buf[:300])}")
                        # Apply same \r handling as the main loop
                        remaining = buf.rstrip("\r")
                        if "\r" in remaining:
                            remaining = remaining.rsplit("\r", 1)[-1]
                        remaining = _strip_ansi(remaining).strip()
                        if remaining:
                            self._process_line(remaining)
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
                    # ConPTY uses \r\n line endings — strip the trailing \r first.
                    line = line.rstrip("\r")
                    # dt also uses \r (carriage return) to overwrite the status bar
                    # with JSON output in-place. After stripping the line-ending \r,
                    # any remaining \r means: STATUS_BAR\r{"answer":"text"}.
                    # Take the LAST \r-separated segment — that is the actual content.
                    if "\r" in line:
                        line = line.rsplit("\r", 1)[-1]
                    line = _strip_ansi(line).strip()
                    if line:
                        self._process_line(line)

                # Check for prompt in remaining buffer (may not end with \n)
                # Only check if we're NOT already in waiting state (avoid redraw spam)
                if not self._waiting_input.is_set():
                    clean_buf = buf.rstrip("\r")
                    if "\r" in clean_buf:
                        clean_buf = clean_buf.rsplit("\r", 1)[-1]
                    clean_buf = _strip_ansi(clean_buf).strip()
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
            # Detect GNAI config YAML corruption error
            if not self._config_error_handled and (
                "unable to load configuration" in line.lower() or
                "unknown escape character" in line.lower() or
                "mapping value is not allowed" in line.lower()
            ):
                self._config_error_handled = True
                self._handle_config_error(line)
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
            # Log output events for session I/O debugging
            etype = event['type']
            if etype == 'answer':
                _session_log("OUTPUT", f"[answer] {event.get('text', '')[:500]}")
            elif etype in ('tool_start', 'tool_request'):
                _session_log("EVENT", f"[{etype}] {event.get('name', '')}")
            elif etype == 'usage':
                _session_log("EVENT", f"[usage] turn complete")
            elif etype == 'ready':
                _session_log("EVENT", f"[ready] waiting for input")
            elif etype == 'error':
                _session_log("EVENT", f"[error] {event.get('text', '')[:200]}")
            elif etype in ('end', 'goodbye'):
                _session_log("EVENT", f"[{etype}] session ending")
            self.event_queue.put(event)

    def _classify_event(self, data):
        """Parse a JSON line from dt gnai chat --json into a typed event."""

        # Answer chunk: {"answer": "text", ...}
        if "answer" in data:
            text = data["answer"]
            self.accumulated_answer += text
            # AI has started responding → echo protection no longer needed.
            # This is important for assistants (e.g. displaydebugger) that do
            # not emit a "usage" event, which is the normal path to reset
            # _ignore_prompt. Without this, the subsequent '> ' prompt is
            # silently ignored and the session is stuck waiting forever.
            if self._ignore_prompt:
                self._ignore_prompt = False
            # Reset the idle timer: if '> ' prompt is not seen within 2 s of
            # the last answer chunk, _on_idle_timeout will synthesise 'ready'.
            self._reset_idle_timer()
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
                _debug(f"conversation_id captured: {conv_id}")
            return {
                "type": "tool_request",
                "name": req.get("name", ""),
                "operation": req.get("operation", ""),
                "request_id": req.get("request_id", ""),
                "conversation_id": self.session_id or "",
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

    def _handle_config_error(self, error_line):
        """Auto-repair ~/.gnai/config.yaml when dt reports a YAML parse error."""
        _debug(f"[config error] detected: {error_line[:200]}")
        fix_script = os.path.join(_SCRIPT_DIR, "fix_gnai_config.ps1")
        if os.name != "nt" or not os.path.exists(fix_script):
            self.event_queue.put({
                "type": "config_repair_failed",
                "text": f"GNAI config error: {error_line}\n\nPlease run: .\\bridge\\fix_gnai_config.ps1",
            })
            return
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", fix_script],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                _debug("[config error] auto-fix succeeded")
                self.event_queue.put({
                    "type": "config_repaired",
                    "message": "GNAI 設定檔已自動修復，重新啟動 session...",
                })
            else:
                _debug(f"[config error] auto-fix failed: {result.stderr[:300]}")
                self.event_queue.put({
                    "type": "config_repair_failed",
                    "text": f"GNAI config error: {error_line}\n\nAuto-fix failed. Please run: .\\bridge\\fix_gnai_config.ps1",
                })
        except Exception as e:
            _debug(f"[config error] auto-fix exception: {e}")
            self.event_queue.put({
                "type": "config_repair_failed",
                "text": f"GNAI config error detected. Please run: .\\bridge\\fix_gnai_config.ps1",
            })

    def _scan_pause_windows(self):
        """Periodically scan and close paused child cmd/GDHM windows."""
        while not self._stop_event.is_set():
            self._stop_event.wait(PAUSE_SCAN_INTERVAL)
            if self._stop_event.is_set():
                break
            if self._pty and self._pty.isalive():
                _close_paused_children(self._pty.pid)
                _close_gdhm_analysis_windows()


# ── Global Session Manager ──────────────────────────────────────────────────
_current_session = None
_session_lock = threading.Lock()


def _get_session():
    global _current_session
    return _current_session


def _start_session(assistant=None, conversation_id=None):
    global _current_session
    with _session_lock:
        if _current_session and _current_session.is_alive:
            _current_session.stop()
            _close_session_log()
        _init_session_log()
        session = ChatSession(assistant, conversation_id)
        session.start()
        _session_log("SESSION", f"assistant={session.assistant} conversation_id={session.conversation_id}")
        _current_session = session
        return session


def _stop_session():
    global _current_session
    with _session_lock:
        if _current_session:
            _current_session.stop()
            _current_session = None
        _close_session_log()


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
        elif self.path.startswith("/driver-history"):
            self._handle_driver_history_get()
        elif self.path.startswith("/dialog/file"):
            self._handle_file_dialog()
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
        elif self.path == "/driver-history":
            self._handle_driver_history_post()
        elif self.path == "/driver-history/delete":
            self._handle_driver_history_delete()
        elif self.path == "/build-cache/lookup":
            self._handle_build_cache_lookup()
        elif self.path == "/build-cache/save":
            self._handle_build_cache_save()
        elif _HAS_REGRESSION and self.path in _rb.PATHS:
            body = self._read_json_body()
            status, result = _rb.dispatch(self.path, body, _debug)
            self._json_response(status, result)
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
            "conversation_id": session.conversation_id if session else None,
        })

    # ── Driver History endpoints ─────────────────────────────────────────────

    def _handle_driver_history_get(self):
        """GET /driver-history?hsd_id=X&build_type=Y  →  lookup one record
           GET /driver-history?build_type=Y            →  list all records"""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        hsd_id     = (qs.get("hsd_id")     or [""])[0].strip()
        build_type = (qs.get("build_type") or ["gfx"])[0].strip()
        list_mode = (qs.get("list", ["0"])[0] == "1")
        if hsd_id and list_mode:
            records = _driver_history.list_for_hsd(hsd_id, build_type)
            self._json_response(200, {"ok": True, "records": records})
        elif hsd_id:
            record = _driver_history.lookup(hsd_id, build_type)
            if record:
                self._json_response(200, {"ok": True, "cached": True, "record": record})
            else:
                self._json_response(200, {"ok": True, "cached": False})
        else:
            records = _driver_history.list_all(build_type)
            self._json_response(200, {"ok": True, "records": records})

    def _handle_driver_history_post(self):
        """POST /driver-history  body: {hsd_id, build_type, hsd_data, qb_data}"""
        body = self._read_json_body()
        hsd_id     = str(body.get("hsd_id")     or "").strip()
        build_type = str(body.get("build_type") or "gfx").strip()
        if not hsd_id:
            self._json_response(400, {"ok": False, "error": "hsd_id required"})
            return
        record_id = _driver_history.save(hsd_id, build_type,
                                         body.get("hsd_data") or {},
                                         body.get("qb_data"))
        _debug(f"driver-history saved hsd_id={hsd_id} type={build_type} record_id={record_id}")
        self._json_response(200, {"ok": True, "record_id": record_id})

    def _handle_driver_history_delete(self):
        """POST /driver-history/delete  body: {record_id, build_type}"""
        body = self._read_json_body()
        record_id  = str(body.get("record_id")  or "").strip()
        build_type = str(body.get("build_type") or "gfx").strip()
        if not record_id:
            self._json_response(400, {"ok": False, "error": "record_id required"})
            return
        removed = _driver_history.delete(record_id, build_type)
        _debug(f"driver-history delete record_id={record_id} removed={removed}")
        self._json_response(200, {"ok": True, "removed": removed})

    def _handle_build_cache_lookup(self):
        """POST /build-cache/lookup  body: {versions: [...], build_type}"""
        body = self._read_json_body()
        versions   = [str(v) for v in (body.get("versions") or []) if v]
        build_type = str(body.get("build_type") or "gfx").strip()
        found   = _build_version_cache.lookup_multi(versions, build_type)
        missing = [v for v in versions if v not in found]
        _debug(f"build-cache lookup type={build_type} versions={versions} found={list(found.keys())}")
        self._json_response(200, {"ok": True, "found": found, "missing": missing})

    def _handle_build_cache_save(self):
        """POST /build-cache/save  body: {build_type, entries: [{version, build_data}]}"""
        body       = self._read_json_body()
        build_type = str(body.get("build_type") or "gfx").strip()
        entries    = body.get("entries") or []
        _build_version_cache.save_multi(entries, build_type)
        _debug(f"build-cache saved {len(entries)} entries type={build_type}")
        self._json_response(200, {"ok": True, "saved": len(entries)})

    def _handle_start(self):
        body = self._read_json_body()
        assistant = body.get("assistant", DEFAULT_ASSISTANT)
        conversation_id = body.get("conversation_id", None)
        # If session already active, return it instead of killing
        existing = _get_session()
        if existing and existing.is_alive:
            self._json_response(200, {
                "status": "already_active",
                "assistant": existing.assistant,
                "conversation_id": existing.conversation_id,
                "session_waiting_input": existing.is_waiting_input,
                "message": "Session already running.",
            })
            return
        try:
            session = _start_session(assistant, conversation_id)
            self._json_response(200, {
                "status": "starting",
                "assistant": session.assistant,
                "conversation_id": session.conversation_id,
                "message": "Session spawned. Connect to /session/stream for events.",
            })
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _handle_send(self):
        session = _get_session()
        if not session or not session.is_alive:
            self._json_response(400, {"error": "no_active_session"})
            return

        # Reject send if GNAI is still processing (prevents duplicate inputs)
        if not session.is_waiting_input:
            _debug("[BLOCKED] send rejected — session not waiting for input")
            self._json_response(409, {"error": "session_busy", "message": "AI is still processing. Please wait."})
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

    def _handle_file_dialog(self):
        """Open a native Windows file-picker dialog via PowerShell and return the chosen path."""
        import urllib.parse
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        title = params.get("title", ["Open File"])[0]
        # Build a PowerShell one-liner that opens the native OpenFileDialog.
        # A hidden TopMost owner form is used so the dialog always appears on top.
        ps = (
            '[System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null; '
            '$owner = New-Object System.Windows.Forms.Form; '
            '$owner.TopMost = $true; '
            '$owner.WindowState = [System.Windows.Forms.FormWindowState]::Minimized; '
            '$owner.ShowInTaskbar = $false; '
            '$owner.Show(); '
            '$d = New-Object System.Windows.Forms.OpenFileDialog; '
            f'$d.Title = \"{title}\"; '
            '$d.Multiselect = $false; '
            'if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) '
            '{ Write-Output $d.FileName } else { Write-Output "" }; '
            '$owner.Dispose()'
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=300,
            )
            path = result.stdout.strip()
            _debug(f"[dialog] file selected: {path!r}")
            self._json_response(200, {"path": path, "selected": bool(path)})
        except subprocess.TimeoutExpired:
            self._json_response(200, {"path": "", "selected": False, "reason": "timeout"})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

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
            # If session is already waiting for input when client (re)connects,
            # immediately send a ready event so UI can sync state.
            if session._waiting_input.is_set():
                ready_event = {
                    "type": "ready",
                    "accumulated_answer": session.accumulated_answer,
                }
                payload = json.dumps(ready_event, ensure_ascii=False)
                self.wfile.write(f"event: ready\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()

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


def _is_port_in_use(host, port):
    """Check if another process is already listening on the port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


_PID_FILE  = os.path.join(_SCRIPT_DIR, "bridge.pid")
_PORT_FILE = os.path.join(_SCRIPT_DIR, "bridge.port")


def _write_pid_file():
    """Write current PID to lock file."""
    try:
        with open(_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def _remove_pid_file():
    """Remove PID lock file on shutdown."""
    try:
        if os.path.exists(_PID_FILE):
            os.remove(_PID_FILE)
    except OSError:
        pass


def _write_port_file(port: int):
    """Write the actual listening port so native_host can discover it."""
    try:
        with open(_PORT_FILE, "w") as f:
            f.write(str(port))
    except OSError:
        pass


def _remove_port_file():
    """Remove port file on shutdown."""
    try:
        if os.path.exists(_PORT_FILE):
            os.remove(_PORT_FILE)
    except OSError:
        pass


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

    # Bind to PORT (0 = OS picks a free port).
    # After bind, read the actual port from the socket.
    # ── Port selection: prefer fixed port, fallback to random if occupied ──
    bind_port = PORT
    if PORT != 0 and _is_port_in_use(HOST, PORT):
        sys.stderr.write(
            f"[bridge] WARNING: Port {PORT} is already in use. Falling back to a random port.\n"
        )
        bind_port = 0

    server = BridgeServer((HOST, bind_port), BridgeHandler)
    actual_port = server.server_address[1]

    _debug(f"dt found at: {dt_cmd}")
    _debug(f"default assistant: {DEFAULT_ASSISTANT}")
    _debug(f"listening on port: {actual_port}")
    _debug(f"auto-close pause windows: {AUTO_CLOSE_PAUSE_WINDOWS}")

    _write_pid_file()
    _write_port_file(actual_port)   # lets native_host discover the port

    _debug(f"Chat Mode Bridge Server running on http://{HOST}:{actual_port} (PID: {os.getpid()})")
    _debug(f"Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] Shutting down...")
        _stop_session()
        server.shutdown()
    finally:
        _remove_pid_file()
        _remove_port_file()


if __name__ == "__main__":
    main()
