"""Camada de controle da transmissão.

A janela do Peek e o modo ``--headless`` usam só esta classe: nunca falam
diretamente com a captura, o aiortc ou o servidor. Os eventos são callbacks
simples (:class:`Signal`), que a janela liga aos sinais do Qt.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from host.capture.video import CaptureError, CaptureSource, VideoCapture
from host.resources import web_dir
from host.rtc.quality import Quality, apply_bitrate_cap
from host.rtc.tracks import FrameConverter, ScreenTrack
from host.server import ViewerServer, lan_ip

log = logging.getLogger(__name__)

FIRST_FRAME_TIMEOUT = 5.0


class SessionState(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    LIVE = "live"
    STOPPING = "stopping"


class ErrorCode(StrEnum):
    CAPTURE_FAILED = "capture_failed"
    NO_FRAMES = "no_frames"
    SOURCE_CLOSED = "source_closed"
    SERVER_FAILED = "server_failed"
    UNEXPECTED = "unexpected"


class SessionError(Exception):
    def __init__(self, code: ErrorCode, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else str(code))
        self.code = code
        self.detail = detail


class Signal:
    """Lista de callbacks. Exceções de um callback não derrubam a sessão."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._callbacks: list[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        self._callbacks.append(callback)

    def emit(self, *args: Any) -> None:
        for callback in list(self._callbacks):
            try:
                callback(*args)
            except Exception:
                log.exception("Erro em um callback", extra={"signal": self._name})


class StreamSession:
    """Uma transmissão por vez: ``start()`` → ao vivo → ``stop()``.

    Sinais:

    * ``state_changed(SessionState)``
    * ``link_ready(str)``: link para mandar aos amigos
    * ``viewers_changed(int)``
    * ``error(ErrorCode)``: a transmissão parou ou não começou

    Durante a transmissão, :meth:`set_quality` e :meth:`switch_source` mudam o que os
    espectadores recebem sem desconectar ninguém.
    """

    def __init__(self, *, port: int = 8080, public: bool = False) -> None:
        self.port = port
        # public=True: servidor só em 127.0.0.1, exposto pelo cloudflared (Fase 3).
        # public=False: servidor na rede local, para testes com --no-tunnel.
        self.public = public
        self.state_changed = Signal("state_changed")
        self.link_ready = Signal("link_ready")
        self.viewers_changed = Signal("viewers_changed")
        self.error = Signal("error")

        self._state = SessionState.IDLE
        self._capture: VideoCapture | None = None
        self._converter: FrameConverter | None = None
        self._server: ViewerServer | None = None
        self._watch_task: asyncio.Task | None = None
        self._link: str | None = None
        self._source: CaptureSource | None = None
        self._quality: Quality | None = None
        self._swap_lock = asyncio.Lock()

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def link(self) -> str | None:
        return self._link

    @property
    def source(self) -> CaptureSource | None:
        return self._source

    @property
    def quality(self) -> Quality | None:
        return self._quality

    @property
    def viewers(self) -> int:
        return self._server.viewer_count if self._server else 0

    async def start(self, source: CaptureSource, quality: Quality) -> str:
        """Começa a transmitir e devolve o link. Em caso de erro, emite ``error`` e levanta
        :class:`SessionError`."""
        if self._state is not SessionState.IDLE:
            raise RuntimeError(f"Sessão não está parada (estado: {self._state})")
        self._set_state(SessionState.PREPARING)
        log.info(
            "Iniciando transmissão",
            extra={"source_kind": source.kind, "source_id": source.id, "quality": quality.preset},
        )
        try:
            link = await self._start(source, quality)
        except SessionError as exc:
            log.error("Falha ao iniciar", extra={"code": exc.code, "detail": exc.detail})
            await self._teardown()
            self.error.emit(exc.code)
            raise
        except Exception as exc:
            log.exception("Erro inesperado ao iniciar")
            await self._teardown()
            self.error.emit(ErrorCode.UNEXPECTED)
            raise SessionError(ErrorCode.UNEXPECTED, str(exc)) from exc

        self._link = link
        self._set_state(SessionState.LIVE)
        self.link_ready.emit(link)
        log.info("Ao vivo", extra={"link": link})
        return link

    async def stop(self) -> None:
        if self._state in (SessionState.IDLE, SessionState.STOPPING):
            return
        log.info("Parando transmissão")
        await self._teardown()

    async def set_quality(self, quality: Quality) -> None:
        """Troca a qualidade durante a transmissão. Em caso de erro, levanta
        :class:`SessionError` e mantém a qualidade anterior."""
        self._require_live()
        log.info("Trocando qualidade", extra={"quality": quality.preset})
        if quality.fps != self._capture.max_fps:
            # O limite de FPS da captura é decidido quando ela é criada.
            await self._swap_capture(self._source, quality.fps)
            if self._state is not SessionState.LIVE:
                return
        apply_bitrate_cap(quality.bitrate_kbps)
        self._converter.quality = quality
        self._quality = quality

    async def switch_source(self, source: CaptureSource) -> None:
        """Passa a mostrar outra tela ou janela. Se ela não funcionar, levanta
        :class:`SessionError` e continua mostrando a anterior."""
        self._require_live()
        log.info("Trocando fonte", extra={"source_kind": source.kind, "source_id": source.id})
        await self._swap_capture(source, self._quality.fps)
        if self._state is SessionState.LIVE:
            self._source = source

    # --- internos ---------------------------------------------------------------

    def _require_live(self) -> None:
        if self._state is not SessionState.LIVE:
            raise RuntimeError(f"Sessão não está transmitindo (estado: {self._state})")

    async def _swap_capture(self, source: CaptureSource, fps: int) -> None:
        """Inicia uma captura nova e só troca quando ela já tem imagem."""
        async with self._swap_lock:
            capture = VideoCapture(source, max_fps=fps)
            try:
                await capture.start()
            except CaptureError as exc:
                raise SessionError(ErrorCode.CAPTURE_FAILED, str(exc)) from exc
            try:
                await asyncio.wait_for(capture.next_frame(), FIRST_FRAME_TIMEOUT)
            except (TimeoutError, CaptureError) as exc:
                await capture.stop()
                raise SessionError(ErrorCode.NO_FRAMES, str(exc)) from exc
            if self._state is not SessionState.LIVE or self._converter is None:
                await capture.stop()  # a transmissão parou enquanto esperávamos
                return

            old, self._capture = self._capture, capture
            self._converter.set_provider(capture)
            watch, self._watch_task = (
                self._watch_task,
                asyncio.create_task(self._watch_capture(capture)),
            )
            if watch is not None:
                watch.cancel()
            if old is not None:
                await old.stop()

    async def _start(self, source: CaptureSource, quality: Quality) -> str:
        apply_bitrate_cap(quality.bitrate_kbps)
        self._source = source
        self._quality = quality

        self._capture = VideoCapture(source, max_fps=quality.fps)
        try:
            await self._capture.start()
        except CaptureError as exc:
            raise SessionError(ErrorCode.CAPTURE_FAILED, str(exc)) from exc
        try:
            await asyncio.wait_for(self._capture.next_frame(), FIRST_FRAME_TIMEOUT)
        except (TimeoutError, CaptureError) as exc:
            raise SessionError(ErrorCode.NO_FRAMES, str(exc)) from exc

        self._converter = FrameConverter(self._capture, quality)
        token = secrets.token_urlsafe(16)
        self._server = ViewerServer(
            token=token,
            make_track=lambda: ScreenTrack(self._converter),
            on_viewers_changed=self.viewers_changed.emit,
            web_dir=web_dir(),
            host="127.0.0.1" if self.public else "0.0.0.0",
            port=self.port,
        )
        try:
            await self._server.start()
        except OSError as exc:
            raise SessionError(ErrorCode.SERVER_FAILED, str(exc)) from exc

        self._watch_task = asyncio.create_task(self._watch_capture(self._capture))
        # TODO(Fase 3): com public=True, iniciar o cloudflared e usar a URL dele.
        return f"http://{lan_ip()}:{self._server.port}{self._server.viewer_path()}"

    async def _watch_capture(self, capture: VideoCapture) -> None:
        await capture.wait_closed()
        if capture.stopping or self._state is not SessionState.LIVE:
            return
        log.warning("A fonte transmitida sumiu")
        await self._teardown()
        self.error.emit(ErrorCode.SOURCE_CLOSED)

    async def _teardown(self) -> None:
        self._set_state(SessionState.STOPPING)
        watch, self._watch_task = self._watch_task, None
        if watch is not None and watch is not asyncio.current_task():
            watch.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch
        server, self._server = self._server, None
        if server is not None:
            await server.stop()
        capture, self._capture = self._capture, None
        if capture is not None:
            await capture.stop()
        self._converter = None
        self._link = None
        self._source = None
        self._quality = None
        self._set_state(SessionState.IDLE)

    def _set_state(self, state: SessionState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)
