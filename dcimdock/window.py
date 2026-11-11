"""The main window: device status, destination, progress bar, optional preview."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, QStandardPaths, Qt, QThread, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QRadioButton, QSizePolicy,
    QTextBrowser, QVBoxLayout, QWidget,
)

from . import device, sync
from .i18n import date, duration, num, size, tr
from .icon import app_icon

PREVIEW = QSize(360, 240)


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
        self.sink.ready.emit(self.path, None if img.isNull() else img)


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
        col.addWidget(self.title)
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
        sort_row.addWidget(QLabel(tr("Sort") + ":"))
        self.by_date = QRadioButton(tr("By date (2026/2026-11)"))
        self.by_dcim = QRadioButton(tr("Like on the iPhone (100APPLE …)"))
        grp = QButtonGroup(self)
        grp.addButton(self.by_date)
        grp.addButton(self.by_dcim)
        sort_row.addWidget(self.by_date)
        sort_row.addWidget(self.by_dcim)
        sort_row.addStretch(1)
        lay.addLayout(sort_row)

        opt_row = QHBoxLayout()
        self.per_device = QCheckBox(tr("Own folder per iPhone"))
        self.preview_box = QCheckBox(tr("Preview"))
        opt_row.addWidget(self.per_device)
        opt_row.addWidget(self.preview_box)
        opt_row.addStretch(1)
        lay.addLayout(opt_row)

        s = self.settings
        self.dest = s.value("dest", default_dest())
        (self.by_dcim if s.value("layout", "date") == "dcim" else self.by_date).setChecked(True)
        self.per_device.setChecked(s.value("per_device", True, type=bool))
        self.preview_box.setChecked(s.value("preview", True, type=bool))
        self._show_dest()
        self.by_date.toggled.connect(self._options_changed)
        self.per_device.toggled.connect(self._options_changed)
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
        self.retry_btn = QPushButton(tr("Check again"))
        self.retry_btn.clicked.connect(self.start)
        self.retry_btn.hide()
        self.go_btn = QPushButton(tr("Back up"))
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self.go_or_stop)
        btns.addWidget(self.open_btn)
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
        busy = state in ("connecting", "scanning", "copying")
        self.go_btn.setEnabled(state == "copying" or (state == "ready" and bool(self.plan and self.plan.tasks)))
        self.go_btn.setText(tr("Stop") if state == "copying" else tr("Back up"))
        for w in (self.dest_btn, self.by_date, self.by_dcim, self.per_device):
            w.setEnabled(not busy)
        self.retry_btn.setVisible(state in ("missing", "error"))

    def _show_dest(self):
        self.dest_label.setText(self.dest)
        self.dest_label.setToolTip(self.dest)

    def _options(self) -> sync.Options:
        folder = ""
        if self.per_device.isChecked() and self.dev:
            folder = sync.safe_name(self.dev.label)
        return sync.Options("dcim" if self.by_dcim.isChecked() else "date", folder)

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
        miss = device.missing()
        if miss:
            self._set_state("missing", tr("Missing programs: {tools}.\nInstall them with:\n\n{cmd}",
                                         tools=", ".join(miss), cmd=device.install_command()))
            return
        self._set_state("none", tr("Connect your iPhone with a USB cable."))
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
        if self.dev and self.dev.udid not in ids:
            self._device_gone()
            return
        if self.dev is None and ids:
            self.dev = device.Device(ids[0])
            self._connect()
        elif self.dev and self.state in ("locked", "trust", "error") and time.monotonic() >= self._retry_at:
            self._connect()

    def _device_gone(self):
        if self.worker:
            self.worker.stop.set()
            self._gone_during_copy = True
        if self.mount:
            device.unmount(self.mount, lazy=True)
        self.dev = self.mount = self.dcim = self.entries = self.plan = None
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
        self._call(lambda: self._plan_blocking(root, udid, opts), self._planned)

    def _plan_blocking(self, root, udid, opts):
        index = sync.Index(root, udid)
        return index, sync.make_plan(self.entries, index, opts)

    def _planned(self, res, err):
        if self.dev is None:
            return
        if err:
            self._set_state("error", str(err))
            return
        self.index, self.plan = res
        p = self.plan
        known = p.known + len(p.adopted)
        if not self.entries:
            text = tr("No photos on the iPhone.")
        elif not p.tasks:
            text = tr("Everything is saved ({k} files).", k=num(known))
        else:
            text = tr("{n} new files ({size}) · {k} already saved",
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
        self.settings.setValue("layout", "dcim" if self.by_dcim.isChecked() else "date")
        self.settings.setValue("per_device", self.per_device.isChecked())
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
        Path(self.dest).mkdir(parents=True, exist_ok=True)
        self._gone_during_copy = False
        self.total = self.plan.bytes
        self.count = len(self.plan.tasks)
        self.t0 = time.monotonic()
        self.speed = 0.0
        self._speed_mark = (self.t0, 0)
        self.bar.setValue(0)
        self.bar.setFormat("0 %")
        self.detail.setText(tr("Preparing…"))
        self.worker = SyncThread(self, self.plan, self.dcim, self.index)
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
        task = self.plan.tasks[min(i, self.count) - 1]
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
        if self.entries and self.index:
            a, b, k = sync.saved_range(self.entries, self.index)
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
