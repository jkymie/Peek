"""Som: buffer por espectador, track no ritmo do relógio e o helper (falso) rodando."""

import asyncio
import sys

import numpy as np
import pytest

from host.capture.audio import (
    BYTES_PER_FRAME,
    MAX_BUFFER_SECONDS,
    SAMPLE_RATE,
    AudioBuffer,
    AudioCapture,
    AudioError,
)
from host.rtc.tracks import AUDIO_FRAME_SAMPLES, SystemAudioTrack


def pcm(frames: int, value: float = 0.5) -> bytes:
    return np.full((frames, 2), value, dtype="<f4").tobytes()


def test_buffer_waits_for_enough_audio_then_plays():
    buffer = AudioBuffer()
    buffer.push(pcm(AUDIO_FRAME_SAMPLES))  # 20 ms: menos que o mínimo para voltar a tocar
    assert buffer.pull(AUDIO_FRAME_SAMPLES) is None

    buffer.push(pcm(AUDIO_FRAME_SAMPLES))
    samples = buffer.pull(AUDIO_FRAME_SAMPLES)
    assert samples.shape == (AUDIO_FRAME_SAMPLES, 2)
    assert np.allclose(samples, 0.5)
    # Já tocando, 20 ms bastam.
    assert buffer.pull(AUDIO_FRAME_SAMPLES) is not None
    assert buffer.pull(AUDIO_FRAME_SAMPLES) is None


def test_buffer_drops_old_audio_when_viewer_falls_behind():
    buffer = AudioBuffer()
    buffer.push(pcm(int(SAMPLE_RATE * MAX_BUFFER_SECONDS * 2)))
    assert len(buffer._data) < SAMPLE_RATE * MAX_BUFFER_SECONDS * BYTES_PER_FRAME


class FakeCapture:
    def __init__(self) -> None:
        self.buffer = AudioBuffer()
        self.unsubscribed = False

    def subscribe(self) -> AudioBuffer:
        return self.buffer

    def unsubscribe(self, buffer: AudioBuffer) -> None:
        self.unsubscribed = True


async def test_track_sends_silence_then_sound():
    capture = FakeCapture()
    track = SystemAudioTrack(capture)

    silent = await track.recv()
    assert silent.samples == AUDIO_FRAME_SAMPLES
    assert silent.sample_rate == SAMPLE_RATE
    assert not silent.to_ndarray().any()

    capture.buffer.push(pcm(AUDIO_FRAME_SAMPLES * 3))
    loud = await track.recv()
    assert loud.pts == AUDIO_FRAME_SAMPLES
    assert loud.to_ndarray().max() == int(0.5 * 32767)

    track.stop()
    assert capture.unsubscribed


# Imita o peek-audio.exe. Modos: "ok" (encontra o Discord e manda 0,5 s de áudio) e
# "old_windows" (sai com o erro de Windows incompatível).
FAKE_HELPER = """\
import sys, time

mode, chunk = sys.argv[1], sys.argv[2]
if mode == "old_windows":
    print("ERROR unsupported_os build=19045", file=sys.stderr, flush=True)
    sys.exit(2)
print("STATUS discord_found pid=1234", file=sys.stderr, flush=True)
print("STATUS capturing", file=sys.stderr, flush=True)
data = open(chunk, "rb").read()
for _ in range(50):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    time.sleep(0.01)
time.sleep(30)
"""


def fake_helper(tmp_path, mode: str) -> list[str]:
    script = tmp_path / "peek_audio.py"
    script.write_text(FAKE_HELPER, encoding="utf-8")
    chunk = tmp_path / "chunk.raw"
    chunk.write_bytes(pcm(480))
    return [sys.executable, str(script), mode, str(chunk)]


async def test_capture_delivers_audio_to_each_subscriber(tmp_path):
    capture = AudioCapture(command=fake_helper(tmp_path, "ok"))
    await capture.start()
    try:
        assert capture.discord_pid == 1234
        first, second = capture.subscribe(), capture.subscribe()
        await asyncio.sleep(0.3)
        assert first.pull(AUDIO_FRAME_SAMPLES) is not None
        assert second.pull(AUDIO_FRAME_SAMPLES) is not None
    finally:
        await capture.stop()


async def test_capture_reports_helper_error(tmp_path):
    with pytest.raises(AudioError) as exc:
        await AudioCapture(command=fake_helper(tmp_path, "old_windows")).start()
    assert exc.value.code == "unsupported_os"


async def test_missing_helper(tmp_path):
    with pytest.raises(AudioError) as exc:
        await AudioCapture(command=[str(tmp_path / "nao-existe.exe")]).start()
    assert exc.value.code == "helper_failed"
