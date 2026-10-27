"""Tracks de mídia do aiortc.

Cada espectador tem a sua :class:`ScreenTrack` (o aiortc codifica uma vez por
conexão), mas a conversão do frame capturado (BGRA → YUV 4:2:0 no tamanho de
envio) é feita uma vez só e compartilhada por :class:`FrameConverter`.

O Windows só entrega frames quando a imagem muda, então a track não espera um
frame novo: ela segue o FPS pedido e reenvia o último frame quando a tela está
parada.

O som segue a mesma ideia: :class:`SystemAudioTrack` manda 20 ms por vez, no ritmo
do relógio, e completa com silêncio quando não há nada tocando.
"""

from __future__ import annotations

import asyncio
import fractions
import logging
import time
from typing import Protocol

import av
import numpy as np
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError

from host.capture.audio import CHANNELS, SAMPLE_RATE, AudioCapture
from host.capture.video import CaptureClosed, CapturedFrame
from host.rtc.quality import Quality, scaled_size

log = logging.getLogger(__name__)

VIDEO_CLOCK_RATE = 90_000
VIDEO_TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK_RATE)
AUDIO_TIME_BASE = fractions.Fraction(1, SAMPLE_RATE)
AUDIO_FRAME_SAMPLES = SAMPLE_RATE // 50  # 20 ms, o tamanho de pacote do Opus
# Se a track atrasar mais que isso (PC sobrecarregado), recomeça a agenda em vez de
# mandar uma rajada de frames para "alcançar" o tempo perdido.
MAX_LAG_SECONDS = 0.5


class FrameProvider(Protocol):
    """O que a track precisa da captura (permite usar uma captura falsa nos testes)."""

    @property
    def latest(self) -> CapturedFrame | None: ...

    async def next_frame(self, after: int = 0) -> CapturedFrame: ...


class FrameConverter:
    """Converte o frame mais recente para o tamanho de envio, uma vez por frame capturado."""

    def __init__(self, provider: FrameProvider, quality: Quality) -> None:
        self._provider = provider
        self.quality = quality
        self._lock = asyncio.Lock()
        self._generation = 0
        self._cache_key: tuple[int, int, int | None] | None = None
        self._cache: np.ndarray | None = None

    def set_provider(self, provider: FrameProvider) -> None:
        """Troca a captura (outra tela/janela ou outro FPS) sem mexer nas tracks."""
        self._provider = provider
        # A captura nova recomeça o ``seq`` em 1: o cache precisa saber de qual captura é.
        self._generation += 1

    async def latest_yuv(self) -> np.ndarray:
        """Frame mais recente em YUV 4:2:0 (``(altura * 3 / 2, largura)``, ``uint8``)."""
        provider = self._provider
        frame = provider.latest
        if frame is None:
            try:
                frame = await provider.next_frame()
            except CaptureClosed:
                if provider is self._provider:
                    raise
                # A captura foi trocada enquanto esperávamos: usa a nova.
                return await self.latest_yuv()
        async with self._lock:
            # Outro espectador pode ter convertido este mesmo frame enquanto esperávamos.
            frame = self._provider.latest or frame
            key = (self._generation, frame.seq, self.quality.height)
            if key != self._cache_key:
                self._cache = await asyncio.to_thread(self._convert, frame, self.quality.height)
                self._cache_key = key
            return self._cache

    @staticmethod
    def _convert(frame: CapturedFrame, target_height: int | None) -> np.ndarray:
        width, height = scaled_size(frame.width, frame.height, target_height)
        source = av.VideoFrame.from_ndarray(frame.data, format="bgra")
        return source.reformat(width=width, height=height, format="yuv420p").to_ndarray()


class ScreenTrack(MediaStreamTrack):
    """Track de vídeo de um espectador, no FPS da qualidade atual."""

    kind = "video"

    def __init__(self, converter: FrameConverter) -> None:
        super().__init__()
        self._converter = converter
        self._start: float | None = None
        self._timestamp = 0

    async def recv(self) -> av.VideoFrame:
        if self.readyState != "live":
            raise MediaStreamError
        await self._wait_next_slot()
        try:
            yuv = await self._converter.latest_yuv()
        except CaptureClosed:
            self.stop()
            raise MediaStreamError from None

        # Um av.VideoFrame novo por track: os codificadores rodam em threads separadas e
        # cada espectador tem seus próprios timestamps.
        frame = av.VideoFrame.from_ndarray(yuv, format="yuv420p")
        frame.pts = self._timestamp
        frame.time_base = VIDEO_TIME_BASE
        return frame

    async def _wait_next_slot(self) -> None:
        now = time.monotonic()
        if self._start is None:
            self._start = now
            return
        self._timestamp += VIDEO_CLOCK_RATE // self._converter.quality.fps
        wait = self._start + self._timestamp / VIDEO_CLOCK_RATE - now
        if wait > 0:
            await asyncio.sleep(wait)
        elif wait < -MAX_LAG_SECONDS:
            self._start = now - self._timestamp / VIDEO_CLOCK_RATE


class SystemAudioTrack(MediaStreamTrack):
    """Track de som de um espectador: o áudio do sistema, sem o Discord."""

    kind = "audio"

    def __init__(self, capture: AudioCapture) -> None:
        super().__init__()
        self._capture = capture
        self._buffer = capture.subscribe()
        self._start: float | None = None
        self._timestamp = 0

    async def recv(self) -> av.AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError
        await self._wait_next_slot()
        samples = self._buffer.pull(AUDIO_FRAME_SAMPLES)
        if samples is None:
            pcm = np.zeros((1, AUDIO_FRAME_SAMPLES * CHANNELS), dtype=np.int16)
        else:
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="stereo")
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self._timestamp
        frame.time_base = AUDIO_TIME_BASE
        return frame

    def stop(self) -> None:
        self._capture.unsubscribe(self._buffer)
        super().stop()

    async def _wait_next_slot(self) -> None:
        now = time.monotonic()
        if self._start is None:
            self._start = now
            return
        self._timestamp += AUDIO_FRAME_SAMPLES
        wait = self._start + self._timestamp / SAMPLE_RATE - now
        if wait > 0:
            await asyncio.sleep(wait)
        elif wait < -MAX_LAG_SECONDS:
            self._start = now - self._timestamp / SAMPLE_RATE
