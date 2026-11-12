"""Render dcimdock.svg into a multi-size .ico for the .exe (Qt draws, Pillow packs)."""
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

root = Path(__file__).resolve().parents[2]
out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)

app = QGuiApplication(sys.argv[:1])
svg = QSvgRenderer(str(root / "dcimdock" / "dcimdock.svg"))
img = QImage(256, 256, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
svg.render(p)
p.end()
buf = QBuffer()
buf.open(QIODevice.WriteOnly)
img.save(buf, "PNG")
png = out.with_suffix(".png")
png.write_bytes(bytes(buf.data()))
Image.open(png).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
