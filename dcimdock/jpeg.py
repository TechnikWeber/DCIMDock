"""An extra JPEG next to each HEIC photo (IMG_0001.HEIC + IMG_0001.jpg).

The HEIC original is always kept; the JPEG is for programs and people that
cannot open HEIC. Two ways to make it, the first one found is used:

* pillow-heif (Python, brought by the AppImage and the Windows .exe)
* heif-dec / heif-convert from libheif (Fedora: libheif-tools)

Capture date, GPS and the other EXIF data go along. The pixels come out
upright, so the EXIF orientation is set to 1 (else viewers turn them twice).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

QUALITY = 92
HEIC_EXT = {".heic", ".heif"}
# Loading pillow-heif can take 20 s and more the first time on Windows: the
# .exe unpacks its DLLs anew at every start and the virus scanner reads each
# one. So it is asked once, early, in the background (see warm_up).
_lock = threading.Lock()
_found: str | None = None


def _pillow():
    try:
        import pillow_heif
        from PIL import Image
    except ImportError:
        return None
    pillow_heif.register_heif_opener()
    return Image


def _tool() -> str:
    return shutil.which("heif-dec") or shutil.which("heif-convert") or ""


def available() -> str:
    """'pillow-heif', 'heif-dec', 'heif-convert' or '' (not possible here). Can be slow once."""
    global _found
    with _lock:
        if _found is None:
            _found = "pillow-heif" if _pillow() is not None else os.path.basename(_tool())
        return _found


def known() -> str | None:
    """What available() found, or None while that is not known yet (never blocks)."""
    return _found


def warm_up() -> None:
    """Find out in the background, so no window has to wait for it."""
    threading.Thread(target=available, name="jpeg-warm-up", daemon=True).start()


def install_hint() -> str:
    from .device import os_release
    info = os_release()
    ids = " ".join((info.get("ID", ""), info.get("ID_LIKE", ""))).lower().split()
    if any(i in ids for i in ("fedora", "rhel", "centos")):
        return "sudo dnf install libheif-tools"
    if any(i in ids for i in ("debian", "ubuntu")):
        return "sudo apt install libheif-examples"
    if any(i in ids for i in ("arch", "manjaro", "endeavouros")):
        return "sudo pacman -S libheif"
    return "pip install pillow-heif"


def wanted(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in HEIC_EXT


def target(heic: Path) -> Path:
    return heic.with_suffix(".jpg")


def _with_pillow(Image, src: Path, out: Path):
    with Image.open(src) as im:
        exif = im.getexif()
        if 0x0112 in exif:
            exif[0x0112] = 1
        icc = im.info.get("icc_profile")
        rgb = im.convert("RGB")
        kw = {"quality": QUALITY, "exif": exif.tobytes()}
        if icc:
            kw["icc_profile"] = icc
        rgb.save(out, "JPEG", **kw)


def _with_tool(tool: str, src: Path, out: Path):
    env = dict(os.environ)
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)    # the AppImage's libraries must not leak into the host tool
    p = subprocess.run([tool, "-q", str(QUALITY), str(src), str(out)], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=120, env=env)
    if p.returncode != 0 or not out.exists():
        raise OSError((p.stderr or p.stdout).strip() or f"{tool} exit code {p.returncode}")
    # some versions write name-1.jpg, name-2.jpg for images with several pictures
    stray = sorted(out.parent.glob(out.stem + "-*.jpg"))
    for s in stray:
        if s != out:
            s.unlink(missing_ok=True)


def convert(heic: Path) -> Path | None:
    """Write NAME.jpg next to NAME.HEIC. Never overwrites: if NAME.jpg is taken,
    nothing is written and None returned. Raises OSError when it fails."""
    out = target(heic)
    if out.exists():
        return None
    part = out.with_name(out.stem + ".part.jpg")   # heif-dec picks the format by extension
    try:
        Image = _pillow()
        if Image is not None:
            _with_pillow(Image, heic, part)
        else:
            tool = _tool()
            if not tool:
                raise OSError("no HEIC converter (pillow-heif or heif-dec)")
            _with_tool(tool, heic, part)
        st = heic.stat()
        os.utime(part, (st.st_mtime, st.st_mtime))
        try:
            os.link(part, out)
            os.unlink(part)
        except FileExistsError:
            part.unlink(missing_ok=True)
            return None
        except OSError:
            if out.exists():
                part.unlink(missing_ok=True)
                return None
            os.rename(part, out)
    except Exception as exc:  # noqa: BLE001 – Pillow raises all kinds
        part.unlink(missing_ok=True)
        raise OSError(str(exc) or type(exc).__name__) from exc
    return out
