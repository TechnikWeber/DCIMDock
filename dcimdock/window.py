"""The main window: device status, destination, progress bar, optional preview."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, QStandardPaths, Qt, QThread, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from . import device, sync
from .i18n import date, duration, num, size, tr
from .icon import app_icon

PREVIEW = QSize(360, 240)
LAYOUT_LABELS = [
    ("ym", "Year / month (2026/2026-11)"),
    ("ymd", "Year / month / day (2026/2026-11/2026-11-03)"),
    ("m", "Month (2026-11)"),
    ("y", "Year (2026)"),
    ("dcim", "Like on the iPhone (100APPLE …)"),
    ("flat", "All in one folder"),
]


class Call(QThread):
    """Run one blocking function off the GUI thread."""
    def __init__(self, parent, fn, *args):
        super().__init__(parent)
        self.fn, self.args = fn, args
        self.res = self.err = None

    def run(self):
        try:
            self.res = self.fn(*self.args)
        except Exception as exc:  # noqa: BLE001 – shown to the user
            self.err = exc


class DiagDialog(QDialog):
    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle(tr("Diagnosis"))
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Paste this into a bug report:")))
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        lay.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy = buttons.addButton(tr("Copy"), QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(text))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class SyncThread(QThread):
    progress = Signal(object, int)   # bytes done (object: may exceed 2^31), file number
    file_done = Signal(str)
    result = Signal(object)

    def __init__(self, parent, plan, dcim, index):
        super().__init__(parent)
        self.plan, self.dcim, self.index = plan, dcim, index
        self.stop = threading.Event()
        self._last = 0.0

    def _progress(self, done, i, _task):
        now = time.monotonic()
        if now - self._last >= 0.1:
            self._last = now
            self.progress.emit(done, i)

    def run(self):
        res = sync.run(self.plan, self.dcim, self.index, self._progress,
                       lambda t, p: self.file_done.emit(str(p)), self.stop.is_set)
        self.result.emit(res)


class VerifyThread(QThread):
    progress = Signal(int, int)

    def __init__(self, parent, root, files):
        super().__init__(parent)
        self.root, self.files = root, files
        self.res = sync.Check()

    def run(self):
        for f in self.files:
            part = sync.verify(sync.Index.from_file(self.root, f),
                               lambda i, n: (i % 25 == 0 or i == n) and self.progress.emit(i, n))
            self.res.ok += part.ok
            self.res.bytes += part.bytes
            self.res.missing += part.missing
            self.res.changed += part.changed


class _MetaProgress(QObject):
    step = Signal(int, int)


class _Decoded(QObject):
    ready = Signal(str, object)  # path, QImage or None


class Decode(QRunnable):
    """Small preview, decoded off the GUI thread at reduced size."""

    def __init__(self, path: str, sink: _Decoded):
        super().__init__()
        self.path, self.sink = path, sink

    def run(self):
        r = QImageReader(self.path)
        r.setAutoTransform(True)
        s = r.size()
        if s.isValid():
            r.setScaledSize(s.scaled(PREVIEW, Qt.KeepAspectRatio))
        img = r.read()
        try:
            self.sink.ready.emit(self.path, None if img.isNull() else img)
        except RuntimeError:   # window closed while decoding
            pass


class IntroDialog(QDialog):
    def __init__(self, parent, show_checkbox: bool):
        super().__init__(parent)
        self.setWindowTitle(tr("Before you start"))
        self.resize(600, 640)
        lay = QVBoxLayout(self)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setHtml(tr("INTRO_HTML"))
        lay.addWidget(text)
        self.hide_box = QCheckBox(tr("Don’t show this again"))
        self.hide_box.setVisible(show_checkbox)
        lay.addWidget(self.hide_box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)


def default_dest() -> str:
    pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
    return str(Path(pics) / "iPhone")


class MainWindow(QMainWindow):
    def __init__(self, source: str | None = None, selftest: bool = False):
        super().__init__()
        self.setWindowTitle("DCIMDock")
        self.setWindowIcon(app_icon())
        self.settings = QSettings("dcimdock", "dcimdock")
        self.source = Path(source).expanduser().resolve() if source else None
        self.selftest = selftest

        self.dev: device.Device | None = None
        self.mount: Path | None = None
        self.dcim: Path | None = None
        self.entries: list[sync.Entry] | None = None
        self.plan: sync.Plan | None = None
        self.index: sync.Index | None = None
        self.state = "none"
        self.worker: SyncThread | None = None
        self._calls: set[Call] = set()
        self._polling = False
        self._connecting = False
        self._retry_at = 0.0
        self._quit_after_stop = False
        self._copy_index = None
        self.devices: dict[str, str] = {}     # udid -> name, all connected iPhones
        self._wanted = ""                     # udid picked in the device box
        self._naming: set[str] = set()
        self._meta_cache: dict = {}
        self._plan_gen = 0
        self.meta_sig = _MetaProgress()
        self.meta_sig.step.connect(self._meta_step)
        self._gone_during_copy = False

        self._build()
        device.cleanup_stale()

        self.poll_timer = QTimer(self, interval=2000, timeout=self.poll)
        self.preview_timer = QTimer(self, interval=400, timeout=self._preview_tick)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.decoded = _Decoded()
        self.decoded.ready.connect(self._preview_ready)
        self._preview_want = ""
        self._preview_busy = False
        self._preview_shown = ""

        QTimer.singleShot(0, self.start)
        if not selftest and not self.settings.value("hide_intro", False, type=bool):
            QTimer.singleShot(300, lambda: self.show_intro(True))

    # ------------------------------------------------------------ layout
    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(48, 48))
        head.addWidget(icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        self.title = QLabel("DCIMDock")
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.35)
        f.setBold(True)
        self.title.setFont(f)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title_row = QHBoxLayout()
        title_row.addWidget(self.title)
        self.device_box = QComboBox()
        self.device_box.setToolTip(tr("Several iPhones are connected. Pick the one to back up."))
        self.device_box.hide()
        self.device_box.activated.connect(self._device_chosen)
        title_row.addWidget(self.device_box)
        title_row.addStretch(1)
        col.addLayout(title_row)
        col.addWidget(self.status)
        head.addLayout(col, 1)
        self.info_btn = QPushButton(tr("Before you start"))
        self.info_btn.clicked.connect(lambda: self.show_intro(False))
        head.addWidget(self.info_btn, 0, Qt.AlignTop)
        lay.addLayout(head)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        lay.addWidget(line)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel(tr("Save to") + ":"))
        self.dest_label = QLabel()
        self.dest_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.dest_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        dest_row.addWidget(self.dest_label, 1)
        self.dest_btn = QPushButton(tr("Change…"))
        self.dest_btn.clicked.connect(self.choose_dest)
        dest_row.addWidget(self.dest_btn)
        lay.addLayout(dest_row)

        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel(tr("Folders") + ":"))
        self.layout_box = QComboBox()
        for key, label in LAYOUT_LABELS:
            self.layout_box.addItem(tr(label), key)
        sort_row.addWidget(self.layout_box, 1)
        lay.addLayout(sort_row)

        opt_row = QHBoxLayout()
        self.per_device = QCheckBox(tr("Own folder per iPhone"))
        self.split = QCheckBox(tr("Photos and videos apart"))
        self.preview_box = QCheckBox(tr("Preview"))
        opt_row.addWidget(self.per_device)
        opt_row.addWidget(self.split)
        opt_row.addWidget(self.preview_box)
        opt_row.addStretch(1)
        lay.addLayout(opt_row)
        opt_row2 = QHBoxLayout()
        self.capture_box = QCheckBox(tr("Sort by the date the photo was taken (EXIF)"))
        self.capture_box.setToolTip(tr("Reads the capture date from the photo or video. Off: the file date is used, which for saved or imported pictures is the day they were saved."))
        self.shots_box = QCheckBox(tr("Screenshots apart"))
        opt_row2.addWidget(self.capture_box)
        opt_row2.addWidget(self.shots_box)
        opt_row2.addStretch(1)
        lay.addLayout(opt_row2)
        self.example = QLabel()
        self.example.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.example.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.example)

        s = self.settings
        self.dest = s.value("dest", default_dest())
        layout = s.value("layout", "ym")
        layout = "ym" if layout == "date" else layout
        self.layout_box.setCurrentIndex(max(0, self.layout_box.findData(layout)))
        self.per_device.setChecked(s.value("per_device", True, type=bool))
        self.split.setChecked(s.value("split", False, type=bool))
        self.capture_box.setChecked(s.value("capture_date", True, type=bool))
        self.shots_box.setChecked(s.value("screenshots", False, type=bool))
        self.preview_box.setChecked(s.value("preview", True, type=bool))
        self._show_dest()
        self._show_example()
        self.layout_box.currentIndexChanged.connect(self._options_changed)
        self.per_device.toggled.connect(self._options_changed)
        self.split.toggled.connect(self._options_changed)
        self.capture_box.toggled.connect(self._options_changed)
        self.shots_box.toggled.connect(self._options_changed)
        self.preview_box.toggled.connect(self._preview_toggled)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.bar.setFormat("")
        lay.addWidget(self.bar)
        self.detail = QLabel(" ")
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.detail)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(PREVIEW.height())
        self.preview.setMinimumWidth(PREVIEW.width())
        self.preview.setFrameShape(QFrame.StyledPanel)
        lay.addWidget(self.preview, 1)
        self.preview.setVisible(self.preview_box.isChecked())
        self.preview_caption = QLabel(" ")
        self.preview_caption.setAlignment(Qt.AlignCenter)
        self.preview_caption.setVisible(self.preview_box.isChecked())
        lay.addWidget(self.preview_caption)
        lay.addStretch(0)

        btns = QHBoxLayout()
        self.open_btn = QPushButton(tr("Open folder"))
        self.open_btn.clicked.connect(self.open_dest)
        self.more_btn = QToolButton()
        self.more_btn.setText(tr("More"))
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        self.more_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menu = QMenu(self.more_btn)
        self.act_full = menu.addAction(tr("Copy everything again (new folder)…"), self.full_copy)
        self.act_verify = menu.addAction(tr("Check the backup…"), self.verify)
        menu.addSeparator()
        fix = menu.addMenu(tr("Troubleshooting"))
        self.act_release = fix.addAction(tr("Release stuck iPhone folders"), self.fix_mounts)
        self.act_repair = fix.addAction(tr("Pair again (ask for Trust again)"), self.fix_pairing)
        self.act_usbmuxd = fix.addAction(tr("Restart the iPhone service (usbmuxd)"), self.fix_usbmuxd)
        fix.addSeparator()
        fix.addAction(tr("Diagnosis…"), self.show_diagnosis)
        self.more_btn.setMenu(menu)
        self.retry_btn = QPushButton(tr("Check again"))
        self.retry_btn.clicked.connect(self.start)
        self.retry_btn.hide()
        self.go_btn = QPushButton(tr("Back up"))
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self.go_or_stop)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.more_btn)
        btns.addStretch(1)
        btns.addWidget(self.retry_btn)
        btns.addWidget(self.go_btn)
        lay.addLayout(btns)
        self.resize(640, 560 if self.preview_box.isChecked() else 340)
        self._set_state("none", tr("Connect your iPhone with a USB cable."))

    # ------------------------------------------------------------ helpers
    def _call(self, fn, cb, *args):
        c = Call(self, fn, *args)
        self._calls.add(c)

        def finished(c=c):
            self._calls.discard(c)
            c.deleteLater()
            cb(c.res, c.err)
        c.finished.connect(finished)
        c.start()

    def _set_state(self, state: str, text: str = ""):
        self.state = state
        self.status.setText(text)
        busy = state in ("connecting", "scanning", "copying", "fixing")
        self.go_btn.setEnabled(state == "copying" or (state == "ready" and bool(self.plan and self.plan.tasks)))
        self.go_btn.setText(tr("Stop") if state == "copying" else tr("Back up"))
        for w in (self.dest_btn, self.layout_box, self.per_device, self.split, self.more_btn,
                  self.capture_box, self.shots_box, self.device_box):
            w.setEnabled(not busy)
        self.act_full.setEnabled(state == "ready" and bool(self.entries))
        if not busy:
            self.capture_box.setEnabled(self.layout_box.currentData() not in ("dcim", "flat"))
        has_dev = bool(self.dev) and not self.source
        self.act_repair.setEnabled(has_dev)
        self.retry_btn.setVisible(state in ("missing", "error"))

    def _show_dest(self):
        self.dest_label.setText(self.dest)
        self.dest_label.setToolTip(self.dest)

    def _options(self) -> sync.Options:
        folder = ""
        if self.per_device.isChecked():
            folder = sync.safe_name(self.dev.label) if self.dev else "iPhone"
        photos, videos = (tr("Photos"), tr("Videos")) if self.split.isChecked() else ("", "")
        shots = tr("Screenshots") if self.shots_box.isChecked() else ""
        return sync.Options(self.layout_box.currentData(), folder, photos, videos, shots,
                            self.capture_box.isChecked())

    def _show_example(self):
        o = self._options()
        t = time.mktime((2026, 11, 3, 14, 0, 0, 0, 0, -1))
        parts = [o.device_folder, o.photo_dir or o.screenshot_dir and "", sync.layout_dir(o.layout, t, "100APPLE"), "IMG_0001.HEIC"]
        self.example.setText(tr("Example") + ": " + "/".join(p for p in parts if p))

    # ------------------------------------------------------------ start / polling
    def start(self):
        if self.state == "copying":
            return
        if self.source:
            self.dev = device.Device("folder-" + sync.safe_name(self.source.name), self.source.name)
            self.title.setText(f"{tr('Folder')}: {self.source}")
            self.dcim = sync.find_dcim(self.source)
            self._scan()
            return
        fixed = device.broken_mounts()
        if fixed:
            device.release_mounts()
        miss = device.missing()
        if miss:
            self._set_state("missing", tr("Missing programs: {tools}.\nInstall them with:\n\n{cmd}",
                                         tools=", ".join(miss), cmd=device.install_command()))
            return
        text = tr("Connect your iPhone with a USB cable.")
        if fixed:
            text += "\n" + tr("Released a stuck iPhone folder: {where}", where=", ".join(fixed))
        self._set_state("none", text)
        self.poll_timer.start()
        self.poll()

    def poll(self):
        if self._polling or self._connecting:
            return
        self._polling = True
        self._call(device.list_devices, self._polled)

    def _polled(self, ids, _err):
        self._polling = False
        ids = ids or []
        self._update_devices(ids)
        if self.dev and self.dev.udid not in ids:
            self._device_gone()
            return
        if self.dev is None and ids:
            self.dev = device.Device(self._wanted if self._wanted in ids else ids[0])
            self._sync_device_box()
            self._connect()
        elif self.dev and self.state in ("locked", "trust", "nophotos", "error") and time.monotonic() >= self._retry_at:
            self._connect()

    def _update_devices(self, ids):
        for gone in [u for u in self.devices if u not in ids]:
            del self.devices[gone]
        for udid in ids:
            if udid not in self.devices:
                self.devices[udid] = ""
            if not self.devices[udid] and udid not in self._naming and len(ids) > 1:
                self._naming.add(udid)
                self._call(device.info, lambda d, err, u=udid: self._named(u, d), udid)
        self._sync_device_box()

    def _named(self, udid, dev):
        self._naming.discard(udid)
        if udid in self.devices and dev is not None:
            self.devices[udid] = dev.name or udid[:8]
            self._sync_device_box()

    def _sync_device_box(self):
        box = self.device_box
        items = [(u, n or u[:8]) for u, n in self.devices.items()]
        current = [(box.itemData(i), box.itemText(i)) for i in range(box.count())]
        if items != current:
            box.blockSignals(True)
            box.clear()
            for udid, name in items:
                box.addItem(name, udid)
            box.blockSignals(False)
        if self.dev:
            i = box.findData(self.dev.udid)
            if i >= 0:
                box.setCurrentIndex(i)
        box.setVisible(len(items) > 1 and not self.source)

    def _device_chosen(self, i):
        udid = self.device_box.itemData(i)
        if not udid or (self.dev and self.dev.udid == udid):
            return
        if self.worker or self._connecting:
            self._sync_device_box()   # not now: put the box back
            return
        self._wanted = udid
        if self.mount:
            device.unmount(self.mount)
        self.mount = self.dcim = self.entries = self.plan = None
        self._meta_cache = {}
        self.summary.clear()
        self.dev = device.Device(udid)
        self._connect()

    def _device_gone(self):
        if self.worker:
            self.worker.stop.set()
            self._gone_during_copy = True
        if self.mount:
            device.unmount(self.mount, lazy=True)
        self.dev = self.mount = self.dcim = self.entries = self.plan = None
        self._meta_cache = {}
        self.title.setText("DCIMDock")
        self.summary.clear()
        self.bar.setValue(0)
        self.bar.setFormat("")
        self.detail.setText(" ")
        self._set_state("none", tr("Connect your iPhone with a USB cable."))

    def _connect(self):
        self._connecting = True
        self._set_state("connecting", tr("Connecting…"))
        self._call(self._connect_blocking, self._connected, self.dev.udid)

    @staticmethod
    def _connect_blocking(udid):
        dev = device.info(udid)
        state, msg = device.pair(udid)
        if state != "ready":
            return dev, state, msg, None
        try:
            return dev, "ready", "", device.mount(udid)
        except device.NoPhotos as exc:
            return dev, "nophotos", str(exc), None
        except device.DeviceError as exc:
            return dev, "mount", str(exc), None

    def _connected(self, res, err):
        self._connecting = False
        if self.dev is None:      # unplugged meanwhile
            return
        if err:
            res = (self.dev, "error", str(err), None)
        dev, state, msg, mp = res
        if dev.name:
            self.dev = dev
        self.title.setText(self._device_title())
        self._retry_at = time.monotonic() + 3
        if state == "ready":
            self.mount = mp
            self.dcim = mp / "DCIM"
            self._scan()
        elif state == "locked":
            self._set_state("locked", tr("Unlock your iPhone."))
        elif state == "trust":
            self._set_state("trust", tr("Unlock your iPhone and tap “Trust”, then enter your passcode."))
        elif state == "denied":
            self._set_state("denied", tr("You tapped “Don’t Trust”. Unplug the iPhone and plug it in again."))
        elif state == "nophotos":
            self._set_state("nophotos", tr("The photos are not visible yet. Unlock your iPhone. (If it has no photos at all, this stays.)"))
        elif state == "gone":
            self._device_gone()
        elif state == "mount":
            self._set_state("error", tr("Could not open the photos: {msg}", msg=_short(msg)))
        else:
            self._set_state("error", tr("The iPhone does not answer: {msg}", msg=_short(msg)))

    def _device_title(self) -> str:
        d = self.dev
        bits = [b for b in (d.product, f"iOS {d.ios}" if d.ios else "") if b]
        return d.label + (f"  ({', '.join(bits)})" if bits else "")

    # ------------------------------------------------------------ scan / plan
    def _scan(self):
        self._set_state("scanning", tr("Reading the photo list…"))
        self.summary.clear()
        self._call(sync.scan, self._scanned, self.dcim)

    def _scanned(self, entries, err):
        if self.dev is None:
            return
        if err:
            self._set_state("error", tr("Could not open the photos: {msg}", msg=_short(str(err))))
            return
        self.entries = entries
        self._replan()

    def _replan(self):
        if self.entries is None or self.dev is None:
            return
        self._set_state("scanning", tr("Reading the photo list…"))
        root = Path(self.dest)
        opts = self._options()
        udid = self.dev.udid
        self._plan_gen += 1
        gen = self._plan_gen
        self._call(lambda: self._plan_blocking(root, udid, opts),
                   lambda res, err: self._planned(res, err) if gen == self._plan_gen else None)

    def _plan_blocking(self, root, udid, opts):
        index = sync.Index(root, udid)
        need = sync.needs_meta(self.entries, index, opts)
        meta = sync.read_meta(self.dcim, need, self._meta_cache, self.meta_sig.step.emit) if need else None
        return index, sync.make_plan(self.entries, index, opts, meta)

    def _meta_step(self, i, n):
        if self.state == "scanning":
            self.status.setText(tr("Reading capture dates… {i} of {n}", i=num(i), n=num(n)))

    def _planned(self, res, err):
        if self.dev is None:
            return
        if err:
            self._set_state("error", str(err))
            return
        self.index, self.plan = res
        self._show_example()
        p = self.plan
        known = p.known + len(p.adopted)
        if not self.entries:
            text = tr("No photos on the iPhone.")
        elif not p.tasks:
            text = tr("Everything is saved ({k} files).", k=num(known))
        else:
            text = tr("{n} new files ({size}) · {k} already saved" if len(p.tasks) != 1 else "1 new file ({size}) · {k} already saved",
                      n=num(len(p.tasks)), size=size(p.bytes), k=num(known))
        self.summary.setText(f"<b>{text}</b>")
        if p.tasks:
            ok, free = sync.free_space_ok(Path(self.dest), p.bytes)
            if not ok:
                self.summary.setText(f"<b>{text}</b><br><span style='color:#c0392b'>"
                                     + tr("Only {free} free in the backup folder, {need} needed.",
                                          free=size(free), need=size(p.bytes + sync.SPACE_RESERVE))
                                     + "</span>")
        self.bar.setValue(0)
        self.bar.setFormat("")
        self._set_state("ready", tr("Ready.") if not self.source else str(self.dcim))
        if p.tasks and not sync.free_space_ok(Path(self.dest), p.bytes)[0]:
            self.go_btn.setEnabled(False)

    def _options_changed(self, *_):
        self.settings.setValue("layout", self.layout_box.currentData())
        self.settings.setValue("per_device", self.per_device.isChecked())
        self.settings.setValue("split", self.split.isChecked())
        self.settings.setValue("capture_date", self.capture_box.isChecked())
        self.settings.setValue("screenshots", self.shots_box.isChecked())
        self._show_example()
        self._replan()

    def choose_dest(self):
        d = QFileDialog.getExistingDirectory(self, tr("Choose the backup folder"), self.dest)
        if d:
            self.dest = d
            self.settings.setValue("dest", d)
            self._show_dest()
            self._replan()

    def open_dest(self):
        Path(self.dest).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.dest))

    # ------------------------------------------------------------ copying
    def go_or_stop(self):
        if self.worker:
            self.worker.stop.set()
            self.go_btn.setEnabled(False)
            self.detail.setText(tr("Stopping…"))
            return
        if not self.plan or not self.plan.tasks:
            return
        self._start_copy(self.plan, self.index)

    def _start_copy(self, plan, index):
        index.root.mkdir(parents=True, exist_ok=True)
        self._gone_during_copy = False
        self._copy_plan, self._copy_index = plan, index
        self.total = plan.bytes
        self.count = len(plan.tasks)
        self.t0 = time.monotonic()
        self.speed = 0.0
        self._speed_mark = (self.t0, 0)
        self.bar.setValue(0)
        self.bar.setFormat("0 %")
        self.detail.setText(tr("Preparing…"))
        self.worker = SyncThread(self, plan, self.dcim, index)
        self.worker.progress.connect(self._progress)
        self.worker.file_done.connect(self._file_done)
        self.worker.result.connect(self._finished)
        self._set_state("copying", tr("Backing up – keep the iPhone connected and unlocked."))
        if self.preview_box.isChecked():
            self.preview_timer.start()
        self.worker.start()

    def _progress(self, done, i):
        frac = done / self.total if self.total else 1.0
        self.bar.setValue(int(frac * 1000))
        self.bar.setFormat(f"{frac * 100:.0f} %")
        now = time.monotonic()
        t_mark, b_mark = self._speed_mark
        if now - t_mark >= 1.0:
            inst = (done - b_mark) / (now - t_mark)
            self.speed = inst if self.speed == 0 else 0.7 * self.speed + 0.3 * inst
            self._speed_mark = (now, done)
        task = self._copy_plan.tasks[min(i, self.count) - 1]
        text = tr("File {i} of {n} · {name}", i=num(i), n=num(self.count), name=task.entry.name)
        if self.speed > 0:
            left = (self.total - done) / self.speed
            text += "  ·  " + tr("{speed}/s · {left} left", speed=size(self.speed), left=duration(left))
        self.detail.setText(text)

    def _file_done(self, path: str):
        self._preview_want = path

    def _finished(self, res: sync.Result):
        self.worker.wait()
        self.worker.deleteLater()
        self.worker = None
        self.preview_timer.stop()
        self._preview_tick()
        if self._quit_after_stop:
            self.close()
            return
        frac = 1.0 if not res.cancelled else (self.bar.value() / 1000)
        self.bar.setValue(int(frac * 1000))
        self.bar.setFormat(f"{frac * 100:.0f} %")
        self.detail.setText(" ")
        QApplication_alert(self)
        self._report(res)
        if self.dev is not None:
            self._replan()

    def _report(self, res: sync.Result):
        parts = []
        if res.cancelled:
            parts.append(tr("The iPhone was unplugged during the backup.") if self._gone_during_copy
                         else tr("Stopped after {n} files. Next time it continues where it stopped.",
                                 n=num(res.copied)))
        else:
            parts.append(tr("{n} files saved ({size}) in {time}.",
                            n=num(res.copied), size=size(res.bytes), time=duration(res.seconds)))
        if res.failed:
            lines = "\n".join(f"  {rel}: {why}" for rel, why in res.failed[:8])
            more = "\n  …" if len(res.failed) > 8 else ""
            parts.append(tr("{n} files could not be read:", n=num(len(res.failed))) + "\n" + lines + more)
        if self.entries and self._copy_index:
            a, b, k = sync.saved_range(self.entries, self._copy_index)
            if a is not None:
                parts.append(tr("From this iPhone, {k} files taken between {a} and {b} are safe on this computer.",
                                k=num(k), a=date(a), b=date(b)))
        if not self.source:
            parts.append(tr("DCIMDock does not delete anything on the iPhone. To free up space, delete the photos in the Photos app and empty “Recently Deleted”. With iCloud Photos turned on, this deletes them from iCloud and all your devices too."))
        box = QMessageBox(QMessageBox.Warning if (res.failed or res.cancelled) else QMessageBox.Information,
                          tr("Backup stopped") if res.cancelled else tr("Backup finished"),
                          "\n\n".join(parts), QMessageBox.Ok, self)
        open_btn = box.addButton(tr("Open folder"), QMessageBox.ActionRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self.open_dest()

    # ------------------------------------------------------------ more menu
    def full_copy(self):
        if self.worker or self.state == "fixing":
            return
        if not self.entries or not self.dev:
            return
        stamp = time.strftime("%Y-%m-%d %H-%M")
        root = Path(self.dest) / f"{tr('Full copy')} {stamp}"
        udid, opts = self.dev.udid, self._options()
        self._set_state("scanning", tr("Reading the photo list…"))
        self._call(lambda: self._plan_blocking(root, udid, opts), self._full_planned)

    def _full_planned(self, res, err):
        if self.dev is None:
            return
        self._set_state("ready", tr("Ready.") if not self.source else str(self.dcim))
        if err or res is None:
            return
        index, plan = res
        root = index.root
        ok, free = sync.free_space_ok(Path(self.dest), plan.bytes)
        text = tr("Copies all {n} files ({size}) from the iPhone into a new folder, without comparing with earlier backups:\n\n{folder}\n\nThe normal backup is not touched.",
                  n=num(len(plan.tasks)), size=size(plan.bytes), folder=root)
        if not ok:
            QMessageBox.warning(self, tr("Copy everything again"), text + "\n\n" + tr(
                "Only {free} free in the backup folder, {need} needed.",
                free=size(free), need=size(plan.bytes + sync.SPACE_RESERVE)))
            return
        ask = QMessageBox(QMessageBox.Question, tr("Copy everything again"), text, QMessageBox.NoButton, self)
        go = ask.addButton(tr("Copy everything"), QMessageBox.AcceptRole)
        ask.addButton(tr("Cancel"), QMessageBox.RejectRole)
        ask.exec()
        if ask.clickedButton() is go:
            self._start_copy(plan, index)

    def verify(self):
        if self.worker or self.state == "fixing":
            return
        root = Path(self.dest)
        files = sorted((root / sync.INDEX_DIR).glob("*.json"))
        if not files:
            QMessageBox.information(self, tr("Check the backup"), tr("There is no backup in {folder} yet.", folder=root))
            return
        self._set_state("fixing", tr("Reading every saved file again and comparing it with its checksum…"))
        self.go_btn.setEnabled(False)
        th = VerifyThread(self, root, files)
        th.progress.connect(lambda i, n: (self.bar.setValue(int(i * 1000 / max(n, 1))),
                                          self.bar.setFormat(f"{i * 100 // max(n, 1)} %"),
                                          self.detail.setText(tr("File {i} of {n}", i=num(i), n=num(n)))))

        def done():
            res = th.res
            th.deleteLater()
            self.detail.setText(" ")
            if self.entries is not None:
                self._replan()
            else:
                self._set_state("none", tr("Connect your iPhone with a USB cable."))
            lines = [tr("{n} files are intact ({size}).", n=num(res.ok), size=size(res.bytes))]
            for title, items in ((tr("Missing:"), res.missing), (tr("Changed or damaged:"), res.changed)):
                if items:
                    lines.append(title + "\n" + "\n".join("  " + x for x in items[:15]) + ("\n  …" if len(items) > 15 else ""))
            if res.missing or res.changed:
                lines.append(tr("Missing files are copied again on the next backup, as long as they are still on the iPhone."))
            QMessageBox(QMessageBox.Warning if (res.missing or res.changed) else QMessageBox.Information,
                        tr("Check the backup"), "\n\n".join(lines), QMessageBox.Ok, self).exec()
        th.finished.connect(done)
        th.start()

    def _fix(self, fn, after, *args):
        if self.worker or self.state == "fixing":
            return
        self.poll_timer.stop()
        if self.mount:
            device.unmount(self.mount, lazy=True)
        self.dev = self.mount = self.dcim = self.entries = self.plan = None
        self.title.setText("DCIMDock")
        self.summary.clear()
        self._set_state("fixing", tr("Working…"))
        self._call(fn, lambda res, err: (after(res, err), self.start()), *args)

    def fix_mounts(self):
        def after(res, err):
            QMessageBox.information(self, tr("Troubleshooting"), tr("Released: {where}", where=", ".join(res)) if res
                                    else tr("No iPhone folder was mounted."))
        self._fix(device.release_mounts, after)

    def fix_pairing(self):
        if not self.dev:
            return
        udid = self.dev.udid

        def after(res, err):
            state = res[0] if res else "error"
            QMessageBox.information(self, tr("Troubleshooting"), tr("Paired again.") if state == "ready" else
                                    tr("Unlock your iPhone and tap “Trust”, then enter your passcode."))
        self._fix(device.repair_pairing, after, udid)

    def fix_usbmuxd(self):
        def after(res, err):
            ok, msg = res if res else (False, str(err))
            QMessageBox.information(self, tr("Troubleshooting"), tr("The iPhone service was restarted. Unplug the iPhone and plug it in again.")
                                    if ok else tr("Could not restart the service: {msg}", msg=_short(msg) or "-"))
        self._fix(device.restart_usbmuxd, after)

    def show_diagnosis(self):
        self.setCursor(Qt.WaitCursor)
        self._call(device.diagnose, lambda res, err: (self.unsetCursor(), DiagDialog(self, res or str(err)).exec()))

    # ------------------------------------------------------------ preview
    def _preview_toggled(self, on: bool):
        self.settings.setValue("preview", on)
        self.preview.setVisible(on)
        self.preview_caption.setVisible(on)
        if on and self.worker:
            self.preview_timer.start()
        elif not on:
            self.preview_timer.stop()
            self.preview.clear()
            self.preview_caption.setText(" ")
            self.resize(self.width(), self.minimumSizeHint().height())

    def _preview_tick(self):
        want = self._preview_want
        if not want or want == self._preview_shown or self._preview_busy or not self.preview_box.isChecked():
            return
        self._preview_shown = want
        kind = sync.is_media(want)
        if kind == "image":
            self._preview_busy = True
            self.pool.start(Decode(want, self.decoded))
        elif kind == "video":
            self.preview.setPixmap(QPixmap())
            self.preview.setText("▶  " + tr("Video"))
            self.preview_caption.setText(Path(want).name)

    def _preview_ready(self, path: str, img):
        self._preview_busy = False
        if not self.preview_box.isChecked():
            return
        if img is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(Path(path).suffix.upper().lstrip("."))
        else:
            self.preview.setPixmap(QPixmap.fromImage(img))
        self.preview_caption.setText(Path(path).name)

    # ------------------------------------------------------------ intro / close
    def show_intro(self, first: bool):
        dlg = IntroDialog(self, show_checkbox=first)
        dlg.exec()
        if first and dlg.hide_box.isChecked():
            self.settings.setValue("hide_intro", True)

    def closeEvent(self, ev):
        if self.worker:
            ask = QMessageBox(QMessageBox.Question, "DCIMDock", tr("A backup is running. Stop it and quit?"),
                              QMessageBox.NoButton, self)
            stop = ask.addButton(tr("Stop and quit"), QMessageBox.DestructiveRole)
            ask.addButton(tr("Cancel"), QMessageBox.RejectRole)
            ask.exec()
            if ask.clickedButton() is stop:
                self._quit_after_stop = True
                self.worker.stop.set()
            ev.ignore()
            return
        self.poll_timer.stop()
        self.preview_timer.stop()
        self.pool.waitForDone(3000)
        for c in list(self._calls):
            c.wait(3000)
        if self.mount:
            device.unmount(self.mount)
        super().closeEvent(ev)


def QApplication_alert(win):
    from PySide6.QtWidgets import QApplication
    QApplication.alert(win)


def _short(msg: str) -> str:
    msg = " ".join(msg.split())
    return msg if len(msg) < 200 else msg[:200] + " …"
