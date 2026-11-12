"""Update check and autostart, without network or touching the real login."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dcimdock import autostart, update


class TestUpdate(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(update.newer("0.10.0", "0.9.9"))
        self.assertTrue(update.newer("v1.0.0", "0.9.0"))
        self.assertFalse(update.newer("0.4.0", "0.4.0"))
        self.assertFalse(update.newer("", "0.4.0"))
        self.assertFalse(update.newer("0.3.9", "0.4.0"))

    def test_no_internet_is_quiet(self):
        with mock.patch.object(update, "latest", side_effect=OSError("offline")):
            self.assertIsNone(update.check())

    def test_expected_sha256(self):
        h = "ab" * 32
        sums = f"{'cd' * 32}  dcimdock-1.0.0-x86_64.AppImage\n{h}  DCIMDock-1.0.0-windows-x64.exe\n"
        self.assertEqual(update.expected_sha256(sums, "DCIMDock-1.0.0-windows-x64.exe"), h)
        self.assertEqual(update.expected_sha256(f"{h} *DCIMDock-1.0.0-windows-x64.exe", "DCIMDock-1.0.0-windows-x64.exe"), h)
        self.assertEqual(update.expected_sha256(sums, "other.exe"), "")
        self.assertEqual(update.expected_sha256("nonsense  DCIMDock-1.0.0-windows-x64.exe", "DCIMDock-1.0.0-windows-x64.exe"), "")

    def _fake_release(self, tmp, payload: bytes, sums: str):
        import io
        name = update.exe_name("9.9.9")
        release = {"assets": [{"name": name, "browser_download_url": "exe"},
                              {"name": "SHA256SUMS", "browser_download_url": "sums"}]}

        class Resp(io.BytesIO):
            headers = {"Content-Length": str(len(payload))}

        def get(url, timeout=30):
            return Resp(payload if url == "exe" else sums.encode())
        return (mock.patch.object(update, "_release", return_value=release),
                mock.patch.object(update, "_get", side_effect=get),
                mock.patch.object(sys, "executable", str(Path(tmp) / "DCIMDock-1.0.0-windows-x64.exe")))

    def test_download_checks_the_sum(self):
        import hashlib
        payload = b"new exe"
        name = update.exe_name("9.9.9")
        with tempfile.TemporaryDirectory() as tmp:
            good = f"{hashlib.sha256(payload).hexdigest()}  {name}\n"
            a, b, c = self._fake_release(tmp, payload, good)
            with a, b, c:
                path = update.download("9.9.9")
            self.assertEqual(path.read_bytes(), payload)
            path.unlink()
            a, b, c = self._fake_release(tmp, payload, f"{'00' * 32}  {name}\n")
            with a, b, c, self.assertRaises(ValueError):
                update.download("9.9.9")
            self.assertEqual(list(Path(tmp).iterdir()), [])     # nothing half-written left

    def test_remove_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "DCIMDock-0.1.0-windows-x64.exe"
            old.write_bytes(b"x")
            update.remove_old(str(old), wait=2)
            self.assertFalse(old.exists())
            keep = Path(tmp) / "notes.txt"
            keep.write_bytes(b"x")
            update.remove_old(str(keep), wait=2)     # never anything but an .exe
            self.assertTrue(keep.exists())


@unittest.skipIf(sys.platform == "win32", "desktop file is Linux")
class TestAutostart(unittest.TestCase):
    def test_desktop_file(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp, "APPIMAGE": "/home/a b/DCIMDock.AppImage"}):
            self.assertFalse(autostart.is_enabled())
            autostart.set_enabled(True)
            text = (Path(tmp) / "autostart/dcimdock.desktop").read_text()
            self.assertIn('Exec="/home/a b/DCIMDock.AppImage" --background', text)
            self.assertTrue(autostart.is_enabled())
            autostart.set_enabled(False)
            self.assertFalse(autostart.is_enabled())

    def test_quote(self):
        self.assertEqual(autostart._desktop_quote(["/usr/bin/dcimdock", "--background"]),
                         "/usr/bin/dcimdock --background")
        self.assertEqual(autostart._desktop_quote(['/x/"q"$']), '"/x/\\"q\\"\\$"')


if __name__ == "__main__":
    unittest.main()
