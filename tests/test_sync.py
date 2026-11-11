"""The copy engine against a fake DCIM folder."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from dcimdock import sync

NOV = time.mktime((2026, 11, 3, 12, 0, 0, 0, 0, -1))
OCT_END = time.mktime((2026, 10, 31, 23, 59, 50, 0, 0, -1))


class Fake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.phone = base / "phone"
        self.dcim = self.phone / "DCIM"
        self.dest = base / "backup"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, data, mtime=NOV):
        p = self.dcim / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (mtime, mtime))
        return p

    def sync(self, layout="date", folder="Phone"):
        entries = sync.scan(sync.find_dcim(self.phone))
        index = sync.Index(self.dest, "UDID")
        plan = sync.make_plan(entries, index, sync.Options(layout, folder))
        res = sync.run(plan, self.dcim, index)
        return plan, res

    def files(self):
        return sorted(p.relative_to(self.dest).as_posix() for p in self.dest.rglob("*")
                      if p.is_file() and ".dcimdock" not in p.parts)


class TestSync(Fake):
    def test_copies_by_date_and_keeps_mtime(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a" * 10)
        self.put("100APPLE/IMG_0002.JPG", b"b" * 20)
        plan, res = self.sync()
        self.assertEqual(res.copied, 2)
        self.assertEqual(self.files(), ["Phone/2026/2026-11/IMG_0001.HEIC", "Phone/2026/2026-11/IMG_0002.JPG"])
        st = (self.dest / "Phone/2026/2026-11/IMG_0001.HEIC").stat()
        self.assertAlmostEqual(st.st_mtime, NOV, delta=1)

    def test_second_run_copies_nothing(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a" * 10)
        self.sync()
        plan, res = self.sync()
        self.assertEqual(plan.tasks, [])
        self.assertEqual(plan.known, 1)

    def test_iphone_restarts_numbering_no_overwrite(self):
        self.put("100APPLE/IMG_0001.HEIC", b"old photo")
        self.sync()
        (self.dcim / "100APPLE/IMG_0001.HEIC").unlink()
        self.put("100APPLE/IMG_0001.HEIC", b"a different new photo", NOV + 86400)
        plan, res = self.sync()
        self.assertEqual(res.copied, 1)
        self.assertEqual((self.dest / "Phone/2026/2026-11/IMG_0001.HEIC").read_bytes(), b"old photo")
        self.assertEqual((self.dest / "Phone/2026/2026-11/IMG_0001_1.HEIC").read_bytes(), b"a different new photo")

    def test_live_photo_pair_stays_together(self):
        # the MOV is a few seconds newer and would fall into the next month
        self.put("100APPLE/IMG_0005.HEIC", b"still", OCT_END)
        self.put("100APPLE/IMG_0005.MOV", b"motion", OCT_END + 20)
        self.put("100APPLE/IMG_E0005.HEIC", b"edited", OCT_END + 30)
        self.put("100APPLE/IMG_O0005.AAE", b"<plist/>", OCT_END + 30)
        self.sync()
        self.assertEqual(self.files(), [
            "Phone/2026/2026-10/IMG_0005.HEIC", "Phone/2026/2026-10/IMG_0005.MOV",
            "Phone/2026/2026-10/IMG_E0005.HEIC", "Phone/2026/2026-10/IMG_O0005.AAE"])

    def test_pair_gets_same_suffix(self):
        self.dest.joinpath("Phone/2026/2026-11").mkdir(parents=True)
        self.dest.joinpath("Phone/2026/2026-11/IMG_0007.MOV").write_bytes(b"someone else's")
        self.put("100APPLE/IMG_0007.HEIC", b"still")
        self.put("100APPLE/IMG_0007.MOV", b"motion")
        self.sync()
        self.assertIn("Phone/2026/2026-11/IMG_0007_1.HEIC", self.files())
        self.assertIn("Phone/2026/2026-11/IMG_0007_1.MOV", self.files())

    def test_late_aae_joins_its_renamed_group(self):
        self.dest.joinpath("Phone/2026/2026-11").mkdir(parents=True)
        self.dest.joinpath("Phone/2026/2026-11/IMG_0009.HEIC").write_bytes(b"other")
        self.put("100APPLE/IMG_0009.HEIC", b"mine")
        self.sync()
        self.put("100APPLE/IMG_O0009.AAE", b"edit", NOV + 3 * 86400)
        self.sync()
        self.assertIn("Phone/2026/2026-11/IMG_O0009_1.AAE", self.files())

    def test_lost_index_adopts_existing_copies(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a" * 10)
        self.sync()
        (self.dest / ".dcimdock/UDID.json").unlink()
        plan, res = self.sync()
        self.assertEqual(res.copied, 0)
        self.assertEqual(len(plan.adopted), 1)
        self.assertEqual(self.files(), ["Phone/2026/2026-11/IMG_0001.HEIC"])

    def test_deleted_backup_file_is_copied_again(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a" * 10)
        self.sync()
        (self.dest / "Phone/2026/2026-11/IMG_0001.HEIC").unlink()
        plan, res = self.sync()
        self.assertEqual(res.copied, 1)

    def test_same_names_in_two_folders_same_month(self):
        self.put("100APPLE/IMG_0001.HEIC", b"first")
        self.put("110APPLE/IMG_0001.HEIC", b"second!")
        self.sync()
        self.assertEqual(self.files(), ["Phone/2026/2026-11/IMG_0001.HEIC", "Phone/2026/2026-11/IMG_0001_1.HEIC"])

    def test_dcim_layout_without_device_folder(self):
        self.put("100APPLE/IMG_0001.HEIC", b"x")
        self.put("101APPLE/IMG_0002.HEIC", b"y")
        self.sync(layout="dcim", folder="")
        self.assertEqual(self.files(), ["100APPLE/IMG_0001.HEIC", "101APPLE/IMG_0002.HEIC"])

    def test_hidden_and_part_files_are_ignored(self):
        self.put(".MISC/Info.plist", b"x")
        self.put("100APPLE/.hidden", b"x")
        self.put("100APPLE/IMG_0001.HEIC.part", b"x")
        plan, res = self.sync()
        self.assertEqual(plan.tasks, [])

    def test_cancel_leaves_no_part_file(self):
        self.put("100APPLE/IMG_0001.MOV", os.urandom(3 * sync.CHUNK))
        entries = sync.scan(self.dcim)
        index = sync.Index(self.dest, "UDID")
        plan = sync.make_plan(entries, index, sync.Options())
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 2
        res = sync.run(plan, self.dcim, index, cancel=cancel)
        self.assertTrue(res.cancelled)
        self.assertEqual(res.copied, 0)
        self.assertEqual(self.files(), [])
        # and the next run picks it up
        plan, res = self.sync()
        self.assertEqual(res.copied, 1)

    def test_unreadable_file_is_reported_and_others_continue(self):
        self.put("100APPLE/IMG_0001.HEIC", b"x")
        bad = self.put("100APPLE/IMG_0002.HEIC", b"y")
        entries = sync.scan(self.dcim)
        bad.unlink()
        index = sync.Index(self.dest, "UDID")
        res = sync.run(sync.make_plan(entries, index, sync.Options()), self.dcim, index)
        self.assertEqual(res.copied, 1)
        self.assertEqual([r for r, _ in res.failed], ["100APPLE/IMG_0002.HEIC"])

    def test_saved_range(self):
        self.put("100APPLE/IMG_0001.HEIC", b"x", OCT_END)
        self.put("100APPLE/IMG_0002.HEIC", b"y", NOV)
        self.sync()
        entries = sync.scan(self.dcim)
        a, b, k = sync.saved_range(entries, sync.Index(self.dest, "UDID"))
        self.assertEqual((a, b, k), (OCT_END, NOV, 2))


class TestNames(unittest.TestCase):
    def test_group_key(self):
        self.assertEqual(sync.group_key("IMG_E0042.HEIC"), "IMG_0042")
        self.assertEqual(sync.group_key("IMG_O0042.AAE"), "IMG_0042")
        self.assertEqual(sync.group_key("IMG_0042.MOV"), "IMG_0042")
        self.assertEqual(sync.group_key("IMG_EXTRA.JPG"), "IMG_EXTRA")

    def test_safe_name(self):
        self.assertEqual(sync.safe_name("Philipp's iPhone"), "Philipp's iPhone")
        self.assertEqual(sync.safe_name("a/b"), "a_b")
        self.assertEqual(sync.safe_name("..."), "iPhone")


if __name__ == "__main__":
    unittest.main()
