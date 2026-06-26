"""
Chat Mode Assistant — Environment Checker
==========================================
Checks all prerequisites before installation.
Can be run standalone or launched from the installer.
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont


# ── Check functions ────────────────────────────────────────────────────────

def check_windows():
    import platform
    ver = platform.version()
    release = platform.release()
    is_ok = sys.platform == "win32"
    return is_ok, f"Windows {release} ({ver})" if is_ok else "Not Windows"


def check_dt_in_path():
    path = shutil.which("dt")
    if path:
        try:
            r = subprocess.run(
                ["dt", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            raw = (r.stdout + r.stderr).strip()
            # Strip ANSI escape codes
            version_text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw).strip().splitlines()
            version = next((l.strip() for l in version_text if l.strip()), "found")
            return True, f"{path}  ({version[:60]})"
        except Exception as e:
            return True, f"{path}  (version check failed: {e})"
    return False, "dt not found in PATH — install Intel Developer Toolkit CLI"


def check_gnai_auth():
    """Check if dt gnai auth has been completed by looking for the config file."""
    config_candidates = [
        os.path.join(os.path.expanduser("~"), ".gnai", "config.yaml"),
        os.path.join(os.path.expanduser("~"), ".gnai", "config.yml"),
        os.path.join(os.environ.get("APPDATA", ""), "gnai", "config.yaml"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".dt", "gnai_config.yaml"),
    ]
    for p in config_candidates:
        if os.path.isfile(p):
            return True, f"Config found: {p}"

    # If no config file found, try running dt gnai and check output
    dt = shutil.which("dt")
    if not dt:
        return False, "dt not found — cannot check GNAI auth"
    try:
        r = subprocess.run(
            ["dt", "gnai", "auth", "--status"],
            capture_output=True, text=True, timeout=15,
        )
        raw = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", r.stdout + r.stderr).strip()
        if r.returncode == 0:
            return True, raw[:100] or "Auth OK"
        # Some dt versions don't have --status, fall through
    except Exception:
        pass

    return False, "GNAI config not found — please run:  dt gnai auth"


def check_chrome():
    """Check if Google Chrome is installed via Registry."""
    import winreg
    keys = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
    ]
    for hive, subkey in keys:
        try:
            with winreg.OpenKey(hive, subkey) as k:
                path, _ = winreg.QueryValueEx(k, "")
                if path and os.path.isfile(path):
                    return True, path
        except (FileNotFoundError, OSError):
            continue

    # Fallback: check common install locations
    common_paths = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return True, p

    return False, "Google Chrome not found — please install Chrome"


# Result constants for assistant check
_ASSISTANT_OK   = "ok"
_ASSISTANT_DENY = "denied"
_ASSISTANT_WARN = "warn"   # could not verify conclusively

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b.", re.I)

# Patterns detected in dt gnai chat --json output (case-insensitive)
_ERROR_PATTERNS = re.compile(
    r"permission.denied|unauthorized|forbidden|not.authorized|"
    r"access.denied|no.access|not.allowed|"
    r"assistant.not.found|unknown.assistant|invalid.assistant|"
    r"does.not.exist|cannot.find|could.not.find",
    re.I,
)
_SUCCESS_PATTERNS = re.compile(
    r"^\s*>\s*$|"           # bare prompt ">"
    r"^\s*>\s+|"            # prompt with text "> ..."
    r"loading|starting|initializ|connecting|authenticat",
    re.I | re.MULTILINE,
)


def _probe_gnai_assistant(assistant_name: str, timeout: float = 10.0):
    """
    Launch `dt gnai chat --json --assistant <name>`, read output for <timeout> seconds,
    and detect whether the assistant is accessible.

    Returns: (_ASSISTANT_OK | _ASSISTANT_DENY | _ASSISTANT_WARN, detail_str)
    """
    dt = shutil.which("dt")
    if not dt:
        return _ASSISTANT_WARN, "dt not found — skipped"

    try:
        proc = subprocess.Popen(
            [dt, "gnai", "chat", "--json", "--assistant", assistant_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception as e:
        return _ASSISTANT_WARN, f"Could not launch dt: {e}"

    # Collect output in background thread; terminate process after timeout
    output_lines = []
    stop_event = threading.Event()

    def _collect():
        for stream in (proc.stdout, proc.stderr):
            try:
                for line in iter(stream.readline, ""):
                    if stop_event.is_set():
                        break
                    clean = _ANSI_RE.sub("", line).strip()
                    if clean:
                        output_lines.append(clean)
            except Exception:
                pass

    t = threading.Thread(target=_collect, daemon=True)
    t.start()
    t.join(timeout=timeout)
    stop_event.set()

    # Terminate the process
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    combined = "\n".join(output_lines)

    if _ERROR_PATTERNS.search(combined):
        # Pick the first matching error line as the detail message
        for line in output_lines:
            if _ERROR_PATTERNS.search(line):
                return _ASSISTANT_DENY, line[:120]
        return _ASSISTANT_DENY, "Permission denied or assistant not accessible"

    if _SUCCESS_PATTERNS.search(combined):
        return _ASSISTANT_OK, "Accessible"

    if combined.strip():
        # Got some output but no clear signal — lean toward OK
        return _ASSISTANT_OK, f"Accessible (output: {combined.splitlines()[0][:80]})"

    # No output at all — dt may buffer without a PTY; can't determine access
    return _ASSISTANT_WARN, "Could not verify — ensure dt gnai auth is complete and you have access"


# ── GNAI Toolkit installation check ───────────────────────────────────────

_toolkit_cache      = None   # dict of {name: {"status": "valid"|"missing", "path": str}}
_toolkit_cache_lock = threading.Lock()
_toolkit_cache_err  = None   # str if the command failed entirely


def _get_installed_toolkits():
    """
    Run `dt gnai toolkits list` once and cache the result.
    Returns (dict | None, error_str | None).
    dict keys are toolkit names (lowercase), values are {"status": "valid"|"missing", "path": str}.
    """
    global _toolkit_cache, _toolkit_cache_err
    with _toolkit_cache_lock:
        if _toolkit_cache is not None or _toolkit_cache_err is not None:
            return _toolkit_cache, _toolkit_cache_err

        dt = shutil.which("dt")
        if not dt:
            _toolkit_cache_err = "dt not found"
            return None, _toolkit_cache_err

        try:
            r = subprocess.run(
                [dt, "gnai", "toolkits", "list"],
                capture_output=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            stdout = r.stdout or ""
            stderr = r.stderr or ""
        except Exception as e:
            _toolkit_cache_err = str(e)
            return None, _toolkit_cache_err

        toolkits = {}

        # ── Parse stdout ─────────────────────────────────────────────────
        # 1) Validation success lines:
        #    ✔️ Toolkit "name" at /path is valid
        for m in re.finditer(r'Toolkit\s+"([^"]+)"\s+at\s+(.+?)\s+is valid', stdout):
            name = m.group(1).strip().lower()
            toolkits[name] = {"status": "valid", "path": m.group(2).strip()}

        # 2) Table rows under the "Toolkit" section (stop at "Assistants" section)
        #    Separator line uses ─ (U+2500), not regular hyphens.
        #    Columns: Name  Description  Path  (separated by 2+ spaces)
        toolkit_section = re.split(r'\bAssistants\b', stdout, maxsplit=1)[0]
        in_table = False
        for line in toolkit_section.splitlines():
            stripped = line.strip()
            # Separator line: all ─ characters
            if re.match(r'^[─\-]{5,}', stripped):
                in_table = True
                continue
            if not in_table or not stripped:
                continue
            # Skip header row
            if re.match(r'^Name\b', stripped, re.I):
                continue
            # Split on 2+ spaces to get columns
            parts = re.split(r'  +', stripped)
            if not parts:
                continue
            name = parts[0].strip().lower()
            path = parts[-1].strip() if len(parts) >= 3 else ""
            if name and name not in toolkits:
                toolkits[name] = {"status": "valid", "path": path}

        # ── Parse stderr ─────────────────────────────────────────────────
        # Missing dependency lines:
        #   Dependency toolkit "name" is not registered
        for m in re.finditer(r'Dependency toolkit\s+"([^"]+)"\s+is not registered', stderr):
            name = m.group(1).strip().lower()
            if name not in toolkits:
                toolkits[name] = {"status": "missing", "path": ""}

        _toolkit_cache = toolkits
        return toolkits, None


def _make_toolkit_check(toolkit_name: str, assistant_name: str):
    """
    Combined check: toolkit installed AND assistant accessible.
    Returns a single result with a summary line.
    """
    def _check():
        # ── 1. Toolkit installed? ─────────────────────────────────────────
        toolkits, err = _get_installed_toolkits()
        if toolkits is None:
            tk_ok, tk_msg = None, f"Could not check toolkits: {err}"
        else:
            key = toolkit_name.lower()
            info = toolkits.get(key)
            if info and info["status"] == "valid":
                tk_ok, tk_msg = True, "installed"
            elif info and info["status"] == "missing":
                tk_ok, tk_msg = False, "missing dependency"
            else:
                tk_ok, tk_msg = False, "not installed"

        # ── 2. Assistant accessible? ──────────────────────────────────────
        result, detail = _probe_gnai_assistant(assistant_name)
        if result == _ASSISTANT_OK:
            ast_ok, ast_msg = True, "accessible"
        elif result == _ASSISTANT_DENY:
            ast_ok, ast_msg = False, f"no access ({detail[:60]})"
        else:
            ast_ok, ast_msg = None, "access unverified"

        # ── 3. Combine ────────────────────────────────────────────────────
        summary = f"Toolkit: {tk_msg}  |  Assistant: {ast_msg}"
        if tk_ok is False:
            return False, summary
        if ast_ok is False:
            return False, summary
        if tk_ok is None or ast_ok is None:
            return None, summary
        return True, summary

    return _check


CHECKS = [
    ("Intel dt CLI (PATH)",      check_dt_in_path,  None),
    ("GNAI Auth (dt gnai auth)",  check_gnai_auth,   None),
    ("sighting",       _make_toolkit_check("sighting",        "sighting_assistant"),
     "dt gnai toolkits register intel-sandbox/SightingAssistantTool"),
    ("displaydebugger", _make_toolkit_check("displaydebugger", "displaydebugger"),
     "dt gnai toolkits register intel-sandbox/displaydebugger"),
    ("sherlog",        _make_toolkit_check("sherlog",         "sherlog"),
     "dt gnai toolkits register intel-innersource/drivers.gpu.core.sherlog-toolkit"),
]


# ── GUI ────────────────────────────────────────────────────────────────────

class App(tk.Tk):

    BG         = "#f8fafc"
    HEADER_BG  = "#1e3a5f"
    CARD_BG    = "#ffffff"
    BLUE       = "#2563eb"
    GREEN      = "#16a34a"
    ORANGE     = "#d97706"
    RED        = "#dc2626"
    GRAY       = "#6b7280"
    TEXT_DARK  = "#111827"
    TEXT_MID   = "#4b5563"
    TEXT_LIGHT = "#9ca3af"
    BORDER     = "#e5e7eb"

    STATUS_RUNNING = ("⏳", "#d97706")
    STATUS_OK      = ("✓",  "#16a34a")
    STATUS_FAIL    = ("✗",  "#dc2626")
    STATUS_WARN    = ("⚠",  "#d97706")

    def __init__(self):
        super().__init__()
        self.title("Chat Mode Assistant — Environment Check")
        self.configure(bg=self.BG)
        self.resizable(True, True)
        self._fonts()
        self._build()
        self._center()
        self.after(200, self._run_checks)

    def _fonts(self):
        self.f_title  = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.f_sub    = tkfont.Font(family="Segoe UI", size=9)
        self.f_body   = tkfont.Font(family="Segoe UI", size=10)
        self.f_bold   = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_mono   = tkfont.Font(family="Consolas",  size=9)
        self.f_badge  = tkfont.Font(family="Segoe UI", size=11, weight="bold")

    def _build(self):
        # ── Header ─────────────────────────────────────────────────────────
        h = tk.Frame(self, bg=self.HEADER_BG, padx=24, pady=18)
        h.pack(fill="x")
        tk.Label(h, text="Chat Mode Assistant",
                 font=self.f_title, fg="white", bg=self.HEADER_BG).pack(anchor="w")
        tk.Label(h, text="Environment Check — Prerequisites",
                 font=self.f_sub, fg="#93c5fd", bg=self.HEADER_BG).pack(anchor="w")

        # ── Body ───────────────────────────────────────────────────────────
        self._body = tk.Frame(self, bg=self.BG, padx=28, pady=20)
        self._body.pack(fill="both", expand=True)

        tk.Label(self._body,
                 text="Checking the following prerequisites:",
                 font=self.f_body, bg=self.BG, fg=self.TEXT_MID,
                 anchor="w").pack(fill="x", pady=(0, 12))

        # ── Check rows ─────────────────────────────────────────────────────
        self._rows = []
        for i, (label, _, install_cmd) in enumerate(CHECKS):
            row_frame = tk.Frame(self._body, bg=self.CARD_BG,
                                 highlightbackground=self.BORDER,
                                 highlightthickness=1, padx=14, pady=10)
            row_frame.pack(fill="x", pady=3)

            badge = tk.Label(row_frame, text="⏳", font=self.f_badge,
                             bg=self.CARD_BG, fg=self.ORANGE, width=2, anchor="w")
            badge.pack(side="left")

            info_frame = tk.Frame(row_frame, bg=self.CARD_BG)
            info_frame.pack(side="left", fill="x", expand=True, padx=(8, 0))

            name_lbl = tk.Label(info_frame, text=label, font=self.f_bold,
                                bg=self.CARD_BG, fg=self.TEXT_DARK, anchor="w")
            name_lbl.pack(fill="x")

            detail_lbl = tk.Label(info_frame, text="Checking...", font=self.f_mono,
                                  bg=self.CARD_BG, fg=self.GRAY, anchor="w",
                                  wraplength=400, justify="left")
            detail_lbl.pack(fill="x")

            install_btn = tk.Button(
                info_frame, text="▶  Install",
                font=self.f_mono,
                command=lambda idx=i: self._install_toolkit(idx),
                bg=self.BLUE, fg="white", relief="flat",
                padx=10, pady=3, cursor="hand2",
            ) if install_cmd else None
            # Install button is hidden initially; pack() is called in _update_row when needed

            self._rows.append((badge, detail_lbl, install_btn))

        # ── Divider ────────────────────────────────────────────────────────
        tk.Frame(self._body, bg=self.BORDER, height=1).pack(fill="x", pady=(16, 10))

        # ── Summary label ──────────────────────────────────────────────────
        self._summary = tk.Label(self._body, text="",
                                 font=self.f_bold, bg=self.BG,
                                 fg=self.GRAY, anchor="w")
        self._summary.pack(fill="x")

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = tk.Frame(self._body, bg=self.BG)
        btn_row.pack(fill="x", pady=(12, 0))

        self._btn_recheck = tk.Button(
            btn_row, text="Re-check", font=self.f_body,
            command=self._recheck,
            bg=self.BLUE, fg="white", relief="flat",
            padx=16, pady=5, cursor="hand2", state="disabled")
        self._btn_recheck.pack(side="left")

        tk.Button(btn_row, text="Close", font=self.f_body,
                  command=self.destroy,
                  bg=self.BORDER, fg=self.TEXT_DARK, relief="flat",
                  padx=16, pady=5, cursor="hand2").pack(side="left", padx=(8, 0))

        # ── Help note ──────────────────────────────────────────────────────
        self._help = tk.Label(self._body, text="",
                              font=self.f_sub, bg=self.BG,
                              fg=self.ORANGE, anchor="w",
                              wraplength=480, justify="left")
        self._help.pack(fill="x", pady=(10, 0))

    def _run_checks(self):
        global _toolkit_cache, _toolkit_cache_err
        with _toolkit_cache_lock:
            _toolkit_cache     = None
            _toolkit_cache_err = None

        self._btn_recheck.config(state="disabled")
        self._summary.config(text="Checking...", fg=self.GRAY)
        self._help.config(text="")

        # Reset all rows to "running" state
        for badge, detail, install_btn in self._rows:
            badge.config(text="⏳", fg=self.ORANGE)
            detail.config(text="Checking...", fg=self.GRAY)
            if install_btn:
                install_btn.pack_forget()
                install_btn.config(state="normal", text="▶  Install")

        def worker():
            results = []
            for i, (label, fn, _) in enumerate(CHECKS):
                try:
                    ok, msg = fn()
                except Exception as e:
                    ok, msg = False, f"Error: {e}"
                results.append((i, ok, msg))
                # Update UI from main thread
                self.after(0, self._update_row, i, ok, msg)

            self.after(0, self._show_summary, results)

        threading.Thread(target=worker, daemon=True).start()

    def _update_row(self, i, ok, msg):
        badge, detail, install_btn = self._rows[i]
        if ok is True:
            icon, color = self.STATUS_OK
            detail_color = self.TEXT_MID
        elif ok is None:
            # Warning state — could not verify
            icon, color = self.STATUS_WARN
            detail_color = self.ORANGE
        else:
            icon, color = self.STATUS_FAIL
            detail_color = self.RED
        badge.config(text=icon, fg=color)
        detail.config(text=msg, fg=detail_color)

        # Show install button only when toolkit is confirmed not installed
        if install_btn:
            toolkit_not_installed = ok is False and (
                "not installed" in msg or "missing dependency" in msg
            )
            if toolkit_not_installed:
                install_btn.pack(anchor="w", pady=(4, 0))
            else:
                install_btn.pack_forget()

    def _show_summary(self, results):
        failed  = [(i, msg) for i, ok, msg in results if ok is False]
        warned  = [(i, msg) for i, ok, msg in results if ok is None]
        total   = len(results)
        passed  = total - len(failed) - len(warned)

        if not failed and not warned:
            self._summary.config(
                text=f"✓  All {total} checks passed — ready to install",
                fg=self.GREEN)
            self._help.config(text="")
        elif not failed:
            self._summary.config(
                text=f"⚠  {passed}/{total} passed, {len(warned)} unverified — please confirm before installing",
                fg=self.ORANGE)
            self._help.config(
                text="⚠ Could not automatically verify (may require manual confirmation):\n" +
                     "\n".join(f"  • {CHECKS[i][0]}: {msg}" for i, msg in warned))
        else:
            self._summary.config(
                text=f"✗  {len(failed)} failed ({passed}/{total} passed) — please fix before installing",
                fg=self.RED)
            help_lines = []
            for i, msg in failed:
                help_lines.append(f"✗ {CHECKS[i][0]}: {msg}")
            for i, msg in warned:
                help_lines.append(f"⚠ {CHECKS[i][0]}: {msg}")
            self._help.config(text="\n".join(help_lines))

        self._btn_recheck.config(state="normal")

    def _install_toolkit(self, i):
        """Open a PowerShell console to run the register command, then re-check."""
        _, _, install_btn = self._rows[i]
        cmd = CHECKS[i][2]
        if not cmd:
            return
        if install_btn:
            install_btn.config(state="disabled", text="Installing…")

        def _run():
            subprocess.Popen(
                ["powershell", "-NoExit", "-Command", cmd],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            ).wait()
            # After the console window is closed, reset button and re-check
            self.after(0, self._run_checks)

        threading.Thread(target=_run, daemon=True).start()

    def _recheck(self):
        self._run_checks()

    def _on_resize(self, event):
        if event.widget is self:
            inner_w = max(200, event.width - 80)
            for _, detail, _ in self._rows:
                detail.config(wraplength=inner_w)
            self._help.config(wraplength=inner_w)

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.minsize(w, h)
        self.bind("<Configure>", self._on_resize)


# ── Entry ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
