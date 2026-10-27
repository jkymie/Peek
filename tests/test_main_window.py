"""A janela de verdade: o React carrega no QtWebEngine e conversa com a ponte."""

import asyncio
import inspect
import time

import pytest
from PySide6.QtWidgets import QApplication

from host.gui import messages as msg
from host.gui.main_window import MainWindow
from host.resources import window_ui_dir
from tests.test_bridge import MONITOR, WINDOW, FakeSession

pytestmark = pytest.mark.skipif(
    not (window_ui_dir() / "index.html").exists(),
    reason="interface não gerada (rode `npm run build` em ui/)",
)


async def _wait_until(predicate, timeout: float) -> None:
    # Processa os eventos do Qt (página, QWebChannel) e deixa o asyncio rodar.
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return
        if time.monotonic() > deadline:
            raise AssertionError("condição não atingida a tempo")
        QApplication.processEvents()
        await asyncio.sleep(0.05)


async def _run_js(window, script: str):
    result = []
    window.view.page().runJavaScript(script, 0, result.append)
    await _wait_until(lambda: bool(result), timeout=5)
    return result[0]


async def _page_shows(window, text: str) -> bool:
    return text in (await _run_js(window, "document.body.innerText") or "")


async def test_react_interface_loads_and_starts(qtbot):
    session = FakeSession()
    window = MainWindow(session, sources_provider=lambda: [MONITOR, WINDOW])
    qtbot.addWidget(window)
    window.show()

    await _wait_until(lambda: _page_shows(window, msg.START), timeout=15)
    text = await _run_js(window, "document.body.innerText")
    assert msg.CHOOSE_TITLE in text
    assert "1080p · 30 fps" in text

    # Clica em "Começar a transmitir" (tela principal e "Equilibrada" já vêm escolhidas).
    await _run_js(
        window,
        "[...document.querySelectorAll('button')]"
        f".find(b => b.textContent.includes({msg.START!r})).click(); true",
    )
    await _wait_until(lambda: session.started_with is not None, timeout=5)
    source, quality = session.started_with
    assert source == MONITOR
    assert quality.preset == "equilibrada"
    await _wait_until(lambda: _page_shows(window, msg.SWITCH_SOURCE), timeout=5)
