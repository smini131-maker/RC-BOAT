"""Persistent local crash diagnostics. Never log credentials or terminal input."""
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading

_native_file = None
_qt_handler = None


def configure():
    global _native_file
    folder = Path(os.getenv('LOCALAPPDATA') or Path.home()) / 'RCBoatControl' / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / 'app.log', maxBytes=2_000_000,
                                  backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger = logging.getLogger('rcboat')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    _native_file = open(folder / 'native_crash.log', 'a', encoding='utf-8')
    faulthandler.enable(file=_native_file, all_threads=True)
    sys.excepthook = lambda kind, value, trace: logger.error(
        'unhandled Python exception', exc_info=(kind, value, trace))
    threading.excepthook = lambda args: logger.error(
        'background thread failed: %s', args.thread.name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    logger.info('GUI process started; pid=%s', os.getpid())
    return folder


def install_qt_handler():
    global _qt_handler
    from PySide6.QtCore import qInstallMessageHandler
    def capture(kind, context, message):
        logging.getLogger('rcboat.qt').warning('%s', message)
    _qt_handler = capture
    qInstallMessageHandler(_qt_handler)
