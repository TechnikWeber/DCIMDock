"""The iPhone's Photos library (PhotoData/Photos.sqlite), read-only. Beta.

DCIM only holds files; what the Photos app knows about them lives in this
database. DCIMDock copies it into a temporary folder and reads:

* trashed: in "Recently Deleted" (the file stays in DCIM until purged)
* hidden: in the "Hidden" album
* favorite
* albums the user made
* assets the library has but DCIM has not: only in iCloud
  ("Optimize iPhone Storage"), so they cannot be backed up over USB

Apple changes the schema with iOS versions (ZGENERICASSET up to iOS 13,
ZASSET since; the album link table is Z_<n>ASSETS with a number that
moves). Everything is looked up by column names; when something does not
fit, load() raises LibraryError and DCIMDock works exactly as without it.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .sync import Entry, group_key

DB = "PhotoData/Photos.sqlite"
USER_ALBUM = 2          # ZGENERICALBUM.ZKIND of albums the user made


class LibraryError(Exception):
    pass


@dataclass
class Info:
    trashed: bool = False
    hidden: bool = False
    favorite: bool = False
    albums: frozenset = frozenset()


@dataclass
class Library:
    assets: dict = field(default_factory=dict)       # (folder, group key) -> Info
    albums: list = field(default_factory=list)        # names of user albums, sorted
    ios_table: str = ""

    def get(self, folder: str, name: str) -> Info | None:
        return self.assets.get((folder, group_key(name)))

    def cloud_only(self, entries: list[Entry]) -> int:
        """Assets in the library (not trashed) without any file in DCIM."""
        have = {(e.folder, group_key(e.name)) for e in entries}
        return sum(1 for k, i in self.assets.items() if not i.trashed and k not in have)

    def counts(self) -> dict:
        return {"assets": len(self.assets),
                "trashed": sum(i.trashed for i in self.assets.values()),
                "hidden": sum(i.hidden for i in self.assets.values()),
                "favorite": sum(i.favorite for i in self.assets.values()),
                "albums": len(self.albums)}


def _columns(con, table: str) -> set[str]:
    return {r[1].upper() for r in con.execute(f'PRAGMA table_info("{table}")')}


def _tables(con) -> set[str]:
    return {r[0].upper() for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _album_link(con, tables: set[str]):
    """(table, album column, asset column) of the album <-> asset link."""
    for t in sorted(tables):
        if not re.fullmatch(r"Z_\d+ASSETS", t):
            continue
        cols = _columns(con, t)
        alb = [c for c in cols if re.fullmatch(r"Z_\d+ALBUMS", c)]
        ast = [c for c in cols if re.fullmatch(r"Z_\d+ASSETS", c)]
        if alb and ast:
            return t, alb[0], ast[0]
    return None


def load(path: Path) -> Library:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise LibraryError(str(exc)) from exc
    try:
        return _load(con)
    except sqlite3.Error as exc:
        raise LibraryError(str(exc)) from exc
    finally:
        con.close()


def _load(con) -> Library:
    tables = _tables(con)
    table = "ZASSET" if "ZASSET" in tables else "ZGENERICASSET" if "ZGENERICASSET" in tables else ""
    if not table:
        raise LibraryError("no asset table")
    cols = _columns(con, table)
    if not {"Z_PK", "ZDIRECTORY", "ZFILENAME"} <= cols:
        raise LibraryError(f"{table} lacks ZDIRECTORY/ZFILENAME")
    pick = [f"COALESCE({c}, 0)" if c in cols else "0" for c in ("ZTRASHEDSTATE", "ZHIDDEN", "ZFAVORITE")]

    albums: dict[int, str] = {}
    if "ZGENERICALBUM" in tables and {"Z_PK", "ZTITLE", "ZKIND"} <= _columns(con, "ZGENERICALBUM"):
        acols = _columns(con, "ZGENERICALBUM")
        trash = " AND COALESCE(ZTRASHEDSTATE, 0) = 0" if "ZTRASHEDSTATE" in acols else ""
        for pk, title in con.execute(
                f"SELECT Z_PK, ZTITLE FROM ZGENERICALBUM WHERE ZKIND = ? AND ZTITLE IS NOT NULL{trash}",
                (USER_ALBUM,)):
            albums[pk] = str(title)
    in_album: dict[int, set] = {}
    link = _album_link(con, tables) if albums else None
    if link:
        t, a_col, s_col = link
        for album_pk, asset_pk in con.execute(f'SELECT "{a_col}", "{s_col}" FROM "{t}"'):
            if album_pk in albums:
                in_album.setdefault(asset_pk, set()).add(albums[album_pk])

    lib = Library(albums=sorted(set(albums.values()), key=str.casefold), ios_table=table)
    sql = f'SELECT Z_PK, ZDIRECTORY, ZFILENAME, {", ".join(pick)} FROM "{table}"'
    for pk, directory, filename, trashed, hidden, fav in con.execute(sql):
        if not directory or not filename:
            continue
        directory = str(directory)
        if not directory.upper().startswith("DCIM/"):
            continue        # e.g. synced from a computer (PhotoData/Sync): not in DCIM anyway
        folder = directory[5:]
        key = (folder, group_key(str(filename)))
        info = Info(bool(trashed), bool(hidden), bool(fav), frozenset(in_album.get(pk, ())))
        old = lib.assets.get(key)
        if old:     # two assets in one group (rare): keep it if either is kept
            info = Info(old.trashed and info.trashed, old.hidden and info.hidden,
                        old.favorite or info.favorite, old.albums | info.albums)
        lib.assets[key] = info
    return lib


def fetch(src, folder: Path) -> Path:
    """Copy Photos.sqlite (+ -wal, -shm) from the source into folder.
    src: a sync source with open_root(); raises LibraryError."""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "Photos.sqlite"
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(out) + suffix)
        try:
            with src.open_root(DB + suffix) as fi, open(target, "wb") as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
        except (OSError, AttributeError) as exc:
            target.unlink(missing_ok=True)
            if suffix == "":
                raise LibraryError(f"{DB}: {exc}") from exc
    return out


def read(src, folder: Path) -> Library:
    """fetch() + load(), the temp copy is removed again."""
    try:
        return load(fetch(src, folder))
    finally:
        for f in folder.glob("Photos.sqlite*"):
            try:
                os.unlink(f)
            except OSError:
                pass
