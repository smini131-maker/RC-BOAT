from __future__ import annotations

import sys
from pathlib import Path
from rcboat_gui.runtime_logging import configure,install_qt_handler

try:
    LOG_DIRECTORY = configure()
except (OSError,RuntimeError):
    LOG_DIRECTORY = None  # A full/unwritable log directory must not prevent startup.

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from rcboat_gui.main_window import MainWindow


def main() -> int:
    if LOG_DIRECTORY is not None:install_qt_handler()
    smoke_test = "--smoke-test" in sys.argv
    auto_connect = "--auto-connect" in sys.argv and not smoke_test
    qt_args = [arg for arg in sys.argv if arg != "--auto-connect"]
    app = QApplication([sys.argv[0]] if smoke_test else qt_args)
    app.setApplicationName("RCBoatControl")
    app.setOrganizationName("AdventureDesign")
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app.setWindowIcon(QIcon(str(bundle_root / "assets" / "cat_boat_icon.ico")))
    window = MainWindow()
    window.show()
    if auto_connect and window.password.text():
        QTimer.singleShot(0, window.toggle_connection)
    if smoke_test:
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
