"""Salva um frame capturado em PNG (verificação da captura de vídeo).

Uso, a partir da raiz do repositório::

    python -m tools.snapshot                       # todos os monitores
    python -m tools.snapshot --window "Bloco de Notas"
    python -m tools.snapshot --all                 # monitores e todas as janelas
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import cv2

from host.capture.video import (
    CaptureError,
    CaptureSource,
    find_window,
    grab_frame,
    list_monitors,
    list_sources,
)


def _file_name(source: CaptureSource) -> str:
    slug = re.sub(r"[^\w.-]+", "_", source.name, flags=re.UNICODE).strip("_")[:50] or "janela"
    return f"{source.kind}-{source.id}-{slug}.png"


def save(source: CaptureSource, out_dir: Path) -> bool:
    started = time.perf_counter()
    try:
        frame = grab_frame(source)
    except CaptureError as exc:
        print(f"FALHOU  {source.name}: {exc}")
        return False
    path = out_dir / _file_name(source)
    # cv2.imwrite não lida com caminhos não ASCII no Windows; imencode + write_bytes sim.
    ok, png = cv2.imencode(".png", frame.data)
    if not ok:
        print(f"FALHOU  {source.name}: não foi possível gerar o PNG")
        return False
    path.write_bytes(png.tobytes())
    elapsed = time.perf_counter() - started
    print(f"OK      {source.name}: {frame.width}x{frame.height} em {elapsed:.2f}s -> {path}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.snapshot", description=__doc__.splitlines()[0]
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--window", metavar="TÍTULO")
    group.add_argument("--all", action="store_true", help="monitores e todas as janelas")
    parser.add_argument("--out", type=Path, default=Path("snapshots"))
    args = parser.parse_args(argv)

    if args.window:
        window = find_window(args.window)
        if window is None:
            print(f"Nenhuma janela com {args.window!r} no título.")
            return 2
        sources = [window]
    elif args.all:
        sources = [s for s in list_sources() if not s.minimized]
    else:
        sources = list_monitors()

    args.out.mkdir(parents=True, exist_ok=True)
    results = [save(source, args.out) for source in sources]
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
