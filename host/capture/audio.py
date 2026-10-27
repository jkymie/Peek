"""Áudio do sistema sem o Discord, vindo do ``peek-audio.exe``.

O helper (``audio-helper/``) escreve PCM float32 estéreo a 48 kHz no ``stdout`` e
eventos de uma linha no ``stderr`` (protocolo no README). Uma thread lê o PCM e
entrega uma cópia para cada espectador (:class:`AudioBuffer`), porque cada
conexão tem o seu próprio codificador e o seu próprio ritmo.

O helper só manda áudio enquanto algo toca; quem lê o buffer completa com silêncio.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from host.resources import resource_root
from host.winproc import kill_with_peek

log = logging.getLogger(__name__)

SAMPLE_RATE = 48_000
CHANNELS = 2
BYTES_PER_FRAME = CHANNELS * 4  # float32

START_TIMEOUT = 5.0
STOP_TIMEOUT = 2.0
# Se o espectador ficar para trás (conexão lenta, PC ocupado), descarta o áudio mais
# antigo em vez de deixar o atraso crescer.
MAX_BUFFER_SECONDS = 0.25
KEEP_AFTER_DROP_SECONDS = 0.06
# Depois de ficar sem áudio, espera juntar um pouco antes de voltar a tocar, para não
# alternar som e silêncio a cada pacote.
RESUME_SECONDS = 0.04


class AudioError(Exception):
    """O som não pôde ser capturado. ``code`` vem do helper (ex.: ``unsupported_os``)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def find_audio_helper() -> Path | None:
    """O ``peek-audio.exe`` gerado pelo ``audio-helper`` (ou embutido no ``Peek.exe``)."""
    exe = resource_root() / "host" / "bin" / "peek-audio.exe"
    return exe if exe.is_file() else None


class AudioBuffer:
    """Fila de áudio de um espectador. Escrita pela thread do helper, lida pela track."""

    def __init__(self) -> None:
        self._data = bytearray()
        self._lock = threading.Lock()
        self._waiting = True

    def push(self, chunk: bytes) -> None:
        with self._lock:
            self._data += chunk
            limit = int(MAX_BUFFER_SECONDS * SAMPLE_RATE) * BYTES_PER_FRAME
            if len(self._data) > limit:
                keep = int(KEEP_AFTER_DROP_SECONDS * SAMPLE_RATE) * BYTES_PER_FRAME
                del self._data[:-keep]

    def pull(self, frames: int) -> np.ndarray | None:
        """``frames`` amostras estéreo (float32, formato ``(frames, 2)``) ou ``None``
        se ainda não há áudio suficiente (quem chama manda silêncio)."""
        size = frames * BYTES_PER_FRAME
        resume = max(size, int(RESUME_SECONDS * SAMPLE_RATE) * BYTES_PER_FRAME)
        with self._lock:
            if len(self._data) < (resume if self._waiting else size):
                self._waiting = True
                return None
            self._waiting = False
            chunk = bytes(self._data[:size])
            del self._data[:size]
        return np.frombuffer(chunk, dtype="<f4").reshape(frames, CHANNELS)


class AudioCapture:
    """O ``peek-audio.exe`` rodando: ``start()`` → ``subscribe()`` → ``stop()``."""

    def __init__(
        self, *, include_discord: bool = False, command: Sequence[str] | None = None
    ) -> None:
        # command: substitui o executável (os testes usam um helper falso).
        self._command = list(command) if command else None
        self._include_discord = include_discord
        self._process: subprocess.Popen[bytes] | None = None
        self._subscribers: set[AudioBuffer] = set()
        self._lock = threading.Lock()
        self._capturing = asyncio.Event()
        self._closed = asyncio.Event()
        self._error: AudioError | None = None
        self._stopping = False
        self.discord_pid: int | None = None

    @property
    def stopping(self) -> bool:
        return self._stopping

    @property
    def error(self) -> AudioError | None:
        """O último erro informado pelo helper, se houver."""
        return self._error

    async def start(self) -> None:
        """Inicia o helper e espera ele começar a capturar. Levanta :class:`AudioError`."""
        command = self._command
        if command is None:
            exe = find_audio_helper()
            if exe is None:
                raise AudioError("helper_missing", "peek-audio.exe não encontrado")
            command = [str(exe)]
        args = [*command, *(["--include-discord"] if self._include_discord else [])]
        log.info("Iniciando o som", extra={"cmd": args})
        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except OSError as exc:
            raise AudioError("helper_failed", str(exc)) from exc
        kill_with_peek(self._process)

        loop = asyncio.get_running_loop()
        for target, name in ((self._read_audio, "audio-pcm"), (self._read_events, "audio-log")):
            threading.Thread(
                target=target, args=(loop, self._process), daemon=True, name=name
            ).start()

        capturing = asyncio.ensure_future(self._capturing.wait())
        closed = asyncio.ensure_future(self._closed.wait())
        try:
            done, _ = await asyncio.wait(
                {capturing, closed}, timeout=START_TIMEOUT, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            capturing.cancel()
            closed.cancel()
        if capturing not in done:
            error = self._error or AudioError("timeout" if not done else "helper_exited")
            await self.stop()
            raise error
        log.info("Som ativo", extra={"discord_pid": self.discord_pid})

    def subscribe(self) -> AudioBuffer:
        buffer = AudioBuffer()
        with self._lock:
            self._subscribers.add(buffer)
        return buffer

    def unsubscribe(self, buffer: AudioBuffer) -> None:
        with self._lock:
            self._subscribers.discard(buffer)

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def stop(self) -> None:
        self._stopping = True
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
        log.info("Som encerrado")

    # --- threads do helper --------------------------------------------------------

    def _read_audio(self, loop: asyncio.AbstractEventLoop, process: subprocess.Popen) -> None:
        leftover = b""
        while chunk := process.stdout.read1(65536):
            data = leftover + chunk
            cut = len(data) - len(data) % BYTES_PER_FRAME  # só amostras inteiras
            data, leftover = data[:cut], data[cut:]
            with self._lock:
                for buffer in self._subscribers:
                    buffer.push(data)

    def _read_events(self, loop: asyncio.AbstractEventLoop, process: subprocess.Popen) -> None:
        for raw in process.stderr:
            self._call(loop, self._on_event, raw.decode("utf-8", "replace").strip())
        # Avisa o fim daqui, depois da última linha, para o erro do helper não se perder.
        code = process.wait()
        self._call(loop, self._on_exit, code)

    @staticmethod
    def _call(loop: asyncio.AbstractEventLoop, callback, *args) -> None:
        with contextlib.suppress(RuntimeError):  # loop já fechado
            loop.call_soon_threadsafe(callback, *args)

    def _on_event(self, line: str) -> None:
        kind, _, rest = line.partition(" ")
        name, _, detail = rest.partition(" ")
        if kind == "STATUS":
            log.info("peek-audio: %s", rest)
            if name == "discord_found":
                with contextlib.suppress(ValueError):
                    self.discord_pid = int(detail.removeprefix("pid="))
            elif name == "capturing":
                self._capturing.set()
        elif kind == "ERROR":
            log.warning("peek-audio: %s", rest)
            self._error = AudioError(name, detail)
        elif line:
            log.debug("peek-audio: %s", line)

    def _on_exit(self, code: int) -> None:
        level = logging.INFO if self._stopping else logging.WARNING
        log.log(level, "peek-audio fechou", extra={"code": code})
        self._closed.set()
