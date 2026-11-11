"""Talking to the iPhone through libimobiledevice and ifuse.

Everything here runs the host's command line tools, so it works the same
from the RPM, install.sh and the AppImage (which brings Python and Qt, but
not usbmuxd: that daemon must come from the distribution).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

TOOLS = ("idevice_id", "ideviceinfo", "idevicepair", "ifuse")
_UDID = re.compile(r"^[0-9A-Fa-f-]{24,40}$")


class DeviceError(Exception):
    pass


@dataclass
class Device:
    udid: str
    name: str = ""
    product: str = ""
    ios: str = ""

    @property
    def label(self) -> str:
        return self.name or "iPhone"


def _env() -> dict:
    env = dict(os.environ)
    # the AppImage's own library and Python paths must not leak into host tools
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH"):
        env.pop(k, None)
    env["LC_ALL"] = "C"
    return env


def _run(args: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, env=_env(), timeout=timeout)
    except FileNotFoundError:
        return 127, f"{args[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"{args[0]}: no answer after {timeout:.0f} s"
    return p.returncode, p.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- setup

def fusermount() -> str:
    return shutil.which("fusermount3") or shutil.which("fusermount") or ""


def usbmuxd_installed() -> bool:
    if shutil.which("usbmuxd"):
        return True
    return any(Path(d, "usbmuxd").exists() for d in ("/usr/sbin", "/usr/bin", "/sbin", "/usr/local/sbin"))


def missing() -> list[str]:
    out = [t for t in TOOLS if not shutil.which(t)]
    if not fusermount():
        out.append("fusermount")
    if not usbmuxd_installed():
        out.append("usbmuxd")
    return out


def os_release(path: str = "/etc/os-release") -> dict:
    data = {}
    try:
        for line in Path(path).read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return data


def install_command(info: dict | None = None) -> str:
    info = os_release() if info is None else info
    ids = " ".join((info.get("ID", ""), info.get("ID_LIKE", ""))).lower().split()
    if any(i in ids for i in ("fedora", "rhel", "centos")):
        return "sudo dnf install ifuse libimobiledevice-utils usbmuxd"
    if any(i in ids for i in ("debian", "ubuntu")):
        return "sudo apt install ifuse libimobiledevice-utils usbmuxd"
    if any(i in ids for i in ("arch", "manjaro", "endeavouros")):
        return "sudo pacman -S ifuse libimobiledevice usbmuxd"
    if any(i.startswith("opensuse") or i in ("suse", "sles") for i in ids):
        return "sudo zypper install ifuse imobiledevice-tools usbmuxd"
    return "ifuse, libimobiledevice (tools) and usbmuxd from your distribution"


# ---------------------------------------------------------------- devices

def parse_ids(out: str) -> list[str]:
    seen: list[str] = []
    for line in out.splitlines():
        udid = line.split()[0] if line.split() else ""
        if _UDID.match(udid) and udid not in seen:
            seen.append(udid)
    return seen


def list_devices() -> list[str]:
    # "ERROR: Unable to retrieve device list!" just means usbmuxd is not
    # running, which on most systems means: nothing is plugged in
    _rc, out = _run(["idevice_id", "-l"], timeout=8)
    return parse_ids(out)


def parse_info(out: str) -> dict:
    data = {}
    for line in out.splitlines():
        if ": " in line and not line.startswith(" "):
            k, v = line.split(": ", 1)
            data[k.strip()] = v.strip()
    return data


def info(udid: str) -> Device:
    # -s: the basic values a phone answers without pairing
    _rc, out = _run(["ideviceinfo", "-u", udid, "-s"], timeout=10)
    d = parse_info(out)
    return Device(udid, d.get("DeviceName", ""), d.get("ProductType", ""), d.get("ProductVersion", ""))


def classify_pair(rc: int, out: str) -> str:
    low = out.lower()
    if rc == 0 and "success" in low:
        return "ready"
    if "denied" in low:
        return "denied"
    if "passcode" in low:
        return "locked"
    if "trust dialog" in low or "accept the trust" in low or "pairing dialog" in low:
        return "trust"
    if "no device found" in low or "not found" in low:
        return "gone"
    return "error"


def pair(udid: str) -> tuple[str, str]:
    """ready | locked | trust | denied | gone | error, plus the tool's message."""
    rc, out = _run(["idevicepair", "-u", udid, "validate"], timeout=10)
    if classify_pair(rc, out) == "ready":
        return "ready", ""
    rc, out = _run(["idevicepair", "-u", udid, "pair"], timeout=15)
    return classify_pair(rc, out), out.strip()


# ---------------------------------------------------------------- mounting

def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "dcimdock"


def _unescape(path: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def parse_mounts(text: str) -> list[str]:
    return [_unescape(line.split()[1]) for line in text.splitlines() if len(line.split()) > 1]


def is_mounted(mp: Path) -> bool:
    try:
        text = Path("/proc/self/mounts").read_text()
    except OSError:
        return False
    return str(mp) in parse_mounts(text)


def unmount(mp: Path, lazy: bool = False):
    tool = fusermount()
    if tool and is_mounted(mp):
        _run([tool, "-u", *(["-z"] if lazy else []), str(mp)], timeout=15)
    try:
        mp.rmdir()
    except OSError:
        pass


def mount(udid: str) -> Path:
    """Mount the media partition read-only; returns the mount point."""
    mp = runtime_dir() / udid
    if is_mounted(mp):
        try:
            os.listdir(mp)
            return mp
        except OSError:      # left over from a crash: "transport endpoint is not connected"
            unmount(mp, lazy=True)
    mp.mkdir(parents=True, exist_ok=True, mode=0o700)
    rc, out = _run(["ifuse", str(mp), "-u", udid, "-o", "ro"], timeout=30)
    if not is_mounted(mp):
        try:
            mp.rmdir()
        except OSError:
            pass
        raise DeviceError(out.strip() or f"ifuse exit code {rc}")
    return mp


def cleanup_stale():
    """Unmount broken mounts an earlier crashed run left behind."""
    base = runtime_dir()
    if not base.is_dir():
        return
    for mp in base.iterdir():
        try:
            os.listdir(mp)
            if not is_mounted(mp):
                mp.rmdir()
        except OSError:
            unmount(mp, lazy=True)
