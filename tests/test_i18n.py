"""Every English text the window and the terminal show has a German one."""
import ast
import unittest
from pathlib import Path

from dcimdock import i18n

SRC = Path(__file__).resolve().parents[1] / "dcimdock"


def literals():
    for f in ("window.py", "app.py", "afc.py"):
        tree = ast.parse((SRC / f).read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    yield f, a.value
                elif isinstance(a, ast.IfExp):
                    for b in (a.body, a.orelse):
                        if isinstance(b, ast.Constant):
                            yield f, b.value


class TestI18n(unittest.TestCase):
    def test_german_for_everything(self):
        missing = sorted({(f, t) for f, t in literals() if t != "INTRO_HTML" and t not in i18n.DE})
        self.assertEqual(missing, [])

    def test_labels_in_tables(self):
        try:
            from dcimdock import window
        except ImportError:
            self.skipTest("PySide6 not installed")
        for _key, label in window.PRESET_LABELS + window.LAYOUT_LABELS:
            self.assertIn(label, i18n.DE)


if __name__ == "__main__":
    unittest.main()
