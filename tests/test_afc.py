"""The Windows backend (AFC) against a fake iPhone that serves a temp folder."""
import asyncio
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

try:
    from pymobiledevice3.exceptions import AfcException, AfcFileNotFoundError
except ImportError:      # pragma: no cover – CI installs it
    AfcException = None

from dcimdock import meta, sync

DATA = Path(__file__).parent / "data"
NOV = time.mktime((2026, 11, 3, 12, 0, 0, 0, 0, -1))


class FakeAfc:
    """Just the read-only part of pymobiledevice3's AfcService, over a folder."""

    def __init__(self, root: Path):
        self.root = root
        self.handles = {}
        self.reads = 0
        self.closed = False
        self.fail_after = None   # pull the cable after this many reads

    def _p(self, path):
        return self.root / path.lstrip("/")

    async def listdir(self, path):
        await asyncio.sleep(0)
        p = self._p(path)
        if not p.is_dir():
            raise AfcFileNotFoundError("nope", 8, path)
        return sorted(os.listdir(p))

    async def stat(self, path):
        p = self._p(path)
        if not p.exists():
            raise AfcFileNotFoundError("nope", 8, path)
        st = p.stat()
        return {"st_size": st.st_size, "st_mtime": datetime.fromtimestamp(st.st_mtime),
                "st_ifmt": "S_IFDIR" if p.is_dir() else "S_IFREG"}

    async def fopen(self, path, mode="r"):
        assert mode == "r", "DCIMDock must only ever open for reading"
        h = len(self.handles) + 1
        self.handles[h] = open(self._p(path), "rb")
        return h

    async def fread(self, h, size):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise AfcException("connection lost", 1)
        return self.handles[h].read(size)

    async def fseek(self, h, offset, whence=0):
        self.handles[h].seek(offset, whence)

    async def fclose(self, h):
        self.handles.pop(h).close()

    async def aclose(self):
        self.closed = True


class FakeLockdown:
    async def close(self):
        pass


@unittest.skipIf(AfcException is None, "pymobiledevice3 not installed")
class TestAfc(unittest.TestCase):
    def setUp(self):
        from dcimdock import afc
        self.afc = afc
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.phone = base / "phone"
        self.dest = base / "backup"
        self.fake = FakeAfc(self.phone)
        self.src = afc.AfcSource("UDID", FakeLockdown(), self.fake)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, data, mtime=NOV):
        p = self.phone / "DCIM" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (mtime, mtime))

    def test_scan_like_a_folder(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a" * 10)
        self.put("100APPLE/IMG_0001.MOV", b"m" * 30)
        self.put("101APPLE/IMG_0100.JPG", b"b" * 20)
        self.put("100APPLE/.hidden", b"x")
        self.assertEqual(self.src.scan(), sync.scan(self.phone / "DCIM"))

    def test_copy_end_to_end(self):
        data = os.urandom(3 * sync.CHUNK + 123)
        self.put("100APPLE/IMG_0001.MOV", data)
        self.put("100APPLE/IMG_0002.JPG", b"j" * 5)
        entries = self.src.scan()
        index = sync.Index(self.dest, "UDID")
        plan = sync.make_plan(entries, index, sync.Options("ym", "Phone"))
        res = sync.run(plan, self.src, index)
        self.assertEqual((res.copied, res.failed), (2, []))
        out = self.dest / "Phone/2026/2026-11/IMG_0001.MOV"
        self.assertEqual(out.read_bytes(), data)
        self.assertAlmostEqual(out.stat().st_mtime, NOV, delta=1)
        self.assertEqual(self.fake.handles, {})           # every file closed again
        self.assertEqual(sync.verify(index).ok, 2)

    def test_cable_pulled_leaves_no_half_file(self):
        self.put("100APPLE/IMG_0001.MOV", os.urandom(3 * sync.CHUNK))
        self.fake.fail_after = 1
        entries = self.src.scan()
        index = sync.Index(self.dest, "UDID")
        plan = sync.make_plan(entries, index, sync.Options("flat", ""))
        res = sync.run(plan, self.src, index)
        self.assertEqual(res.copied, 0)
        self.assertEqual(len(res.failed), 1)
        self.assertEqual([p for p in self.dest.rglob("*") if p.is_file() and ".dcimdock" not in p.parts], [])

    def test_capture_dates_over_afc(self):
        for name in ("photo.heic", "photo.jpg", "video.mov", "screenshot.png"):
            shutil.copy(DATA / name, self._dst(name))
        entries = self.src.scan()
        got = sync.read_meta(self.src, entries, {})
        for e in entries:
            want = meta.read(str(self.phone / "DCIM" / e.rel))
            self.assertEqual(got[e.rel], want, e.rel)

    def _dst(self, name):
        p = self.phone / "DCIM/100APPLE" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def test_file_object(self):
        self.put("a.bin", bytes(range(256)) * 10)
        with self.src.open_file("a.bin") as f:
            f.seek(100)
            self.assertEqual(f.read(3), bytes([100, 101, 102]))
            f.seek(-2, os.SEEK_END)
            self.assertEqual(f.read(), bytes([254, 255]))
            f.seek(0)
            self.assertEqual(len(f.read()), 2560)

    def test_cancel_scan(self):
        self.put("100APPLE/IMG_0001.JPG", b"x")
        with self.assertRaises(sync.Cancelled):
            self.src.scan(lambda: True)

    def test_udid(self):
        n = self.afc.normalize_udid
        self.assertEqual(n("00008110001A2B3C4D5E801E"), "00008110-001A2B3C4D5E801E")
        self.assertEqual(n("00008110-001A2B3C4D5E801E"), "00008110-001A2B3C4D5E801E")
        legacy = "0123456789abcdef0123456789abcdef01234567"
        self.assertEqual(n(legacy), legacy)

    def test_pair_states(self):
        from pymobiledevice3 import exceptions as ex
        c = self.afc.classify
        self.assertEqual(c(ex.PairingDialogResponsePendingError()), "trust")
        self.assertEqual(c(ex.UserDeniedPairingError()), "denied")
        self.assertEqual(c(ex.PasswordRequiredError()), "locked")
        self.assertEqual(c(ex.NoDeviceConnectedError()), "gone")
        self.assertEqual(c(RuntimeError("x")), "error")

    def test_backend_api_matches(self):
        from dcimdock import device
        names = ["Device", "DeviceError", "NoPhotos", "HAS_MOUNTS", "SERVICE_ACTION", "missing",
                 "install_command", "cleanup_stale", "broken_mounts", "release_mounts", "list_devices",
                 "info", "pair", "repair_pairing", "restart_service", "diagnose", "mount", "dcim_of", "unmount"]
        for name in names:
            self.assertTrue(hasattr(device, name), f"device.{name}")
            self.assertTrue(hasattr(self.afc, name), f"afc.{name}")


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(AfcException is None, "pymobiledevice3 not installed")
class TestAfcLibrary(unittest.TestCase):
    def test_library_over_afc(self):
        from dcimdock import afc, library
        from .test_library import make_db
        with tempfile.TemporaryDirectory() as tmp:
            phone = Path(tmp) / "phone"
            (phone / "PhotoData").mkdir(parents=True)
            (phone / "DCIM/100APPLE").mkdir(parents=True)
            make_db(phone / "PhotoData/Photos.sqlite")
            fake = FakeAfc(phone)
            src = afc.AfcSource("UDID", FakeLockdown(), fake)
            lib = library.read(src, Path(tmp) / "lib")
            self.assertEqual(lib.albums, ["Urlaub"])
            self.assertEqual(fake.handles, {})
