import asyncio
import json
import re

import pytest
from PySide6.QtGui import QGuiApplication

from host.capture.video import CaptureSource, SourceKind
from host.gui import messages as msg
from host.gui.bridge import Bridge, source_key, source_label
from host.session import ErrorCode, SessionError, SessionState, Signal

MONITOR = CaptureSource(SourceKind.MONITOR, 1, "Tela 1", 1920, 1080, primary=True)
WINDOW = CaptureSource(SourceKind.WINDOW, 1234, "Filme.mp4 - VLC", process_name="vlc.exe")
LINK = "http://192.168.0.10:8080/s/abc"


class FakeSession:
    """Mesma interface pública da StreamSession, sem captura nem rede."""

    def __init__(self, *, fail_with: ErrorCode | None = None, swap_fails: bool = False) -> None:
        self.state_changed = Signal("state_changed")
        self.link_ready = Signal("link_ready")
        self.viewers_changed = Signal("viewers_changed")
        self.sound_changed = Signal("sound_changed")
        self.error = Signal("error")
        self.state = SessionState.IDLE
        self.public = True
        self.started_with = None
        self.quality = None
        self.source = None
        self.stopped = False
        self._fail_with = fail_with
        self._swap_fails = swap_fails

    async def start(self, source, quality):
        self.started_with = (source, quality)
        if self._fail_with is not None:
            self.error.emit(self._fail_with)
            raise SessionError(self._fail_with)
        self.state = SessionState.LIVE
        self.source, self.quality = source, quality
        self.link_ready.emit(LINK)
        return LINK

    async def stop(self):
        self.stopped = True
        self.state = SessionState.IDLE
        self.viewers_changed.emit(0)

    async def set_quality(self, quality):
        if self._swap_fails:
            raise SessionError(ErrorCode.NO_FRAMES)
        self.quality = quality

    async def switch_source(self, source):
        if self._swap_fails:
            raise SessionError(ErrorCode.CAPTURE_FAILED)
        self.source = source


@pytest.fixture
def make_bridge(qtbot):
    def _make(session, sources=(MONITOR, WINDOW)):
        bridge = Bridge(session, sources_provider=lambda: list(sources))
        states: list[dict] = []
        bridge.state_changed.connect(lambda payload: states.append(json.loads(payload)))
        bridge.states = states
        return bridge

    return _make


def test_initial_state_lists_sources_and_qualities(make_bridge):
    bridge = make_bridge(FakeSession())
    bridge.ready()
    state = bridge.states[-1]

    assert state["screen"] == "choose"
    assert [s["key"] for s in state["sources"]] == ["monitor:1", "window:1234"]
    assert state["sources"][0]["detail"] == "1920 x 1080"
    assert state["sources"][1] == {
        "key": "window:1234",
        "kind": "window",
        "title": "Filme.mp4 - VLC",
        "detail": "vlc",
        "label": "Filme.mp4 - VLC  ·  vlc",
    }
    assert state["defaultQuality"] == "equilibrada"
    nitida = next(q for q in state["qualities"] if q["id"] == "nitida")
    assert nitida == {
        "id": "nitida",
        "name": "Nítida",
        "description": "Para filmes, séries e textos",
        "details": "1080p · 30 fps",
    }
    assert state["texts"]["START"] == msg.START


async def test_start_shows_link_and_counts_viewers(make_bridge):
    session = FakeSession()
    bridge = make_bridge(session)

    await bridge.start_streaming(source_key(MONITOR), "nitida")

    source, quality = session.started_with
    assert source == MONITOR
    assert quality.preset == "nitida"
    assert [s["screen"] for s in bridge.states] == ["preparing", "live"]
    state = bridge.states[-1]
    assert state["link"] == LINK
    assert state["quality"] == "nitida"
    assert state["liveSourceLabel"] == "Tela inteira"
    assert state["viewersText"] == msg.viewers_text(0)

    session.viewers_changed.emit(2)
    assert bridge.states[-1]["viewersText"] == "2 pessoas assistindo"


async def test_unknown_source_or_quality_does_nothing(make_bridge):
    session = FakeSession()
    bridge = make_bridge(session)
    await bridge.start_streaming("window:999", "nitida")
    await bridge.start_streaming(source_key(MONITOR), "ultra")
    assert session.started_with is None


async def test_copy_link(make_bridge):
    bridge = make_bridge(FakeSession())
    await bridge.start_streaming(source_key(MONITOR), "equilibrada")
    bridge.copyLink()
    assert QGuiApplication.clipboard().text() == LINK


async def test_change_quality_while_live(make_bridge):
    session = FakeSession()
    bridge = make_bridge(session)
    await bridge.start_streaming(source_key(MONITOR), "equilibrada")

    await bridge.change_quality("fluida")

    assert session.quality.preset == "fluida"
    assert session.quality.fps == 60
    busy = [s["busy"] for s in bridge.states[-2:]]
    assert busy == ["quality", None]
    state = bridge.states[-1]
    assert state["quality"] == "fluida"
    assert state["notice"]["text"] == msg.QUALITY_CHANGED.format(name="Fluida")
    assert not state["notice"]["error"]


async def test_failed_quality_change_keeps_previous(make_bridge):
    bridge = make_bridge(FakeSession(swap_fails=True))
    await bridge.start_streaming(source_key(MONITOR), "equilibrada")

    await bridge.change_quality("maxima")

    state = bridge.states[-1]
    assert state["screen"] == "live"
    assert state["quality"] == "equilibrada"
    assert state["notice"] == {"id": 1, "text": msg.QUALITY_FAILED, "error": True}


async def test_switch_source_while_live(make_bridge):
    session = FakeSession()
    bridge = make_bridge(session)
    await bridge.start_streaming(source_key(MONITOR), "equilibrada")

    await bridge.change_source(source_key(WINDOW))

    assert session.source == WINDOW
    state = bridge.states[-1]
    assert state["liveSource"] == "window:1234"
    assert state["liveSourceLabel"] == source_label(WINDOW, 1)
    assert state["notice"]["text"] == msg.SOURCE_SWITCHED.format(name=source_label(WINDOW, 1))


async def test_failed_switch_keeps_showing_previous_source(make_bridge):
    bridge = make_bridge(FakeSession(swap_fails=True))
    await bridge.start_streaming(source_key(MONITOR), "equilibrada")

    await bridge.change_source(source_key(WINDOW))

    state = bridge.states[-1]
    assert state["screen"] == "live"
    assert state["liveSource"] == "monitor:1"
    assert state["notice"]["text"] == msg.SWITCH_FAILED.format(name="Tela inteira")
    assert state["notice"]["error"]


async def test_stop_returns_to_choose(make_bridge):
    session = FakeSession()
    bridge = make_bridge(session)
    await bridge.start_streaming(source_key(MONITOR), "equilibrada")
    await bridge.stop_streaming()
    assert session.stopped
    assert bridge.states[-1]["screen"] == "choose"


async def test_error_shows_plain_message_and_retry(make_bridge):
    bridge = make_bridge(FakeSession(fail_with=ErrorCode.NO_FRAMES))
    await bridge.start_streaming(source_key(MONITOR), "equilibrada")
    state = bridge.states[-1]
    assert state["screen"] == "error"
    assert state["error"] == msg.error_message(ErrorCode.NO_FRAMES)

    bridge.backToChoose()
    assert bridge.states[-1]["screen"] == "choose"


async def test_only_one_action_at_a_time(make_bridge):
    session = FakeSession()
    bridge = make_bridge(session)
    bridge.start(source_key(MONITOR), "equilibrada")
    bridge.start(source_key(WINDOW), "nitida")  # segundo clique: ignorado
    await asyncio.sleep(0)
    await bridge._task
    assert session.started_with[0] == MONITOR


def test_source_labels():
    assert source_label(MONITOR, monitor_count=1) == "Tela inteira"
    assert source_label(MONITOR, monitor_count=2) == "Tela inteira 1 (principal)"
    assert source_label(WINDOW, monitor_count=1) == "Filme.mp4 - VLC  ·  vlc"


def test_quality_details():
    assert msg.quality_details(1080, 60) == "1080p · 60 fps"
    assert msg.quality_details(None, 30) == "Original · 30 fps"


FORBIDDEN_TERMS = re.compile(
    r"\b(bitrate|kbps|mbps|webrtc|tunnel|túnel|cloudflared|porta|port|ice|stun|sdp|codec|fps)\b",
    re.IGNORECASE,
)


def test_window_texts_have_no_technical_terms():
    # Regra 5 do README: o FPS só aparece no rótulo ao lado do nome da qualidade
    # (quality_details), nunca nos textos.
    texts = list(msg.ui_texts().values())
    texts += list(msg.ERRORS.values())
    texts += [t for pair in msg.QUALITY_LABELS.values() for t in pair]
    offenders = [t for t in texts if FORBIDDEN_TERMS.search(t)]
    assert not offenders
