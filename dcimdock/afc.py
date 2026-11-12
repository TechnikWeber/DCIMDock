"""Talking to the iPhone directly over AFC with pymobiledevice3 (Windows).

Windows has no ifuse. Apple's driver (the "Apple Devices" app from the
Microsoft Store, or iTunes) brings the Apple Mobile Device Service, which
plays the part of usbmuxd. pymobiledevice3 speaks lockdown and AFC through it.
Nothing is mounted: the photos are read through an AfcSource, which sync.py
uses like a folder (scan() and open_file()).

The module offers the same functions as device.py, so the window and the
terminal mode do not care which one they got (see backend.py). On Linux it
can be tried with DCIMDOCK_BACKEND=afc.

AFC is used read-only here: only listdir, stat, fopen("r"), fread, fseek and
fclose. Nothing on the iPhone is written or deleted.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import io
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Callable

from .device import Device, DeviceError, NoPhotos  # noqa: F401 – part of the backend API
from .sync import Cancelled, Entry

HAS_MOUNTS = False
# Microsoft Store page of the "Apple Devices" app (brings the Apple Mobile Device Service)
INSTALL_URL = "https://apps.microsoft.com/detail/9NP83LWLPZ9K" if sys.platform == "win32" else ""
SERVICE_ACTION = ("Restart the iPhone service (Apple Mobile Device Service)" if sys.platform == "win32"
                  else "Restart the iPhone service (usbmuxd)")
DCIM = "/DCIM"
TIMEOUT = 30          # seconds for one AFC request; a pulled cable must not hang a thread
WINDOWS_MUX = ("127.0.0.1", 27015)
# The Store app has no Windows service: its driver is a startup task that runs
# only from the next sign-in on. Started by hand it needs the package context.
_STORE_PKG = "AppleInc.AppleDevices"
_STORE_LAUNCH = (
    f"$p = Get-AppxPackage {_STORE_PKG} | Select-Object -First 1; if (-not $p) {{ exit 3 }}; "
    "Invoke-CommandInDesktopPackage -PackageFamilyName $p.PackageFamilyName -AppId App "
    "-Command (Join-Path $p.InstallLocation 'AppleMobileDeviceLauncher.exe') -ErrorAction Stop")


# ---------------------------------------------------------------- event loop

class _Loop:
    """pymobiledevice3 is asyncio; the window calls from worker threads.
    One loop in its own thread owns every connection, the callers wait."""

    _lock = threading.Lock()
    _loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get(cls) -> asyncio.AbstractEventLoop:
        with cls._lock:
            if cls._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="dcimdock-afc", daemon=True).start()
                cls._loop = loop
            return cls._loop


def _run(coro, timeout: float | None = TIMEOUT):
    fut = asyncio.run_coroutine_threadsafe(coro, _Loop.get())
    try:
        return fut.result(timeout)
    except concurrent.futures.TimeoutError:
        fut.cancel()
        raise TimeoutError(f"no answer after {timeout:.0f} s") from None


def _errors():
    """Exceptions that mean: the iPhone or the service did not play along."""
    from pymobiledevice3.exceptions import PyMobileDevice3Exception
    return (PyMobileDevice3Exception, ConnectionError, TimeoutError, asyncio.IncompleteReadError, EOFError)


def _io(fn, *args, timeout: float | None = TIMEOUT):
    """Run an AFC call; every failure becomes an OSError, which sync.py expects
    for a file that could not be read (cable pulled, iPhone locked)."""
    try:
        return _run(fn(*args), timeout)
    except OSError:
        raise
    except _errors() as exc:
        raise OSError(str(exc) or type(exc).__name__) from exc


def normalize_udid(serial: str) -> str:
    """Apple's service on Windows reports 00008110001A…, libimobiledevice
    00008110-001A…. The index file is named after the UDID, so a backup drive
    moved between Linux and Windows must see the same name."""
    s = serial.strip()
    if len(s) == 24 and "-" not in s:
        return f"{s[:8]}-{s[8:]}".upper()
    return s


# ---------------------------------------------------------------- setup

def _mux_reachable() -> bool:
    if sys.platform != "win32":
        return True     # usbmuxd on Linux starts only once an iPhone is plugged in
    try:
        with socket.create_connection(WINDOWS_MUX, timeout=1):
            return True
    except OSError:
        return False


def _powershell(script: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _store_app_installed() -> bool:
    if sys.platform != "win32":
        return False
    try:
        p = _powershell(f"if (Get-AppxPackage {_STORE_PKG}) {{ exit 0 }} else {{ exit 1 }}")
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0


def _wait_for_mux(seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _mux_reachable():
            return True
        time.sleep(0.5)
    return False


def start_store_driver(wait: float = 20) -> tuple[bool, str]:
    """Start the Apple Devices app's driver now instead of at the next sign-in."""
    if sys.platform != "win32":
        return False, "not Windows"
    try:
        p = _powershell(_STORE_LAUNCH)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if p.returncode == 3:
        return False, "Apple Devices app not installed"
    if p.returncode != 0:
        return False, (p.stdout + p.stderr).strip()
    return _wait_for_mux(wait), ""


def missing() -> list[str]:
    try:
        import pymobiledevice3  # noqa: F401
    except ImportError:
        return ["pymobiledevice3"]
    if not _mux_reachable():
        # just installed from the Store: its driver would only start at the next sign-in
        if start_store_driver()[0]:
            return []
        return ["Apple Mobile Device Service"]
    return []


def install_command(info: dict | None = None) -> str:
    if sys.platform == "win32":
        from .i18n import tr
        if _store_app_installed():
            return tr("“Apple Devices” is installed, but its driver did not start. "
                      "Sign out of Windows and in again, or restart the PC.")
        return tr("“Apple Devices” from the Microsoft Store (or iTunes from apple.com)") + "\n" + INSTALL_URL
    return "pip install pymobiledevice3"


def selfcheck() -> str:
    """Import everything a real connection needs (a frozen .exe may miss modules)."""
    import pymobiledevice3.exceptions  # noqa: F401
    import pymobiledevice3.lockdown  # noqa: F401
    import pymobiledevice3.services.afc  # noqa: F401
    import pymobiledevice3.usbmux  # noqa: F401
    return "afc ok"


def cleanup_stale():
    pass


def broken_mounts() -> list[str]:
    return []


def release_mounts() -> list[str]:
    return []


# ---------------------------------------------------------------- devices

def list_devices() -> list[str]:
    from pymobiledevice3 import usbmux
    try:
        devs = _run(usbmux.list_devices(), 8)
    except Exception:   # noqa: BLE001 – no service, no device: nothing plugged in
        return []
    out: list[str] = []
    for d in devs:
        udid = normalize_udid(d.serial)
        if d.is_usb and udid not in out:
            out.append(udid)
    return out


async def _lockdown(udid: str, autopair: bool = False):
    from pymobiledevice3.lockdown import create_using_usbmux
    # pair_timeout=0: send the request, do not wait for the tap; the window asks again
    return await create_using_usbmux(serial=udid, autopair=autopair, pair_timeout=0, connection_type="USB")


async def _info(udid: str) -> Device:
    ld = await _lockdown(udid)
    try:
        v = ld.all_values
        return Device(udid, v.get("DeviceName") or "", v.get("ProductType") or "", v.get("ProductVersion") or "")
    finally:
        await ld.close()


def info(udid: str) -> Device:
    try:
        return _run(_info(udid), 10)
    except Exception:   # noqa: BLE001 – a name is nice to have, not needed
        return Device(udid)


def classify(exc: BaseException) -> str:
    from pymobiledevice3 import exceptions as ex
    if isinstance(exc, ex.UserDeniedPairingError):
        return "denied"
    if isinstance(exc, ex.PairingDialogResponsePendingError):
        return "trust"
    if isinstance(exc, ex.PasswordRequiredError):
        return "locked"
    if isinstance(exc, (ex.NoDeviceConnectedError, ex.DeviceNotFoundError, ex.ConnectionTerminatedError)):
        return "gone"
    return "error"


async def _pair(udid: str, forget: bool = False) -> None:
    if forget:
        ld = await _lockdown(udid)
        try:
            await ld.unpair()
        except Exception:   # noqa: BLE001 – not paired is fine too
            pass
        finally:
            await ld.close()
    ld = await _lockdown(udid, autopair=True)
    await ld.close()


def pair(udid: str, forget: bool = False) -> tuple[str, str]:
    """ready | locked | trust | denied | gone | error, plus a message."""
    try:
        _run(_pair(udid, forget), 20)
    except Exception as exc:   # noqa: BLE001 – sorted into states
        return classify(exc), str(exc) or type(exc).__name__
    return "ready", ""


def repair_pairing(udid: str) -> tuple[str, str]:
    """Forget the trust on this computer and ask the iPhone again."""
    return pair(udid, forget=True)


def restart_service() -> tuple[bool, str]:
    if sys.platform != "win32":
        from . import device
        return device.restart_service()
    if _store_app_installed():      # Store app: no service, start its driver (no admin rights)
        return start_store_driver()
    # Restart-Service needs admin rights: Windows shows its UAC prompt
    inner = ("Get-Service | Where-Object { $_.DisplayName -like 'Apple Mobile Device*' } "
             "| Restart-Service -Force")
    cmd = ["powershell", "-NoProfile", "-Command",
           f"$p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
           f"-ArgumentList '-NoProfile','-Command',\"{inner}\"; exit $p.ExitCode"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def diagnose() -> str:
    from . import __version__
    import platform
    lines = [f"DCIMDock {__version__} (AFC)", f"System: {platform.platform()}"]
    try:
        from importlib.metadata import version
        lines.append(f"pymobiledevice3: {version('pymobiledevice3')}")
    except Exception:   # noqa: BLE001
        lines.append("pymobiledevice3: -")
    lines.append(f"Missing: {', '.join(missing()) or 'nothing'}")
    if sys.platform == "win32":
        lines.append(f"Apple Mobile Device Service: {'answers' if _mux_reachable() else 'NOT reachable'}")
        lines.append(f"Apple Devices app (Store): {'installed' if _store_app_installed() else 'not installed'}")
    ids = list_devices()
    lines.append(f"Devices: {', '.join(ids) or 'no device'}")
    for udid in ids:
        d = info(udid)
        lines.append(f"  {udid}: {d.name or '?'} {d.product} iOS {d.ios or '?'}")
        try:
            async def check(u=udid):
                ld = await _lockdown(u)
                try:
                    return ld.paired
                finally:
                    await ld.close()
            lines.append(f"  paired: {_run(check(), 10)}")
        except Exception as exc:   # noqa: BLE001
            lines.append(f"  pairing: {exc!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------- the photos

class AfcFile(io.RawIOBase):
    """A file on the iPhone as a read-only, seekable Python file."""

    def __init__(self, afc, path: str):
        super().__init__()
        self._afc, self._path = afc, path
        self._handle = _io(afc.fopen, path, "r")
        self._pos = 0       # where we want to read
        self._at = 0        # where the iPhone's handle stands
        self._size: int | None = None

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            pos = offset
        elif whence == os.SEEK_CUR:
            pos = self._pos + offset
        else:
            if self._size is None:
                self._size = int(_io(self._afc.stat, self._path)["st_size"])
            pos = self._size + offset
        if pos < 0:
            raise OSError("negative seek position")
        self._pos = pos
        return pos

    def readinto(self, b) -> int:
        if self.closed:
            raise ValueError("read from a closed file")
        if self._at != self._pos:
            _io(self._afc.fseek, self._handle, self._pos)
            self._at = self._pos
        data = _io(self._afc.fread, self._handle, len(b))
        n = len(data)
        b[:n] = data
        self._pos += n
        self._at += n
        return n

    def close(self):
        if not self.closed:
            try:
                _io(self._afc.fclose, self._handle, timeout=5)
            except OSError:
                pass
        super().close()


class AfcSource:
    """The DCIM tree on a connected iPhone (see sync.DirSource)."""

    def __init__(self, udid: str, lockdown, afc):
        self.udid, self._lockdown, self._afc = udid, lockdown, afc

    def __str__(self) -> str:
        return f"iPhone:{DCIM}"

    def scan(self, cancel: Callable[[], bool] = lambda: False) -> list[Entry]:
        try:
            return _run(self._scan(cancel), None)
        except Cancelled:
            raise
        except OSError:
            raise
        except _errors() as exc:
            raise OSError(str(exc) or type(exc).__name__) from exc

    async def _scan(self, cancel) -> list[Entry]:
        from pymobiledevice3.exceptions import AfcException
        afc = self._afc
        out: list[Entry] = []

        async def stat(path):
            try:
                return await asyncio.wait_for(afc.stat(path), TIMEOUT)
            except AfcException:
                return None     # vanished meanwhile, or not readable

        async def walk(rel: str):
            if cancel():
                raise Cancelled
            folder = f"{DCIM}/{rel}" if rel else DCIM
            names = sorted(n for n in await asyncio.wait_for(afc.listdir(folder), TIMEOUT)
                           if not n.startswith("."))
            stats = await asyncio.gather(*(stat(f"{folder}/{n}") for n in names))
            subdirs = []
            for name, st in zip(names, stats):
                if st is None:
                    continue
                r = f"{rel}/{name}" if rel else name
                if st.get("st_ifmt") == "S_IFDIR":
                    subdirs.append(r)
                elif st.get("st_ifmt") == "S_IFREG" and not name.endswith(".part"):
                    out.append(Entry(r, int(st["st_size"]), st["st_mtime"].timestamp()))
            for r in subdirs:
                await walk(r)

        await walk("")
        return out

    def open_file(self, rel: str) -> io.BufferedReader:
        return io.BufferedReader(AfcFile(self._afc, f"{DCIM}/{rel}"), buffer_size=64 * 1024)

    def open_root(self, rel: str) -> io.BufferedReader:
        """A file next to DCIM, e.g. PhotoData/Photos.sqlite."""
        return io.BufferedReader(AfcFile(self._afc, f"/{rel}"), buffer_size=1024 * 1024)

    async def aclose(self):
        for c in (self._afc.aclose, self._lockdown.close):
            try:
                await asyncio.wait_for(c(), 5)
            except Exception:   # noqa: BLE001 – already gone is fine
                pass

    def close(self):
        try:
            _run(self.aclose(), 12)
        except Exception:   # noqa: BLE001
            pass


async def _open(udid: str) -> AfcSource:
    from pymobiledevice3 import exceptions as ex
    from pymobiledevice3.services.afc import AfcService
    ld = await _lockdown(udid)
    try:
        if not ld.paired:
            raise NoPhotos("not paired")
        afc = AfcService(ld)
        await afc.__aenter__()
    except ex.PasswordRequiredError as exc:
        await ld.close()
        raise NoPhotos(str(exc) or "locked") from exc
    except BaseException:
        await ld.close()
        raise
    src = AfcSource(udid, ld, afc)
    try:
        st = await afc.stat(DCIM)
        ok = st.get("st_ifmt") == "S_IFDIR"
    except ex.AfcException:
        ok = False
    if not ok:
        # opened while locked or before Trust: nothing to see, do not keep it
        await src.aclose()
        raise NoPhotos("DCIM not visible")
    return src


def mount(udid: str) -> AfcSource:
    """Open the photo storage. 'mount' only for the same name as device.py:
    nothing is mounted, the returned source reads straight from the iPhone."""
    try:
        return _run(_open(udid), 30)
    except DeviceError:
        raise
    except _errors() as exc:
        raise DeviceError(str(exc) or type(exc).__name__) from exc


def dcim_of(src: AfcSource) -> AfcSource:
    return src


def unmount(src: AfcSource, lazy: bool = False):
    src.close()
