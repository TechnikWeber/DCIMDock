"""Entry point: `dcimdock` opens the window, `dcimdock --cli` copies in the terminal."""
from __future__ import annotations

import argparse
import configparser
import os
import sys
import time
from pathlib import Path

from . import __version__


def _icon_theme_fallback():
    """Inside the AppImage Qt has no KDE/GNOME platform plugin, so it does not
    know the desktop's icon theme. Read it from kdeglobals, else pick one."""
    from PySide6.QtGui import QIcon

    if QIcon.themeName() not in ("", "hicolor"):
        return
    theme = ""
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kdeglobals"
    if cfg.exists():
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(cfg)
            theme = parser.get("Icons", "Theme", fallback="")
        except configparser.Error:
            pass
    for candidate in (theme, "breeze", "Adwaita"):
        if candidate and Path("/usr/share/icons", candidate).is_dir():
            QIcon.setThemeName(candidate)
            return


def _default_dest() -> Path:
    pics = ""
    try:
        import subprocess
        pics = subprocess.run(["xdg-user-dir", "PICTURES"], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(pics or Path.home() / "Pictures") / "iPhone"


from .sync import PRESETS  # noqa: E402

KINDS = ("photos", "videos", "screenshots")


def _day(text: str) -> float:
    try:
        return time.mktime(time.strptime(text, "%Y-%m-%d"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text}") from None


def _kinds(text: str) -> set[str]:
    kinds = {k.strip().lower() for k in text.split(",") if k.strip()}
    bad = kinds - set(KINDS)
    if bad or not kinds:
        raise argparse.ArgumentTypeError(f"kinds are {', '.join(KINDS)}")
    return kinds


def selection_from(args):
    from . import sync
    if args.date_from is not None or args.date_to is not None:
        a, b = sync.date_range("custom", custom=(args.date_from, args.date_to))
    else:
        a, b = sync.date_range(args.period)
    kinds = args.only or set(KINDS)
    extra = {}
    if args.beta:
        extra = dict(skip_trashed=not args.include_deleted, skip_hidden=args.skip_hidden,
                     favorites_only=args.favorites, albums=frozenset(args.album))
    return sync.Selection(a, b, "photos" in kinds, "videos" in kinds, "screenshots" in kinds,
                          not args.no_live, not args.no_edits, **extra)


def cli(args) -> int:
    from . import sync
    from .backend import device
    from .i18n import date, duration, num, size, tr

    mount = None
    if args.source:
        src = Path(args.source).expanduser().resolve()
        dcim = sync.find_dcim(src)
        dev = device.Device("folder-" + sync.safe_name(src.name), src.name)
    else:
        miss = device.missing()
        if miss:
            print(tr("Missing programs: {tools}.\nInstall them with:\n\n{cmd}",
                     tools=", ".join(miss), cmd=device.install_command()), file=sys.stderr)
            return 2
        ids = device.list_devices()
        if not ids:
            print(tr("Connect your iPhone with a USB cable."), file=sys.stderr)
            return 1
        dev = device.info(ids[0])
        state, msg = device.pair(dev.udid)
        while state in ("locked", "trust"):
            print(tr("Unlock your iPhone and tap “Trust”, then enter your passcode."), file=sys.stderr)
            time.sleep(3)
            state, msg = device.pair(dev.udid)
        if state != "ready":
            print(tr("The iPhone does not answer: {msg}", msg=msg), file=sys.stderr)
            return 1
        try:
            mount = device.mount(dev.udid)
        except device.DeviceError as exc:
            print(tr("Could not open the photos: {msg}", msg=str(exc)), file=sys.stderr)
            return 1
        dcim = device.dcim_of(mount)
        print(f"{dev.label} ({dev.product}, iOS {dev.ios})")

    try:
        root = Path(args.dest).expanduser().resolve() if args.dest else _default_dest()
        if args.full:
            stamp = time.strftime('%Y-%m-%d %H-%M')
            name = f"{tr('Selection')} {stamp}" if selection_from(args).active else f"{tr('Full copy')} {stamp}"
            root = root / name
        print(tr("Reading the photo list…"))
        entries = sync.scan(dcim)
        lib = None
        if args.beta:
            import tempfile

            from . import library
            try:
                with tempfile.TemporaryDirectory(prefix="dcimdock-") as tmp:
                    lib = library.read(sync.as_source(dcim), Path(tmp))
                cloud = lib.cloud_only(entries)
                if cloud:
                    print(tr("{n} photos and videos are only in iCloud and cannot be backed up. On the iPhone: Settings → Photos → “Download and Keep Originals”.",
                             n=num(cloud)), file=sys.stderr)
                missing = set(args.album) - set(lib.albums)
                if missing:
                    print(f"! albums not found: {', '.join(sorted(missing))} (have: {', '.join(lib.albums) or '-'})",
                          file=sys.stderr)
            except library.LibraryError as exc:
                print(tr("Photos library not readable, working without it: {msg}", msg=str(exc)), file=sys.stderr)
        index = sync.Index(root, dev.udid)
        split = (tr("Photos"), tr("Videos")) if args.split else ("", "")
        opts = sync.Options(args.layout, "" if args.no_device_folder else sync.safe_name(dev.label), *split,
                            tr("Screenshots") if args.screenshots else "", not args.file_date,
                            selection_from(args))
        need = sync.needs_meta(entries, index, opts)
        meta = None
        if need:
            def step(i, n):
                if sys.stdout.isatty():
                    print("\r" + tr("Reading capture dates… {i} of {n}", i=num(i), n=num(n)), end="", flush=True)
            meta = sync.read_meta(dcim, need, {}, step)
            if sys.stdout.isatty():
                print()
        plan = sync.make_plan(entries, index, opts, meta, lib)
        known = plan.known + len(plan.adopted)
        if plan.skipped:
            print(tr("{n} not selected", n=num(plan.skipped)))
        if not plan.tasks:
            print(tr("Nothing new in the selection · {k} already saved", k=num(known)) if plan.skipped
                  else tr("Everything is saved ({k} files).", k=num(known)))
            if plan.adopted:
                index.save()   # remember files that were found already copied
            return 0
        print(tr("{n} new files ({size}) · {k} already saved" if len(plan.tasks) != 1 else "1 new file ({size}) · {k} already saved",
                 n=num(len(plan.tasks)), size=size(plan.bytes), k=num(known)))
        print(f"→ {root}")
        if args.dry_run:
            for t in plan.tasks:
                print(f"  {t.entry.rel}  →  {t.dest}")
            return 0
        ok, free = sync.free_space_ok(root, plan.bytes)
        if not ok:
            print(tr("Only {free} free in the backup folder, {need} needed.",
                     free=size(free), need=size(plan.bytes + sync.SPACE_RESERVE)), file=sys.stderr)
            return 1
        root.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        last = [0.0]
        tty = sys.stdout.isatty()

        def progress(done, i, task):
            now = time.monotonic()
            if not tty or now - last[0] < 0.25:
                return
            last[0] = now
            speed = done / max(now - t0, 0.001)
            left = (plan.bytes - done) / speed if speed else 0
            line = (f"{done * 100 / plan.bytes:5.1f} %  " +
                    tr("File {i} of {n} · {name}", i=num(i), n=num(len(plan.tasks)), name=task.entry.name)
                    + "  " + tr("{speed}/s · {left} left", speed=size(speed), left=duration(left)))
            print("\r" + line[:150].ljust(150), end="", flush=True)

        try:
            res = sync.run(plan, dcim, index, progress)
        except KeyboardInterrupt:
            print()
            return 130
        if tty:
            print("\r" + " " * 150 + "\r", end="")
        print(tr("{n} files saved ({size}) in {time}.", n=num(res.copied), size=size(res.bytes),
                 time=duration(res.seconds)))
        for rel, why in res.failed:
            print(f"  ! {rel}: {why}", file=sys.stderr)
        a, b, k = sync.saved_range(entries, index)
        if a is not None:
            print(tr("From this iPhone, {k} files taken between {a} and {b} are safe on this computer.",
                     k=num(k), a=date(a), b=date(b)))
        return 1 if res.failed else 0
    finally:
        if mount:
            device.unmount(mount)


def verify_cli(args) -> int:
    from . import sync
    from .i18n import num, size, tr

    root = Path(args.dest).expanduser().resolve() if args.dest else _default_dest()
    files = sorted((root / sync.INDEX_DIR).glob("*.json"))
    if not files:
        print(tr("There is no backup in {folder} yet.", folder=root), file=sys.stderr)
        return 1
    bad = 0
    for f in files:
        res = sync.verify(sync.Index.from_file(root, f))
        print(tr("{n} files are intact ({size}).", n=num(res.ok), size=size(res.bytes)))
        for x in res.missing:
            print(f"  {tr('Missing:')} {x}")
        for x in res.changed:
            print(f"  {tr('Changed or damaged:')} {x}")
        bad += len(res.missing) + len(res.changed)
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dcimdock",
        description="Copy the photos and videos from an iPhone to this computer.",
    )
    parser.add_argument("--version", action="version", version=f"dcimdock {__version__}")
    parser.add_argument("--cli", action="store_true", help="copy in the terminal, no window")
    parser.add_argument("--dest", help="backup folder (default: ~/Pictures/iPhone)")
    parser.add_argument("--layout", choices=("ym", "ymd", "m", "y", "dcim", "flat"), default="ym",
                        help="ym: 2026/2026-11 (default), ymd: 2026/2026-11/2026-11-03, m: 2026-11, "
                             "y: 2026, dcim: like on the iPhone, flat: one folder")
    parser.add_argument("--split", action="store_true", help="photos and videos into separate folders")
    parser.add_argument("--screenshots", action="store_true", help="screenshots into their own folder")
    parser.add_argument("--file-date", action="store_true",
                        help="sort by the file date instead of the capture date from EXIF")
    parser.add_argument("--full", action="store_true",
                        help="copy everything into a new folder, without comparing with earlier backups")
    parser.add_argument("--verify", action="store_true",
                        help="read the backup in --dest again and compare it with the checksums")
    parser.add_argument("--no-device-folder", action="store_true",
                        help="no subfolder named after the iPhone")
    parser.add_argument("--dry-run", action="store_true", help="only show what would be copied")
    parser.add_argument("--source", help="copy from this folder instead of an iPhone (for tests)")
    sel = parser.add_argument_group("selection (default: everything)")
    sel.add_argument("--period", choices=[p for p in PRESETS if p != "custom"], default="all",
                     help="7d/30d/90d: the last days including today, year: this year, lastyear: the previous one")
    sel.add_argument("--from", dest="date_from", type=_day, metavar="YYYY-MM-DD", help="first day to copy")
    sel.add_argument("--to", dest="date_to", type=_day, metavar="YYYY-MM-DD", help="last day to copy (included)")
    sel.add_argument("--only", type=_kinds, metavar="KINDS",
                     help="comma separated: photos, videos, screenshots")
    sel.add_argument("--no-live", action="store_true", help="without the video of Live Photos")
    sel.add_argument("--no-edits", action="store_true", help="without edited versions (IMG_E…) and .AAE files")
    beta = parser.add_argument_group("beta: read the Photos library of the iPhone")
    beta.add_argument("--beta", action="store_true",
                      help="read it: leaves out Recently Deleted, warns about photos only in iCloud")
    beta.add_argument("--include-deleted", action="store_true", help="with --beta: copy Recently Deleted too")
    beta.add_argument("--skip-hidden", action="store_true", help="with --beta: without hidden photos")
    beta.add_argument("--favorites", action="store_true", help="with --beta: only favorites")
    beta.add_argument("--album", action="append", default=[], metavar="NAME",
                      help="with --beta: only from this album (can be given more than once)")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--background", action="store_true",
                        help="start with only the tray icon (used by the autostart)")
    args = parser.parse_args(argv)

    if args.verify:
        return verify_cli(args)
    if args.cli:
        return cli(args)

    if args.selftest:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("dcimdock")
    app.setApplicationDisplayName("DCIMDock")
    app.setDesktopFileName("dcimdock")
    app.setApplicationVersion(__version__)
    _icon_theme_fallback()
    app.setQuitOnLastWindowClosed(False)    # the tray icon may keep it running
    win = MainWindow(source=args.source, selftest=args.selftest, background=args.background)
    if args.background and win.tray:
        pass        # only the tray icon; the window opens from there
    else:
        win.show()
    if args.selftest:
        def report():
            ok = not win.windowIcon().isNull()
            backend = "ifuse"
            from .backend import device
            if hasattr(device, "selfcheck"):
                try:
                    backend = device.selfcheck()
                except Exception as exc:   # noqa: BLE001
                    backend, ok = f"afc BROKEN: {exc!r}", False
            from . import jpeg
            line = (f"selftest {'ok' if ok else 'FAILED'}: dcimdock {__version__}, Qt window built, "
                    f"icon {'ok' if not win.windowIcon().isNull() else 'MISSING'}, {backend}, "
                    f"jpeg {jpeg.available() or '-'}")
            print(line)
            log = os.environ.get("DCIMDOCK_SELFTEST_LOG")   # the windowed .exe has no stdout
            if log:
                Path(log).write_text(line + "\n", "utf-8")
            app.exit(0 if ok else 1)
        QTimer.singleShot(500, report)
    rc = app.exec()
    # tear the window down while the QApplication still exists: leaving it to
    # Python's garbage collector crashed PySide 6.12 (the AppImage) on exit
    win.deleteLater()
    del win
    app.processEvents()
    return rc
