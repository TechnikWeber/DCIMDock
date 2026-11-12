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
