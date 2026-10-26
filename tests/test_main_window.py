import re

import pytest
from PySide6.QtGui import QGuiApplication

from host.capture.video import CaptureSource, SourceKind
from host.gui import messages as msg
from host.gui.main_window import MainWindow, source_label
from host.session import ErrorCode, SessionError, SessionState, Signal

MONITOR = CaptureSource(SourceKind.MONITOR, 1, "Tela 1", 1920, 1080, primary=True)
WINDOW = CaptureSource(SourceKind.WINDOW, 1234, "Filme.mp4 - VLC", process_name="vlc.exe")
LINK = "http://192.168.0.10:8080/s/abc"


class FakeSession:
    """Mesma interface pública da StreamSession, sem captura nem rede."""

    def __init__(self, *, fail_with: ErrorCode | None = None) -> None:
        self.state_changed = Signal("state_changed")
        self.link_ready = Signal("link_ready")
        self.viewers_changed = Signal("viewers_changed")
        self.error = Signal("error")
        self.state = SessionState.IDLE
        self.started_with = None
        self.stopped = False
        self._fail_with = fail_with

    async def start(self, source, quality):
        self.started_with = (source, quality)
        if self._fail_with is not None:
            self.error.emit(self._fail_with)
            raise SessionError(self._fail_with)
        self.state = SessionState.LIVE
        self.link_ready.emit(LINK)
        return LINK

    async def stop(self):
        self.stopped = True
        self.state = SessionState.IDLE
        self.viewers_changed.emit(0)


@pytest.fixture
def make_window(qtbot):
    def _make(session, sources=(MONITOR, WINDOW)):
        window = MainWindow(session, sources_provider=lambda: list(sources))
        qtbot.addWidget(window)
        return window

    return _make


def test_primary_screen_is_preselected_with_reminder(make_window):
    window = make_window(FakeSession())
    assert window.selected_source() == MONITOR
    assert window.start_button.isEnabled()
    assert not window.reminder_label.isHidden()

    window.source_list.setCurrentRow(1)
    assert window.selected_source() == WINDOW
    assert window.reminder_label.isHidden()


def test_no_sources_disables_start(make_window):
    window = make_window(FakeSession(), sources=())
    assert window.selected_source() is None
    assert not window.start_button.isEnabled()


async def test_start_shows_link_and_counts_viewers(make_window):
    session = FakeSession()
    window = make_window(session)
    window.quality_combo.setCurrentIndex(window.quality_combo.findData("nitida"))

    await window.start_streaming()

    source, quality = session.started_with
    assert source == MONITOR
    assert quality.preset == "nitida"
    assert window._pages.currentWidget() is window._live_page
    assert window.link_edit.text() == LINK
    assert window.viewers_label.text() == msg.viewers_text(0)

    session.viewers_changed.emit(2)
    assert window.viewers_label.text() == "2 pessoas assistindo"


async def test_copy_link(make_window):
    window = make_window(FakeSession())
    await window.start_streaming()
    window.copy_link()
    assert QGuiApplication.clipboard().text() == LINK
    assert window.copy_button.text() == msg.LINK_COPIED


async def test_stop_returns_to_choose(make_window):
    session = FakeSession()
    window = make_window(session)
    await window.start_streaming()
    await window.stop_streaming()
    assert session.stopped
    assert window._pages.currentWidget() is window._choose_page


async def test_error_shows_plain_message_and_retry(make_window):
    window = make_window(FakeSession(fail_with=ErrorCode.NO_FRAMES))
    await window.start_streaming()
    assert window._pages.currentWidget() is window._error_page
    assert window.error_label.text() == msg.error_message(ErrorCode.NO_FRAMES)

    window.retry_button.click()
    assert window._pages.currentWidget() is window._choose_page


def test_source_labels():
    assert source_label(MONITOR, monitor_count=1) == "Tela inteira"
    assert source_label(MONITOR, monitor_count=2) == "Tela inteira 1 (principal)"
    assert source_label(WINDOW, monitor_count=1) == "Filme.mp4 - VLC  ·  vlc"


FORBIDDEN_TERMS = re.compile(
    r"\b(bitrate|kbps|mbps|webrtc|tunnel|túnel|cloudflared|porta|port|ice|stun|sdp|codec|fps)\b",
    re.IGNORECASE,
)


def test_window_texts_have_no_technical_terms():
    texts = [v for k, v in vars(msg).items() if isinstance(v, str) and not k.startswith("_")]
    texts += list(msg.ERRORS.values())
    texts += [t for pair in msg.QUALITY_LABELS.values() for t in pair]
    offenders = [t for t in texts if FORBIDDEN_TERMS.search(t)]
    assert not offenders
