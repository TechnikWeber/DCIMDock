"""Renders docs/screenshot.png and docs/intro.png from the real window.

A temporary folder with painted demo photos stands in for the iPhone, and the
copy is slowed down so the picture shows a backup in progress.

    python3 tools/screenshot.py            # needs a running desktop session
"""
import os
import random
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPolygonF
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dcimdock import device, sync, window  # noqa: E402

device.cleanup_stale = lambda: None


def paint_photo(path: Path, seed: int):
    rnd = random.Random(seed)
    img = QImage(1600, 1200, QImage.Format_RGB32)
    p = QPainter(img)
    sky = QLinearGradient(0, 0, 0, 1200)
    h = rnd.randint(180, 230)
    sky.setColorAt(0, QColor.fromHsv(h, 120, 240))
    sky.setColorAt(0.7, QColor.fromHsv(rnd.randint(10, 40), 110, 255))
    p.fillRect(img.rect(), sky)
    p.setPen(QColor(0, 0, 0, 0))
    p.setBrush(QColor(255, 244, 214))
    p.drawEllipse(QPointF(rnd.randint(300, 1300), rnd.randint(180, 420)), 90, 90)
    for layer in range(3):
        pts = [QPointF(0, 1200)]
        y = 650 + layer * 160
        for x in range(0, 1700, 100):
            pts.append(QPointF(x, y + rnd.randint(-160, 60)))
        pts.append(QPointF(1600, 1200))
        p.setBrush(QColor.fromHsv(rnd.randint(90, 150), 140, 150 - layer * 40))
        p.drawPolygon(QPolygonF(pts))
    p.end()
    img.save(str(path), "JPG", 88)


tmp = Path(tempfile.mkdtemp())
os.environ["XDG_CONFIG_HOME"] = str(tmp / "config")   # default settings, not yours
app = QApplication(sys.argv[:1])
app.setDesktopFileName("dcimdock")
dcim = tmp / "Demo-iPhone" / "DCIM" / "100APPLE"
dcim.mkdir(parents=True)
t = time.mktime((2026, 11, 8, 14, 0, 0, 0, 0, -1))
for i in range(1, 61):
    f = dcim / f"IMG_{4100 + i:04d}.JPG"
    paint_photo(f, i)
    with open(f, "ab") as fh:          # make them as large as real photos
        fh.write(os.urandom(2_400_000))
    os.utime(f, (t + i * 60, t + i * 60))

real_copy = sync.copy_one


def slow_copy(src, dest, e, progress, cancel):
    def slow(n):
        time.sleep(0.025)
        progress(n)
    return real_copy(src, dest, e, slow, cancel)


sync.copy_one = slow_copy
sync.CHUNK = 256 * 1024

win = window.MainWindow(source=str(tmp / "Demo-iPhone"), selftest=True)
win.dest = str(tmp / "Pictures" / "iPhone")
win._show_dest()
win.preview_box.setChecked(True)
win.resize(660, 600)
win.show()


def fake_device_title():
    win.title.setText("Demo iPhone  (iPhone15,2, iOS 26.1)")


def go():
    fake_device_title()
    win.go_or_stop()


def shoot():
    fake_device_title()
    win.dest_label.setText(str(Path("~/Pictures/iPhone")))
    win.grab().save(str(ROOT / "docs" / "screenshot.png"))
    dlg = window.IntroDialog(None, True)
    dlg.resize(600, 760)
    dlg.show()

    def intro():
        dlg.grab().save(str(ROOT / "docs" / "intro.png"))
        dlg.close()
        win.worker.stop.set()
        win._quit_after_stop = True
        print("saved docs/screenshot.png, docs/intro.png")
    QTimer.singleShot(600, intro)


QTimer.singleShot(1200, go)
QTimer.singleShot(9000, shoot)
QTimer.singleShot(12000, app.quit)
app.exec()
