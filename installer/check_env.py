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
from tkinter import font as tkfont, messagebox

# Where to grab the latest dt.exe when it's missing from PATH.
DT_DOWNLOAD_URL = "https://gfx-assets.intel.com/artifactory/gfx-build-assets/build-tools/devtool-go/latest/artifacts/win64/dt.exe"

# Opens the download in the default browser, then reminds the user to run
# `dt.exe install` once the download finishes (mirrors the toolkit "Install"
# button flow — runs in a PowerShell console via _install_toolkit()).
DT_INSTALL_HELP_CMD = (
    f"Start-Process '{DT_DOWNLOAD_URL}'; "
    "Write-Host ''; "
    "Write-Host 'Downloading dt.exe in your browser...' -ForegroundColor Cyan; "
    "Write-Host 'Once the download finishes, run this from the downloaded file''s folder:'; "
    "Write-Host '  dt.exe install' -ForegroundColor Yellow; "
    "Write-Host ''; "
    "Read-Host 'Press Enter to close this window'"
)


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
    return False, (
        "dt not found in PATH — download the latest dt.exe from "
        f"{DT_DOWNLOAD_URL} and run 'dt.exe install'"
    )


def check_gnai_connection():
    """Test GNAI connectivity by launching dt gnai chat --json and checking for any response."""
    dt = shutil.which("dt")
    if not dt:
        return False, "dt not found — cannot test GNAI"

    _ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b.", re.I)
    output_lines = []
    stop_event = threading.Event()

    try:
        proc = subprocess.Popen(
            [dt, "gnai", "chat", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            ) if sys.platform == "win32" else 0,
        )
    except Exception as e:
        return False, f"Could not launch dt: {e}"

    with _active_procs_lock:
        _active_procs.append(proc)

    def _collect():
        for stream in (proc.stdout, proc.stderr):
            try:
                for line in iter(stream.readline, ""):
                    if stop_event.is_set():
                        break
                    clean = _ANSI.sub("", line).strip()
                    if clean:
                        output_lines.append(clean)
            except Exception:
                pass

    t = threading.Thread(target=_collect, daemon=True)
    t.start()
    t.join(timeout=10)
    stop_event.set()
    _kill_proc_tree(proc)

    with _active_procs_lock:
        try:
            _active_procs.remove(proc)
        except ValueError:
            pass

    if output_lines:
        # Any response means dt gnai chat is working
        first = output_lines[0][:100]
        # Check for auth/permission errors in the output
        _ERR = re.compile(
            r"unauthorized|forbidden|not.authorized|access.denied|permission.denied|login|sign.in",
            re.I,
        )
        for line in output_lines:
            if _ERR.search(line):
                return False, f"GNAI not authenticated: {line[:100]}"
        return True, f"dt gnai chat responded: {first}"

    return False, "dt gnai chat did not respond — ensure GNAI is set up correctly"


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


# ── GNAI Toolkit installation check ───────────────────────────────────────

_toolkit_cache      = None   # dict of {name: {"status": "valid"|"missing", "path": str}}
_toolkit_cache_lock = threading.Lock()
_toolkit_cache_err  = None   # str if the command failed entirely

# ── Active subprocess tracking (for cleanup on exit) ──────────────────────
_active_procs      = []
_active_procs_lock = threading.Lock()


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


def _kill_proc_tree(proc):
    """Terminate a process and all its children (Windows: taskkill /F /T)."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=5,
            )
            return
        except Exception:
            pass
    # Fallback
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _make_toolkit_check(toolkit_name: str):
    """
    Check: is the toolkit installed? Returns a single result with a summary line.
    """
    def _check():
        toolkits, err = _get_installed_toolkits()
        if toolkits is None:
            return None, f"Could not check toolkits: {err}"

        key = toolkit_name.lower()
        info = toolkits.get(key)
        if info and info["status"] == "valid":
            return True, "Toolkit: installed"
        elif info and info["status"] == "missing":
            return False, "Toolkit: missing dependency"
        else:
            return False, "Toolkit: not installed"

    return _check


CHECKS = [
    ("Intel dt CLI (PATH)",      check_dt_in_path,  DT_INSTALL_HELP_CMD),
    ("GNAI Connection Test",     check_gnai_connection, None),
    ("sighting",       _make_toolkit_check("sighting"),
     "dt gnai toolkits register intel-sandbox/SightingAssistantTool"),
    ("displaydebugger", _make_toolkit_check("displaydebugger"),
     "dt gnai toolkits register intel-sandbox/displaydebugger"),
    ("sherlog",        _make_toolkit_check("sherlog"),
     "dt gnai toolkits register intel-innersource/drivers.gpu.core.sherlog-toolkit"),
]

# Index of the sighting row inside CHECKS (used to attach the config button)
_SIGHTING_IDX = next(i for i, (label, _, _c) in enumerate(CHECKS) if label == "sighting")

# Index of the dt CLI row (its "Install" button downloads dt.exe instead of
# running a toolkit register command)
_DT_IDX = next(i for i, (label, _, _c) in enumerate(CHECKS) if label == "Intel dt CLI (PATH)")


# Recommended config content written to sighting toolkit's install directory
SIGHTING_CONFIG_CONTENT = """{\n  \"version\": \"1.0\",\n  \"configured\": true,\n  \"features\": {\n    \"state_tokens_enabled\": false,\n    \"verbose_progress_updates\": false,\n    \"table_output_format\": true,\n    \"html_report_generation\": false,\n    \"subprocess_pause\": {\n      \"displaydebugger\": true,\n      \"sherlog\": true\n    }\n  },\n  \"cache\": {\n    \"enabled\": true,\n    \"rag_mandatory_checklist\": true,\n    \"rag_bkm\": true,\n    \"hsd_article\": false,\n    \"force_refresh\": false\n  },\n  \"paths\": {\n    \"gfx_repo_path\": \"\"\n  }\n}"""


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
        self._exit_code = 2  # 0=passed, 1=failed, 2=not completed
        self._install_in_progress = False
        self._fonts()
        self._build()
        self._center()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
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

        # ── Body (scrollable) ────────────────────────────────────────────
        # Wrapped in a Canvas + Scrollbar so content that doesn't fit the
        # window height gets a vertical slider instead of being clipped.
        scroll_container = tk.Frame(self, bg=self.BG)
        scroll_container.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(scroll_container, bg=self.BG, highlightthickness=0)
        self._vscroll = tk.Scrollbar(scroll_container, orient="vertical",
                                     command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar is shown/hidden on demand by _update_scrollbar_visibility()

        self._body = tk.Frame(self._canvas, bg=self.BG, padx=28, pady=20)
        self._body_window = self._canvas.create_window((0, 0), window=self._body, anchor="nw")

        def _on_body_configure(event):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
            self._update_scrollbar_visibility()
        self._body.bind("<Configure>", _on_body_configure)

        def _on_canvas_configure(event):
            self._canvas.itemconfig(self._body_window, width=event.width)
            self._update_scrollbar_visibility()
        self._canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse wheel scrolling (Windows sends delta in multiples of 120)
        def _on_mousewheel(event):
            if self._vscroll.winfo_ismapped():
                self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._canvas.bind_all("<MouseWheel>", _on_mousewheel)

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
                info_frame, text=("⬇  Download dt.exe" if i == _DT_IDX else "▶  Install"),
                font=self.f_mono,
                command=lambda idx=i: self._install_toolkit(idx),
                bg=self.BLUE, fg="white", relief="flat",
                padx=10, pady=3, cursor="hand2",
            ) if install_cmd else None
            # Install button is hidden initially; pack() is called in _update_row when needed

            # Config button — only for the sighting row
            config_btn = tk.Button(
                info_frame, text="⚙  Apply Recommended Config",
                font=self.f_mono,
                command=lambda idx=i: self._apply_sighting_config(idx),
                bg="#059669", fg="white", relief="flat",
                padx=10, pady=3, cursor="hand2",
            ) if i == _SIGHTING_IDX else None

            self._rows.append((badge, detail_lbl, install_btn, config_btn))

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

        self._btn_close = tk.Button(
            btn_row, text="Close", font=self.f_body,
            command=self.destroy,
            bg=self.BORDER, fg=self.TEXT_DARK, relief="flat",
            padx=16, pady=5, cursor="hand2")
        self._btn_close.pack(side="left", padx=(8, 0))

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

        # Reset all rows
        for i, (badge, detail, install_btn, config_btn) in enumerate(self._rows):
            badge.config(text="⏳", fg=self.ORANGE)
            detail.config(text="Checking...", fg=self.GRAY)
            if install_btn:
                install_btn.pack_forget()
                install_btn.config(
                    state="normal",
                    text="⬇  Download dt.exe" if i == _DT_IDX else "▶  Install",
                )
            if config_btn:
                config_btn.pack_forget()
                config_btn.config(state="normal", text="⚙  Apply Recommended Config",
                                  bg="#059669")

        def worker():
            results = []
            for i, (label, fn, _) in enumerate(CHECKS):
                try:
                    ok, msg = fn()
                except Exception as e:
                    ok, msg = False, f"Error: {e}"
                self.after(0, self._update_row, i, ok, msg)
                results.append((i, ok, msg))

            self.after(0, self._show_summary, results)

        threading.Thread(target=worker, daemon=True).start()

    def _update_row(self, i, ok, msg):
        badge, detail, install_btn, config_btn = self._rows[i]
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
        # (or, for the dt CLI row, whenever dt itself is missing from PATH)
        if install_btn:
            toolkit_not_installed = ok is False and (
                "not installed" in msg or "missing dependency" in msg
            )
            dt_missing = (i == _DT_IDX and ok is False)
            if toolkit_not_installed or dt_missing:
                install_btn.pack(anchor="w", pady=(4, 0))
            else:
                install_btn.pack_forget()

        # Show config button only when sighting toolkit is confirmed installed
        if config_btn:
            if ok is True:
                config_btn.pack(anchor="w", pady=(4, 0))
            else:
                config_btn.pack_forget()

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
        self._exit_code = 1 if failed else 0

    def _install_toolkit(self, i):
        """Open a PowerShell console to run the register command, then re-check."""
        _, _, install_btn, _ = self._rows[i]
        cmd = CHECKS[i][2]
        if not cmd:
            return
        self._set_install_in_progress(True)
        if install_btn:
            install_btn.config(text="Installing…")

        def _run():
            subprocess.Popen(
                ["powershell", "-Command", cmd],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            ).wait()
            # The console closes itself once the command finishes; re-enable controls and re-check
            self.after(0, self._set_install_in_progress, False)
            self.after(0, self._run_checks)

        threading.Thread(target=_run, daemon=True).start()

    def _set_install_in_progress(self, in_progress: bool):
        """Block other Install buttons, Re-check, and Close while an install console is running."""
        self._install_in_progress = in_progress
        state = "disabled" if in_progress else "normal"
        for _, _, install_btn, _ in self._rows:
            if install_btn:
                install_btn.config(state=state)
        self._btn_recheck.config(state=state)
        self._btn_close.config(state=state)

    def _recheck(self):
        self._run_checks()

    def _apply_sighting_config(self, row_idx: int):
        """Write the recommended config.local.json to the sighting toolkit directory."""
        _, _, _, config_btn = self._rows[row_idx]
        toolkits, err = _get_installed_toolkits()
        if err or not toolkits or "sighting" not in toolkits:
            messagebox.showerror(
                "Error",
                "Cannot determine sighting toolkit path.\n" + (err or "Toolkit not found"),
            )
            return

        toolkit_path = toolkits["sighting"]["path"]
        if not toolkit_path or not os.path.isdir(toolkit_path):
            messagebox.showerror(
                "Error",
                f"Sighting toolkit path not found or is not a directory:\n{toolkit_path}",
            )
            return

        config_path = os.path.join(toolkit_path, "config.local.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(SIGHTING_CONFIG_CONTENT)
            if config_btn:
                config_btn.config(text="✓  Config Applied", state="disabled", bg=self.GREEN)
            messagebox.showinfo(
                "Config Applied",
                f"Recommended config written to:\n{config_path}",
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write config:\n{e}")

    def _on_close(self):
        """Kill all active gnai subprocesses before closing the window."""
        if self._install_in_progress:
            return
        with _active_procs_lock:
            procs = list(_active_procs)
        for proc in procs:
            _kill_proc_tree(proc)
        self.destroy()

    def _on_resize(self, event):
        if event.widget is self:
            inner_w = max(200, event.width - 100)
            for _, detail, _, _cb in self._rows:
                detail.config(wraplength=inner_w)
            self._help.config(wraplength=inner_w)

    def _update_scrollbar_visibility(self):
        """Show the vertical scrollbar only when body content overflows the canvas."""
        bbox = self._canvas.bbox("all")
        if not bbox:
            return
        content_h = bbox[3] - bbox[1]
        canvas_h = self._canvas.winfo_height()
        if content_h > canvas_h:
            if not self._vscroll.winfo_ismapped():
                self._vscroll.pack(side="right", fill="y")
        else:
            if self._vscroll.winfo_ismapped():
                self._vscroll.pack_forget()

    def _center(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Default to 1366x768, clamped so it still fits on smaller screens
        w = min(1366, sw)
        h = min(768, sh)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.minsize(min(800, w), min(600, h))
        self.bind("<Configure>", self._on_resize)


# ── Entry ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
    sys.exit(getattr(app, '_exit_code', 2))
