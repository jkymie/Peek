"""Ponta a ponta sem tela nem navegador: captura falsa → servidor → espectador aiortc."""

import asyncio
import time

import aiohttp
import numpy as np
import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription

from host.capture.video import CaptureClosed, CapturedFrame
from host.resources import web_dir
from host.rtc.quality import PRESETS, resolve_quality
from host.rtc.tracks import FrameConverter, ScreenTrack
from host.server import ViewerServer

TOKEN = "token-de-teste"


class FakeProvider:
    """Imita VideoCapture: um frame fixo, que só muda quando o teste pede."""

    def __init__(self, width: int, height: int) -> None:
        self._data = np.zeros((height, width, 4), dtype=np.uint8)
        self._data[..., 2] = 200  # vermelho em BGRA
        self._seq = 0
        self.closed = False
        self.push()

    def push(self) -> None:
        self._seq += 1
        h, w = self._data.shape[:2]
        self._latest = CapturedFrame(self._data, w, h, self._seq, time.monotonic())

    @property
    def latest(self) -> CapturedFrame:
        return self._latest

    async def next_frame(self, after: int = 0) -> CapturedFrame:
        if self.closed:
            raise CaptureClosed("fechada")
        return self._latest


@pytest.fixture
async def stream():
    provider = FakeProvider(1920, 1080)
    converter = FrameConverter(provider, PRESETS["economica"])
    counts: list[int] = []
    server = ViewerServer(
        token=TOKEN,
        make_track=lambda: ScreenTrack(converter),
        on_viewers_changed=counts.append,
        web_dir=web_dir(),
        host="127.0.0.1",
        port=0,
        ice_servers=(),
    )
    await server.start()
    yield server, counts, provider
    await server.stop()


async def _connect_viewer(http: aiohttp.ClientSession, port: int):
    ws = await http.ws_connect(f"http://127.0.0.1:{port}/s/{TOKEN}/ws")
    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    received: asyncio.Future = asyncio.get_running_loop().create_future()

    @pc.on("track")
    def on_track(track):
        received.set_result(track)

    await pc.setLocalDescription(await pc.createOffer())
    await ws.send_json({"type": "offer", "sdp": pc.localDescription.sdp})
    answer = await ws.receive_json(timeout=10)
    assert answer["type"] == "answer"
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
    track = await asyncio.wait_for(received, 10)
    return ws, pc, track


async def _wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condição não atingida a tempo")
        await asyncio.sleep(0.05)


async def test_viewer_receives_scaled_video_and_is_counted(stream):
    server, counts, _provider = stream
    async with aiohttp.ClientSession() as http:
        ws, pc, track = await _connect_viewer(http, server.port)
        frame = await asyncio.wait_for(track.recv(), 15)
        # 1920x1080 em "Econômica" (480p), mantendo a proporção e com largura par.
        assert (frame.width, frame.height) == (854, 480)
        await _wait_for(lambda: server.viewer_count == 1)
        assert counts[-1] == 1

        await pc.close()
        await ws.close()
        await _wait_for(lambda: server.viewer_count == 0)
        assert counts[-1] == 0


async def test_static_screen_still_produces_frames_at_target_fps(stream):
    server, _counts, _provider = stream
    async with aiohttp.ClientSession() as http:
        ws, pc, track = await _connect_viewer(http, server.port)
        await asyncio.wait_for(track.recv(), 15)
        started = time.monotonic()
        for _ in range(15):
            await asyncio.wait_for(track.recv(), 5)
        # Nenhum frame novo na captura, mas a track continua no ritmo (~30 fps).
        assert time.monotonic() - started < 2.0
        await pc.close()
        await ws.close()


async def test_stop_notifies_viewers(stream):
    server, _counts, _provider = stream
    async with aiohttp.ClientSession() as http:
        ws, pc, _track = await _connect_viewer(http, server.port)
        await server.stop()
        message = await ws.receive_json(timeout=5)
        assert message == {"type": "ended"}
        await pc.close()


async def test_wrong_token_is_rejected(stream):
    server, _counts, _provider = stream
    base = f"http://127.0.0.1:{server.port}"
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{base}/s/{TOKEN}") as response:
            assert response.status == 200
            assert response.headers["Referrer-Policy"] == "no-referrer"
        async with http.get(f"{base}/s/outro-token") as response:
            assert response.status == 404
        with pytest.raises(aiohttp.WSServerHandshakeError):
            await http.ws_connect(f"{base}/s/outro-token/ws")


async def test_room_full(stream):
    server, _counts, _provider = stream
    server._max_viewers = 0
    async with aiohttp.ClientSession() as http:
        ws = await http.ws_connect(f"http://127.0.0.1:{server.port}/s/{TOKEN}/ws")
        assert await ws.receive_json(timeout=5) == {"type": "full"}
        await ws.close()


def test_resolve_quality_overrides():
    quality = resolve_quality("nitida", resolution="original", fps=60, bitrate_kbps=2000)
    assert (quality.height, quality.fps, quality.bitrate_kbps) == (None, 60, 2000)
