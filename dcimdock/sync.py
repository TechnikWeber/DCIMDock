"""Copy engine: list the iPhone's DCIM folder, work out what is new, copy it.

Pure Python without Qt, so the window, the terminal mode and the tests share it.

Rules this module guarantees:

* Nothing on the source is ever changed (the iPhone is mounted read-only anyway).
* Nothing in the destination is ever overwritten. A name that is taken by a
  different file gets a suffix (IMG_0001_1.HEIC).
* A file only gets its final name after it was written completely, synced to
  disk and its size checked. Until then it is called NAME.part.
* Files that belong together (Live Photo HEIC + MOV, edited IMG_E…, the .AAE
  edit file) land in the same folder with the same suffix.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

CHUNK = 1 << 20          # 1 MiB reads: few round trips over AFC, low memory
INDEX_DIR = ".dcimdock"  # inside the destination, so it travels with the backup
SPACE_RESERVE = 200 * 1024 * 1024
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".3gp"}
IMAGE_EXT = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".gif", ".dng", ".tif", ".tiff", ".webp"}

_EDIT_PREFIX = re.compile(r"^([A-Za-z]+_)[EO](\d)")
_SUFFIX = re.compile(r"^_(\d+)$")


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    """One file on the device. rel is relative to DCIM, with '/'."""
    rel: str
    size: int
    mtime: float

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def folder(self) -> str:
        return self.rel.rsplit("/", 1)[0] if "/" in self.rel else ""


@dataclass
class Task:
    entry: Entry
    dest: str  # relative to the destination root


@dataclass
class Plan:
    tasks: list[Task] = field(default_factory=list)
    adopted: list[Task] = field(default_factory=list)  # already there, only indexed
    known: int = 0
    known_bytes: int = 0

    @property
    def bytes(self) -> int:
        return sum(t.entry.size for t in self.tasks)


@dataclass
class Result:
    copied: int = 0
    bytes: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False
    seconds: float = 0.0


@dataclass
class Options:
    layout: str = "date"       # "date": YYYY/YYYY-MM, "dcim": like 100APPLE
    device_folder: str = ""    # subfolder per iPhone, "" for none


def is_media(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    return ""


def group_key(name: str) -> str:
    """IMG_E0042.HEIC, IMG_O0042.AAE, IMG_0042.MOV -> IMG_0042."""
    stem = os.path.splitext(name)[0]
    return _EDIT_PREFIX.sub(r"\1\2", stem).upper()


def with_suffix(name: str, n: int) -> str:
    if n == 0:
        return name
    stem, ext = os.path.splitext(name)
    return f"{stem}_{n}{ext}"


def safe_name(text: str) -> str:
    text = re.sub(r"[/\\\x00-\x1f]", "_", text).strip(" .")
    return text[:80] or "iPhone"


def date_dir(t: float) -> str:
    lt = time.localtime(t)
    return f"{lt.tm_year:04d}/{lt.tm_year:04d}-{lt.tm_mon:02d}"


def find_dcim(root: Path) -> Path:
    """A mounted iPhone has DCIM/ at the top. --source may point at either."""
    for cand in (root / "DCIM", root / "dcim"):
        if cand.is_dir():
            return cand
    return root


def scan(dcim: Path, cancel: Callable[[], bool] = lambda: False) -> list[Entry]:
    out: list[Entry] = []
    for top, dirs, files in os.walk(dcim):
        if cancel():
            raise Cancelled
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if f.startswith(".") or f.endswith(".part"):
                continue
            p = os.path.join(top, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            rel = os.path.relpath(p, dcim).replace(os.sep, "/")
            out.append(Entry(rel, st.st_size, st.st_mtime))
    return out


class Index:
    """What was already copied from one device: rel -> size, mtime, dest, sha256."""

    def __init__(self, root: Path, device_id: str):
        self.root = root
        self.path = root / INDEX_DIR / f"{safe_name(device_id)}.json"
        self.files: dict[str, dict] = {}
        try:
            data = json.loads(self.path.read_text("utf-8"))
            if isinstance(data.get("files"), dict):
                self.files = data["files"]
        except (OSError, ValueError):
            pass

    def known(self, e: Entry) -> Optional[str]:
        rec = self.files.get(e.rel)
        if not rec or rec.get("size") != e.size or abs(rec.get("mtime", 0) - e.mtime) > 2:
            return None
        dest = rec.get("dest", "")
        try:
            if dest and (self.root / dest).stat().st_size == e.size:
                return dest
        except OSError:
            pass
        return None

    def add(self, e: Entry, dest: str, sha256: str = ""):
        self.files[e.rel] = {"size": e.size, "mtime": e.mtime, "dest": dest, "sha256": sha256}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "files": self.files}, indent=0), "utf-8")
        os.replace(tmp, self.path)


def _same_file(p: Path, e: Entry) -> Optional[bool]:
    """None: free. True: the same file is already there. False: taken by another."""
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return False
    return st.st_size == e.size and abs(st.st_mtime - e.mtime) <= 2


def make_plan(entries: list[Entry], index: Index, opts: Options) -> Plan:
    plan = Plan()
    root = index.root
    reserved: set[str] = set()
    groups: dict[tuple[str, str], list[Entry]] = {}
    for e in entries:
        groups.setdefault((e.folder, group_key(e.name)), []).append(e)

    for (folder, _key), members in groups.items():
        new: list[Entry] = []
        prev_dest = ""
        prev_entry: Optional[Entry] = None
        for e in members:
            dest = index.known(e)
            if dest:
                plan.known += 1
                plan.known_bytes += e.size
                prev_dest, prev_entry = dest, e
            else:
                new.append(e)
        if not new:
            continue

        start = 0
        if prev_dest and prev_entry:
            # a file joined a group that was saved earlier (e.g. a new .AAE):
            # put it next to its siblings with the same suffix
            base = prev_dest.rsplit("/", 1)[0] if "/" in prev_dest else ""
            got = os.path.splitext(prev_dest.rsplit("/", 1)[-1])[0]
            orig = os.path.splitext(prev_entry.name)[0]
            m = _SUFFIX.match(got[len(orig):]) if got.startswith(orig) else None
            start = int(m.group(1)) if m else 0
        else:
            sub = date_dir(min(e.mtime for e in members)) if opts.layout == "date" else folder
            base = "/".join(p for p in (opts.device_folder, sub) if p)

        n = start
        while True:
            targets, adopted, clash = [], [], False
            for e in new:
                rel = f"{base}/{with_suffix(e.name, n)}" if base else with_suffix(e.name, n)
                if rel in reserved:
                    clash = True
                    break
                state = _same_file(root / rel, e)
                if state is None:
                    targets.append(Task(e, rel))
                elif state:
                    adopted.append(Task(e, rel))
                else:
                    clash = True
                    break
            if not clash:
                break
            n += 1
        for t in targets + adopted:
            reserved.add(t.dest)
        plan.tasks += targets
        plan.adopted += adopted
    return plan


def free_space_ok(root: Path, need: int) -> tuple[bool, int]:
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    return free >= need + SPACE_RESERVE, free


def _place(part: Path, dest: Path):
    """Give the finished file its name without ever replacing another file."""
    try:
        os.link(part, dest)          # fails if dest exists: no overwrite race
        os.unlink(part)
    except FileExistsError:
        raise
    except OSError:
        # FAT/exFAT drives have no hard links
        if dest.exists():
            raise FileExistsError(str(dest))
        os.rename(part, dest)


def copy_one(src: Path, dest: Path, e: Entry, progress: Callable[[int], None],
             cancel: Callable[[], bool]) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    try:
        with open(src, "rb", buffering=0) as fi, open(part, "wb") as fo:
            while True:
                if cancel():
                    raise Cancelled
                chunk = fi.read(CHUNK)
                if not chunk:
                    break
                fo.write(chunk)
                h.update(chunk)
                progress(len(chunk))
            fo.flush()
            os.fsync(fo.fileno())
        written = part.stat().st_size
        if written != e.size:
            raise OSError(f"size mismatch: {written} of {e.size} bytes")
        os.utime(part, (e.mtime, e.mtime))
        _place(part, dest)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    return h.hexdigest()


def run(plan: Plan, dcim: Path, index: Index,
        progress: Callable[[int, int, Task], None] = lambda done, i, t: None,
        file_done: Callable[[Task, Path], None] = lambda t, p: None,
        cancel: Callable[[], bool] = lambda: False) -> Result:
    """Copy plan.tasks. progress(bytes_done_total, task_number, task)."""
    res = Result()
    t0 = time.monotonic()
    for t in plan.adopted:
        index.add(t.entry, t.dest)
    if plan.adopted:
        index.save()
    done = 0
    last_save = time.monotonic()
    unsaved = 0
    try:
        for i, task in enumerate(plan.tasks, 1):
            dest = index.root / task.dest
            progress(done, i, task)

            def step(n, i=i, task=task):
                nonlocal done
                done += n
                progress(done, i, task)
            before = done
            try:
                digest = copy_one(dcim / task.entry.rel, dest, task.entry, step, cancel)
            except Cancelled:
                raise
            except OSError as exc:
                done = before + task.entry.size  # keep the bar honest
                res.failed.append((task.entry.rel, exc.strerror or str(exc)))
                continue
            index.add(task.entry, task.dest, digest)
            res.copied += 1
            res.bytes += task.entry.size
            unsaved += 1
            file_done(task, dest)
            if unsaved >= 25 or time.monotonic() - last_save > 5:
                index.save()
                unsaved, last_save = 0, time.monotonic()
    except Cancelled:
        res.cancelled = True
    finally:
        index.save()
        res.seconds = time.monotonic() - t0
    return res


def saved_range(entries: list[Entry], index: Index) -> tuple[Optional[float], Optional[float], int]:
    """Oldest and newest capture time of everything from this device that is safe."""
    times = [e.mtime for e in entries if index.known(e)]
    if not times:
        return None, None, 0
    return min(times), max(times), len(times)
