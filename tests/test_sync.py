"""The copy engine against a fake DCIM folder."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from dcimdock import sync

DATA = Path(__file__).parent / "data"
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

    def sync(self, layout="ym", folder="Phone", split=False):
        entries = sync.scan(sync.find_dcim(self.phone))
        index = sync.Index(self.dest, "UDID")
        kinds = ("Photos", "Videos") if split else ("", "")
        plan = sync.make_plan(entries, index, sync.Options(layout, folder, *kinds))
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


    def test_split_photos_videos_live_photo_stays_with_photo(self):
        self.put("100APPLE/IMG_0001.HEIC", b"still")
        self.put("100APPLE/IMG_0001.MOV", b"live part")
        self.put("100APPLE/IMG_0002.MOV", b"a real video")
        self.put("100APPLE/IMG_0003.PNG", b"screenshot")
        self.sync(split=True)
        self.assertEqual(self.files(), [
            "Phone/Photos/2026/2026-11/IMG_0001.HEIC", "Phone/Photos/2026/2026-11/IMG_0001.MOV",
            "Phone/Photos/2026/2026-11/IMG_0003.PNG", "Phone/Videos/2026/2026-11/IMG_0002.MOV"])

    def test_layouts(self):
        t = NOV
        self.assertEqual(sync.layout_dir("ym", t, "100APPLE"), "2026/2026-11")
        self.assertEqual(sync.layout_dir("ymd", t, "100APPLE"), "2026/2026-11/2026-11-03")
        self.assertEqual(sync.layout_dir("m", t, "100APPLE"), "2026-11")
        self.assertEqual(sync.layout_dir("y", t, "100APPLE"), "2026")
        self.assertEqual(sync.layout_dir("dcim", t, "100APPLE"), "100APPLE")
        self.assertEqual(sync.layout_dir("flat", t, "100APPLE"), "")

    def test_flat_layout(self):
        self.put("100APPLE/IMG_0001.HEIC", b"x")
        self.put("101APPLE/IMG_0002.HEIC", b"y")
        self.sync(layout="flat", folder="")
        self.assertEqual(self.files(), ["IMG_0001.HEIC", "IMG_0002.HEIC"])

    def test_verify_finds_missing_and_damaged(self):
        self.put("100APPLE/IMG_0001.HEIC", b"one")
        self.put("100APPLE/IMG_0002.HEIC", b"two")
        self.put("100APPLE/IMG_0003.HEIC", b"three")
        self.sync()
        (self.dest / "Phone/2026/2026-11/IMG_0001.HEIC").unlink()
        (self.dest / "Phone/2026/2026-11/IMG_0002.HEIC").write_bytes(b"TWO")
        idx = sync.Index.from_file(self.dest, self.dest / ".dcimdock/UDID.json")
        res = sync.verify(idx)
        self.assertEqual(res.ok, 1)
        self.assertEqual(res.missing, ["Phone/2026/2026-11/IMG_0001.HEIC"])
        self.assertEqual(res.changed, ["Phone/2026/2026-11/IMG_0002.HEIC"])


    def plan_with_meta(self, **kw):
        entries = sync.scan(self.dcim)
        index = sync.Index(self.dest, "UDID")
        opts = sync.Options("ym", "", **kw)
        meta = sync.read_meta(self.dcim, sync.needs_meta(entries, index, opts), {})
        return sync.make_plan(entries, index, opts, meta)

    def test_capture_date_sorts_old_photo_into_its_month(self):
        self.put("100APPLE/IMG_0001.HEIC", (DATA / "photo.heic").read_bytes())   # taken 2019-07
        self.put("100APPLE/IMG_0002.JPG", (DATA / "photo.jpg").read_bytes())
        self.put("100APPLE/IMG_0003.JPG", b"no exif at all")
        dests = sorted(t.dest for t in self.plan_with_meta().tasks)
        self.assertEqual(dests, ["2019/2019-07/IMG_0001.HEIC", "2019/2019-07/IMG_0002.JPG",
                                 "2026/2026-11/IMG_0003.JPG"])
        dests = sorted(t.dest for t in self.plan_with_meta(capture_date=False).tasks)
        self.assertTrue(all(d.startswith("2026/2026-11/") for d in dests))

    def test_live_photo_movie_follows_photo_capture_date(self):
        self.put("100APPLE/IMG_0004.HEIC", (DATA / "photo.heic").read_bytes())
        self.put("100APPLE/IMG_0004.MOV", (DATA / "video.mov").read_bytes())  # mvhd says 2020
        dests = sorted(t.dest for t in self.plan_with_meta().tasks)
        self.assertEqual(dests, ["2019/2019-07/IMG_0004.HEIC", "2019/2019-07/IMG_0004.MOV"])

    def test_screenshots_folder(self):
        self.put("100APPLE/IMG_0005.PNG", (DATA / "screenshot.png").read_bytes())
        self.put("100APPLE/IMG_0006.PNG", (DATA / "plain.png").read_bytes())
        self.put("100APPLE/IMG_0007.MOV", (DATA / "video.mov").read_bytes())
        plan = self.plan_with_meta(capture_date=False, screenshot_dir="Screenshots",
                                   photo_dir="Photos", video_dir="Videos")
        self.assertEqual(sorted(t.dest for t in plan.tasks), [
            "Photos/2026/2026-11/IMG_0006.PNG", "Screenshots/2026/2026-11/IMG_0005.PNG",
            "Videos/2026/2026-11/IMG_0007.MOV"])

    def test_known_files_are_not_read_again(self):
        self.put("100APPLE/IMG_0001.JPG", (DATA / "photo.jpg").read_bytes())
        self.sync()
        entries = sync.scan(self.dcim)
        self.assertEqual(sync.needs_meta(entries, sync.Index(self.dest, "UDID"), sync.Options("ym", "Phone")), [])


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


class TestSelection(Fake):
    def plan(self, sel, capture=False, layout="flat"):
        entries = sync.scan(self.dcim)
        index = sync.Index(self.dest, "UDID")
        opts = sync.Options(layout, "", capture_date=capture, selection=sel)
        meta = sync.read_meta(self.dcim, sync.needs_meta(entries, index, opts), {})
        return sync.make_plan(entries, index, opts, meta), index

    def names(self, plan):
        return sorted(t.entry.name for t in plan.tasks)

    def test_default_is_everything(self):
        self.assertFalse(sync.Selection().active)
        self.put("100APPLE/IMG_0001.HEIC", b"a")
        plan, _ = self.plan(sync.Selection())
        self.assertEqual((len(plan.tasks), plan.skipped), (1, 0))

    def test_date_range_by_file_date(self):
        self.put("100APPLE/IMG_0001.JPG", b"a", OCT_END)
        self.put("100APPLE/IMG_0002.JPG", b"b", NOV)
        a = sync.date_range("custom", custom=(NOV, NOV))
        plan, _ = self.plan(sync.Selection(*a))
        self.assertEqual(self.names(plan), ["IMG_0002.JPG"])
        self.assertEqual(plan.skipped, 1)

    def test_live_photo_stays_together_in_range(self):
        # the .MOV is a second older than the day: the group's date decides
        self.put("100APPLE/IMG_0001.HEIC", b"a", NOV)
        self.put("100APPLE/IMG_0001.MOV", b"m", OCT_END)
        a, b = sync.date_range("custom", custom=(OCT_END, OCT_END))
        plan, _ = self.plan(sync.Selection(a, b))
        self.assertEqual(self.names(plan), ["IMG_0001.HEIC", "IMG_0001.MOV"])

    def test_kinds(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a")
        self.put("100APPLE/IMG_0001.MOV", b"live")
        self.put("100APPLE/IMG_0002.MOV", b"video")
        (self.dcim / "100APPLE/IMG_0003.PNG").write_bytes((DATA / "screenshot.png").read_bytes())
        (self.dcim / "100APPLE/IMG_0004.PNG").write_bytes((DATA / "plain.png").read_bytes())
        plan, _ = self.plan(sync.Selection(photos=False, screenshots=False))
        self.assertEqual(self.names(plan), ["IMG_0002.MOV"])
        plan, _ = self.plan(sync.Selection(videos=False))
        self.assertEqual(self.names(plan), ["IMG_0001.HEIC", "IMG_0001.MOV", "IMG_0003.PNG", "IMG_0004.PNG"])
        plan, _ = self.plan(sync.Selection(screenshots=False, videos=False, live=False))
        self.assertEqual(self.names(plan), ["IMG_0001.HEIC", "IMG_0004.PNG"])
        plan, _ = self.plan(sync.Selection(photos=False, videos=False))
        self.assertEqual(self.names(plan), ["IMG_0003.PNG"])

    def test_without_edits(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a")
        self.put("100APPLE/IMG_E0001.HEIC", b"e")
        self.put("100APPLE/IMG_O0001.AAE", b"x")
        plan, _ = self.plan(sync.Selection(edits=False))
        self.assertEqual(self.names(plan), ["IMG_0001.HEIC"])

    def test_later_run_without_selection_fills_the_gap(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a")
        self.put("100APPLE/IMG_0001.MOV", b"m")
        plan, index = self.plan(sync.Selection(live=False), layout="ym")
        sync.run(plan, self.dcim, index)
        self.assertEqual(sync.unsaved(sync.scan(self.dcim), index), 1)
        plan, index = self.plan(sync.Selection(), layout="ym")
        self.assertEqual([t.dest for t in plan.tasks], ["2026/2026-11/IMG_0001.MOV"])
        sync.run(plan, self.dcim, index)
        self.assertEqual(sync.unsaved(sync.scan(self.dcim), index), 0)

    def test_presets(self):
        now = time.mktime((2026, 1, 3, 15, 0, 0, 0, 0, -1))
        day = lambda y, m, d: time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))  # noqa: E731
        self.assertEqual(sync.date_range("all", now), (None, None))
        self.assertEqual(sync.date_range("7d", now), (day(2025, 12, 28), day(2026, 1, 4)))
        self.assertEqual(sync.date_range("year", now), (day(2026, 1, 1), day(2026, 1, 4)))
        self.assertEqual(sync.date_range("lastyear", now), (day(2025, 1, 1), day(2026, 1, 1)))
        self.assertEqual(sync.date_range("custom", now, (None, now)), (None, day(2026, 1, 4)))

    def test_is_edit(self):
        self.assertTrue(sync.is_edit("IMG_E0001.HEIC"))
        self.assertTrue(sync.is_edit("IMG_0001.AAE"))
        self.assertFalse(sync.is_edit("IMG_0001.HEIC"))
        self.assertFalse(sync.is_edit("IMG_EDIT.JPG"))


class TestRename(Fake):
    def run_once(self, **kw):
        entries = sync.scan(self.dcim)
        index = sync.Index(self.dest, "UDID")
        opts = sync.Options("ym", "", capture_date=False, rename=True)
        plan = sync.make_plan(entries, index, opts)
        res = sync.run(plan, self.dcim, index, **kw)
        return plan, res

    def test_prefix_for_the_whole_group(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a", NOV)
        self.put("100APPLE/IMG_0001.MOV", b"m", NOV + 1)
        self.run_once()
        self.assertEqual(self.files(), ["2026/2026-11/2026-11-03_12-00-00_IMG_0001.HEIC",
                                        "2026/2026-11/2026-11-03_12-00-00_IMG_0001.MOV"])

    def test_late_member_joins_with_same_prefix(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a", NOV)
        self.run_once()
        self.put("100APPLE/IMG_O0001.AAE", b"edit", NOV + 600)
        plan, _ = self.run_once()
        self.assertEqual([t.dest for t in plan.tasks], ["2026/2026-11/2026-11-03_12-00-00_IMG_O0001.AAE"])

    def test_clash_gets_suffix(self):
        self.put("100APPLE/IMG_0001.HEIC", b"a", NOV)
        self.run_once()
        # the iPhone starts again at IMG_0001 with a different photo at the same second
        (self.dcim / "100APPLE/IMG_0001.HEIC").write_bytes(b"other")
        os.utime(self.dcim / "100APPLE/IMG_0001.HEIC", (NOV, NOV))
        sync.Index(self.dest, "UDID").path.unlink()
        self.run_once()
        self.assertIn("2026/2026-11/2026-11-03_12-00-00_IMG_0001_1.HEIC", self.files())


class TestJpeg(Fake):
    def test_jpeg_next_to_heic(self):
        from dcimdock import jpeg
        if not jpeg.available():
            self.skipTest("no HEIC converter")
        self.put("100APPLE/IMG_0001.HEIC", (DATA / "photo.heic").read_bytes())
        self.put("100APPLE/IMG_0002.JPG", b"j")
        entries = sync.scan(self.dcim)
        index = sync.Index(self.dest, "UDID")
        plan = sync.make_plan(entries, index, sync.Options("flat", "", capture_date=False))
        res = sync.run(plan, self.dcim, index, jpeg=True)
        self.assertEqual((res.jpegs, res.jpeg_failed), (1, []))
        self.assertEqual(self.files(), ["IMG_0001.HEIC", "IMG_0001.jpg", "IMG_0002.JPG"])
        out = self.dest / "IMG_0001.jpg"
        self.assertEqual(out.read_bytes()[:2], b"\xff\xd8")
        self.assertAlmostEqual(out.stat().st_mtime, NOV, delta=1)
        self.assertIsNone(jpeg.convert(self.dest / "IMG_0001.HEIC"))   # never overwrites
