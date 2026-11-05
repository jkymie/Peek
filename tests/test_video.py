import asyncio

import numpy as np
import pytest

from host.capture.video import (
    CaptureClosed,
    CaptureSource,
    SourceKind,
    VideoCapture,
    _FrameThrottle,
    grab_frame,
    list_monitors,
    list_windows,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _accepted_over(
    throttle: _FrameThrottle, clock: FakeClock, arrival_interval: float, seconds: float
):
    accepted = 0
    steps = round(seconds / arrival_interval)
    for i in range(steps):
        clock.now = i * arrival_interval
        accepted += throttle.accept()
    return accepted


@pytest.mark.parametrize(("max_fps", "expected"), [(30, 30), (15, 15), (60, 60)])
def test_throttle_follows_target_fps_with_60hz_arrivals(max_fps, expected):
    clock = FakeClock()
    throttle = _FrameThrottle(max_fps, clock)
    # Monitor de 60 Hz entrega 60 frames por segundo; o teto de 60 fps deve aceitar todos.
    accepted = _accepted_over(throttle, clock, 1 / 60, seconds=10)
    assert accepted == pytest.approx(expected * 10, abs=2)


def test_throttle_accepts_first_frame_after_static_screen():
    clock = FakeClock()
    throttle = _FrameThrottle(30, clock)
    assert throttle.accept()
    clock.now = 5.0  # tela parada por 5 s
    assert throttle.accept()
    clock.now = 5.01
    assert not throttle.accept()


def test_throttle_without_limit_accepts_everything():
    throttle = _FrameThrottle(None)
    assert all(throttle.accept() for _ in range(100))


def _fake_capture() -> VideoCapture:
    capture = VideoCapture(CaptureSource(SourceKind.MONITOR, 1, "Tela 1"))
    capture._loop = asyncio.get_running_loop()
    capture._waiter = capture._loop.create_future()
    return capture


def _frame(value: int) -> np.ndarray:
    return np.full((4, 6, 4), value, dtype=np.uint8)


async def test_next_frame_delivers_latest_to_multiple_consumers():
    capture = _fake_capture()
    consumers = [asyncio.create_task(capture.next_frame()) for _ in range(3)]
    await asyncio.sleep(0)
    capture._publish(_frame(1), 0.0)
    frames = await asyncio.gather(*consumers)
    assert {f.seq for f in frames} == {1}
    assert (frames[0].width, frames[0].height) == (6, 4)


async def test_next_frame_skips_stale_frames():
    capture = _fake_capture()
    for value in (1, 2, 3):
        capture._publish(_frame(value), 0.0)
    frame = await capture.next_frame(after=1)
    assert frame.seq == 3
    assert frame.data[0, 0, 0] == 3


async def test_cancelled_consumer_does_not_break_others():
    capture = _fake_capture()
    cancelled = asyncio.create_task(capture.next_frame())
    other = asyncio.create_task(capture.next_frame())
    await asyncio.sleep(0)
    cancelled.cancel()
    await asyncio.sleep(0)
    capture._publish(_frame(1), 0.0)
    assert (await other).seq == 1


async def test_next_frame_raises_when_source_closes():
    capture = _fake_capture()
    waiting = asyncio.create_task(capture.next_frame())
    await asyncio.sleep(0)
    capture._mark_closed()
    with pytest.raises(CaptureClosed):
        await waiting


# --- integração: precisa de uma sessão gráfica do Windows --------------------


@pytest.mark.capture
def test_list_monitors_has_a_primary():
    monitors = list_monitors()
    assert monitors
    assert [m.id for m in monitors] == list(range(1, len(monitors) + 1))
    assert sum(m.primary for m in monitors) == 1
    assert all(m.width > 0 and m.height > 0 for m in monitors)


@pytest.mark.capture
def test_list_windows_have_titles():
    assert all(w.name and w.kind is SourceKind.WINDOW for w in list_windows())


@pytest.mark.capture
def test_grab_frame_from_primary_monitor_matches_resolution():
    monitor = next(m for m in list_monitors() if m.primary)
    frame = grab_frame(monitor)
    assert frame.data.shape == (monitor.height, monitor.width, 4)
    assert frame.data.dtype == np.uint8
    assert frame.data.any()  # não é uma imagem toda preta


@pytest.mark.capture
async def test_video_capture_delivers_frames():
    capture = VideoCapture(list_monitors()[0], max_fps=30)
    await capture.start()
    try:
        frame = await asyncio.wait_for(capture.next_frame(), timeout=5)
        assert frame.seq >= 1
    finally:
        await capture.stop()
    assert not capture.running


def test_capture_options_fall_back_to_simpler_settings():
    from host.capture.video import _capture_options

    assert _capture_options(30) == [
        {"cursor_capture": True, "minimum_update_interval": 16},
        {"cursor_capture": True},
        {"cursor_capture": None},
    ]
    assert _capture_options(None) == [{"cursor_capture": True}, {"cursor_capture": None}]


def test_start_capture_retries_when_start_fails(monkeypatch):
    import sys
    import types

    from host.capture import video

    attempts = []

    class FakeWindowsCapture:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def event(self, handler):
            return handler

        def start_free_threaded(self):
            attempts.append(self.kwargs)
            if "minimum_update_interval" in self.kwargs:
                raise RuntimeError("Setting a minimum update interval is not supported")
            return "control"

    monkeypatch.setitem(
        sys.modules, "windows_capture", types.SimpleNamespace(WindowsCapture=FakeWindowsCapture)
    )
    source = CaptureSource(SourceKind.MONITOR, 1, "Tela 1")
    assert video._start_capture(source, 30, lambda f, c: None, lambda: None) == "control"
    assert len(attempts) == 2
    assert "minimum_update_interval" not in attempts[1]

    FakeWindowsCapture.start_free_threaded = lambda self: (_ for _ in ()).throw(OSError("boom"))
    with pytest.raises(video.CaptureError, match="boom"):
        video._start_capture(source, 30, lambda f, c: None, lambda: None)
