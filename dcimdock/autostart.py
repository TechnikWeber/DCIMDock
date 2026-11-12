"""Start DCIMDock in the background when the user logs in.

Linux: ~/.config/autostart/dcimdock.desktop (freedesktop, KDE and GNOME).
Windows: the Run key of the current user in the registry.
Both start `dcimdock --background`: only the tray icon, the window opens
from there.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

NAME = "DCIMDock"
FLAG = "--background"


def command() -> list[str]:
    """How this very copy of DCIMDock is started again."""
    if os.environ.get("APPIMAGE"):
        return [os.environ["APPIMAGE"], FLAG]
    if getattr(sys, "frozen", False):           # the Windows .exe
        return [sys.executable, FLAG]
    exe = shutil.which("dcimdock")
    if exe and sys.platform != "win32":
        return [exe, FLAG]
    py = sys.executable
    if sys.platform == "win32":
        w = Path(py).with_name("pythonw.exe")    # no console window
        py = str(w) if w.exists() else py
    return [py, "-m", "dcimdock", FLAG]


def _desktop_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / "dcimdock.desktop"


def _win_quote(args: list[str]) -> str:
    return " ".join(f'"{a}"' if " " in a or not a else a for a in args)


def _desktop_quote(args: list[str]) -> str:
    """Exec= quoting of the desktop entry spec: double quotes, escape \\ " ` $."""
    def q(a: str) -> str:
        if a and not any(c in a for c in ' \t\n"\'\\><~|&;$*?#()`'):
            return a
        return '"' + "".join("\\" + c if c in '"`$\\' else c for c in a) + '"'
    return " ".join(q(a) for a in args)


def is_enabled() -> bool:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, NAME)
            return True
        except OSError:
            return False
    return _desktop_file().exists()


def set_enabled(on: bool) -> None:
    """Raises OSError if it cannot be written."""
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, _win_quote(command()))
            else:
                try:
                    winreg.DeleteValue(k, NAME)
                except FileNotFoundError:
                    pass
        return
    f = _desktop_file()
    if not on:
        f.unlink(missing_ok=True)
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NAME}\n"
        "Comment=Back up the iPhone when it is plugged in\n"
        f"Exec={_desktop_quote(command())}\n"
        "Icon=dcimdock\n"
        "X-GNOME-Autostart-enabled=true\n"
        "NoDisplay=true\n", "utf-8")


def follow() -> None:
    """After an update the autostart must start the new file, not the old one."""
    if not (os.environ.get("APPIMAGE") or getattr(sys, "frozen", False)):
        return      # run from source or a package: the command does not move
    try:
        if is_enabled():
            set_enabled(True)
    except OSError:
        pass
