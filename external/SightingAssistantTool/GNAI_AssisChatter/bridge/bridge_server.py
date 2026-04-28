import json
import os
import re
import queue
import subprocess
import sys
import threading
import time
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("GNAI_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("GNAI_BRIDGE_PORT", "8775"))
TIMEOUT_SECONDS = int(os.environ.get("GNAI_BRIDGE_TIMEOUT", "240"))
REQUIRE_API_KEY = os.environ.get("GNAI_BRIDGE_API_KEY", "").strip()
DEFAULT_ASSISTANT = os.environ.get("GNAI_BRIDGE_DEFAULT_ASSISTANT", "sighting_assistant")
DT_PATH_OVERRIDE = os.environ.get("GNAI_BRIDGE_DT_PATH", "").strip()
MAX_FOLLOWUP_ROUNDS = int(os.environ.get("GNAI_BRIDGE_MAX_FOLLOWUP_ROUNDS", "0"))
FOLLOWUP_BUDGET_MS = int(os.environ.get("GNAI_BRIDGE_FOLLOWUP_BUDGET_MS", "85000"))
DEBUG_LOG = os.environ.get("GNAI_BRIDGE_DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}
MAX_HISTORY_MESSAGES = int(os.environ.get("GNAI_BRIDGE_MAX_HISTORY_MESSAGES", "12"))
MAX_HISTORY_CHARS = int(os.environ.get("GNAI_BRIDGE_MAX_HISTORY_CHARS", "12000"))
ECHO_RESPONSE = os.environ.get("GNAI_BRIDGE_ECHO_RESPONSE", "1").strip().lower() in {"1", "true", "yes", "on"}
STREAM_HEARTBEAT_SECONDS = max(1, int(os.environ.get("GNAI_BRIDGE_STREAM_HEARTBEAT_SECONDS", "2")))
STREAM_EMIT_INTERVAL_SECONDS = max(0.1, float(os.environ.get("GNAI_BRIDGE_STREAM_EMIT_INTERVAL_SECONDS", "0.5")))
STREAM_READ_CHARS = max(64, int(os.environ.get("GNAI_BRIDGE_STREAM_READ_CHARS", "1024")))
AUTO_CLOSE_PAUSE_WINDOWS = os.environ.get("GNAI_BRIDGE_AUTO_CLOSE_PAUSE_WINDOWS", "1").strip().lower() in {"1", "true", "yes", "on"}
PAUSE_SCAN_INTERVAL_SECONDS = max(1, int(os.environ.get("GNAI_BRIDGE_PAUSE_SCAN_INTERVAL_SECONDS", "2")))

_ECHO_LOCK = threading.Lock()


def _debug(message):
    if DEBUG_LOG:
        sys.stdout.write(f"[bridge-debug] {message}\n")


def _echo_assistant_output(text, append_newline=False):
    if not ECHO_RESPONSE:
        return
    if not isinstance(text, str) or text == "":
        if append_newline:
            with _ECHO_LOCK:
                sys.stdout.write("\n")
                sys.stdout.flush()
        return
    with _ECHO_LOCK:
        sys.stdout.write(text)
        if append_newline:
            sys.stdout.write("\n")
        sys.stdout.flush()


_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]"   # standard CSI: ESC [ ... letter  (e.g. \x1b[2m)
    r"|\x1b[^[\x1b]"            # other ESC sequences (ESC + single char)
    r"|\[[0-9;]+m",             # bare [Nm] / [N;Nm] without ESC (when ESC is stripped upstream)
    re.IGNORECASE
)

def _strip_ansi(text):
    return _ANSI_ESCAPE_RE.sub("", text)


def _short(text, limit=280):
    value = (text or "").replace("\r", " ").replace("\n", " ").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def _collect_descendant_processes_windows(root_pid):
    if os.name != "nt":
        return []

    script = (
        "$items = Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine; "
        "$items | ConvertTo-Json -Compress"
    )

    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
        )
    except Exception:
        return []

    if completed.returncode != 0 or not completed.stdout.strip():
        return []

    try:
        data = json.loads(completed.stdout)
    except Exception:
        return []

    rows = data if isinstance(data, list) else [data]
    by_parent = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        parent = row.get("ParentProcessId")
        if parent is None:
            continue
        by_parent.setdefault(int(parent), []).append(row)

    descendants = []
    stack = [int(root_pid)]
    seen = set(stack)
    while stack:
        parent = stack.pop()
        for child in by_parent.get(parent, []):
            pid = int(child.get("ProcessId", 0) or 0)
            if pid <= 0 or pid in seen:
                continue
            seen.add(pid)
            descendants.append(child)
            stack.append(pid)

    return descendants


def _maybe_close_paused_child_windows(root_pid):
    if os.name != "nt" or not AUTO_CLOSE_PAUSE_WINDOWS:
        return

    descendants = _collect_descendant_processes_windows(root_pid)
    targets = []

    for row in descendants:
        name = str(row.get("Name", "")).strip().lower()
        cmdline = str(row.get("CommandLine", "")).strip().lower()
        pid = int(row.get("ProcessId", 0) or 0)
        if pid <= 0:
            continue

        if name not in {"cmd.exe", "powershell.exe", "pwsh.exe"}:
            continue

        looks_pause = (
            " pause" in cmdline
            or "&& pause" in cmdline
            or " -noexit" in cmdline
            or " /k " in cmdline
        )
        if not looks_pause:
            continue

        targets.append((pid, name, cmdline))

    for pid, name, cmdline in targets:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=6,
            )
            _debug(f"auto-closed paused child process pid={pid} name={name} cmd='{_short(cmdline, 180)}'")
        except Exception as err:
            _debug(f"failed to auto-close paused child pid={pid}: {err}")


def _is_expected_disconnect_error(err):
    if isinstance(err, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    if isinstance(err, OSError):
        winerror = getattr(err, "winerror", None)
        errno = getattr(err, "errno", None)
        if winerror in {10053, 10054, 995}:
            return True
        if errno in {32, 54, 104}:
            return True
    return False


def _resolve_dt_command():
    if DT_PATH_OVERRIDE:
        if os.path.isfile(DT_PATH_OVERRIDE):
            return DT_PATH_OVERRIDE, "override"
        return None, f"override_not_found:{DT_PATH_OVERRIDE}"

    dt_from_path = shutil.which("dt")
    if dt_from_path:
        return dt_from_path, "path"

    return None, "not_found"


def _json_response(handler, status_code, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        handler.send_response(status_code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, x-gnai-assistant")
        handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as err:
        # Client disconnected or local socket got aborted before response was written.
        if _is_expected_disconnect_error(err):
            _debug(f"response write skipped (client disconnected): {err}")
        else:
            sys.stdout.write(f"[bridge] response write skipped: {err}\n")


def _stream_json_line(handler, payload):
    try:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        handler.wfile.write(body)
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as err:
        if _is_expected_disconnect_error(err):
            _debug(f"stream write skipped (client disconnected): {err}")
        else:
            sys.stdout.write(f"[bridge] stream write skipped: {err}\n")
        return False


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        _, exc, _ = sys.exc_info()
        if exc and _is_expected_disconnect_error(exc):
            _debug(f"request aborted by client {client_address}: {exc}")
            return
        super().handle_error(request, client_address)


def _extract_bearer_token(headers):
    auth = headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return ""
    return auth[7:].strip()


def _check_auth(headers):
    if not REQUIRE_API_KEY:
        return True
    token = _extract_bearer_token(headers)
    return token == REQUIRE_API_KEY


def _get_last_user_message(messages):
    if not isinstance(messages, list):
        return ""
    for item in reversed(messages):
        if isinstance(item, dict) and item.get("role") == "user":
            content = item.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _build_prompt_from_messages(messages):
    if not isinstance(messages, list):
        return ""

    def _normalize_text(value):
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    max_chars = max(1000, MAX_HISTORY_CHARS)

    # Keep only user/assistant turns and cap turn count first.
    turns = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = _normalize_text(item.get("content", ""))
        if not text:
            continue
        turns.append((role, text))

    if not turns:
        return ""

    turns = turns[-max(1, MAX_HISTORY_MESSAGES):]

    # Build from newest to oldest within budget so we do not cut messages mid-way.
    selected = []
    used = 0
    for role, text in reversed(turns):
        block = f"{role.upper()}:\n{text}"
        block_len = len(block) + 2
        if selected and (used + block_len) > max_chars:
            break
        selected.append(block)
        used += block_len

    selected.reverse()
    if not selected:
        role, text = turns[-1]
        selected = [f"{role.upper()}:\n{text[:max_chars]}"]

    latest_user_text = ""
    for role, text in reversed(turns):
        if role == "user":
            latest_user_text = text
            break

    user_hsd_ids = []
    for role, text in turns:
        if role != "user":
            continue
        for found in re.findall(r"\b(?:HSD\s*[:#-]?\s*)?(\d{8,})\b", text, flags=re.IGNORECASE):
            if found not in user_hsd_ids:
                user_hsd_ids.append(found)

    facts = []
    if user_hsd_ids:
        facts.append("Known HSD IDs from user: " + ", ".join(user_hsd_ids[-3:]))

    prompt = "You are continuing an existing conversation.\n"
    prompt += "Do not ask the user to repeat details that already exist in the memory facts or transcript.\n"
    prompt += "If HSD IDs exist below, use them directly in your answer.\n"

    # For stateless dt ask, use a focused follow-up template so the model keeps the same HSD context.
    if latest_user_text and user_hsd_ids:
        active_hsd = user_hsd_ids[-1]
        focused = (
            f"Please assist with the HSD id {active_hsd}.\n"
            "This is a follow-up question for the same HSD case.\n"
            "This HSD ID is from user input history.\n"
            "Do not replace it with IDs mentioned only by assistant output.\n"
            "Do not ask for HSD ID again unless user asks to change HSD.\n\n"
            "Follow-up request:\n"
            f"{latest_user_text}\n\n"
            "Answer directly for this HSD case."
        )
        if len(focused) <= max_chars:
            return focused

    if facts:
        prompt += "\nMemory facts:\n"
        for item in facts:
            prompt += f"- {item}\n"

    prompt += "\nConversation transcript (recent turns):\n\n"
    prompt += "\n\n".join(selected)

    if latest_user_text:
        prompt += "\n\nCurrent user request:\n"
        prompt += latest_user_text

    prompt += "\n\nAnswer as ASSISTANT and continue from the context above."
    return prompt


def _trim_text(text, limit=2000):
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n... [truncated]"


def _normalize_conversation_id(value):
    raw = str(value or "").strip()
    if not raw:
        return ""

    # Keep the ID shell-safe and bounded for CLI argument usage.
    normalized = re.sub(r"[^A-Za-z0-9._:+-]", "-", raw)
    return normalized[:80]


def _build_dt_command(dt_command, prompt_text, assistant=None, conversation_id=None, gnai_mode="ask"):
    mode = gnai_mode if gnai_mode in ("ask", "chat") else "ask"
    if mode == "chat":
        # gnai chat requires --prompt flag; use --prompt="..." single-token form for reliable parsing
        cmd = [dt_command, "gnai", "chat", f'--prompt={prompt_text}']
    else:
        cmd = [dt_command, "gnai", "ask", prompt_text]
    # Per session policy: only pass conversation id, never force assistant from bridge.
    if conversation_id:
        cmd.extend(["--conversation-id", str(conversation_id)])
    return cmd


def _build_dt_run_kwargs():
    env = os.environ.copy()
    env["CI"] = "1"
    env.setdefault("TERM", "dumb")
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("LESS", "-F -X")

    kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "shell": False,
        "stdin": subprocess.DEVNULL,
        "env": env,
    }

    if os.name == "nt":
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if create_no_window:
            kwargs["creationflags"] = create_no_window

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _build_dt_popen_kwargs():
    env = os.environ.copy()
    env["CI"] = "1"
    env.setdefault("TERM", "dumb")
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("LESS", "-F -X")

    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "shell": False,
        "stdin": subprocess.DEVNULL,
        "env": env,
        "bufsize": 1,
    }

    if os.name == "nt":
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if create_no_window:
            kwargs["creationflags"] = create_no_window

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _run_dt_gnai(prompt_text, assistant=None, conversation_id=None, gnai_mode="ask"):
    dt_command, dt_source = _resolve_dt_command()
    if not dt_command:
        return {
            "ok": False,
            "error": (
                "dt command not found. Please install/configure dt CLI first, "
                "or set GNAI_BRIDGE_DT_PATH to full dt executable path."
            ),
            "status": 500,
            "dt_source": dt_source,
        }

    cmd = _build_dt_command(
        dt_command,
        prompt_text,
        assistant=assistant,
        conversation_id=conversation_id,
        gnai_mode=gnai_mode,
    )
    has_assistant_flag = "--assistant" in cmd

    _debug(
        "dt start "
        f"dt_source={dt_source} assistant_flag={has_assistant_flag} "
        f"conversation_id={conversation_id or '-'} prompt='{_short(prompt_text)}'"
    )
    _debug(f"dt cmd: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(cmd, **_build_dt_popen_kwargs())
        started = time.time()
        stdout_text = ""
        stderr_text = ""
        while True:
            elapsed = time.time() - started
            remaining = TIMEOUT_SECONDS - elapsed
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=TIMEOUT_SECONDS, output=stdout_text, stderr=stderr_text)

            slice_timeout = min(PAUSE_SCAN_INTERVAL_SECONDS, max(0.5, remaining))
            try:
                stdout_text, stderr_text = proc.communicate(timeout=slice_timeout)
                break
            except subprocess.TimeoutExpired:
                _maybe_close_paused_child_windows(proc.pid)
                continue

        class _Completed:
            pass

        completed = _Completed()
        completed.stdout = stdout_text
        completed.stderr = stderr_text
        completed.returncode = proc.returncode
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "dt executable not found. Please check GNAI_BRIDGE_DT_PATH or PATH.",
            "status": 500,
            "dt_source": dt_source,
        }
    except subprocess.TimeoutExpired as err:
        try:
            proc.kill()
        except Exception:
            pass
        _debug(f"dt timeout after {TIMEOUT_SECONDS}s")
        return {
            "ok": False,
            "error": f"dt gnai ask timeout after {TIMEOUT_SECONDS}s",
            "status": 504,
            "stdout": _trim_text(err.stdout or ""),
            "stderr": _trim_text(err.stderr or ""),
            "return_code": None,
        }

    duration_ms = int((time.time() - started) * 1000)
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if completed.returncode != 0:
        combined = f"{stderr}\n{stdout}".lower()
        hint = ""
        if "press any key" in combined:
            hint = "Detected interactive prompt from dt/underlying command. Bridge now runs non-interactive, but please verify dt side scripts do not enforce pause."

        _debug(
            "dt failed "
            f"code={completed.returncode} duration_ms={duration_ms} "
            f"stderr='{_short(stderr)}' stdout='{_short(stdout)}'"
        )
        return {
            "ok": False,
            "error": stderr or stdout or f"dt gnai ask failed with exit code {completed.returncode}",
            "status": 502,
            "duration_ms": duration_ms,
            "return_code": completed.returncode,
            "dt_source": dt_source,
            "stdout": _trim_text(stdout),
            "stderr": _trim_text(stderr),
            "hint": hint,
        }

    _debug(
        "dt ok "
        f"duration_ms={duration_ms} return_code={completed.returncode} "
        f"content='{_short(stdout or '(empty response)')}'"
    )

    return {
        "ok": True,
        "content": stdout or "(empty response)",
        "duration_ms": duration_ms,
        "return_code": completed.returncode,
        "dt_source": dt_source,
    }


def _run_dt_gnai_stream(prompt_text, on_delta, assistant=None, conversation_id=None, gnai_mode="ask"):
    dt_command, dt_source = _resolve_dt_command()
    if not dt_command:
        return {
            "ok": False,
            "error": (
                "dt command not found. Please install/configure dt CLI first, "
                "or set GNAI_BRIDGE_DT_PATH to full dt executable path."
            ),
            "status": 500,
            "dt_source": dt_source,
        }

    cmd = _build_dt_command(
        dt_command,
        prompt_text,
        assistant=assistant,
        conversation_id=conversation_id,
        gnai_mode=gnai_mode,
    )
    has_assistant_flag = "--assistant" in cmd

    _debug(
        "dt stream start "
        f"dt_source={dt_source} assistant_flag={has_assistant_flag} "
        f"conversation_id={conversation_id or '-'} prompt='{_short(prompt_text)}'"
    )
    _debug(f"dt stream cmd: {' '.join(cmd)}")
    q = queue.Queue()
    started = time.time()
    stdout_parts = []
    stderr_parts = []

    def _pump_chars(name, stream):
        try:
            while True:
                # Read in chunks instead of per-character to reduce CPU overhead.
                chunk = stream.read(STREAM_READ_CHARS)
                if not chunk:
                    break
                q.put((name, chunk))
        finally:
            q.put((f"{name}_done", None))

    def _emit_pending_delta(text):
        if not text:
            return True
        if on_delta(text) is False:
            try:
                proc.kill()
            except Exception:
                pass
            return False
        return True

    try:
        proc = subprocess.Popen(cmd, **_build_dt_popen_kwargs())
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "dt executable not found. Please check GNAI_BRIDGE_DT_PATH or PATH.",
            "status": 500,
            "dt_source": dt_source,
        }

    t_out = threading.Thread(target=_pump_chars, args=("stdout", proc.stdout), daemon=True)
    t_err = threading.Thread(target=_pump_chars, args=("stderr", proc.stderr), daemon=True)
    t_out.start()
    t_err.start()

    stdout_done = False
    stderr_done = False
    pending = ""
    last_emit = time.time()
    last_pause_scan = 0.0
    last_activity = time.time()

    while not (stdout_done and stderr_done):
        if (time.time() - last_activity) > TIMEOUT_SECONDS:
            try:
                proc.kill()
            except Exception:
                pass
            duration_ms = int((time.time() - started) * 1000)
            _debug(f"dt stream inactivity timeout after {TIMEOUT_SECONDS}s")
            return {
                "ok": False,
                "error": f"dt gnai ask inactivity timeout after {TIMEOUT_SECONDS}s (no new data)",
                "status": 504,
                "stdout": _trim_text("".join(stdout_parts)),
                "stderr": _trim_text("".join(stderr_parts)),
                "return_code": None,
                "duration_ms": duration_ms,
                "dt_source": dt_source,
            }

        try:
            kind, data = q.get(timeout=0.2)
        except queue.Empty:
            kind, data = None, None

        now_for_scan = time.time()
        if (now_for_scan - last_pause_scan) >= PAUSE_SCAN_INTERVAL_SECONDS:
            _maybe_close_paused_child_windows(proc.pid)
            last_pause_scan = now_for_scan

        if kind == "stdout":
            stdout_parts.append(data)
            pending += data
            now = time.time()
            last_activity = now

            # Prefer line-level emission; otherwise flush by time budget.
            newline_idx = pending.rfind("\n")
            if newline_idx >= 0:
                ready = pending[: newline_idx + 1]
                pending = pending[newline_idx + 1 :]
                if not _emit_pending_delta(ready):
                    return {
                        "ok": False,
                        "error": "client disconnected during stream",
                        "status": 499,
                        "stdout": _trim_text("".join(stdout_parts)),
                        "stderr": _trim_text("".join(stderr_parts)),
                        "return_code": None,
                        "duration_ms": int((time.time() - started) * 1000),
                        "dt_source": dt_source,
                    }
                last_emit = now

            if pending and (now - last_emit) >= STREAM_EMIT_INTERVAL_SECONDS:
                if not _emit_pending_delta(pending):
                    return {
                        "ok": False,
                        "error": "client disconnected during stream",
                        "status": 499,
                        "stdout": _trim_text("".join(stdout_parts)),
                        "stderr": _trim_text("".join(stderr_parts)),
                        "return_code": None,
                        "duration_ms": int((time.time() - started) * 1000),
                        "dt_source": dt_source,
                    }
                pending = ""
                last_emit = now
        elif kind == "stderr":
            stderr_parts.append(data)
        elif kind == "stdout_done":
            stdout_done = True
        elif kind == "stderr_done":
            stderr_done = True

    if pending:
        if not _emit_pending_delta(pending):
            return {
                "ok": False,
                "error": "client disconnected during stream",
                "status": 499,
                "stdout": _trim_text("".join(stdout_parts)),
                "stderr": _trim_text("".join(stderr_parts)),
                "return_code": None,
                "duration_ms": int((time.time() - started) * 1000),
                "dt_source": dt_source,
            }

    return_code = proc.wait(timeout=5)
    duration_ms = int((time.time() - started) * 1000)
    stdout = "".join(stdout_parts).strip()
    stderr = "".join(stderr_parts).strip()

    if return_code != 0:
        _debug(
            "dt stream failed "
            f"code={return_code} duration_ms={duration_ms} "
            f"stderr='{_short(stderr)}' stdout='{_short(stdout)}'"
        )
        return {
            "ok": False,
            "error": stderr or stdout or f"dt gnai ask failed with exit code {return_code}",
            "status": 502,
            "duration_ms": duration_ms,
            "return_code": return_code,
            "dt_source": dt_source,
            "stdout": _trim_text(stdout),
            "stderr": _trim_text(stderr),
        }

    _debug(
        "dt stream ok "
        f"duration_ms={duration_ms} return_code={return_code} "
        f"content='{_short(stdout or '(empty response)')}'"
    )

    return {
        "ok": True,
        "content": stdout or "(empty response)",
        "duration_ms": duration_ms,
        "return_code": return_code,
        "dt_source": dt_source,
    }


def _looks_like_kickoff_only(content):
    text = (content or "").strip().lower()
    if not text:
        return True

    patterns = [
        r"let me start",
        r"i\s*'?ll analyze",
        r"gathering all (the )?necessary data",
        r"i\s*will analyze",
        r"我會先",
        r"先收集",
        r"開始分析",
        r"先進行",
    ]

    if len(text) < 240:
        for p in patterns:
            if re.search(p, text):
                return True

    return False


def _build_followup_prompt(original_prompt, previous_output):
    return (
        "Your previous reply only described starting the analysis and did not provide the final result. "
        "Please provide the complete final analysis directly. Do not restate process steps or say you are about to start."
        "\n\nOriginal user request:\n"
        f"{original_prompt}\n\n"
        "Your previous reply:\n"
        f"{previous_output}\n\n"
        "Now provide the final deliverable answer directly."
    )


def _is_direct_punchline_prompt(prompt_text):
    text = str(prompt_text or "").strip().lower()
    if not text:
        return False

    normalized = re.sub(r"\s+", " ", text)
    return bool(
        re.fullmatch(
            r"please give me a punchline summary of hsd \d{8,} and skip attachment check",
            normalized,
        )
    )


def _run_dt_gnai_with_followup(prompt_text, assistant=None, conversation_id=None):
    first = _run_dt_gnai(prompt_text, assistant=assistant, conversation_id=conversation_id)
    if not first.get("ok"):
        return first

    content = first.get("content", "")
    total_duration = int(first.get("duration_ms") or 0)
    rounds = 0
    dt_source = first.get("dt_source")
    return_code = first.get("return_code")

    while rounds < max(0, MAX_FOLLOWUP_ROUNDS) and _looks_like_kickoff_only(content):
        if total_duration >= max(0, FOLLOWUP_BUDGET_MS):
            break

        rounds += 1
        _debug(f"followup round={rounds} triggered")
        followup_prompt = _build_followup_prompt(prompt_text, content)
        nxt = _run_dt_gnai(followup_prompt, assistant=assistant, conversation_id=conversation_id)
        if not nxt.get("ok"):
            nxt["followup_rounds"] = rounds
            nxt["partial_content"] = content
            nxt["duration_ms"] = int(nxt.get("duration_ms") or 0) + total_duration
            return nxt

        content = nxt.get("content", content)
        total_duration += int(nxt.get("duration_ms") or 0)
        dt_source = nxt.get("dt_source", dt_source)
        return_code = nxt.get("return_code", return_code)

        if total_duration >= max(0, FOLLOWUP_BUDGET_MS):
            break

    return {
        "ok": True,
        "content": content,
        "duration_ms": total_duration,
        "return_code": return_code,
        "dt_source": dt_source,
        "followup_rounds": rounds,
    }


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "GNAIBridge/1.0"
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self):
        _json_response(self, 200, {"ok": True})

    def do_GET(self):
        if self.path in ("/health", "/v1/health"):
            dt_command, dt_source = _resolve_dt_command()
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "gnai-bridge",
                    "host": HOST,
                    "port": PORT,
                    "timeout_seconds": TIMEOUT_SECONDS,
                    "default_assistant": DEFAULT_ASSISTANT,
                    "requires_api_key": bool(REQUIRE_API_KEY),
                    "streaming": {
                        "enabled": True,
                        "path": "/v1/chat/completions/stream",
                    },
                    "dt": {
                        "resolved": bool(dt_command),
                        "path": dt_command,
                        "source": dt_source,
                    },
                },
            )
            return

        _json_response(self, 404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        if self.path not in (
            "/chat/completions",
            "/v1/chat/completions",
            "/chat/completions/stream",
            "/v1/chat/completions/stream",
        ):
            _json_response(self, 404, {"ok": False, "error": "Not found"})
            return

        if not _check_auth(self.headers):
            _json_response(self, 401, {"ok": False, "error": "Unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            _json_response(self, 400, {"ok": False, "error": "Invalid Content-Length"})
            return

        try:
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            _json_response(self, 400, {"ok": False, "error": "Invalid JSON payload"})
            return

        assistant = (
            self.headers.get("x-gnai-assistant", "").strip()
            or str(payload.get("assistant", "")).strip()
            or DEFAULT_ASSISTANT
        )
        conversation_id = _normalize_conversation_id(
            payload.get("conversation_id") or payload.get("conversationId")
        )
        gnai_mode = str(payload.get("gnai_mode", "ask")).strip().lower()
        if gnai_mode not in ("ask", "chat"):
            gnai_mode = "ask"

        prompt = _get_last_user_message(payload.get("messages"))
        if not prompt:
            _json_response(self, 400, {"ok": False, "error": "No user message found in payload.messages"})
            return

        direct_dt_mode = _is_direct_punchline_prompt(prompt)

        _debug(
            "request "
            f"path={self.path} assistant={assistant} model={payload.get('model', 'N/A')} "
            f"conversation_id={conversation_id or '-'} "
            f"direct_dt_mode={direct_dt_mode} "
            f"prompt='{_short(prompt)}'"
        )

        if self.path in ("/chat/completions/stream", "/v1/chat/completions/stream"):
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, x-gnai-assistant")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return

            if not _stream_json_line(
                self,
                {
                    "type": "start",
                    "assistant": assistant,
                    "model": payload.get("model", "dt-gnai"),
                    "created": int(time.time()),
                },
            ):
                return

            heartbeat_stop = threading.Event()

            def _heartbeat_loop():
                while not heartbeat_stop.wait(STREAM_HEARTBEAT_SECONDS):
                    if not _stream_json_line(
                        self,
                        {
                            "type": "heartbeat",
                            "ts": int(time.time()),
                        },
                    ):
                        heartbeat_stop.set()
                        break

            heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
            heartbeat_thread.start()

            def _on_delta(delta_text):
                _echo_assistant_output(delta_text)
                return _stream_json_line(
                    self,
                    {
                        "type": "chunk",
                        "delta": _strip_ansi(delta_text),
                    },
                )

            try:
                stream_result = _run_dt_gnai_stream(
                    prompt,
                    _on_delta,
                    assistant=None if direct_dt_mode else assistant,
                    conversation_id=conversation_id,
                    gnai_mode=gnai_mode,
                )
                if not stream_result.get("ok"):
                    _stream_json_line(
                        self,
                        {
                            "type": "error",
                            "error": stream_result.get("error", "Unknown bridge error"),
                            "assistant": assistant,
                            "dt_source": stream_result.get("dt_source"),
                            "duration_ms": stream_result.get("duration_ms"),
                            "return_code": stream_result.get("return_code"),
                            "conversation_id": conversation_id,
                            "stdout": stream_result.get("stdout"),
                            "stderr": stream_result.get("stderr"),
                        },
                    )
                    return

                if ECHO_RESPONSE:
                    content_text = str(stream_result.get("content", ""))
                    if content_text and not content_text.endswith("\n"):
                        _echo_assistant_output("", append_newline=True)

                _stream_json_line(
                    self,
                    {
                        "type": "done",
                        "content": stream_result.get("content", ""),
                        "assistant": assistant,
                        "duration_ms": stream_result.get("duration_ms"),
                        "return_code": stream_result.get("return_code"),
                        "conversation_id": conversation_id,
                        "dt_source": stream_result.get("dt_source"),
                    },
                )
                return
            finally:
                heartbeat_stop.set()

        if direct_dt_mode:
            result = _run_dt_gnai(
                prompt,
                assistant=None,
                conversation_id=conversation_id,
                gnai_mode=gnai_mode,
            )
            result.setdefault("followup_rounds", 0)
        else:
            result = _run_dt_gnai_with_followup(
                prompt,
                assistant=assistant,
                conversation_id=conversation_id,
            )
        if not result.get("ok"):
            _debug(
                "response error "
                f"status={result.get('status', 500)} duration_ms={result.get('duration_ms')} "
                f"error='{_short(result.get('error', 'Unknown bridge error'))}'"
            )
            _json_response(
                self,
                int(result.get("status", 500)),
                {
                    "ok": False,
                    "error": result.get("error", "Unknown bridge error"),
                    "assistant": assistant,
                    "dt_source": result.get("dt_source"),
                    "duration_ms": result.get("duration_ms"),
                    "return_code": result.get("return_code"),
                    "conversation_id": conversation_id,
                    "stdout": result.get("stdout"),
                    "stderr": result.get("stderr"),
                    "hint": result.get("hint"),
                    "followup_rounds": result.get("followup_rounds", 0),
                    "partial_content": result.get("partial_content"),
                },
            )
            return

        content = result["content"]
        _echo_assistant_output(content, append_newline=True)
        response_payload = {
            "id": f"gnai-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", "dt-gnai"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            },
            "bridge": {
                "assistant": assistant,
                "duration_ms": result.get("duration_ms"),
                "return_code": result.get("return_code"),
                "conversation_id": conversation_id,
                "dt_source": result.get("dt_source"),
                "followup_rounds": result.get("followup_rounds", 0),
            },
        }
        _debug(
            "response ok "
            f"duration_ms={result.get('duration_ms')} followup_rounds={result.get('followup_rounds', 0)} "
            f"content='{_short(content)}'"
        )
        _json_response(self, 200, response_payload)

    def log_message(self, fmt, *args):
        sys.stdout.write("[bridge] " + (fmt % args) + "\n")


def main():
    print(f"Starting GNAI bridge on http://{HOST}:{PORT}")
    print(f"Default assistant: {DEFAULT_ASSISTANT}")
    if REQUIRE_API_KEY:
        print("API key auth: enabled")
    else:
        print("API key auth: disabled")
    print(f"Bridge debug log: {'enabled' if DEBUG_LOG else 'disabled'}")
    print(f"Echo assistant output: {'enabled' if ECHO_RESPONSE else 'disabled'}")

    server = BridgeHTTPServer((HOST, PORT), BridgeHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Bridge stopped.")


if __name__ == "__main__":
    main()
