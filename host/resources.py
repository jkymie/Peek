"""Caminho dos arquivos que acompanham o Peek (em desenvolvimento e no ``Peek.exe``)."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    # PyInstaller extrai os arquivos embutidos em sys._MEIPASS.
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else Path(__file__).resolve().parents[1]


def web_dir() -> Path:
    """Página de quem assiste (gerada a partir de ``ui/src/viewer``)."""
    return resource_root() / "web"


def window_ui_dir() -> Path:
    """Interface da janela do Peek (gerada a partir de ``ui/src/broadcaster``)."""
    return resource_root() / "host" / "gui" / "ui"
