"""
Chat Mode Assistant — Extension ID Configurator
================================================
Post-install GUI: registers your Chrome Extension ID with the Native Messaging host.
Run this after loading the Chrome extension in Developer mode.
"""

import json
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import font as tkfont


# ── Paths ──────────────────────────────────────────────────────────────────

def get_install_dir():
    """Return the directory containing this executable/script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


INSTALL_DIR   = get_install_dir()
MANIFEST_PATH = os.path.join(INSTALL_DIR, "nm_manifest.json")
EXTENSION_DIR = os.path.join(INSTALL_DIR, "extension")


# ── Helpers ────────────────────────────────────────────────────────────────

def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def get_current_ext_id(manifest):
    origins = manifest.get("allowed_origins", [])
    if origins:
        ext_id = origins[0].replace("chrome-extension://", "").rstrip("/")
        if ext_id and ext_id != "PLACEHOLDER_EXTENSION_ID":
            return ext_id
    return ""


def validate_ext_id(ext_id):
    """Chrome Extension IDs are 32 lowercase letters (a-p base-32 encoding)."""
    return bool(re.fullmatch(r"[a-z]{32}", ext_id))


def open_folder(path):
    try:
        os.startfile(path)
    except Exception:
        subprocess.run(["explorer", path], check=False)


# ── App ────────────────────────────────────────────────────────────────────

class App(tk.Tk):

    BG         = "#f8fafc"
    HEADER_BG  = "#1e3a5f"
    CARD_BG    = "#ffffff"
    BLUE       = "#2563eb"
    GREEN      = "#16a34a"
    ORANGE     = "#d97706"
    RED        = "#dc2626"
    TEXT_DARK  = "#111827"
    TEXT_MID   = "#4b5563"
    TEXT_LIGHT = "#9ca3af"
    BORDER     = "#e5e7eb"

    def __init__(self):
        super().__init__()
        self.title("Chat Mode Assistant — Setup")
        self.configure(bg=self.BG)
        self.resizable(False, False)
        self._fonts()
        self._build()
        self._load_current_id()
        self._center()

    # ── Fonts ──────────────────────────────────────────────────────────────

    def _fonts(self):
        self.f_title  = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.f_sub    = tkfont.Font(family="Segoe UI", size=9)
        self.f_body   = tkfont.Font(family="Segoe UI", size=10)
        self.f_bold   = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_mono   = tkfont.Font(family="Consolas",  size=11)
        self.f_btn    = tkfont.Font(family="Segoe UI", size=10, weight="bold")

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build(self):
        self._header()
        self._body()

    def _header(self):
        h = tk.Frame(self, bg=self.HEADER_BG, padx=24, pady=18)
        h.pack(fill="x")
        tk.Label(h, text="Chat Mode Assistant", font=self.f_title,
                 fg="white", bg=self.HEADER_BG).pack(anchor="w")
        tk.Label(h, text="Extension Setup  —  Step-by-step configuration",
                 font=self.f_sub, fg="#93c5fd", bg=self.HEADER_BG).pack(anchor="w")

    def _body(self):
        body = tk.Frame(self, bg=self.BG, padx=28, pady=22)
        body.pack(fill="both", expand=True)

        # ── Step 1 ──────────────────────────────────────────────────────
        self._step_label(body, "Step 1", "Load the extension in Chrome")

        path_card = tk.Frame(body, bg="#eff6ff", highlightbackground="#bfdbfe",
                             highlightthickness=1, padx=12, pady=8)
        path_card.pack(fill="x", pady=(6, 4))
        tk.Label(path_card, text=EXTENSION_DIR, font=self.f_mono,
                 bg="#eff6ff", fg="#1e40af",
                 wraplength=400, justify="left").pack(side="left", fill="x", expand=True)
        tk.Button(path_card, text="Open Folder", font=self.f_sub,
                  command=lambda: open_folder(EXTENSION_DIR),
                  bg=self.BLUE, fg="white", relief="flat",
                  padx=10, pady=3, cursor="hand2").pack(side="right", padx=(10, 0))

        steps = [
            "1.  Go to  chrome://extensions/",
            "2.  Enable  Developer mode  (toggle, top-right corner)",
            "3.  Click  Load unpacked  →  select the folder shown above",
            "4.  Find  Chat Mode Assistant  →  copy the 32-character ID",
        ]
        for s in steps:
            tk.Label(body, text=s, font=self.f_sub, bg=self.BG,
                     fg=self.TEXT_MID, anchor="w").pack(fill="x", pady=1)

        # ── Divider ──────────────────────────────────────────────────────
        tk.Frame(body, bg=self.BORDER, height=1).pack(fill="x", pady=16)

        # ── Step 2 ──────────────────────────────────────────────────────
        self._step_label(body, "Step 2", "Paste your Extension ID below")

        self._id_var = tk.StringVar()
        entry_frame = tk.Frame(body, bg=self.BG)
        entry_frame.pack(fill="x", pady=(8, 0))

        entry = tk.Entry(entry_frame, textvariable=self._id_var,
                         font=self.f_mono, bg="white",
                         relief="solid", bd=1, width=36,
                         insertbackground=self.BLUE)
        entry.pack(side="left", ipady=5, padx=(0, 8))
        entry.bind("<Return>", lambda e: self._save())

        tk.Button(entry_frame, text="Save", font=self.f_btn,
                  command=self._save,
                  bg=self.GREEN, fg="white", relief="flat",
                  padx=20, pady=5, cursor="hand2").pack(side="left")

        self._status = tk.Label(body, text="", font=self.f_sub,
                                bg=self.BG, fg=self.TEXT_LIGHT, anchor="w")
        self._status.pack(fill="x", pady=(6, 0))

        # ── Footer ───────────────────────────────────────────────────────
        tk.Frame(body, bg=self.BORDER, height=1).pack(fill="x", pady=(20, 8))
        tk.Label(body,
                 text=f"Install directory:  {INSTALL_DIR}",
                 font=self.f_sub, bg=self.BG, fg=self.TEXT_LIGHT,
                 anchor="w", wraplength=480, justify="left").pack(fill="x")

    def _step_label(self, parent, badge, text):
        row = tk.Frame(parent, bg=self.BG)
        row.pack(fill="x", pady=(0, 2))
        tk.Label(row, text=badge, font=self.f_sub,
                 bg=self.BLUE, fg="white", padx=6, pady=2).pack(side="left")
        tk.Label(row, text=f"  {text}", font=self.f_bold,
                 bg=self.BG, fg=self.TEXT_DARK).pack(side="left")

    # ── Logic ──────────────────────────────────────────────────────────────

    def _load_current_id(self):
        try:
            manifest = load_manifest()
            current_id = get_current_ext_id(manifest)
            if current_id:
                self._id_var.set(current_id)
                self._set_status(f"Currently configured: {current_id}", self.GREEN)
        except FileNotFoundError:
            self._set_status(
                f"⚠  nm_manifest.json not found — please re-run the installer.",
                self.RED)
        except Exception as e:
            self._set_status(f"⚠  Could not read manifest: {e}", self.RED)

    def _save(self):
        ext_id = self._id_var.get().strip().lower()

        if not ext_id:
            self._set_status("Please enter the Extension ID.", self.ORANGE)
            return
        if not validate_ext_id(ext_id):
            self._set_status(
                "Extension ID must be exactly 32 lowercase letters (a–z).",
                self.ORANGE)
            return

        try:
            manifest = load_manifest()
            manifest["allowed_origins"] = [f"chrome-extension://{ext_id}/"]
            save_manifest(manifest)
            self._set_status(
                f"✓  Saved!  Extension {ext_id[:8]}... is now registered.",
                self.GREEN)
            self.after(2800, self.destroy)
        except PermissionError:
            self._set_status(
                f"✗  Permission denied — cannot write to {MANIFEST_PATH}",
                self.RED)
        except FileNotFoundError:
            self._set_status(
                "✗  nm_manifest.json not found — please re-run the installer.",
                self.RED)
        except Exception as e:
            self._set_status(f"✗  Error: {e}", self.RED)

    def _set_status(self, msg, color):
        self._status.config(text=msg, fg=color)

    # ── Centering ──────────────────────────────────────────────────────────

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")


# ── Entry ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
