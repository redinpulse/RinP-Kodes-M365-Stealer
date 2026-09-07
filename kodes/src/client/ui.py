"""
User interface utilities for the Kodes client.

Single Tk root, created on the MAIN thread (macOS requirement).
All UI updates from other threads are marshalled via root.after().
"""
import logging
import tkinter as tk
from tkinter import messagebox, ttk

import pyperclip

logger = logging.getLogger(__name__)

_root = None
_status_var = None


class KodesUI:
    """Owns the single Tk root. setup()/run() must be called on the MAIN thread."""

    def __init__(self):
        self.running = False

    def setup(self):
        """Create the Tk root. MUST be called on the MAIN thread."""
        global _root, _status_var
        _root = tk.Tk()
        _root.title("Kodes Client")
        _root.geometry("300x100")
        _root.withdraw()
        _status_var = tk.StringVar(value="Kodes Client")

        if hasattr(_root, 'createcommand'):
            _root.createcommand('::tk::mac::ShowPreferences', self.show_status)
            _root.createcommand('::tk::mac::Quit', self.stop)

        _root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.running = True

    def run(self):
        """Run the Tk mainloop. Blocking; call on the MAIN thread."""
        if _root:
            _root.mainloop()

    def stop(self):
        """Stop the mainloop (thread-safe)."""
        self.running = False
        if _root:
            _root.after(0, _root.quit)

    def update_status(self, text):
        if _root and _status_var:
            _root.after(0, lambda: _status_var.set(text))

    def notify(self, title, message):
        if _root:
            _root.after(0, lambda: _toast(title, message))

    def show_status(self):
        if not _root:
            return
        _root.deiconify()
        _root.focus_force()
        for w in _root.winfo_children():
            w.destroy()
        frame = ttk.Frame(_root, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, textvariable=_status_var).pack(pady=5)
        ttk.Button(frame, text="Hide", command=self.hide_window).pack(pady=5)

    def hide_window(self):
        if _root:
            _root.withdraw()


def _toast(title, message, duration_ms=12000):
    """A NON-modal notification that dismisses itself after a timeout.

    messagebox.showinfo is modal: it blocks the Tk mainloop in its own event
    loop, and while it stays open, after-callbacks like update_status are
    not processed — the worker flow deadlocks. Hence Toplevel + auto-dismiss.
    """
    if not _root:
        return
    top = tk.Toplevel(_root)
    top.title(title)
    top.attributes("-topmost", True)
    frame = ttk.Frame(top, padding="15")
    frame.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frame, text=message, wraplength=280, justify="left").pack(pady=5)
    ttk.Button(frame, text="Kapat", command=top.destroy).pack(pady=5)
    top.after(duration_ms, top.destroy)


def show_code_notification(code):
    """Show the device code (thread-safe; uses the shared root)."""
    try:
        pyperclip.copy(code)
        if _root:
            msg = (f"Enter {code} in the window that opened to continue "
                   f"signing in.\n\nThe code has been copied to the clipboard.")
            _root.after(0, lambda: _toast("Kodes - Sign-In Code", msg, 15000))
        logger.info("Code notification displayed to user")
    except Exception as e:
        logger.error(f"Failed to show notification: {e}")



