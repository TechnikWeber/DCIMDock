"""The main window: device status, destination, progress bar, optional preview."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QDate, QDir, QObject, QRunnable, QSettings, QSize, QStandardPaths, Qt, QThread,
                            QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QSystemTrayIcon, QProgressBar, QPushButton,
    QSizePolicy, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

import tempfile

from . import __version__, autostart, jpeg, library, sync, update
from .backend import device
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

    def __init__(self, parent, plan, dcim, index, jpeg=False):
        super().__init__(parent)
        self.plan, self.dcim, self.index, self.jpeg = plan, dcim, index, jpeg
        self.stop = threading.Event()
        self._last = 0.0

    def _progress(self, done, i, _task):
        now = time.monotonic()
        if now - self._last >= 0.1:
            self._last = now
            self.progress.emit(done, i)

    def run(self):
        res = sync.run(self.plan, self.dcim, self.index, self._progress,
                       lambda t, p: self.file_done.emit(str(p)), self.stop.is_set, self.jpeg)
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


PRESET_LABELS = [
    ("all", "Any date"),
    ("7d", "Last 7 days"),
    ("30d", "Last 30 days"),
    ("90d", "Last 90 days"),
    ("year", "This year"),
    ("lastyear", "Last year"),
    ("custom", "From … to …"),
]


def _qdate_time(d: QDate) -> float:
    return time.mktime((d.year(), d.month(), d.day(), 12, 0, 0, 0, 0, -1))


class DateChoice(QWidget):
    """'Order by: date taken | date saved' – an either/or instead of a checkbox.

    Keeps the checkbox interface (isChecked = by capture date), so the rest
    of the window did not have to change.
    """
    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(tr("Order by") + ":"))
        self.combo = QComboBox()
        self.combo.addItem(tr("Date taken"), True)
        self.combo.setItemData(0, tr("The time the camera wrote into the photo or video (EXIF). "
                                     "Pictures without it, e.g. from WhatsApp, use the date saved."), Qt.ToolTipRole)
        self.combo.addItem(tr("Date saved"), False)
        self.combo.setItemData(1, tr("When the file was saved on the iPhone: for pictures saved from apps or "
                                     "the web the day they were saved; after restoring the iPhone it can be that day."),
                               Qt.ToolTipRole)
        self.combo.currentIndexChanged.connect(lambda _: self.toggled.emit(self.isChecked()))
        row.addWidget(self.combo)
        self.setToolTip(tr("Decides the date folder, the period in “Copy” and the time in file names."))

    def isChecked(self) -> bool:
        return bool(self.combo.currentData())

    def setChecked(self, on: bool):
        self.combo.setCurrentIndex(0 if on else 1)


class SelectionChoice:
    """What the selection dialog stores: a preset plus the custom days, so
    "last 30 days" stays relative to today."""

    KINDS = ("photos", "videos", "screenshots", "live", "edits")
    BETA = {"skip_trashed": True, "skip_hidden": False, "favorites_only": False}

    def __init__(self, settings: QSettings | None = None):
        self.preset = "all"
        today = QDate.currentDate()
        self.first = today.addMonths(-1)
        self.last = today
        self.flags = {k: True for k in self.KINDS}
        self.beta = False
        self.beta_flags = dict(self.BETA)
        self.albums: set[str] = set()
        if settings is not None:
            self.beta = settings.value("beta", False, type=bool)
            for k, default in self.BETA.items():
                self.beta_flags[k] = settings.value(f"sel_{k}", default, type=bool)
            raw = settings.value("sel_albums", [])
            self.albums = set([raw] if isinstance(raw, str) and raw else raw or [])
            self.preset = settings.value("sel_preset", "all")
            if self.preset not in sync.PRESETS:
                self.preset = "all"
            for attr, key in (("first", "sel_from"), ("last", "sel_to")):
                d = QDate.fromString(str(settings.value(key, "")), Qt.ISODate)
                if d.isValid():
                    setattr(self, attr, d)
            for k in self.KINDS:
                self.flags[k] = settings.value(f"sel_{k}", True, type=bool)

    def save(self, settings: QSettings):
        settings.setValue("sel_preset", self.preset)
        settings.setValue("sel_from", self.first.toString(Qt.ISODate))
        settings.setValue("sel_to", self.last.toString(Qt.ISODate))
        for k in self.KINDS:
            settings.setValue(f"sel_{k}", self.flags[k])
        for k in self.BETA:
            settings.setValue(f"sel_{k}", self.beta_flags[k])
        settings.setValue("sel_albums", sorted(self.albums))

    def selection(self) -> sync.Selection:
        a, b = sync.date_range(self.preset, custom=(_qdate_time(self.first), _qdate_time(self.last)))
        extra = dict(self.beta_flags, albums=frozenset(self.albums)) if self.beta else {}
        return sync.Selection(a, b, **self.flags, **extra)

    def describe(self) -> str:
        sel = self.selection()
        tail = " " + tr("(without “Recently Deleted”)") if sel.skip_trashed else ""
        if not sel.active:
            return tr("Everything") + tail
        bits = []
        if self.preset == "custom":
            bits.append(f"{date(_qdate_time(self.first))} – {date(_qdate_time(self.last))}")
        elif self.preset != "all":
            bits.append(tr(dict(PRESET_LABELS)[self.preset]))
        kinds = [tr(n) for k, n in (("photos", "Photos"), ("videos", "Videos"), ("screenshots", "Screenshots"))
                 if self.flags[k]]
        if len(kinds) < 3:
            bits.append(tr("only {what}", what=", ".join(kinds)))
        if not self.flags["live"]:
            bits.append(tr("without Live Photo videos"))
        if not self.flags["edits"]:
            bits.append(tr("without edits"))
        if sel.skip_hidden:
            bits.append(tr("without hidden"))
        if sel.favorites_only:
            bits.append(tr("only favorites"))
        if sel.albums:
            bits.append(tr("albums: {names}", names=", ".join(sorted(sel.albums, key=str.casefold))))
        return " · ".join(bits) + tail

    def folder_label(self) -> str:
        """Part of the folder name for "copy the selection into a new folder"."""
        a, b = self.selection().date_from, self.selection().date_to
        if a is None and b is None:
            return ""
        fa = time.strftime("%Y-%m-%d", time.localtime(a)) if a is not None else "…"
        fb = time.strftime("%Y-%m-%d", time.localtime(b - 1)) if b is not None else "…"
        return f"{fa} {tr('to')} {fb}"


class SelectionDialog(QDialog):
    def __init__(self, parent, choice: SelectionChoice, capture_date: bool, albums=None):
        super().__init__(parent)
        self.setWindowTitle(tr("What to copy"))
        self.beta = choice.beta
        lay = QVBoxLayout(self)

        when = QGroupBox(tr("Date"))
        form = QFormLayout(when)
        self.preset = QComboBox()
        for key, label in PRESET_LABELS:
            self.preset.addItem(tr(label), key)
        self.preset.setCurrentIndex(max(0, self.preset.findData(choice.preset)))
        form.addRow(tr("Period") + ":", self.preset)
        self.first = QDateEdit(choice.first)
        self.last = QDateEdit(choice.last)
        for w in (self.first, self.last):
            w.setCalendarPopup(True)
            w.setMaximumDate(QDate.currentDate().addYears(1))
        days = QHBoxLayout()
        days.addWidget(self.first)
        days.addWidget(QLabel(tr("to")))
        days.addWidget(self.last)
        days.addStretch(1)
        form.addRow(tr("From") + ":", days)
        basis = QLabel(tr("Uses the date the photo was taken (EXIF), else the file date.") if capture_date
                       else tr("Uses the date saved (“Order by” in the window)."))
        basis.setWordWrap(True)
        basis.setStyleSheet("color: palette(placeholder-text);")
        form.addRow(basis)
        lay.addWidget(when)

        what = QGroupBox(tr("Kinds"))
        col = QVBoxLayout(what)
        self.boxes = {}
        for key, label, tip in (
            ("photos", "Photos", "Pictures from the camera and saved pictures."),
            ("videos", "Videos", "Videos of their own. The short video of a Live Photo is set below."),
            ("screenshots", "Screenshots", "Recognised by the “Screenshot” mark iOS writes into them."),
            ("live", "Live Photo videos (.MOV next to the photo)", "Off: only the still image of a Live Photo."),
            ("edits", "Edits (IMG_E… and .AAE files)", "The edited version and the file with the edit steps. The original is always copied."),
        ):
            b = QCheckBox(tr(label))
            b.setToolTip(tr(tip))
            b.setChecked(choice.flags[key])
            col.addWidget(b)
            self.boxes[key] = b
        lay.addWidget(what)

        self.beta_boxes = {}
        self.album_list = None
        if self.beta:
            lib = QGroupBox(tr("Photos library (beta)"))
            col = QVBoxLayout(lib)
            for key, label in (("skip_trashed", "Leave out “Recently Deleted”"),
                               ("skip_hidden", "Leave out hidden photos"),
                               ("favorites_only", "Only favorites")):
                b = QCheckBox(tr(label))
                b.setChecked(choice.beta_flags[key])
                col.addWidget(b)
                self.beta_boxes[key] = b
            known = sorted(set(albums or []) | choice.albums, key=str.casefold)
            if known:
                col.addWidget(QLabel(tr("Only from these albums (none ticked: any):")))
                self.album_list = QListWidget()
                self.album_list.setMaximumHeight(140)
                for name in known:
                    it = QListWidgetItem(name)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked if name in choice.albums else Qt.Unchecked)
                    self.album_list.addItem(it)
                col.addWidget(self.album_list)
            else:
                hint = QLabel(tr("Your albums appear here once an iPhone is connected."))
                hint.setStyleSheet("color: palette(placeholder-text);")
                col.addWidget(hint)
            lay.addWidget(lib)

        note = QLabel(tr("Files that are already saved are never copied again. What is left out stays on the iPhone and can be copied later."))
        note.setWordWrap(True)
        lay.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Reset)
        buttons.button(QDialogButtonBox.Reset).setText(tr("Everything"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._reset)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons
        lay.addWidget(buttons)

        self._old_beta, self._old_albums = dict(choice.beta_flags), set(choice.albums)
        self.preset.currentIndexChanged.connect(self._update)
        for b in self.boxes.values():
            b.toggled.connect(self._update)
        self.first.dateChanged.connect(self._update)
        self.last.dateChanged.connect(self._update)
        self._update()

    def _reset(self):
        self.preset.setCurrentIndex(0)
        for b in self.boxes.values():
            b.setChecked(True)
        for k, b in self.beta_boxes.items():
            b.setChecked(SelectionChoice.BETA[k])
        if self.album_list:
            for i in range(self.album_list.count()):
                self.album_list.item(i).setCheckState(Qt.Unchecked)

    def _update(self, *_):
        custom = self.preset.currentData() == "custom"
        self.first.setEnabled(custom)
        self.last.setEnabled(custom)
        kinds = any(self.boxes[k].isChecked() for k in ("photos", "videos", "screenshots"))
        order = not custom or self.first.date() <= self.last.date()
        self.boxes["live"].setEnabled(self.boxes["photos"].isChecked() or self.boxes["screenshots"].isChecked())
        self.boxes["edits"].setEnabled(kinds)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(kinds and order)

    def _accept(self):
        self.choice = SelectionChoice()
        self.choice.preset = self.preset.currentData()
        self.choice.first, self.choice.last = self.first.date(), self.last.date()
        self.choice.flags = {k: b.isChecked() for k, b in self.boxes.items()}
        self.choice.beta = self.beta
        self.choice.beta_flags = {k: b.isChecked() for k, b in self.beta_boxes.items()} or dict(self._old_beta)
        self.choice.albums = ({self.album_list.item(i).text() for i in range(self.album_list.count())
                               if self.album_list.item(i).checkState() == Qt.Checked}
                              if self.album_list else set(self._old_albums))
        self.accept()


class SettingsDialog(QDialog):
    """Options that are set once and then left alone."""

    def __init__(self, parent, settings: QSettings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Settings"))
        lay = QVBoxLayout(self)

        files = QGroupBox(tr("Files"))
        col = QVBoxLayout(files)
        self.rename = QCheckBox(tr("Name files by the time they were taken"))
        self.rename.setToolTip(tr("2026-11-03_14-22-05_IMG_0001.HEIC instead of IMG_0001.HEIC: every program sorts them by time, and a new IMG_0001 never meets an old one."))
        col.addWidget(self.rename)
        col.addWidget(self._hint(tr("Example: 2026-11-03_14-22-05_IMG_0001.HEIC")))
        self.jpeg = QCheckBox(tr("Also save a JPEG next to every HEIC photo"))
        self.jpeg.setToolTip(tr("IMG_0001.HEIC stays as it is, IMG_0001.jpg is added for programs that cannot open HEIC."))
        col.addWidget(self.jpeg)
        self.jpeg_hint = self._hint("")
        col.addWidget(self.jpeg_hint)
        lay.addWidget(files)

        auto = QGroupBox(tr("Automatic"))
        col = QVBoxLayout(auto)
        self.auto = QCheckBox(tr("Back up automatically when an iPhone is plugged in"))
        self.auto.setToolTip(tr("Uses the folder, the folders and the selection set in the window. Closing the window keeps DCIMDock running next to the clock."))
        col.addWidget(self.auto)
        self.login = QCheckBox(tr("Start in the background when I log in"))
        col.addWidget(self.login)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            col.addWidget(self._hint(tr("This desktop shows no tray icons: DCIMDock then only works while its window is open.")))
        lay.addWidget(auto)

        other = QGroupBox(tr("Other"))
        col = QVBoxLayout(other)
        self.updates = QCheckBox(tr("Check for new versions (once a day, asks GitHub)"))
        upd_row = QHBoxLayout()
        upd_row.addWidget(self.updates, 1)
        self.check_now = QPushButton(tr("Check now"))
        self.check_now.setToolTip(tr("Installed: {v}", v=__version__))
        # updating quits DCIMDock: keep what was set here first
        self.check_now.clicked.connect(lambda: parent.check_update_now(self, before_update=self._accept))
        upd_row.addWidget(self.check_now)
        col.addLayout(upd_row)
        lay.addWidget(other)
        beta = QGroupBox(tr("Beta features"))
        col = QVBoxLayout(beta)
        self.beta = QCheckBox(tr("Read the iPhone's Photos library"))
        col.addWidget(self.beta)
        col.addWidget(self._hint(tr("Leaves out “Recently Deleted”, warns about photos that are only in iCloud, and adds hidden photos, favorites and albums to “What to copy”. Still new: if the library cannot be read, DCIMDock works as without it.")))
        lay.addWidget(beta)

        self.rename.setChecked(settings.value("rename", False, type=bool))
        self._jpeg_known(jpeg.known())
        if jpeg.known() is None:    # still loading (slow once on Windows): do not freeze the dialog
            self.jpeg_hint.setText(tr("Checking the HEIC converter…"))
            # the main window owns the thread, so quitting waits for it
            parent._call(jpeg.available, lambda res, err: self._jpeg_known(res or ""))
        self.auto.setChecked(settings.value("auto_backup", False, type=bool))
        self.login.setChecked(autostart.is_enabled())
        self.updates.setChecked(settings.value("check_updates", True, type=bool))
        self.beta.setChecked(settings.value("beta", False, type=bool))
        self.auto.toggled.connect(self._auto_toggled)
        self.login.setEnabled(self.auto.isChecked())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _jpeg_known(self, how: str | None):
        self.jpeg.setEnabled(bool(how))
        self.jpeg.setChecked(bool(how) and self.settings.value("jpeg", False, type=bool))
        if how is None:
            return
        self.jpeg_hint.setText("" if how else tr("Needs a HEIC converter: {cmd}", cmd=jpeg.install_hint()))
        self.jpeg_hint.setVisible(not how)

    def _auto_toggled(self, on: bool):
        self.login.setEnabled(on)
        if not on:
            self.login.setChecked(False)

    @staticmethod
    def _hint(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setContentsMargins(24, 0, 0, 0)
        lab.setStyleSheet("color: palette(placeholder-text);")
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return lab

    def _accept(self):
        s = self.settings
        s.setValue("rename", self.rename.isChecked())
        if jpeg.known() is not None:    # else the box is only a placeholder: keep the setting
            s.setValue("jpeg", self.jpeg.isChecked())
        s.setValue("auto_backup", self.auto.isChecked())
        s.setValue("check_updates", self.updates.isChecked())
        s.setValue("beta", self.beta.isChecked())
        want = self.login.isChecked()
        if want != autostart.is_enabled():
            try:
                autostart.set_enabled(want)
            except OSError as exc:
                QMessageBox.warning(self, tr("Settings"), tr("Could not change the autostart: {msg}", msg=str(exc)))
        self.accept()


def native(path: str) -> str:
    return QDir.toNativeSeparators(path)


def default_dest() -> str:
    pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
    return str(Path(pics) / "iPhone")


class MainWindow(QMainWindow):
    def __init__(self, source: str | None = None, selftest: bool = False, background: bool = False):
        super().__init__()
        self.setWindowTitle("DCIMDock")
        self.setWindowIcon(app_icon())
        self.settings = QSettings("dcimdock", "dcimdock")
        self.source = Path(source).expanduser().resolve() if source else None
        self.selftest = selftest

        self.dev: device.Device | None = None
        self.mount = None      # mount point (Linux) or open AFC connection (Windows)
        self.dcim = None       # Path or sync source
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
        self.background = background
        self.tray: QSystemTrayIcon | None = None
        self._really_quit = False
        self._auto_run = False                # the running copy was started automatically
        self._auto_done: set[str] = set()     # udids backed up automatically since plugged in
        self._told: set[tuple[str, str]] = set()   # (udid, state) already shown as a tray message
        self._update: tuple[str, str] | None = None
        self.library: library.Library | None = None
        self.lib_error = ""

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

        self._setup_tray()
        QTimer.singleShot(0, self.start)
        if not selftest and not background and not self.settings.value("hide_intro", False, type=bool):
            QTimer.singleShot(300, lambda: self.show_intro(True))
        if not selftest and not source:
            QTimer.singleShot(4000, self._check_update)
        jpeg.warm_up()

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
        self.capture_box = DateChoice()
        self.shots_box = QCheckBox(tr("Screenshots apart"))
        opt_row2.addWidget(self.capture_box)
        opt_row2.addWidget(self.shots_box)
        opt_row2.addStretch(1)
        lay.addLayout(opt_row2)
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel(tr("Copy") + ":"))
        self.sel_label = QLabel()
        self.sel_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sel_row.addWidget(self.sel_label, 1)
        self.sel_btn = QPushButton(tr("Choose…"))
        self.sel_btn.setToolTip(tr("Only a period, only photos or videos, without Live Photo videos or edits."))
        self.sel_btn.clicked.connect(self.choose_selection)
        sel_row.addWidget(self.sel_btn)
        lay.addLayout(sel_row)
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
        self.choice = SelectionChoice(s)
        self._show_selection()
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
        self.act_full.setToolTip(tr("Uses the selection, if one is set."))
        self.act_verify = menu.addAction(tr("Check the backup…"), self.verify)
        menu.addSeparator()
        menu.addAction(tr("Settings…"), self.show_settings)
        menu.addAction(tr("Check for updates…"), self.check_update_now)
        fix = menu.addMenu(tr("Troubleshooting"))
        self.act_release = fix.addAction(tr("Release stuck iPhone folders"), self.fix_mounts)
        self.act_release.setVisible(device.HAS_MOUNTS)
        self.act_repair = fix.addAction(tr("Pair again (ask for Trust again)"), self.fix_pairing)
        self.act_usbmuxd = fix.addAction(tr(device.SERVICE_ACTION), self.fix_usbmuxd)
        fix.addSeparator()
        fix.addAction(tr("Diagnosis…"), self.show_diagnosis)
        self.more_btn.setMenu(menu)
        self.retry_btn = QPushButton(tr("Check again"))
        self.retry_btn.clicked.connect(self.start)
        self.retry_btn.hide()
        self.store_btn = QPushButton(tr("Open Microsoft Store"))
        self.store_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(device.INSTALL_URL)))
        self.store_btn.hide()
        self.svc_btn = QPushButton(tr("Start the iPhone service"))
        self.svc_btn.clicked.connect(self.start_service)
        self.svc_btn.hide()
        self.go_btn = QPushButton(tr("Back up"))
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self.go_or_stop)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.more_btn)
        self.update_label = QLabel()
        self.update_label.setOpenExternalLinks(True)
        self.update_label.hide()
        btns.addWidget(self.update_label)
        self.update_btn = QPushButton()
        self.update_btn.clicked.connect(self.update_itself)
        self.update_btn.hide()
        btns.addWidget(self.update_btn)
        btns.addStretch(1)
        btns.addWidget(self.store_btn)
        btns.addWidget(self.svc_btn)
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
                  self.capture_box, self.shots_box, self.device_box, self.sel_btn):
            w.setEnabled(not busy)
        self.act_full.setEnabled(state == "ready" and bool(self.entries))
        if not busy:
            self.capture_box.setEnabled(self._dates_matter())
        has_dev = bool(self.dev) and not self.source
        self.act_repair.setEnabled(has_dev)
        self.retry_btn.setVisible(state in ("missing", "error"))
        self.store_btn.setVisible(state == "missing" and bool(device.INSTALL_URL))
        self.svc_btn.setVisible(state == "missing" and bool(device.INSTALL_URL))

    def _show_dest(self):
        self.dest_label.setText(native(self.dest))
        self.dest_label.setToolTip(native(self.dest))

    def _options(self) -> sync.Options:
        folder = ""
        if self.per_device.isChecked():
            folder = sync.safe_name(self.dev.label) if self.dev else "iPhone"
        photos, videos = (tr("Photos"), tr("Videos")) if self.split.isChecked() else ("", "")
        shots = tr("Screenshots") if self.shots_box.isChecked() else ""
        return sync.Options(self.layout_box.currentData(), folder, photos, videos, shots,
                            self.capture_box.isChecked(), self.choice.selection(),
                            self.settings.value("rename", False, type=bool))

    def _dates_matter(self) -> bool:
        sel = self.choice.selection()
        return self.layout_box.currentData() not in ("dcim", "flat") or sel.date_from is not None or sel.date_to is not None

    def _show_selection(self):
        text = self.choice.describe()
        active = self.choice.selection().active
        self.sel_label.setText(f"<b>{text}</b>" if active else text)
        self.sel_label.setToolTip(text)

    def choose_selection(self):
        if self.worker:
            return
        dlg = SelectionDialog(self, self.choice, self.capture_box.isChecked(),
                              self.library.albums if self.library else None)
        if dlg.exec() == QDialog.Accepted:
            self.choice = dlg.choice
            self.choice.save(self.settings)
            self._show_selection()
            if not self.worker:
                self.capture_box.setEnabled(self._dates_matter())
            self._replan()

    def _show_example(self):
        o = self._options()
        t = time.mktime((2026, 11, 3, 14, 0, 0, 0, 0, -1))
        name = (sync.time_prefix(t) if o.rename else "") + "IMG_0001.HEIC"
        parts = [o.device_folder, o.photo_dir or o.screenshot_dir and "", sync.layout_dir(o.layout, t, "100APPLE"), name]
        self.example.setText(tr("Example") + ": " + os.sep.join(p.replace("/", os.sep) for p in parts if p))

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
        # unplugged: the next time it is plugged in counts as new
        self._auto_done &= set(ids)
        self._told = {k for k in self._told if k[0] in ids}
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
        self.mount = self.dcim = self.entries = self.plan = self.library = None
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
        self.dev = self.mount = self.dcim = self.entries = self.plan = self.library = None
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
            self.dcim = device.dcim_of(mp)
            self._scan()
        elif state == "locked":
            self._set_state("locked", tr("Unlock your iPhone."))
            self._tell("locked", tr("Unlock your iPhone."))
        elif state == "trust":
            self._set_state("trust", tr("Unlock your iPhone and tap “Trust”, then enter your passcode."))
            self._tell("trust", tr("Unlock your iPhone and tap “Trust”, then enter your passcode."))
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
        self._call(self._scan_blocking, self._scanned, self.dcim, self.choice.beta)

    @staticmethod
    def _scan_blocking(dcim, beta):
        entries = sync.scan(dcim)
        lib, why = None, ""
        if beta:
            try:
                with tempfile.TemporaryDirectory(prefix="dcimdock-") as tmp:
                    lib = library.read(sync.as_source(dcim), Path(tmp))
            except library.LibraryError as exc:
                why = str(exc) or "?"
        return entries, lib, why

    def _scanned(self, res, err):
        if self.dev is None:
            return
        if err:
            self._set_state("error", tr("Could not open the photos: {msg}", msg=_short(str(err))))
            return
        entries, self.library, self.lib_error = res
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
        return index, sync.make_plan(self.entries, index, opts, meta, self.library)

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
        elif not p.tasks and p.skipped:
            text = tr("Nothing new in the selection · {k} already saved", k=num(known))
        elif not p.tasks:
            text = tr("Everything is saved ({k} files).", k=num(known))
        else:
            text = tr("{n} new files ({size}) · {k} already saved" if len(p.tasks) != 1 else "1 new file ({size}) · {k} already saved",
                      n=num(len(p.tasks)), size=size(p.bytes), k=num(known))
        if p.skipped:
            text += " · " + tr("{n} not selected", n=num(p.skipped))
        html = f"<b>{text}</b>"
        if self.library is not None and self.entries:
            cloud = self.library.cloud_only(self.entries)
            if cloud:
                html += "<br><span style='color:#c0392b'>" + tr(
                    "{n} photos and videos are only in iCloud and cannot be backed up. On the iPhone: Settings → Photos → “Download and Keep Originals”.",
                    n=num(cloud)) + "</span>"
                self._tell("cloud", tr("{n} photos and videos are only in iCloud and cannot be backed up. On the iPhone: Settings → Photos → “Download and Keep Originals”.", n=num(cloud)))
        elif self.choice.beta and self.lib_error and not self.source:
            html += "<br><span style='color: palette(placeholder-text)'>" + tr(
                "Photos library not readable, working without it: {msg}", msg=_short(self.lib_error)) + "</span>"
        self.summary.setText(html)
        if p.tasks:
            ok, free = sync.free_space_ok(Path(self.dest), p.bytes)
            if not ok:
                self.summary.setText(html + "<br><span style='color:#c0392b'>"
                                     + tr("Only {free} free in the backup folder, {need} needed.",
                                          free=size(free), need=size(p.bytes + sync.SPACE_RESERVE))
                                     + "</span>")
        self.bar.setValue(0)
        self.bar.setFormat("")
        self._set_state("ready", tr("Ready.") if not self.source else str(self.dcim))
        if p.tasks and not sync.free_space_ok(Path(self.dest), p.bytes)[0]:
            self.go_btn.setEnabled(False)
            self._tell("space", tr("Not enough free space in the backup folder."))
            return
        if (p.tasks and not self.source and self.settings.value("auto_backup", False, type=bool)
                and self.dev.udid not in self._auto_done and not self.worker):
            self._auto_done.add(self.dev.udid)
            self._auto_run = True
            self._start_copy(p, self.index)

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
        self._copy_jpeg = self.settings.value("jpeg", False, type=bool) and bool(jpeg.available())
        self.worker = SyncThread(self, plan, self.dcim, index, self._copy_jpeg)
        self.worker.progress.connect(self._progress)
        self.worker.file_done.connect(self._file_done)
        self.worker.result.connect(self._finished)
        self._set_state("copying", tr("Backing up – keep the iPhone connected and unlocked."))
        if self.tray:
            self.tray.setToolTip("DCIMDock – " + tr("Backing up {n} files…", n=num(self.count)))
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
            self._really_quit = True
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
        auto, self._auto_run = self._auto_run, False
        if self.tray:
            self.tray.setToolTip("DCIMDock")
        if self.tray and (auto or not self.isVisible()) and not self.isActiveWindow():
            self._tray_report(res)
            return
        parts = []
        if res.cancelled:
            parts.append(tr("The iPhone was unplugged during the backup.") if self._gone_during_copy
                         else tr("Stopped after {n} files. Next time it continues where it stopped.",
                                 n=num(res.copied)))
        if res.failed:
            lines = "\n".join(f"  {rel}: {why}" for rel, why in res.failed[:8])
            more = "\n  …" if len(res.failed) > 8 else ""
            parts.append(tr("{n} files could not be read:", n=num(len(res.failed))) + "\n" + lines + more)
        if res.jpeg_failed:
            lines = "\n".join(f"  {rel}: {why}" for rel, why in res.jpeg_failed[:5])
            parts.append(tr("{n} JPEG copies failed (the HEIC files are saved):", n=num(len(res.jpeg_failed)))
                         + "\n" + lines)
        if self.entries and self._copy_index:
            a, b, k = sync.saved_range(self.entries, self._copy_index)
            if a is not None:
                parts.append(tr("From this iPhone, {k} files taken between {a} and {b} are safe on this computer.",
                                k=num(k), a=date(a), b=date(b)))
            left = sync.unsaved(self.entries, self._copy_index)
            if left and not res.cancelled:
                parts.append(tr("{n} files on the iPhone are not in this backup (not selected or not readable).",
                                n=num(left)))
        if not self.source:
            parts.append(tr("DCIMDock does not delete anything on the iPhone. To free up space, delete the photos in the Photos app and empty “Recently Deleted”. With iCloud Photos turned on, this deletes them from iCloud and all your devices too."))
        box = QMessageBox(QMessageBox.Warning if (res.failed or res.cancelled) else QMessageBox.Information,
                          tr("Backup stopped") if res.cancelled else tr("Backup finished"),
                          self._overview_html(res, parts), QMessageBox.Ok, self)
        box.setTextFormat(Qt.RichText)
        open_btn = box.addButton(tr("Open folder"), QMessageBox.ActionRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self.open_dest()

    def _overview_html(self, res: sync.Result, notes: list[str]) -> str:
        """The numbers as a small table, the notes below it."""
        from html import escape

        from .app import overview
        cells = []
        for label, value in overview(res, self._copy_plan, getattr(self, "_copy_jpeg", False)):
            part = label.startswith(" ")        # a part of the row above
            style = "white-space:nowrap;padding-right:24px" + (";padding-left:14px" if part else "")
            cells.append(f'<tr><td style="{style}">{escape(label.strip())}</td>'
                         f'<td align="right" style="white-space:nowrap">'
                         f'{escape(value) if part else "<b>" + escape(value) + "</b>"}</td></tr>')
        root = str(self._copy_index.root) if self._copy_index else self.dest
        html = "<table cellspacing=0 cellpadding=1>" + "".join(cells) + "</table>"
        html += f"<p>{escape(tr('Folder'))}: {escape(native(root))}</p>"
        return html + "".join("<p>" + escape(p).replace("\n", "<br>") + "</p>" for p in notes)

    # ------------------------------------------------------------ more menu
    def full_copy(self):
        if self.worker or self.state == "fixing":
            return
        if not self.entries or not self.dev:
            return
        stamp = time.strftime("%Y-%m-%d %H-%M")
        if self.choice.selection().active:
            label = self.choice.folder_label()
            name = f"{tr('Selection')} {label} ({stamp})" if label else f"{tr('Selection')} {stamp}"
        else:
            name = f"{tr('Full copy')} {stamp}"
        root = Path(self.dest) / sync.safe_name(name)
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
                  n=num(len(plan.tasks)), size=size(plan.bytes), folder=native(str(root)))
        if self.choice.selection().active:
            text += "\n\n" + tr("Selection: {what}", what=self.choice.describe())
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
        self._fix(device.restart_service, after)

    def start_service(self):
        """The 'missing' screen on Windows: start Apple's driver, then look again."""
        def after(res, err):
            ok, msg = res if res else (False, str(err))
            if not ok:
                QMessageBox.warning(self, tr("Start the iPhone service"),
                                    tr("Could not start the service: {msg}", msg=_short(msg) or "-"))
        self._fix(device.restart_service, after)

    def show_diagnosis(self):
        self.setCursor(Qt.WaitCursor)
        def lib_line():
            if not self.choice.beta:
                return "Photos library (beta): off"
            if self.library is not None:
                c = self.library.counts()
                return (f"Photos library (beta): {self.library.ios_table}, {c['assets']} assets, "
                        f"{c['trashed']} deleted, {c['hidden']} hidden, {c['favorite']} favorites, "
                        f"{c['albums']} albums, {self.library.cloud_only(self.entries or [])} only in iCloud")
            return f"Photos library (beta): not read {self.lib_error}"
        self._call(device.diagnose, lambda res, err: (self.unsetCursor(), DiagDialog(
            self, (res or str(err)) + "\n" + lib_line()).exec()))

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

    # ------------------------------------------------------------ background
    def _setup_tray(self):
        want = self.background or self.settings.value("auto_backup", False, type=bool)
        if not want or not QSystemTrayIcon.isSystemTrayAvailable():
            if self.tray:
                self.tray.hide()
                self.tray.deleteLater()
                self.tray = None
            return
        if self.tray:
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("DCIMDock")
        menu = QMenu(self)
        menu.addAction(tr("Open DCIMDock"), self.show_window)
        menu.addAction(tr("Open folder"), self.open_dest)
        menu.addAction(tr("Check for updates…"), self.check_update_now)
        menu.addSeparator()
        quit_act = QAction(tr("Quit"), menu)
        quit_act.triggered.connect(self.quit_all)
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_window() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.show()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_all(self):
        self._really_quit = True
        if self.worker:
            self.show_window()
        self.close()

    def _tell(self, state: str, text: str):
        """A tray message while the window is hidden, once per iPhone and state."""
        if not self.tray or self.isVisible() or not self.dev:
            return
        key = (self.dev.udid, state)
        if key in self._told:
            return
        self._told.add(key)
        self.tray.showMessage("DCIMDock", text, QSystemTrayIcon.Information, 8000)

    def _tray_report(self, res: sync.Result):
        icon = QSystemTrayIcon.Information
        if res.cancelled:
            text = (tr("The iPhone was unplugged during the backup.") if self._gone_during_copy
                    else tr("Stopped after {n} files. Next time it continues where it stopped.", n=num(res.copied)))
            icon = QSystemTrayIcon.Warning
        else:
            text = tr("{n} files saved ({size}) in {time}.", n=num(res.copied), size=size(res.bytes),
                      time=duration(res.seconds))
        if res.failed or res.jpeg_failed:
            text += " " + tr("{n} with problems – open DCIMDock for details.",
                             n=num(len(res.failed) + len(res.jpeg_failed)))
            icon = QSystemTrayIcon.Warning
            self.status.setText(text)
        self.tray.showMessage("DCIMDock", text, icon, 10000)

    def show_settings(self):
        if self.worker:
            return
        dlg = SettingsDialog(self, self.settings)
        was_beta = self.choice.beta
        if dlg.exec() == QDialog.Accepted:
            self._setup_tray()
            self.choice = SelectionChoice(self.settings)
            self._show_selection()
            self._show_example()
            if self.choice.beta != was_beta and self.dcim is not None and not self.worker:
                self._scan()        # read (or forget) the library
            else:
                self._replan()

    def check_update_now(self, box_parent=None, before_update=None):
        """Asked for by hand: ask GitHub now, whatever the daily limit, and say what came out."""
        box_parent = box_parent or self
        box_parent.setCursor(Qt.WaitCursor)

        def done(res, err):
            box_parent.unsetCursor()
            if err or not res or not res[0]:
                QMessageBox.warning(box_parent, "DCIMDock", tr("Could not ask GitHub: {msg}", msg=_short(str(err)) or "-"))
                return
            self.settings.setValue("update_checked", time.time())
            v, page = res
            if not update.newer(v):
                QMessageBox.information(box_parent, "DCIMDock", tr("You have the newest version ({v}).", v=__version__))
                return
            self.settings.setValue("update_seen", v)
            self._show_update((v, page))
            itself = update.can_update_itself()
            box = QMessageBox(QMessageBox.Information, "DCIMDock",
                              tr("Version {v} is available", v=v) + "\n" + tr("Installed: {v}", v=__version__),
                              QMessageBox.NoButton, box_parent)
            go = box.addButton(tr("Update now") if itself else tr("Open download page"), QMessageBox.AcceptRole)
            box.addButton(tr("Later"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not go:
                return
            if not itself:
                QDesktopServices.openUrl(QUrl(page))
                return
            if before_update:
                before_update()         # e.g. the settings dialog saves and closes
            QTimer.singleShot(0, self.update_itself)
        self._call(update.latest, done)

    def _check_update(self):
        if not self.settings.value("check_updates", True, type=bool):
            return
        last = self.settings.value("update_checked", 0.0, type=float)
        if time.time() - last < 86400:
            seen = self.settings.value("update_seen", "")
            if seen and update.newer(seen):
                self._show_update((seen, update.PAGE))
            return

        def done(res, err):
            self.settings.setValue("update_checked", time.time())
            if res:
                self.settings.setValue("update_seen", res[0])
                self._show_update(res)
        self._call(update.check, done)

    def _show_update(self, res):
        self._update = res
        v, page = res
        self.update_label.setText(f'<a href="{page}">' + tr("Version {v} is available", v=v) + "</a>")
        self.update_label.show()
        if update.can_update_itself():
            self.update_btn.setText(tr("Update now"))
            self.update_btn.setToolTip(tr("Downloads the new version, checks it and restarts DCIMDock."))
            self.update_btn.show()
        if self.tray and not self.isVisible():
            self.tray.showMessage("DCIMDock", tr("Version {v} is available", v=v), QSystemTrayIcon.Information, 8000)

    def update_itself(self):
        """Windows .exe: fetch the new one, start it, quit. It deletes this file."""
        if not self._update:
            return
        if self.worker or self.state == "fixing":
            QMessageBox.information(self, "DCIMDock", tr("Please wait until the backup is finished."))
            return
        v = self._update[0]
        self.update_btn.setEnabled(False)
        self.update_btn.setText(tr("Downloading…"))

        def done(path, err):
            if err or not path:
                self.update_btn.setEnabled(True)
                self.update_btn.setText(tr("Update now"))
                QMessageBox.warning(self, "DCIMDock", tr("The update did not work: {msg}", msg=_short(str(err)) or "-")
                                    + "\n\n" + tr("You can download it by hand: {page}", page=self._update[1]))
                return
            import subprocess
            import sys
            args = [str(path), "--replace", sys.executable]
            if not self.isVisible():
                args.append("--background")
            try:
                subprocess.Popen(args, close_fds=True, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            except OSError as exc:
                self.update_btn.setEnabled(True)
                self.update_btn.setText(tr("Update now"))
                QMessageBox.warning(self, "DCIMDock", tr("The update did not work: {msg}", msg=str(exc)))
                return
            self.quit_all()
        self._call(update.download, done, v)

    def closeEvent(self, ev):
        if (self.tray and not self._really_quit and not self.selftest
                and self.settings.value("auto_backup", False, type=bool)):
            # keep watching for the iPhone next to the clock
            self.hide()
            if not self.settings.value("told_tray", False, type=bool):
                self.settings.setValue("told_tray", True)
                self.tray.showMessage("DCIMDock", tr("DCIMDock keeps running here and backs up the iPhone when it is plugged in. Quit from this icon's menu."),
                                      QSystemTrayIcon.Information, 10000)
            ev.ignore()
            return
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
        if self.tray:
            self.tray.hide()
        super().closeEvent(ev)
        QTimer.singleShot(0, QApplication_quit)


def QApplication_quit():
    from PySide6.QtWidgets import QApplication
    QApplication.quit()


def QApplication_alert(win):
    from PySide6.QtWidgets import QApplication
    QApplication.alert(win)


def _short(msg: str) -> str:
    msg = " ".join(msg.split())
    return msg if len(msg) < 200 else msg[:200] + " …"
