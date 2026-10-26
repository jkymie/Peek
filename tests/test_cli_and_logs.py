import json
import logging

import pytest

from host.__main__ import build_parser, main
from host.logs import setup_logging


def test_parser_defaults_match_readme():
    args = build_parser().parse_args([])
    assert not args.headless
    assert args.monitor == 1
    assert args.quality == "equilibrada"
    assert args.port == 8080
    assert args.window is None


def test_parser_rejects_window_and_monitor_together():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--window", "x", "--monitor", "2"])


def test_help_runs(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--headless" in capsys.readouterr().out


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()  # no Windows, um arquivo aberto impede apagar o tmp_path
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


@pytest.mark.usefixtures("restore_root_logger")
def test_log_file_is_json_lines_with_extra_fields(tmp_path):
    log_path = setup_logging(log_dir=tmp_path)
    logging.getLogger("peek.test").info("olá", extra={"viewers": 2})
    for handler in logging.getLogger().handlers:
        handler.flush()

    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["msg"] == "olá"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "peek.test"
    assert entry["viewers"] == 2
