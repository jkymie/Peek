"""Inicia a janela do Peek com o loop do Qt e do asyncio unificados (qasync)."""

from __future__ import annotations

import asyncio
import logging
import sys

import qasync
from PySide6.QtWidgets import QApplication

from host.gui import messages as msg
from host.gui.main_window import MainWindow
from host.session import StreamSession

log = logging.getLogger(__name__)


def run_gui(
    *, port: int, public: bool = True, sound: bool = True, include_discord: bool = False
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(msg.APP_NAME)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    closed = asyncio.Event()
    app.aboutToQuit.connect(closed.set)

    session = StreamSession(port=port, public=public, sound=sound, include_discord=include_discord)
    window = MainWindow(session)
    window.show()
    log.info("Janela aberta")

    with loop:
        loop.run_until_complete(closed.wait())
    return 0
