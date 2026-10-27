"""Ponte entre a interface React da janela (``ui/``) e a :class:`StreamSession`.

A interface roda dentro da janela (QtWebEngine) e conversa com o Python pelo
QWebChannel. O Python é o dono do estado: a cada mudança, :attr:`Bridge.state_changed`
manda o estado inteiro em JSON e a interface só desenha o que recebeu. Os cliques
voltam como chamadas aos slots (``start``, ``stop``, ``setQuality``...).

Telas (campo ``screen`` do estado):

1. ``choose``: o que mostrar + qualidade + "Começar a transmitir"
2. ``preparing``
3. ``live``: link, contador, troca de qualidade, "Trocar tela" e "Parar"
4. ``error``: frase clara + "Tentar novamente"
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from host.capture.video import CaptureSource, SourceKind, list_sources
from host.gui import messages as msg
from host.rtc.quality import DEFAULT_PRESET, PRESETS, resolve_quality
from host.session import ErrorCode, SessionError, SoundState, StreamSession

log = logging.getLogger(__name__)

QUALITY_ORDER = ("economica", "equilibrada", "nitida", "fluida", "maxima")


def source_label(source: CaptureSource, monitor_count: int) -> str:
    if source.kind is SourceKind.MONITOR:
        name = (
            msg.SCREEN_ITEM if monitor_count == 1 else msg.SCREEN_ITEM_NUMBERED.format(n=source.id)
        )
        if source.primary and monitor_count > 1:
            name += f" ({msg.SCREEN_PRIMARY})"
        return name
    app = _app_name(source)
    label = f"{source.name}  ·  {app}" if app else source.name
    if source.minimized:
        label += f"  ({msg.WINDOW_MINIMIZED})"
    return label


def source_key(source: CaptureSource) -> str:
    return f"{source.kind}:{source.id}"


def _app_name(source: CaptureSource) -> str:
    return source.process_name.removesuffix(".exe").removesuffix(".EXE")


def _source_item(source: CaptureSource, monitor_count: int) -> dict[str, Any]:
    if source.kind is SourceKind.MONITOR:
        title = source_label(source, monitor_count)
        detail = f"{source.width} x {source.height}" if source.width else ""
    else:
        title = source.name
        if source.minimized:
            title += f" ({msg.WINDOW_MINIMIZED})"
        detail = _app_name(source)
    return {
        "key": source_key(source),
        "kind": str(source.kind),
        "title": title,
        "detail": detail,
        "label": source_label(source, monitor_count),
    }


def _quality_items() -> list[dict[str, str]]:
    items = []
    for preset in QUALITY_ORDER:
        quality = PRESETS[preset]
        name, description = msg.QUALITY_LABELS[preset]
        items.append(
            {
                "id": preset,
                "name": name,
                "description": description,
                "details": msg.quality_details(quality.height, quality.fps),
            }
        )
    return items


class Bridge(QObject):
    """Objeto publicado no QWebChannel com o nome ``peek``."""

    state_changed = Signal(str)

    def __init__(
        self,
        session: StreamSession,
        *,
        sources_provider: Callable[[], list[CaptureSource]] = list_sources,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._sources_provider = sources_provider
        self._sources: list[CaptureSource] = []
        self._task: asyncio.Task | None = None
        self._stop_task: asyncio.Task | None = None
        self._notice_ids = itertools.count(1)
        self.closing = False

        self.screen = "choose"
        self.link = ""
        self.viewers = 0
        self.error = ""
        self.busy: str | None = None  # "quality" ou "source" enquanto a troca acontece
        self.notice: dict[str, Any] | None = None
        self.live_source: CaptureSource | None = None
        self.live_quality = DEFAULT_PRESET

        session.link_ready.connect(self._on_link_ready)
        session.viewers_changed.connect(self._on_viewers_changed)
        session.sound_changed.connect(self._on_sound_changed)
        session.error.connect(self._on_error)

        self.refresh_sources(emit=False)

    # --- estado ------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        monitor_count = sum(s.kind is SourceKind.MONITOR for s in self._sources)
        live = self.live_source
        return {
            "screen": self.screen,
            "sources": [_source_item(s, monitor_count) for s in self._sources],
            "qualities": _quality_items(),
            "defaultQuality": DEFAULT_PRESET,
            "quality": self.live_quality,
            "liveSource": source_key(live) if live else None,
            "liveSourceLabel": source_label(live, monitor_count) if live else "",
            "link": self.link,
            "localOnly": not self._session.public,
            "viewers": self.viewers,
            "viewersText": msg.viewers_text(self.viewers),
            "error": self.error,
            "busy": self.busy,
            "notice": self.notice,
            "texts": msg.ui_texts(),
        }

    def emit_state(self) -> None:
        self.state_changed.emit(json.dumps(self.state(), ensure_ascii=False))

    # --- slots chamados pela interface ---------------------------------------------

    # Os nomes em camelCase são os que o JavaScript chama.

    @Slot()
    def ready(self) -> None:
        self.emit_state()

    @Slot()
    def refreshSources(self) -> None:
        self.refresh_sources()

    @Slot(str, str)
    def start(self, key: str, preset: str) -> None:
        self._spawn(self.start_streaming(key, preset))

    @Slot()
    def stop(self) -> None:
        # Parar sempre funciona, mesmo no meio de uma troca de qualidade ou de tela.
        self._stop_task = asyncio.ensure_future(self.stop_streaming())

    @Slot(str)
    def setQuality(self, preset: str) -> None:
        self._spawn(self.change_quality(preset))

    @Slot(str)
    def switchSource(self, key: str) -> None:
        self._spawn(self.change_source(key))

    @Slot()
    def copyLink(self) -> None:
        QGuiApplication.clipboard().setText(self.link)

    @Slot()
    def backToChoose(self) -> None:
        self.screen = "choose"
        self.error = ""
        self.refresh_sources()

    # --- ações ---------------------------------------------------------------------

    def refresh_sources(self, *, emit: bool = True) -> None:
        try:
            self._sources = self._sources_provider()
        except Exception:
            log.exception("Erro ao listar telas e janelas")
            self._sources = []
        if emit:
            self.emit_state()

    async def start_streaming(self, key: str, preset: str) -> None:
        source = self._find_source(key)
        if source is None or preset not in PRESETS:
            return
        self.live_source = source
        self.live_quality = preset
        self.notice = None
        self.screen = "preparing"
        self.emit_state()
        # Em caso de erro, a sessão já emitiu `error`, que mostra a tela de erro.
        with contextlib.suppress(SessionError):
            await self._session.start(source, resolve_quality(preset))

    async def stop_streaming(self) -> None:
        await self._session.stop()
        self.screen = "choose"
        self.busy = None
        self.notice = None
        self.refresh_sources()

    async def change_quality(self, preset: str) -> None:
        if self.screen != "live" or preset not in PRESETS or preset == self.live_quality:
            return
        self.busy = "quality"
        self.emit_state()
        try:
            await self._session.set_quality(resolve_quality(preset))
        except (SessionError, RuntimeError):
            log.exception("Não foi possível trocar a qualidade")
            self._notify(msg.QUALITY_FAILED, error=True)
        else:
            self.live_quality = preset
            self._notify(msg.QUALITY_CHANGED.format(name=msg.QUALITY_LABELS[preset][0]))
        finally:
            self.busy = None
            self.emit_state()

    async def change_source(self, key: str) -> None:
        source = self._find_source(key)
        if self.screen != "live" or source is None or source == self.live_source:
            return
        monitor_count = sum(s.kind is SourceKind.MONITOR for s in self._sources)
        self.busy = "source"
        self.emit_state()
        try:
            await self._session.switch_source(source)
        except (SessionError, RuntimeError):
            log.exception("Não foi possível trocar a fonte")
            current = source_label(self.live_source, monitor_count) if self.live_source else ""
            self._notify(msg.SWITCH_FAILED.format(name=current), error=True)
        else:
            self.live_source = source
            self._notify(msg.SOURCE_SWITCHED.format(name=source_label(source, monitor_count)))
        finally:
            self.busy = None
            self.emit_state()

    # --- eventos da sessão ---------------------------------------------------------

    def _on_link_ready(self, link: str) -> None:
        self.link = link
        self.viewers = 0
        self.screen = "live"
        self.emit_state()

    def _on_viewers_changed(self, count: int) -> None:
        self.viewers = count
        self.emit_state()

    def _on_sound_changed(self, state: SoundState) -> None:
        if state is SoundState.FAILED:
            self._notify(msg.SOUND_FAILED, error=True)
            self.emit_state()

    def _on_error(self, code: ErrorCode) -> None:
        if self.closing:
            return
        self.error = msg.error_message(code)
        self.screen = "error"
        self.busy = None
        self.emit_state()

    # --- auxiliares ----------------------------------------------------------------

    def _find_source(self, key: str) -> CaptureSource | None:
        return next((s for s in self._sources if source_key(s) == key), None)

    def _notify(self, text: str, *, error: bool = False) -> None:
        self.notice = {"id": next(self._notice_ids), "text": text, "error": error}

    def _spawn(self, coro) -> None:
        # Uma ação por vez (evita dois cliques em "Começar" abrirem duas transmissões).
        if self._task is not None and not self._task.done():
            coro.close()
            return
        self._task = asyncio.ensure_future(coro)
