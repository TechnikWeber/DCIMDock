"""Is there a newer release on GitHub? Asked at most once a day, can be switched off.

Only one anonymous request to the GitHub API; nothing about the computer or
the photos is sent.

The Windows .exe can also update itself: download the new .exe next to the
old one, check it against SHA256SUMS of the release, start it with
--replace OLD, and the new one deletes the old file once it has quit.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__

URL = "https://api.github.com/repos/TechnikWeber/DCIMDock/releases/latest"
PAGE = "https://github.com/TechnikWeber/DCIMDock/releases/latest"


def parse(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:3]) if nums else ()


def newer(remote: str, local: str = __version__) -> bool:
    return bool(parse(remote)) and parse(remote) > parse(local)


HEADERS = {"User-Agent": f"DCIMDock/{__version__}"}


def _release(url: str = URL, timeout: float = 6) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", **HEADERS})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def latest(timeout: float = 6) -> tuple[str, str]:
    """(version, page) of the latest release. Raises OSError/ValueError."""
    data = _release(timeout=timeout)
    return str(data.get("tag_name", "")).lstrip("v"), str(data.get("html_url") or PAGE)


def check() -> tuple[str, str] | None:
    """The newer release, or None (none, or no internet)."""
    try:
        v, page = latest()
    except (OSError, ValueError):
        return None
    return (v, page) if newer(v) else None

# ---------------------------------------------------------------- self update (Windows .exe)

def exe_name(v: str) -> str:
    return f"DCIMDock-{v}-windows-x64.exe"


def can_update_itself() -> bool:
    """Only the frozen Windows .exe, and only where it may write next to itself."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    return os.access(Path(sys.executable).parent, os.W_OK)


def expected_sha256(sums: str, name: str) -> str:
    """The checksum of NAME in a `sha256sum` file, or ''."""
    for line in sums.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return ""


def _get(url: str, timeout: float = 30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout)


def download(v: str, progress: Callable[[int, int], None] | None = None) -> Path:
    """Fetch the .exe of version V next to this one, checked. Raises OSError/ValueError."""
    data = _release(f"https://api.github.com/repos/TechnikWeber/DCIMDock/releases/tags/v{v}")
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    name = exe_name(v)
    if name not in assets:
        raise ValueError(f"{name} is not part of the release")
    if "SHA256SUMS" not in assets:
        raise ValueError("the release has no SHA256SUMS")
    with _get(assets["SHA256SUMS"]) as r:
        want = expected_sha256(r.read().decode("utf-8", "replace"), name)
    if not want:
        raise ValueError(f"no checksum for {name}")
    target = Path(sys.executable).with_name(name)
    part = target.with_name(name + ".part")
    h = hashlib.sha256()
    try:
        with _get(assets[name]) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 16):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if h.hexdigest() != want:
            raise ValueError("the download is damaged (checksum differs)")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return target


def remove_old(old: str, wait: float = 60) -> None:
    """Run by the new .exe: delete the old one as soon as it has quit."""
    path = Path(old)
    if path.resolve() == Path(sys.executable).resolve() or path.suffix.lower() != ".exe":
        return
    end = time.monotonic() + wait
    while time.monotonic() < end:
        try:
            path.unlink(missing_ok=True)
            return
        except OSError:     # still running
            time.sleep(1)
