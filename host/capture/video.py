"""Captura de tela e de janelas com ``windows-capture`` (Windows Graphics Capture).

Duas partes:

* **Listagem** das fontes disponíveis (monitores e janelas), usada pela janela do
  Peek para a pessoa escolher o que mostrar. Feita direto na API Win32 via
  ``ctypes``, porque o ``windows-capture`` não expõe uma listagem.
* **Captura contínua** (:class:`VideoCapture`). O ``windows-capture`` chama um
  callback em uma thread própria; cada frame é copiado e entregue ao loop do
  ``asyncio``. Só o frame mais recente é mantido: quem consome (uma track por
  espectador) sempre pega a imagem mais nova e frames atrasados são descartados.

Os frames são ``numpy.ndarray`` com formato ``(altura, largura, 4)`` em BGRA.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import logging
import os
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


class SourceKind(StrEnum):
    MONITOR = "monitor"
    WINDOW = "window"


@dataclass(frozen=True)
class CaptureSource:
    """Algo que pode ser transmitido: um monitor inteiro ou uma janela.

    ``id`` é o índice do monitor (começando em 1, como no ``windows-capture``)
    ou o HWND da janela.
    """

    kind: SourceKind
    id: int
    name: str
    width: int = 0
    height: int = 0
    primary: bool = False
    process_name: str = ""
    minimized: bool = False


@dataclass(frozen=True)
class CapturedFrame:
    data: np.ndarray = field(repr=False)  # (altura, largura, 4) uint8, BGRA
    width: int
    height: int
    seq: int  # contador crescente, começa em 1
    captured_at: float  # time.monotonic() de quando o frame chegou


class CaptureError(RuntimeError):
    """Não foi possível iniciar ou manter a captura."""


class CaptureClosed(CaptureError):
    """A fonte deixou de existir (ex.: a janela transmitida foi fechada)."""


# --------------------------------------------------------------------------- #
# Listagem de fontes (Win32)
# --------------------------------------------------------------------------- #

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi")

_MONITORINFOF_PRIMARY = 0x1
_ENUM_CURRENT_SETTINGS = -1
_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_DWMWA_CLOAKED = 14
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Janelas do próprio Windows que aparecem como "visíveis" mas não fazem sentido transmitir.
_IGNORED_WINDOW_CLASSES = frozenset(
    {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
)


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    )


class _DEVMODEW(ctypes.Structure):
    # Variante "display" da union de DEVMODEW; só os tamanhos importam para o resto.
    _fields_ = (
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    )


_MonitorEnumProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)
_WindowEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumDisplayMonitors.argtypes = (
    wintypes.HDC,
    ctypes.c_void_p,
    _MonitorEnumProc,
    wintypes.LPARAM,
)
_user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(_MONITORINFOEXW))
_user32.EnumDisplaySettingsW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(_DEVMODEW),
)
_user32.EnumWindows.argtypes = (_WindowEnumProc, wintypes.LPARAM)
_user32.IsWindowVisible.argtypes = (wintypes.HWND,)
_user32.IsIconic.argtypes = (wintypes.HWND,)
_user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
_user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_dwmapi.DwmGetWindowAttribute.argtypes = (
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


def list_monitors() -> list[CaptureSource]:
    """Monitores na mesma ordem (e com o mesmo índice, a partir de 1) do ``windows-capture``."""
    handles: list[int] = []

    @_MonitorEnumProc
    def _collect(hmonitor, _hdc, _rect, _lparam):
        handles.append(hmonitor)
        return True

    if not _user32.EnumDisplayMonitors(None, None, _collect, 0):
        raise CaptureError(f"EnumDisplayMonitors falhou (erro {ctypes.get_last_error()})")

    monitors = []
    for index, hmonitor in enumerate(handles, start=1):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if not _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            log.warning("GetMonitorInfoW falhou", extra={"monitor_index": index})
            continue

        # O retângulo do monitor depende do DPI awareness do processo; a resolução do modo
        # de vídeo atual é sempre em pixels reais, que é o tamanho que a captura entrega.
        mode = _DEVMODEW()
        mode.dmSize = ctypes.sizeof(mode)
        if _user32.EnumDisplaySettingsW(info.szDevice, _ENUM_CURRENT_SETTINGS, ctypes.byref(mode)):
            width, height = mode.dmPelsWidth, mode.dmPelsHeight
        else:
            width = info.rcMonitor.right - info.rcMonitor.left
            height = info.rcMonitor.bottom - info.rcMonitor.top

        monitors.append(
            CaptureSource(
                kind=SourceKind.MONITOR,
                id=index,
                name=f"Tela {index}",
                width=width,
                height=height,
                primary=bool(info.dwFlags & _MONITORINFOF_PRIMARY),
            )
        )
    return monitors


def _window_text(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _window_class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _is_cloaked(hwnd: int) -> bool:
    # Janelas "escondidas" pelo DWM (apps UWP suspensos, outras áreas de trabalho virtuais).
    cloaked = wintypes.DWORD()
    result = _dwmapi.DwmGetWindowAttribute(
        hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return result == 0 and cloaked.value != 0


def _process_image_name(pid: int) -> str:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def _is_capturable_window(hwnd: int) -> bool:
    if not _user32.IsWindowVisible(hwnd):
        return False
    if _user32.GetWindow(hwnd, _GW_OWNER):
        return False  # diálogos e pop-ups pertencem a outra janela
    ex_style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    if ex_style & (_WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE):
        return False
    if _window_class(hwnd) in _IGNORED_WINDOW_CLASSES:
        return False
    return not _is_cloaked(hwnd)


def list_windows(*, exclude_own_process: bool = True) -> list[CaptureSource]:
    """Janelas de nível superior que fazem sentido transmitir, na ordem Z (a da frente primeiro)."""
    own_pid = os.getpid()
    windows: list[CaptureSource] = []

    @_WindowEnumProc
    def _collect(hwnd, _lparam):
        try:
            if not _is_capturable_window(hwnd):
                return True
            title = _window_text(hwnd).strip()
            if not title:
                return True
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if exclude_own_process and pid.value == own_pid:
                return True
            windows.append(
                CaptureSource(
                    kind=SourceKind.WINDOW,
                    id=hwnd,
                    name=title,
                    process_name=_process_image_name(pid.value),
                    minimized=bool(_user32.IsIconic(hwnd)),
                )
            )
        except Exception:  # um callback ctypes não pode deixar exceção escapar
            log.exception("Erro ao inspecionar janela", extra={"hwnd": hwnd})
        return True

    _user32.EnumWindows(_collect, 0)
    return windows


def list_sources() -> list[CaptureSource]:
    """Monitores primeiro, depois janelas."""
    return list_monitors() + list_windows()


def find_window(title: str) -> CaptureSource | None:
    """Primeira janela cujo título contém ``title`` (sem diferenciar maiúsculas)."""
    needle = title.casefold()
    return next((w for w in list_windows() if needle in w.name.casefold()), None)


# --------------------------------------------------------------------------- #
# Captura
# --------------------------------------------------------------------------- #


def _create_capture(source: CaptureSource, max_fps: int | None):
    """Cria o objeto do ``windows-capture``. Importado aqui para a listagem não depender dele."""
    from windows_capture import WindowsCapture

    target = (
        {"monitor_index": source.id}
        if source.kind is SourceKind.MONITOR
        else {"window_hwnd": source.id}
    )
    # Pede ao Windows o dobro do FPS: os frames só chegam na grade de atualização do monitor,
    # então um intervalo exato de 1/FPS faria perder frames. O ritmo final é do _FrameThrottle.
    interval_ms = max(1, 500 // max_fps) if max_fps else None
    try:
        return WindowsCapture(cursor_capture=True, minimum_update_interval=interval_ms, **target)
    except Exception as exc:
        if interval_ms is None:
            raise CaptureError(f"Não foi possível preparar a captura de {source}: {exc}") from exc
        # MinUpdateInterval só existe em builds mais novos do Windows 11; sem ele, o limite
        # de FPS fica só no lado Python.
        log.info("Captura sem minimum_update_interval", extra={"reason": str(exc)})
        try:
            return WindowsCapture(cursor_capture=True, **target)
        except Exception as exc2:
            raise CaptureError(f"Não foi possível preparar a captura de {source}: {exc2}") from exc2


class _FrameThrottle:
    """Descarta frames que chegam mais rápido que o FPS máximo pedido."""

    def __init__(self, max_fps: int | None, clock: Callable[[], float] = time.monotonic) -> None:
        self._interval = 1.0 / max_fps if max_fps else 0.0
        self._clock = clock
        self._slot: float | None = None  # horário "ideal" do último frame aceito

    def accept(self) -> bool:
        interval = self._interval
        if not interval:
            return True
        now = self._clock()
        if self._slot is None or now - self._slot > 2 * interval:
            # Primeiro frame, ou a tela ficou parada: recomeça a agenda a partir de agora.
            self._slot = now
            return True
        # Tolerância de 1/4 de intervalo para frames que chegam um pouco adiantados.
        if now < self._slot + 0.75 * interval:
            return False
        # Avança a agenda pelo slot (não por "agora") para não acumular atraso, sem deixar
        # que um frame atrasado libere uma rajada logo em seguida.
        self._slot = max(self._slot + interval, now - interval / 2)
        return True


class VideoCapture:
    """Captura contínua de uma fonte, consumível de forma assíncrona.

    Uso::

        capture = VideoCapture(source, max_fps=30)
        await capture.start()
        frame = await capture.next_frame()
        frame = await capture.next_frame(after=frame.seq)
        await capture.stop()

    Vários consumidores podem chamar :meth:`next_frame` ao mesmo tempo; cada um
    recebe o frame mais recente disponível.
    """

    def __init__(self, source: CaptureSource, *, max_fps: int | None = 30) -> None:
        self.source = source
        self.max_fps = max_fps
        self._loop: asyncio.AbstractEventLoop | None = None
        self._control = None
        self._throttle = _FrameThrottle(max_fps)
        self._latest: CapturedFrame | None = None
        self._seq = 0
        self._waiter: asyncio.Future[None] | None = None
        self._stopping = threading.Event()
        self._closed = False

    @property
    def latest(self) -> CapturedFrame | None:
        return self._latest

    @property
    def running(self) -> bool:
        return self._control is not None and not self._closed

    async def start(self) -> None:
        if self._control is not None:
            raise RuntimeError("Captura já iniciada")
        self._loop = asyncio.get_running_loop()
        self._waiter = self._loop.create_future()

        capture = _create_capture(self.source, self.max_fps)
        capture.event(self._make_frame_handler())
        capture.event(self._make_closed_handler())
        try:
            self._control = capture.start_free_threaded()
        except Exception as exc:
            raise CaptureError(
                f"Não foi possível iniciar a captura de {self.source}: {exc}"
            ) from exc
        log.info(
            "Captura iniciada",
            extra={
                "source_kind": self.source.kind,
                "source_id": self.source.id,
                "max_fps": self.max_fps,
            },
        )

    async def stop(self) -> None:
        if self._control is None:
            return
        self._stopping.set()
        control, self._control = self._control, None
        try:
            control.stop()
            await asyncio.to_thread(control.wait)
        except Exception:
            log.exception("Erro ao parar a captura")
        self._mark_closed()
        log.info("Captura parada", extra={"frames": self._seq})

    async def next_frame(self, after: int = 0) -> CapturedFrame:
        """Espera um frame com ``seq`` maior que ``after`` e devolve o mais recente."""
        while self._latest is None or self._latest.seq <= after:
            if self._closed or self._waiter is None:
                raise CaptureClosed(f"A captura de {self.source} terminou")
            # shield: se um consumidor for cancelado, o futuro compartilhado continua valendo.
            await asyncio.shield(self._waiter)
        return self._latest

    # --- chamados na thread do windows-capture ---------------------------------

    def _make_frame_handler(self):
        def on_frame_arrived(frame, control) -> None:
            if self._stopping.is_set():
                control.stop()
                return
            if not self._throttle.accept():
                return
            # frame_buffer é uma visão do buffer nativo, válida só durante o callback.
            data = np.ascontiguousarray(frame.frame_buffer).copy()
            captured_at = time.monotonic()
            try:
                self._loop.call_soon_threadsafe(self._publish, data, captured_at)
            except RuntimeError:  # loop já fechado
                control.stop()

        return on_frame_arrived

    def _make_closed_handler(self):
        def on_closed() -> None:
            log.info("Fonte de captura encerrada", extra={"source_id": self.source.id})
            with contextlib.suppress(RuntimeError):  # loop já fechado
                self._loop.call_soon_threadsafe(self._mark_closed)

        return on_closed

    # --- chamados no loop do asyncio --------------------------------------------

    def _publish(self, data: np.ndarray, captured_at: float) -> None:
        if self._closed:
            return
        self._seq += 1
        height, width = data.shape[:2]
        self._latest = CapturedFrame(data, width, height, self._seq, captured_at)
        self._wake()

    def _mark_closed(self) -> None:
        self._closed = True
        self._wake()

    def _wake(self) -> None:
        waiter = self._waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(None)
        if not self._closed and self._loop is not None:
            self._waiter = self._loop.create_future()


def grab_frame(source: CaptureSource, timeout: float = 5.0) -> CapturedFrame:
    """Captura um único frame de forma síncrona (ferramentas e, depois, miniaturas)."""
    result: list[np.ndarray] = []
    done = threading.Event()

    capture = _create_capture(source, max_fps=None)

    @capture.event
    def on_frame_arrived(frame, control) -> None:
        if not result:
            result.append(np.ascontiguousarray(frame.frame_buffer).copy())
            done.set()
        control.stop()

    @capture.event
    def on_closed() -> None:
        done.set()

    try:
        control = capture.start_free_threaded()
    except Exception as exc:
        raise CaptureError(f"Não foi possível iniciar a captura de {source}: {exc}") from exc
    try:
        if not done.wait(timeout):
            # Janelas minimizadas, por exemplo, não produzem frames.
            raise CaptureError(f"Nenhum frame de {source} em {timeout:.0f}s")
    finally:
        control.stop()
        control.wait()

    if not result:
        raise CaptureClosed(f"A fonte {source} foi fechada antes de produzir um frame")
    data = result[0]
    height, width = data.shape[:2]
    return CapturedFrame(data, width, height, seq=1, captured_at=time.monotonic())
