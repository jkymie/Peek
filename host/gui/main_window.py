"""Janela principal do Peek.

A interface é feita em React (``ui/src/broadcaster``) e roda dentro da janela pelo
QtWebEngine. A janela só monta o navegador embutido e liga a :class:`Bridge` ao
QWebChannel; as telas e os estados ficam em ``host.gui.bridge``.

Para desenvolver a interface com recarregamento automático, rode ``npm run dev`` em
``ui/`` e abra o Peek com ``PEEK_UI_DEV_URL=http://localhost:5173/``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from host.capture.video import CaptureSource, list_sources
from host.gui import messages as msg
from host.gui.bridge import Bridge
from host.resources import window_ui_dir
from host.session import SessionState, StreamSession

log = logging.getLogger(__name__)

BACKGROUND = "#111214"  # mesmo fundo da interface: evita um clarão branco ao abrir


def ui_url() -> QUrl:
    dev_url = os.environ.get("PEEK_UI_DEV_URL")
    if dev_url:
        return QUrl(dev_url)
    return QUrl.fromLocalFile(str(window_ui_dir() / "index.html"))


class MainWindow(QWidget):
    closed = Signal()  # a janela fechou de vez (depois de parar a transmissão, se havia)

    def __init__(
        self,
        session: StreamSession,
        *,
        sources_provider: Callable[[], list[CaptureSource]] = list_sources,
    ) -> None:
        super().__init__()
        self._session = session
        self._closing_task: asyncio.Task | None = None

        self.setWindowTitle(msg.APP_NAME)
        self.setMinimumSize(560, 640)
        self.resize(640, 760)

        self.bridge = Bridge(session, sources_provider=sources_provider, parent=self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("peek", self.bridge)

        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.page().setBackgroundColor(QColor(BACKGROUND))
        self.view.page().setWebChannel(self._channel)
        self.view.load(ui_url())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.bridge.closing or self._session.state is SessionState.IDLE:
            event.accept()
            self.closed.emit()
            return
        answer = QMessageBox(self)
        answer.setIcon(QMessageBox.Icon.Question)
        answer.setWindowTitle(msg.CLOSE_CONFIRM_TITLE)
        answer.setText(msg.CLOSE_CONFIRM_TEXT)
        yes = answer.addButton(msg.CLOSE_CONFIRM_YES, QMessageBox.ButtonRole.AcceptRole)
        answer.addButton(msg.CLOSE_CONFIRM_NO, QMessageBox.ButtonRole.RejectRole)
        answer.exec()
        event.ignore()
        if answer.clickedButton() is yes:
            self.bridge.closing = True
            self._closing_task = asyncio.ensure_future(self._stop_and_close())

    async def _stop_and_close(self) -> None:
        try:
            await self._session.stop()
        finally:
            self.close()
