from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from rcboat_gui.main_window import MainWindow


def main() -> int:
    app = QApplication([sys.argv[0]] if "--smoke-test" in sys.argv else sys.argv)
    app.setApplicationName("RCBoatControl")
    app.setOrganizationName("AdventureDesign")
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app.setWindowIcon(QIcon(str(bundle_root / "assets" / "cat_boat_icon.ico")))
    window = MainWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        app.processEvents()
        if "--screenshot" in sys.argv:
            index = sys.argv.index("--screenshot")
            if index + 1 < len(sys.argv):
                target = Path(sys.argv[index + 1])
                target.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(target))
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
