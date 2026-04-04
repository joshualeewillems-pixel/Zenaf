"""
Native folder picker on the host running the API (same machine as filesystem scan).

Web browsers cannot expose full drive paths to JavaScript; the UI calls this endpoint
so the server process opens the OS dialog and returns an absolute path.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _pick_directory_windows_powershell() -> str | None:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description = 'Choose folder for workspace identity scan'; "
        "$d.UseDescriptionForTitle = $true; "
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $d.SelectedPath }"
    )
    try:
        # Do NOT use CREATE_NO_WINDOW: WinForms FolderBrowserDialog in PowerShell needs a normal
        # process/desktop; hiding the console can leave ShowDialog() blocked with no visible UI and
        # wedge the API worker (and any follow-up requests like /auth/me).
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Sta", "-Command", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("[workspace-identity] PowerShell folder picker failed: %s", e)
        return None
    if r.returncode != 0:
        logger.warning("[workspace-identity] PowerShell rc=%s stderr=%s", r.returncode, (r.stderr or "").strip())
        return None
    line = (r.stdout or "").strip().replace("\r\n", "\n").split("\n")[0].strip()
    if not line:
        return None
    p = Path(line)
    return str(p.resolve()) if p.is_dir() else None


def _pick_directory_tkinter() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    try:
        chosen = filedialog.askdirectory(mustexist=True)
    except tk.TclError as e:
        logger.warning("[workspace-identity] tkinter folder picker failed: %s", e)
        chosen = ""
    finally:
        root.destroy()
    if not chosen or not str(chosen).strip():
        return None
    p = Path(str(chosen).strip()).expanduser()
    return str(p.resolve()) if p.is_dir() else None


def pick_scan_root_directory() -> tuple[str | None, str | None]:
    """
    Open a native folder dialog (blocking).

    Returns:
        (absolute_path, None) on success,
        (None, None) when the user cancels or the dialog returns no folder,
        (None, error_message) when no GUI picker is available.
    """
    if sys.platform == "win32":
        # Never use tkinter from a FastAPI thread on Windows: Tk is main-thread-only and can
        # deadlock the whole Python process, freezing the API (including session checks).
        path = _pick_directory_windows_powershell()
        if path:
            return path, None
        return None, None

    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        try:
            import tkinter  # noqa: F401
        except ImportError:
            return None, "Folder picker needs tkinter (install python3-tk or use Windows with PowerShell)."
        path = _pick_directory_tkinter()
        if path:
            return path, None
        return None, None

    return None, f"Folder picker is not implemented for platform: {sys.platform!r}."
