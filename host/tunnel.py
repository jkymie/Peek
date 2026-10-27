"""Link público: o ``cloudflared`` expõe o servidor local em um endereço HTTPS.

Usa um *quick tunnel* do ``trycloudflare.com`` (sem conta e sem configuração). O
``cloudflared`` roda como subprocesso sem janela de console; a URL pública é lida da
saída dele. O link só é entregue depois que a primeira conexão com a Cloudflare foi
registrada e o endereço novo já existe no DNS (isso leva alguns segundos), para que
funcione assim que for copiado.

O processo é encerrado junto com o Peek, mesmo se o Peek for fechado à força
(:func:`host.winproc.kill_with_peek`).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from host.resources import resource_root
from host.winproc import kill_with_peek

log = logging.getLogger(__name__)

START_TIMEOUT = 30.0
DNS_TIMEOUT = 30.0
STOP_TIMEOUT = 5.0

_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_REGISTERED_RE = re.compile(r"Registered tunnel connection")
_ERROR_RE = re.compile(r"\b(ERR|FTL)\b")


class TunnelError(Exception):
    """Não foi possível criar o link público."""


def find_cloudflared() -> Path | None:
    """O ``cloudflared.exe`` embutido em ``host/bin`` ou, em desenvolvimento, o do PATH."""
    bundled = resource_root() / "host" / "bin" / "cloudflared.exe"
    if bundled.is_file():
        return bundled
    found = shutil.which("cloudflared")
    return Path(found) if found else None


class Tunnel:
    """Um link público por transmissão: ``start()`` → ``url`` → ``stop()``."""

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        timeout: float = START_TIMEOUT,
        dns_timeout: float = DNS_TIMEOUT,
    ) -> None:
        # command: substitui o executável (os testes usam um cloudflared falso).
        self._command = list(command) if command else None
        self._timeout = timeout
        self._dns_timeout = dns_timeout
        self._process: subprocess.Popen[str] | None = None
        self._url: str | None = None
        self._url_seen: str | None = None
        self._last_error = ""
        self._ready = asyncio.Event()
        self._closed = asyncio.Event()
        self._stopping = False

    @property
    def url(self) -> str | None:
        return self._url

    @property
    def stopping(self) -> bool:
        return self._stopping

    async def start(self, local_url: str) -> str:
        """Inicia o ``cloudflared`` apontando para ``local_url`` e devolve a URL pública.
        Levanta :class:`TunnelError` se não conseguir a tempo."""
        command = self._command
        if command is None:
            exe = find_cloudflared()
            if exe is None:
                raise TunnelError("cloudflared não encontrado")
            command = [str(exe)]
        args = [*command, "tunnel", "--no-autoupdate", "--url", local_url]
        log.info("Iniciando o link público", extra={"cmd": args})

        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except OSError as exc:
            raise TunnelError(f"não foi possível iniciar o cloudflared: {exc}") from exc
        kill_with_peek(self._process)

        loop = asyncio.get_running_loop()
        threading.Thread(
            target=self._read_output, args=(loop, self._process), daemon=True, name="cloudflared"
        ).start()

        ready = asyncio.ensure_future(self._ready.wait())
        closed = asyncio.ensure_future(self._closed.wait())
        try:
            done, _ = await asyncio.wait(
                {ready, closed}, timeout=self._timeout, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            ready.cancel()
            closed.cancel()

        if ready not in done:
            reason = "o cloudflared fechou" if closed in done else "tempo esgotado"
            detail = f"{reason}: {self._last_error}" if self._last_error else reason
            await self.stop()
            raise TunnelError(detail)

        await self._wait_dns(urlsplit(self._url_seen).hostname)
        self._url = self._url_seen
        log.info("Link público pronto", extra={"url": self._url})
        return self._url

    async def wait_closed(self) -> None:
        """Termina quando o ``cloudflared`` fecha (por ``stop()`` ou por conta própria)."""
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
        log.info("Link público encerrado")

    # --- internos ---------------------------------------------------------------

    async def _wait_dns(self, hostname: str) -> None:
        """Espera o endereço novo existir no DNS. Se demorar demais, entrega o link mesmo
        assim: ele deve começar a funcionar logo depois."""
        loop = asyncio.get_running_loop()
        start = time.monotonic()
        while time.monotonic() - start < self._dns_timeout:
            try:
                await loop.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            except OSError:
                await asyncio.sleep(1.0)
                continue
            log.info("Endereço do link já existe", extra={"secs": time.monotonic() - start})
            return
        if self._dns_timeout > 0:
            log.warning("O endereço do link ainda não existe", extra={"host": hostname})

    def _read_output(self, loop: asyncio.AbstractEventLoop, process: subprocess.Popen) -> None:
        """Thread: lê o stderr do cloudflared (é onde ele escreve tudo)."""
        for line in process.stderr:
            self._call(loop, self._on_line, line.rstrip())
        code = process.wait()
        self._call(loop, self._on_exit, code)

    @staticmethod
    def _call(loop: asyncio.AbstractEventLoop, callback, *args) -> None:
        with contextlib.suppress(RuntimeError):  # loop já fechado
            loop.call_soon_threadsafe(callback, *args)

    def _on_line(self, line: str) -> None:
        log.debug("cloudflared: %s", line)
        if _ERROR_RE.search(line):
            self._last_error = line
        if self._url_seen is None and (match := _URL_RE.search(line)):
            self._url_seen = match.group(0)
        if self._url_seen and _REGISTERED_RE.search(line):
            self._ready.set()

    def _on_exit(self, code: int) -> None:
        level = logging.INFO if self._stopping else logging.WARNING
        log.log(level, "cloudflared fechou", extra={"code": code, "last_error": self._last_error})
        self._closed.set()
