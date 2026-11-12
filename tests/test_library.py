"""The Photos library (beta) against a hand-made Photos.sqlite like iOS 17's."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dcimdock import library, sync

from .test_sync import Fake


def make_db(path: Path, table="ZASSET", link="Z_30ASSETS", a_col="Z_30ALBUMS", s_col="Z_3ASSETS"):
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE {table} (Z_PK INTEGER PRIMARY KEY, ZDIRECTORY TEXT, ZFILENAME TEXT, "
                "ZTRASHEDSTATE INTEGER, ZHIDDEN INTEGER, ZFAVORITE INTEGER)")
    con.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZKIND INTEGER, ZTRASHEDSTATE INTEGER)")
    con.execute(f"CREATE TABLE {link} ({a_col} INTEGER, {s_col} INTEGER)")
    rows = [
        (1, "DCIM/100APPLE", "IMG_0001.HEIC", 0, 0, 1),   # favorite, in "Urlaub"
        (2, "DCIM/100APPLE", "IMG_0002.HEIC", 1, 0, 0),   # recently deleted
        (3, "DCIM/100APPLE", "IMG_0003.JPG", 0, 1, 0),    # hidden
        (4, "DCIM/100APPLE", "IMG_0004.HEIC", 0, 0, 0),   # only in iCloud: no file
        (5, "PhotoData/Sync/100SYNCD", "IMG_9999.JPG", 0, 0, 0),
    ]
    con.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO ZGENERICALBUM VALUES (?,?,?,?)",
                    [(10, "Urlaub", 2, 0), (11, "Recents", 1000000201, 0), (12, "Alt", 2, 1)])
    con.executemany(f"INSERT INTO {link} VALUES (?,?)", [(10, 1), (11, 1), (11, 3), (12, 3)])
    con.commit()
    con.close()


class TestLibrary(Fake):
    def setUp(self):
        super().setUp()
        self.put("100APPLE/IMG_0001.HEIC", b"a")
        self.put("100APPLE/IMG_0001.MOV", b"live")
        self.put("100APPLE/IMG_0002.HEIC", b"b")
        self.put("100APPLE/IMG_0003.JPG", b"c")
        (self.phone / "PhotoData").mkdir()
        make_db(self.phone / "PhotoData/Photos.sqlite")

    def lib(self):
        with tempfile.TemporaryDirectory() as tmp:
            return library.read(sync.DirSource(self.dcim), Path(tmp))

    def test_reads_flags_and_albums(self):
        lib = self.lib()
        self.assertEqual(lib.albums, ["Urlaub"])
        i = lib.get("100APPLE", "IMG_0001.MOV")         # the Live Photo video counts with its photo
        self.assertTrue(i.favorite)
        self.assertEqual(i.albums, frozenset({"Urlaub"}))
        self.assertTrue(lib.get("100APPLE", "IMG_0002.HEIC").trashed)
        self.assertTrue(lib.get("100APPLE", "IMG_0003.JPG").hidden)
        self.assertEqual(lib.cloud_only(sync.scan(self.dcim)), 1)
        self.assertEqual(lib.counts()["assets"], 4)

    def plan(self, sel, lib):
        entries = sync.scan(self.dcim)
        index = sync.Index(self.dest, "UDID")
        return sync.make_plan(entries, index, sync.Options("flat", "", capture_date=False, selection=sel),
                              None, lib)

    def names(self, plan):
        return sorted(t.entry.name for t in plan.tasks)

    def test_filters(self):
        lib = self.lib()
        all4 = ["IMG_0001.HEIC", "IMG_0001.MOV", "IMG_0002.HEIC", "IMG_0003.JPG"]
        self.assertEqual(self.names(self.plan(sync.Selection(), lib)), all4)
        p = self.plan(sync.Selection(skip_trashed=True), lib)
        self.assertEqual(self.names(p), ["IMG_0001.HEIC", "IMG_0001.MOV", "IMG_0003.JPG"])
        self.assertEqual(p.skipped, 1)
        self.assertEqual(self.names(self.plan(sync.Selection(skip_trashed=True, skip_hidden=True), lib)),
                         ["IMG_0001.HEIC", "IMG_0001.MOV"])
        self.assertEqual(self.names(self.plan(sync.Selection(favorites_only=True), lib)),
                         ["IMG_0001.HEIC", "IMG_0001.MOV"])
        self.assertEqual(self.names(self.plan(sync.Selection(albums=frozenset({"Urlaub"})), lib)),
                         ["IMG_0001.HEIC", "IMG_0001.MOV"])

    def test_without_library_filters_are_ignored(self):
        self.assertEqual(len(self.plan(sync.Selection(skip_trashed=True), None).tasks), 4)

    def test_skipping_deleted_is_not_a_selection(self):
        self.assertFalse(sync.Selection(skip_trashed=True).active)
        self.assertTrue(sync.Selection(favorites_only=True).active)

    def test_old_ios_and_other_link_numbers(self):
        db = self.phone / "PhotoData/Photos.sqlite"
        db.unlink()
        make_db(db, table="ZGENERICASSET", link="Z_26ASSETS", a_col="Z_26ALBUMS", s_col="Z_34ASSETS")
        lib = self.lib()
        self.assertEqual(lib.ios_table, "ZGENERICASSET")
        self.assertEqual(lib.get("100APPLE", "IMG_0001.HEIC").albums, frozenset({"Urlaub"}))

    def test_broken_or_missing(self):
        (self.phone / "PhotoData/Photos.sqlite").write_bytes(b"not a database")
        with self.assertRaises(library.LibraryError):
            self.lib()
        (self.phone / "PhotoData/Photos.sqlite").unlink()
        with self.assertRaises(library.LibraryError):
            self.lib()


