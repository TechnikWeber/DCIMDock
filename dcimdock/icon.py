"""The app icon: the installed theme icon if there is one, else the bundled SVG."""
from importlib import resources

from PySide6.QtGui import QIcon


def app_icon() -> QIcon:
    themed = QIcon.fromTheme("dcimdock")
    if not themed.isNull():
        return themed
    return QIcon(str(resources.files(__package__).joinpath("dcimdock.svg")))
