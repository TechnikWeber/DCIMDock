"""Capture dates and the screenshot flag from small sample files.

The samples in tests/data were made with libheif/Pillow and ffmpeg:
photo.* taken 2019-07-14 10:20:30 (DateTimeOriginal; DateTime says 2025),
screenshot.png marked "Screenshot" like iOS does, video.* created
2020-02-03 04:05:06 UTC (moov at the end in .mov, at the start in .mp4).
"""
import calendar
import time
import unittest
from pathlib import Path

from dcimdock import meta

DATA = Path(__file__).parent / "data"
TAKEN = time.mktime((2019, 7, 14, 10, 20, 30, 0, 0, -1))
VIDEO = calendar.timegm((2020, 2, 3, 4, 5, 6, 0, 0, 0))


class TestMeta(unittest.TestCase):
    def test_heic(self):
        self.assertEqual(meta.read(str(DATA / "photo.heic")).date, TAKEN)

    def test_jpeg(self):
        m = meta.read(str(DATA / "photo.jpg"))
        self.assertEqual(m.date, TAKEN)
        self.assertFalse(m.screenshot)

    def test_screenshot_png(self):
        m = meta.read(str(DATA / "screenshot.png"))
        self.assertTrue(m.screenshot)
        self.assertEqual(m.date, time.mktime((2026, 6, 6, 12, 0, 0, 0, 0, -1)))

    def test_plain_png(self):
        self.assertEqual(meta.read(str(DATA / "plain.png")), meta.Meta())

    def test_movies(self):
        self.assertEqual(meta.read(str(DATA / "video.mov")).date, VIDEO)
        self.assertEqual(meta.read(str(DATA / "video.mp4")).date, VIDEO)

    def test_garbage_never_raises(self):
        for name in ("x.jpg", "x.heic", "x.mov", "x.png", "x.dng"):
            for data in (b"", b"\xff\xd8\xff\xe1\xff\xff", b"\x00\x00\x00\x01meta" + b"\xff" * 30, b"\x89PNG\r\n\x1a\n" + b"\xff" * 20):
                p = Path(self.tmp) / name
                p.write_bytes(data)
                self.assertIsInstance(meta.read(str(p)), meta.Meta)

    def setUp(self):
        import tempfile
        self._t = tempfile.TemporaryDirectory()
        self.tmp = self._t.name

    def tearDown(self):
        self._t.cleanup()


if __name__ == "__main__":
    unittest.main()
