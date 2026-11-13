from __future__ import annotations

import encodings.idna  # Load before the network threads use getaddrinfo.
import sys
from pathlib import Path
from rcboat_gui.runtime_logging import configure,install_qt_handler

try:
    LOG_DIRECTORY = configure()
except (OSError,RuntimeError):
    LOG_DIRECTORY = None  # A full/unwritable log directory must not prevent startup.

from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from rcboat_gui.main_window import MainWindow


def main() -> int:
    if LOG_DIRECTORY is not None:install_qt_handler()
    smoke_test = "--smoke-test" in sys.argv
    auto_connect = "--no-auto-connect" not in sys.argv and not smoke_test
    qt_args = [arg for arg in sys.argv if arg not in {"--auto-connect", "--no-auto-connect"}]
    app = QApplication([sys.argv[0]] if smoke_test else qt_args)
    app.setApplicationName("RCBoatControl")
    app.setOrganizationName("AdventureDesign")
    instance_lock = None
    if not smoke_test:
        local_data = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
        local_data.mkdir(parents=True, exist_ok=True)
        instance_lock = QLockFile(str(local_data / "console.lock"))
        instance_lock.setStaleLockTime(0)
        if not instance_lock.tryLock(0):
            QMessageBox.information(None, "RC 보트 관제센터", "관제 앱이 이미 실행 중입니다. 열린 창을 사용해 주세요.")
            return 0
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app.setWindowIcon(QIcon(str(bundle_root / "assets" / "cat_boat_icon.ico")))
    window = MainWindow()
    window.show()
    if auto_connect and window.password.text():
        QTimer.singleShot(250, window.auto_connect)
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
    try:
        return app.exec()
    finally:
        if instance_lock is not None:
            instance_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
