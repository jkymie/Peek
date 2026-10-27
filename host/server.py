"""Servidor dos espectadores: página + sinalização WebRTC por WebSocket.

Rotas (o ``token`` é o "código da sala", aleatório a cada transmissão):

* ``GET /s/<token>``    → página do espectador
* ``GET /s/<token>/ws`` → sinalização
* ``GET /static/...``   → arquivos de ``web/``

Protocolo da sinalização (JSON):

* espectador → Peek: ``{"type": "offer", "sdp": "..."}`` (com todos os candidatos ICE)
* Peek → espectador: ``{"type": "answer", "sdp": "..."}``, ``{"type": "ended"}``
  (transmissão encerrada) ou ``{"type": "full"}`` (limite de espectadores)

Uma ``RTCPeerConnection`` por espectador. A página não tem nenhum controle de quem
transmite: o único comando aceito é a oferta.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import WSMsgType, web
from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)

log = logging.getLogger(__name__)

STUN_SERVERS = ("stun:stun.l.google.com:19302",)
MAX_VIEWERS = 6
MAX_MESSAGE_BYTES = 64 * 1024

_ENDED_PAGE = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Peek</title><link rel="stylesheet" href="/static/style.css">
<body><main class="message"><p>Este link não está mais ativo.</p>
<p>Peça um link novo para quem está transmitindo.</p></main></body></html>"""


def lan_ip() -> str:
    """IP desta máquina na rede local (nenhum pacote é enviado)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))  # endereço de documentação; só escolhe a rota
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


@dataclass(eq=False)
class _Viewer:
    id: int
    ws: web.WebSocketResponse
    pc: RTCPeerConnection | None = None
    connected: bool = field(default=False)


class ViewerServer:
    def __init__(
        self,
        *,
        token: str,
        make_tracks: Callable[[], list[MediaStreamTrack]],
        on_viewers_changed: Callable[[int], None],
        web_dir: Path,
        host: str,
        port: int,
        max_viewers: int = MAX_VIEWERS,
        ice_servers: tuple[str, ...] = STUN_SERVERS,
    ) -> None:
        self._token = token
        self._make_tracks = make_tracks
        self._on_viewers_changed = on_viewers_changed
        self._web_dir = web_dir
        self._host = host
        self._port = port
        self._max_viewers = max_viewers
        self._ice_servers = ice_servers
        self._viewers: set[_Viewer] = set()
        self._ids = itertools.count(1)
        self._runner: web.AppRunner | None = None
        self._viewer_count = 0
        self._closing = False

    @property
    def viewer_count(self) -> int:
        return self._viewer_count

    @property
    def port(self) -> int:
        return self._port

    def viewer_path(self) -> str:
        return f"/s/{self._token}"

    def set_bitrate(self, bitrate_kbps: int) -> None:
        """Leva a nova qualidade a quem já está assistindo, sem esperar o navegador pedir.

        O codificador de cada espectador é criado pelo aiortc e não é exposto; depende de
        detalhe interno (revisar ao atualizar a versão fixada).
        """
        for viewer in self._viewers:
            if viewer.pc is None:
                continue
            for sender in viewer.pc.getSenders():
                encoder = getattr(sender, "_RTCRtpSender__encoder", None)
                if encoder is not None and hasattr(encoder, "target_bitrate"):
                    encoder.target_bitrate = bitrate_kbps * 1000

    async def start(self) -> None:
        app = web.Application(middlewares=[_security_headers])
        app.router.add_get("/s/{token}", self._handle_page)
        app.router.add_get("/s/{token}/", self._handle_page)
        app.router.add_get("/s/{token}/ws", self._handle_ws)
        app.router.add_static("/static", self._web_dir)
        self._runner = web.AppRunner(app, access_log=None, handle_signals=False)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()  # OSError se a porta estiver ocupada
        if self._port == 0:  # porta escolhida pelo sistema (testes)
            self._port = site._server.sockets[0].getsockname()[1]
        log.info("Servidor iniciado", extra={"host": self._host, "port": self._port})

    async def stop(self) -> None:
        self._closing = True
        viewers = list(self._viewers)
        await asyncio.gather(*(self._close_viewer(v, notify=True) for v in viewers))
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        log.info("Servidor parado")

    # --- handlers --------------------------------------------------------------

    def _valid_token(self, request: web.Request) -> bool:
        return not self._closing and request.match_info["token"] == self._token

    async def _handle_page(self, request: web.Request) -> web.StreamResponse:
        if not self._valid_token(request):
            return web.Response(status=404, text=_ENDED_PAGE, content_type="text/html")
        return web.FileResponse(self._web_dir / "index.html", headers={"Cache-Control": "no-store"})

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        if not self._valid_token(request):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MESSAGE_BYTES)
        await ws.prepare(request)

        if len(self._viewers) >= self._max_viewers:
            await ws.send_json({"type": "full"})
            await ws.close()
            return ws

        viewer = _Viewer(next(self._ids), ws)
        self._viewers.add(viewer)
        log.info("Espectador conectou", extra={"viewer": viewer.id, "total": len(self._viewers)})
        try:
            async for msg in ws:
                if msg.type is not WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "offer" and viewer.pc is None:
                    await self._answer(viewer, str(data.get("sdp", "")))
        finally:
            await self._close_viewer(viewer, notify=False)
        return ws

    async def _answer(self, viewer: _Viewer, sdp: str) -> None:
        config = RTCConfiguration(iceServers=[RTCIceServer(urls=url) for url in self._ice_servers])
        pc = viewer.pc = RTCPeerConnection(config)

        @pc.on("connectionstatechange")
        async def _on_state() -> None:
            log.info("Estado da conexão", extra={"viewer": viewer.id, "state": pc.connectionState})
            viewer.connected = pc.connectionState == "connected"
            self._update_count()
            if pc.connectionState in ("failed", "closed"):
                await viewer.ws.close()

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
            for track in self._make_tracks():
                pc.addTrack(track)
            await pc.setLocalDescription(await pc.createAnswer())
        except Exception:
            log.exception("Oferta inválida", extra={"viewer": viewer.id})
            await viewer.ws.close()
            return
        await viewer.ws.send_json({"type": "answer", "sdp": pc.localDescription.sdp})

    async def _close_viewer(self, viewer: _Viewer, *, notify: bool) -> None:
        if viewer not in self._viewers:
            return
        self._viewers.discard(viewer)
        viewer.connected = False
        if notify and not viewer.ws.closed:
            with contextlib.suppress(Exception):
                await viewer.ws.send_json({"type": "ended"})
        with contextlib.suppress(Exception):
            await viewer.ws.close()
        if viewer.pc is not None:
            for sender in viewer.pc.getSenders():
                if sender.track is not None:
                    sender.track.stop()
            await viewer.pc.close()
        log.info("Espectador saiu", extra={"viewer": viewer.id, "total": len(self._viewers)})
        self._update_count()

    def _update_count(self) -> None:
        count = sum(v.connected for v in self._viewers)
        if count != self._viewer_count:
            self._viewer_count = count
            self._on_viewers_changed(count)


@web.middleware
async def _security_headers(request: web.Request, handler) -> web.StreamResponse:
    response = await handler(request)
    host = request.host
    response.headers.setdefault(
        "Content-Security-Policy",
        f"default-src 'self'; connect-src 'self' ws://{host} wss://{host}; "
        "img-src 'self' data:; media-src 'self' blob:; frame-ancestors 'none'",
    )
    # O token está na URL: não vazar para outros sites.
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response
