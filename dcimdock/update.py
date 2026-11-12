"""Is there a newer release on GitHub? Asked at most once a day, can be switched off.

Only one anonymous request to the GitHub API; nothing about the computer or
the photos is sent.
"""
from __future__ import annotations

import json
import re
import urllib.request

from . import __version__

URL = "https://api.github.com/repos/TechnikWeber/DCIMDock/releases/latest"
PAGE = "https://github.com/TechnikWeber/DCIMDock/releases/latest"


def parse(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:3]) if nums else ()


def newer(remote: str, local: str = __version__) -> bool:
    return bool(parse(remote)) and parse(remote) > parse(local)


def latest(timeout: float = 6) -> tuple[str, str]:
    """(version, page) of the latest release. Raises OSError/ValueError."""
    req = urllib.request.Request(URL, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"DCIMDock/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return str(data.get("tag_name", "")).lstrip("v"), str(data.get("html_url") or PAGE)


def check() -> tuple[str, str] | None:
    """The newer release, or None (none, or no internet)."""
    try:
        v, page = latest()
    except (OSError, ValueError):
        return None
    return (v, page) if newer(v) else None
