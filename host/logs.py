"""Configuração de logging.

Quem transmite nunca vê um terminal, então tudo vai para um arquivo em
``%LOCALAPPDATA%\\Peek\\logs``, uma linha JSON por evento, fácil de filtrar
quando alguém mandar o log para análise. No modo ``--headless`` os logs
também aparecem no terminal em formato legível.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

LOG_FILE_NAME = "peek.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5

# Atributos padrão de LogRecord; o que não estiver aqui veio de `extra=` e vai para o JSON.
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys() | {"message", "asctime"}
)


class JsonFormatter(logging.Formatter):
    """Formata cada registro como um objeto JSON em uma linha."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def default_log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Peek" / "logs"


def current_log_path() -> Path:
    """Arquivo de log em uso (o do handler configurado em :func:`setup_logging`)."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return default_log_dir() / LOG_FILE_NAME


def setup_logging(
    *, console: bool = False, debug: bool = False, log_dir: Path | None = None
) -> Path:
    """Configura o logger raiz e devolve o caminho do arquivo de log."""
    log_dir = log_dir or default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
        )
        root.addHandler(console_handler)

    # Bibliotecas muito verbosas em DEBUG.
    for noisy in ("aioice", "aiortc", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.INFO if debug else logging.WARNING)

    return log_path
