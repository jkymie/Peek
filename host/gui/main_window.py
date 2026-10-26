"""Janela principal do Peek.

Quatro telas, uma por estado da transmissão:

1. **Escolher**: o que mostrar + qualidade + "Começar a transmitir"
2. **Preparando**
3. **Transmitindo**: link, "Copiar link", contador de pessoas e "Parar"
4. **Erro**: frase clara + "Tentar novamente"

A janela só conversa com a :class:`~host.session.StreamSession` (nunca com a
captura, o aiortc ou o servidor). Os eventos da sessão chegam na thread do Qt,
porque o loop do asyncio é o próprio loop do Qt (qasync).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from host.capture.video import CaptureSource, SourceKind, list_sources
from host.gui import messages as msg
from host.rtc.quality import DEFAULT_PRESET, resolve_quality
from host.session import ErrorCode, SessionError, SessionState, StreamSession

log = logging.getLogger(__name__)

# Marco 1: só três opções na janela; as outras continuam disponíveis no --quality.
WINDOW_PRESETS = ("economica", "equilibrada", "nitida")
LINK_COPIED_MS = 2000


def source_label(source: CaptureSource, monitor_count: int) -> str:
    if source.kind is SourceKind.MONITOR:
        name = (
            msg.SCREEN_ITEM if monitor_count == 1 else msg.SCREEN_ITEM_NUMBERED.format(n=source.id)
        )
        if source.primary and monitor_count > 1:
            name += f" ({msg.SCREEN_PRIMARY})"
        return name
    app = source.process_name.removesuffix(".exe").removesuffix(".EXE")
    label = f"{source.name}  ·  {app}" if app else source.name
    if source.minimized:
        label += f"  ({msg.WINDOW_MINIMIZED})"
    return label


def _title(text: str) -> QLabel:
    # O tamanho vem da folha de estilo (que sobrepõe setFont).
    label = QLabel(text)
    label.setProperty("title", True)
    label.setWordWrap(True)
    return label


def _text(text: str = "", *, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if muted:
        label.setProperty("muted", True)
    return label


def _primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("primary", True)
    button.setMinimumHeight(40)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


STYLE = """
QWidget { font-size: 10.5pt; }
QLabel[title="true"] { font-size: 15pt; font-weight: 600; }
QLabel[muted="true"] { color: palette(placeholder-text); }
QPushButton { padding: 6px 14px; }
QPushButton[primary="true"] {
    background: #5865f2; color: white; border: 0; border-radius: 6px;
    font-weight: 600; padding: 8px 18px;
}
QPushButton[primary="true"]:hover { background: #4752c4; }
QPushButton[primary="true"]:disabled { background: #a5abf0; }
QListWidget::item { padding: 6px; }
"""


class MainWindow(QWidget):
    def __init__(
        self,
        session: StreamSession,
        *,
        sources_provider: Callable[[], list[CaptureSource]] = list_sources,
    ) -> None:
        super().__init__()
        self._session = session
        self._sources_provider = sources_provider
        self._task: asyncio.Task | None = None
        self._closing = False

        self.setWindowTitle(msg.APP_NAME)
        self.setMinimumSize(480, 540)
        self.setStyleSheet(STYLE)

        self._pages = QStackedWidget()
        self._choose_page = self._build_choose_page()
        self._preparing_page = self._build_preparing_page()
        self._live_page = self._build_live_page()
        self._error_page = self._build_error_page()
        for page in (self._choose_page, self._preparing_page, self._live_page, self._error_page):
            self._pages.addWidget(page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(self._pages)

        session.link_ready.connect(self._on_link_ready)
        session.viewers_changed.connect(self._on_viewers_changed)
        session.error.connect(self._on_error)

        self.refresh_sources()

    # --- construção das telas ----------------------------------------------------

    def _build_choose_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(_title(msg.CHOOSE_TITLE), 1)
        self.refresh_button = QPushButton(msg.REFRESH)
        self.refresh_button.clicked.connect(self.refresh_sources)
        header.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.source_list = QListWidget()
        # Títulos longos são cortados com "…" (o nome completo aparece ao passar o mouse).
        self.source_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.source_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.source_list.currentItemChanged.connect(self._on_source_selected)
        self.source_list.itemDoubleClicked.connect(lambda _item: self.start_button.click())
        layout.addWidget(self.source_list, 1)

        self.reminder_label = _text(msg.FULL_SCREEN_REMINDER, muted=True)
        self.reminder_label.hide()
        layout.addWidget(self.reminder_label)

        layout.addWidget(_text(msg.QUALITY_TITLE))
        self.quality_combo = QComboBox()
        for preset in WINDOW_PRESETS:
            name, _description = msg.QUALITY_LABELS[preset]
            self.quality_combo.addItem(name, preset)
        self.quality_combo.setCurrentIndex(WINDOW_PRESETS.index(DEFAULT_PRESET))
        self.quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        layout.addWidget(self.quality_combo)
        self.quality_hint = _text(muted=True)
        layout.addWidget(self.quality_hint)
        self._on_quality_changed()

        self.start_button = _primary_button(msg.START)
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(lambda: self._spawn(self.start_streaming()))
        layout.addWidget(self.start_button)
        return page

    def _build_preparing_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        label = _title(msg.PREPARING)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        progress = QProgressBar()
        progress.setRange(0, 0)  # indeterminado
        progress.setTextVisible(False)
        layout.addWidget(progress)
        layout.addStretch(1)
        return page

    def _build_live_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(_title(msg.LIVE_TITLE))
        self.live_source_label = _text(muted=True)
        layout.addWidget(self.live_source_label)
        layout.addSpacing(8)

        link_row = QHBoxLayout()
        self.link_edit = QLineEdit()
        self.link_edit.setReadOnly(True)
        self.link_edit.setMinimumHeight(36)
        link_row.addWidget(self.link_edit, 1)
        self.copy_button = _primary_button(msg.COPY_LINK)
        self.copy_button.setMinimumWidth(170)  # cabe "Link copiado!" sem mudar de tamanho
        self.copy_button.clicked.connect(self.copy_link)
        link_row.addWidget(self.copy_button)
        layout.addLayout(link_row)
        layout.addWidget(_text(msg.SHARE_HINT, muted=True))
        layout.addWidget(_text(msg.LOCAL_NETWORK_HINT, muted=True))

        layout.addSpacing(12)
        self.viewers_label = _title(msg.viewers_text(0))
        layout.addWidget(self.viewers_label)
        layout.addStretch(1)

        self.stop_button = QPushButton(msg.STOP)
        self.stop_button.setMinimumHeight(40)
        self.stop_button.clicked.connect(lambda: self._spawn(self.stop_streaming()))
        layout.addWidget(self.stop_button)
        return page

    def _build_error_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addStretch(1)
        layout.addWidget(_title(msg.ERROR_TITLE))
        self.error_label = _text()
        layout.addWidget(self.error_label)
        layout.addStretch(1)
        self.retry_button = _primary_button(msg.TRY_AGAIN)
        self.retry_button.clicked.connect(self._back_to_choose)
        layout.addWidget(self.retry_button)
        return page

    # --- ações ---------------------------------------------------------------------

    def refresh_sources(self) -> None:
        previous = self.selected_source()
        self.source_list.clear()
        try:
            sources = self._sources_provider()
        except Exception:
            log.exception("Erro ao listar telas e janelas")
            sources = []
        monitor_count = sum(s.kind is SourceKind.MONITOR for s in sources)
        for source in sources:
            item = QListWidgetItem(source_label(source, monitor_count))
            item.setToolTip(item.text())
            item.setData(Qt.ItemDataRole.UserRole, source)
            self.source_list.addItem(item)
            if previous is not None and (source.kind, source.id) == (previous.kind, previous.id):
                self.source_list.setCurrentItem(item)
        if not sources:
            item = QListWidgetItem(msg.NO_SOURCES)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.source_list.addItem(item)
        elif self.source_list.currentItem() is None:
            self.source_list.setCurrentRow(0)  # tela principal: o caso mais comum
        self._on_source_selected()

    def selected_source(self) -> CaptureSource | None:
        item = self.source_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    async def start_streaming(self) -> None:
        source = self.selected_source()
        if source is None:
            return
        quality = resolve_quality(self.quality_combo.currentData())
        self.live_source_label.setText(
            msg.LIVE_SOURCE.format(name=self.source_list.currentItem().text())
        )
        self._pages.setCurrentWidget(self._preparing_page)
        # Em caso de erro, a sessão já emitiu `error`, que mostra a tela de erro.
        with contextlib.suppress(SessionError):
            await self._session.start(source, quality)

    async def stop_streaming(self) -> None:
        self.stop_button.setEnabled(False)
        try:
            await self._session.stop()
        finally:
            self.stop_button.setEnabled(True)
        self._back_to_choose()

    def copy_link(self) -> None:
        QGuiApplication.clipboard().setText(self.link_edit.text())
        self.copy_button.setText(msg.LINK_COPIED)
        QTimer.singleShot(LINK_COPIED_MS, lambda: self.copy_button.setText(msg.COPY_LINK))

    # --- eventos da sessão ---------------------------------------------------------

    def _on_link_ready(self, link: str) -> None:
        self.link_edit.setText(link)
        self.link_edit.setCursorPosition(0)  # mostra o começo do link
        self.viewers_label.setText(msg.viewers_text(0))
        self._pages.setCurrentWidget(self._live_page)

    def _on_viewers_changed(self, count: int) -> None:
        self.viewers_label.setText(msg.viewers_text(count))

    def _on_error(self, code: ErrorCode) -> None:
        if self._closing:
            return
        self.error_label.setText(msg.error_message(code))
        self._pages.setCurrentWidget(self._error_page)

    # --- auxiliares ----------------------------------------------------------------

    def _on_source_selected(self, *_args) -> None:
        source = self.selected_source()
        self.start_button.setEnabled(source is not None)
        self.reminder_label.setVisible(source is not None and source.kind is SourceKind.MONITOR)

    def _on_quality_changed(self, *_args) -> None:
        _name, description = msg.QUALITY_LABELS[self.quality_combo.currentData()]
        self.quality_hint.setText(description)

    def _back_to_choose(self) -> None:
        self.refresh_sources()
        self._pages.setCurrentWidget(self._choose_page)

    def _spawn(self, coro) -> None:
        # Uma ação por vez (evita dois cliques em "Começar" abrirem duas transmissões).
        if self._task is not None and not self._task.done():
            coro.close()
            return
        self._task = asyncio.ensure_future(coro)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing or self._session.state is SessionState.IDLE:
            event.accept()
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
            self._closing = True
            self._task = asyncio.ensure_future(self._stop_and_close())

    async def _stop_and_close(self) -> None:
        try:
            await self._session.stop()
        finally:
            self.close()
