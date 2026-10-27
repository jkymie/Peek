"""Troca de qualidade e de tela durante a transmissão, com uma captura falsa."""

import asyncio
import time
from typing import ClassVar

import numpy as np
import pytest

import host.session
from host.capture.video import CaptureClosed, CapturedFrame, CaptureError, CaptureSource, SourceKind
from host.rtc.quality import PRESETS
from host.session import ErrorCode, SessionError, SessionState, StreamSession
from host.tunnel import TunnelError

SCREEN = CaptureSource(SourceKind.MONITOR, 1, "Tela 1", 64, 48, primary=True)
WINDOW = CaptureSource(SourceKind.WINDOW, 42, "Filme", 32, 24)
BROKEN = CaptureSource(SourceKind.WINDOW, 99, "Quebrada")


class FakeCapture:
    created: ClassVar[list["FakeCapture"]] = []

    def __init__(self, source: CaptureSource, *, max_fps: int | None = 30) -> None:
        self.source = source
        self.max_fps = max_fps
        self.stopped = False
        self._closed = asyncio.Event()
        data = np.zeros((source.height or 2, source.width or 2, 4), dtype=np.uint8)
        self.latest: CapturedFrame | None = None
        self._frame = CapturedFrame(data, data.shape[1], data.shape[0], 1, time.monotonic())
        FakeCapture.created.append(self)

    @property
    def stopping(self) -> bool:
        return self.stopped

    async def start(self) -> None:
        if self.source is BROKEN:
            raise CaptureError("não deu")
        self.latest = self._frame

    async def next_frame(self, after: int = 0) -> CapturedFrame:
        if self.stopped:
            raise CaptureClosed("parada")
        return self._frame

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def stop(self) -> None:
        self.stopped = True
        self._closed.set()


class FakeTunnel:
    created: ClassVar[list["FakeTunnel"]] = []
    fail = False

    def __init__(self) -> None:
        self.local_url: str | None = None
        self.stopping = False
        self._closed = asyncio.Event()
        FakeTunnel.created.append(self)

    async def start(self, local_url: str) -> str:
        if FakeTunnel.fail:
            raise TunnelError("sem internet")
        self.local_url = local_url
        return "https://teste.trycloudflare.com"

    async def wait_closed(self) -> None:
        await self._closed.wait()

    def crash(self) -> None:
        self._closed.set()

    async def stop(self) -> None:
        self.stopping = True
        self._closed.set()


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FakeCapture.created = []
    FakeTunnel.created = []
    FakeTunnel.fail = False
    monkeypatch.setattr(host.session, "VideoCapture", FakeCapture)
    monkeypatch.setattr(host.session, "Tunnel", FakeTunnel)


@pytest.fixture
async def live_session():
    session = StreamSession(port=0, public=True)
    errors: list[ErrorCode] = []
    session.error.connect(errors.append)
    await session.start(SCREEN, PRESETS["equilibrada"])
    yield session, errors
    await session.stop()


async def test_switch_source_swaps_capture_without_stopping(live_session):
    session, errors = live_session
    first = FakeCapture.created[0]
    converter = session._converter

    await session.switch_source(WINDOW)

    second = FakeCapture.created[-1]
    assert second.source == WINDOW
    assert first.stopped and not second.stopped
    assert session.source == WINDOW
    assert session.state is SessionState.LIVE
    assert session._converter is converter  # os espectadores continuam nas mesmas tracks
    yuv = await converter.latest_yuv()
    assert yuv.shape == (24 * 3 // 2, 32)  # já é a imagem da janela nova
    assert not errors


async def test_failed_switch_keeps_previous_source(live_session):
    session, errors = live_session
    first = FakeCapture.created[0]

    with pytest.raises(SessionError) as exc:
        await session.switch_source(BROKEN)

    assert exc.value.code is ErrorCode.CAPTURE_FAILED
    assert session.source == SCREEN
    assert session.state is SessionState.LIVE
    assert not first.stopped
    assert not errors  # não derruba a transmissão


async def test_quality_with_same_fps_keeps_capture(live_session):
    session, _errors = live_session

    await session.set_quality(PRESETS["nitida"])

    assert len(FakeCapture.created) == 1
    assert session.quality.preset == "nitida"
    assert session._converter.quality.height == 1080


async def test_quality_with_other_fps_restarts_capture(live_session):
    session, _errors = live_session

    await session.set_quality(PRESETS["fluida"])

    assert len(FakeCapture.created) == 2
    assert FakeCapture.created[-1].max_fps == 60
    assert FakeCapture.created[-1].source == SCREEN
    assert FakeCapture.created[0].stopped
    assert session.quality.preset == "fluida"


async def test_changes_require_live_session():
    session = StreamSession(port=0, public=True)
    with pytest.raises(RuntimeError):
        await session.set_quality(PRESETS["nitida"])
    with pytest.raises(RuntimeError):
        await session.switch_source(WINDOW)


async def test_public_link_comes_from_tunnel(live_session):
    session, _errors = live_session
    tunnel = FakeTunnel.created[0]

    assert session.link.startswith("https://teste.trycloudflare.com/s/")
    assert tunnel.local_url == f"http://127.0.0.1:{session._server.port}"

    await session.stop()
    assert tunnel.stopping
    assert session.link is None


async def test_tunnel_failure_reports_error_and_cleans_up():
    FakeTunnel.fail = True
    session = StreamSession(port=0, public=True)
    errors: list[ErrorCode] = []
    session.error.connect(errors.append)

    with pytest.raises(SessionError) as exc:
        await session.start(SCREEN, PRESETS["equilibrada"])

    assert exc.value.code is ErrorCode.TUNNEL_FAILED
    assert errors == [ErrorCode.TUNNEL_FAILED]
    assert session.state is SessionState.IDLE
    assert FakeCapture.created[0].stopped
    assert session._server is None


async def test_tunnel_crash_ends_session(live_session):
    session, errors = live_session

    FakeTunnel.created[0].crash()
    for _ in range(50):
        if session.state is SessionState.IDLE:
            break
        await asyncio.sleep(0.01)

    assert session.state is SessionState.IDLE
    assert errors == [ErrorCode.TUNNEL_LOST]
    assert FakeCapture.created[0].stopped
