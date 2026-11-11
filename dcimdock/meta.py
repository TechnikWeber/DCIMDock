"""Capture date and screenshot flag from the first bytes of a photo or video.

No dependencies: a small EXIF/TIFF reader plus just enough ISO-BMFF (HEIC,
MOV, MP4) to find the Exif item or the movie header. Every reader is
defensive: broken or unknown files give None, never an exception.

Dates are returned as the camera's wall-clock time interpreted in the local
time zone (time.mktime), because folders are named after the day the photo
was taken where it was taken, not after this computer's time zone.
"""
from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from typing import BinaryIO, Optional

HEAD = 128 * 1024           # JPEG and PNG keep their EXIF near the start
MAX_META = 4 * 1024 * 1024  # upper bound for a HEIC meta box / Exif item
QT_EPOCH = 2082844800       # seconds from 1904-01-01 to 1970-01-01


@dataclass
class Meta:
    date: Optional[float] = None
    screenshot: bool = False


# ------------------------------------------------------------------ EXIF/TIFF

def _exif_time(text: str) -> Optional[float]:
    text = text.strip("\x00 ")
    if len(text) < 19 or text.startswith("0000"):
        return None
    try:
        tm = time.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
        return time.mktime(tm[:8] + (-1,))
    except (ValueError, OverflowError):
        return None


def parse_tiff(buf: bytes, off: int = 0) -> Meta:
    """DateTimeOriginal (else DateTime) and ImageDescription == 'Screenshot'."""
    meta = Meta()
    if len(buf) < off + 8:
        return meta
    order = buf[off:off + 2]
    if order == b"II":
        e = "<"
    elif order == b"MM":
        e = ">"
    else:
        return meta
    if struct.unpack_from(e + "H", buf, off + 2)[0] != 42:
        return meta

    def ifd(pos):
        out = {}
        if pos <= 0 or off + pos + 2 > len(buf):
            return out
        n = struct.unpack_from(e + "H", buf, off + pos)[0]
        for i in range(min(n, 512)):
            p = off + pos + 2 + 12 * i
            if p + 12 > len(buf):
                break
            tag, typ, cnt = struct.unpack_from(e + "HHI", buf, p)
            if typ == 2:  # ASCII
                if cnt <= 4:
                    raw = buf[p + 8:p + 8 + cnt]
                else:
                    vo = struct.unpack_from(e + "I", buf, p + 8)[0]
                    raw = buf[off + vo:off + vo + cnt]
                out[tag] = raw.split(b"\x00", 1)[0].decode("latin-1", "replace")
            elif typ == 4:  # LONG
                out[tag] = struct.unpack_from(e + "I", buf, p + 8)[0]
        return out

    ifd0 = ifd(struct.unpack_from(e + "I", buf, off + 4)[0])
    exif = ifd(ifd0[0x8769]) if isinstance(ifd0.get(0x8769), int) else {}
    for tag, src in ((0x9003, exif), (0x9004, exif), (0x0132, ifd0)):
        if isinstance(src.get(tag), str):
            meta.date = _exif_time(src[tag])
            if meta.date:
                break
    desc = ifd0.get(0x010E)
    comment = exif.get(0x9286)
    meta.screenshot = any(isinstance(x, str) and "Screenshot" in x for x in (desc, comment))
    return meta


def parse_jpeg(buf: bytes) -> Meta:
    i = 2
    if buf[:2] != b"\xff\xd8":
        return Meta()
    while i + 4 <= len(buf):
        if buf[i] != 0xFF:
            break
        marker = buf[i + 1]
        if marker == 0xFF:          # padding
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack_from(">H", buf, i + 2)[0]
        if marker == 0xE1 and buf[i + 4:i + 10] == b"Exif\x00\x00":
            return parse_tiff(buf, i + 10)
        if marker == 0xDA:          # image data starts, no EXIF before it
            break
        i += 2 + length
    return Meta()


def parse_png(buf: bytes) -> Meta:
    if buf[:8] != b"\x89PNG\r\n\x1a\n":
        return Meta()
    i = 8
    while i + 8 <= len(buf):
        length, typ = struct.unpack_from(">I4s", buf, i)
        if typ == b"eXIf":
            return parse_tiff(buf[i + 8:i + 8 + length])
        if typ == b"IDAT":
            break
        i += 12 + length
    return Meta()


# ------------------------------------------------------------------ ISO-BMFF

def _boxes(f: BinaryIO, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(16)
        if len(hdr) < 8:
            return
        size, typ = struct.unpack_from(">I4s", hdr)
        head = 8
        if size == 1:
            if len(hdr) < 16:
                return
            size = struct.unpack_from(">Q", hdr, 8)[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head:
            return
        yield typ, pos, head, size
        pos += size


def _sub(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack_from(">I4s", buf, pos)
        head = 8
        if size == 1:
            size = struct.unpack_from(">Q", buf, pos + 8)[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head:
            return
        yield typ, pos, head, size
        pos += size


def _uint(buf: bytes, pos: int, n: int) -> int:
    return int.from_bytes(buf[pos:pos + n], "big") if n else 0


def heic_exif_location(meta: bytes) -> Optional[tuple[int, int]]:
    """meta is the payload of the 'meta' box (after version/flags)."""
    exif_id = None
    iloc = None
    for typ, pos, head, size in _sub(meta, 0, len(meta)):
        body = pos + head
        if typ == b"iinf":
            ver = meta[body]
            p = body + 4
            count = _uint(meta, p, 2 if ver == 0 else 4)
            p += 2 if ver == 0 else 4
            for t2, p2, h2, s2 in _sub(meta, p, pos + size):
                if t2 != b"infe":
                    continue
                v = meta[p2 + h2]
                q = p2 + h2 + 4
                if v < 2:
                    continue
                item = _uint(meta, q, 2 if v == 2 else 4)
                q += (2 if v == 2 else 4) + 2
                if meta[q:q + 4] == b"Exif":
                    exif_id = item
            del count
        elif typ == b"iloc":
            iloc = (body, pos + size)
    if exif_id is None or iloc is None:
        return None
    p, _end = iloc
    ver = meta[p]
    p += 4
    off_size, len_size = meta[p] >> 4, meta[p] & 15
    base_size, idx_size = meta[p + 1] >> 4, (meta[p + 1] & 15 if ver in (1, 2) else 0)
    p += 2
    count = _uint(meta, p, 2 if ver < 2 else 4)
    p += 2 if ver < 2 else 4
    for _ in range(count):
        item = _uint(meta, p, 2 if ver < 2 else 4)
        p += 2 if ver < 2 else 4
        method = 0
        if ver in (1, 2):
            method = _uint(meta, p, 2) & 15
            p += 2
        p += 2  # data_reference_index
        base = _uint(meta, p, base_size)
        p += base_size
        extents = _uint(meta, p, 2)
        p += 2
        first = None
        for _e in range(extents):
            p += idx_size
            eo = _uint(meta, p, off_size)
            p += off_size
            el = _uint(meta, p, len_size)
            p += len_size
            if first is None:
                first = (eo, el)
        if item == exif_id and first and method == 0:
            return base + first[0], first[1]
    return None


def parse_heic(f: BinaryIO, size: int) -> Meta:
    for typ, pos, head, bsize in _boxes(f, 0, size):
        if typ != b"meta":
            continue
        if bsize > MAX_META:
            return Meta()
        f.seek(pos + head + 4)
        loc = heic_exif_location(f.read(bsize - head - 4))
        if not loc:
            return Meta()
        off, length = loc
        f.seek(off)
        data = f.read(min(length, MAX_META))
        if len(data) < 8:
            return Meta()
        skip = struct.unpack_from(">I", data)[0]  # offset to the TIFF header
        if 4 + skip < len(data) and data[4 + skip:4 + skip + 2] in (b"II", b"MM"):
            return parse_tiff(data, 4 + skip)
        i = data.find(b"Exif\x00\x00")
        return parse_tiff(data, i + 6) if i >= 0 else Meta()
    return Meta()


def parse_movie(f: BinaryIO, size: int) -> Meta:
    """Creation time from moov/mvhd (UTC) – iPhones put moov at either end."""
    for typ, pos, head, bsize in _boxes(f, 0, size):
        if typ != b"moov":
            continue
        for t2, p2, h2, s2 in _boxes(f, pos + head, pos + bsize):
            if t2 != b"mvhd":
                continue
            f.seek(p2 + h2)
            body = f.read(12)
            if len(body) < 8:
                return Meta()
            if body[0] == 1:
                created = struct.unpack_from(">Q", body, 4)[0]
            else:
                created = struct.unpack_from(">I", body, 4)[0]
            if created > QT_EPOCH + 86400:   # 0 means "not set"
                return Meta(float(created - QT_EPOCH))
            return Meta()
    return Meta()


# ------------------------------------------------------------------ entry

def read(path: str) -> Meta:
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if ext in (".jpg", ".jpeg"):
                return parse_jpeg(f.read(HEAD))
            if ext == ".png":
                return parse_png(f.read(HEAD))
            if ext in (".heic", ".heif", ".avif"):
                return parse_heic(f, size)
            if ext in (".mov", ".mp4", ".m4v", ".3gp"):
                return parse_movie(f, size)
            if ext in (".dng", ".tif", ".tiff"):
                return parse_tiff(f.read(HEAD))
    except (OSError, struct.error, IndexError, ValueError):
        pass
    return Meta()
