"""Ponto de entrada: ``python -m host`` (janela) ou ``python -m host --headless``.

As opções de linha de comando existem só para desenvolvimento e testes; tudo o que
elas fazem também precisa estar disponível pela janela do Peek.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from host import __version__
from host.logs import setup_logging

log = logging.getLogger("host")

QUALITY_PRESETS = ("economica", "equilibrada", "nitida", "fluida", "maxima")


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("precisa ser um número positivo")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m host",
        description="Peek: transmita sua tela para os amigos assistirem pelo navegador.",
    )
    parser.add_argument("--version", action="version", version=f"Peek {__version__}")
    parser.add_argument("--headless", action="store_true", help="roda sem interface gráfica")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--window", metavar="TÍTULO", help="transmite só a janela com esse título")
    source.add_argument(
        "--monitor",
        type=_positive_int,
        default=1,
        metavar="N",
        help="monitor a transmitir quando não houver --window (padrão: 1)",
    )
    parser.add_argument("--quality", choices=QUALITY_PRESETS, default="equilibrada")
    parser.add_argument(
        "--resolution", choices=("480", "720", "1080", "original"), help="padrão: do preset"
    )
    parser.add_argument("--fps", type=int, choices=(15, 30, 60), help="padrão: do preset")
    parser.add_argument(
        "--bitrate",
        type=_positive_int,
        metavar="KBPS",
        help="limite de envio de vídeo por espectador (padrão: do preset)",
    )
    parser.add_argument("--port", type=_positive_int, default=8080, help="padrão: 8080")
    parser.add_argument("--no-tunnel", action="store_true", help="não inicia o cloudflared")
    parser.add_argument(
        "--include-discord", action="store_true", help="inclui o áudio do Discord na transmissão"
    )
    parser.add_argument("--no-audio", action="store_true", help="transmite só o vídeo")
    parser.add_argument(
        "--list-sources", action="store_true", help="lista telas e janelas disponíveis e sai"
    )
    parser.add_argument("--debug", action="store_true", help="logs detalhados")
    return parser


def _print_sources() -> None:
    from host.capture.video import SourceKind, list_sources

    for src in list_sources():
        if src.kind is SourceKind.MONITOR:
            extra = " (principal)" if src.primary else ""
            print(f"--monitor {src.id}  {src.name}{extra}  {src.width}x{src.height}")
        else:
            extra = "  [minimizada]" if src.minimized else ""
            print(f'--window "{src.name}"  ({src.process_name}){extra}')


def _run_headless(args: argparse.Namespace) -> int:
    from host.capture.video import find_window, list_monitors

    if args.window:
        source = find_window(args.window)
        if source is None:
            log.error("Nenhuma janela com %r no título. Use --list-sources.", args.window)
            return 2
    else:
        monitors = list_monitors()
        if not 1 <= args.monitor <= len(monitors):
            log.error(
                "Monitor %d não existe (há %d). Use --list-sources.", args.monitor, len(monitors)
            )
            return 2
        source = monitors[args.monitor - 1]

    log.info(
        "Fonte escolhida: %s",
        source.name,
        extra={"source_kind": source.kind, "source_id": source.id},
    )
    if not args.no_tunnel:
        # TODO(Fase 3, quarta): cloudflared. Até lá, só rede local.
        log.warning("O link público ainda não está implementado; usando só a rede local.")
    if not args.no_audio:
        log.info("Áudio ainda não implementado; transmitindo só o vídeo.")

    from host.rtc.quality import resolve_quality

    quality = resolve_quality(
        args.quality, resolution=args.resolution, fps=args.fps, bitrate_kbps=args.bitrate
    )
    try:
        return asyncio.run(_headless_session(source, quality, args.port))
    except KeyboardInterrupt:
        return 0


async def _headless_session(source, quality, port: int) -> int:
    from host.gui.messages import error_message
    from host.session import SessionError, StreamSession

    session = StreamSession(port=port, public=False)
    finished = asyncio.Event()
    session.viewers_changed.connect(lambda n: log.info("Pessoas assistindo: %d", n))
    session.error.connect(lambda code: (log.error(error_message(code)), finished.set()))

    try:
        link = await session.start(source, quality)
    except SessionError:
        return 1
    print(f"\n  Link para assistir: {link}\n  Ctrl+C para parar.\n", flush=True)
    try:
        await finished.wait()  # só termina sozinho se der erro (ex.: janela fechada)
        return 1
    finally:
        await session.stop()


def _run_gui(args: argparse.Namespace) -> int:
    from host.gui.app import run_gui

    return run_gui(port=args.port)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = args.headless or args.list_sources
    log_path = setup_logging(console=console, debug=args.debug)
    log.debug(
        "Peek %s iniciando", __version__, extra={"args": vars(args), "log_file": str(log_path)}
    )

    if args.list_sources:
        _print_sources()
        return 0
    try:
        return _run_headless(args) if args.headless else _run_gui(args)
    except Exception:
        log.exception("Erro inesperado")
        return 1


if __name__ == "__main__":
    sys.exit(main())
