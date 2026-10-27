"""Link público com um cloudflared falso (um script Python que imita a saída dele)."""

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from host.tunnel import Tunnel, TunnelError

BANNER = """\
2026-10-27T12:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...
2026-10-27T12:00:01Z INF +--------------------------------------------------------+
2026-10-27T12:00:01Z INF |  Your quick Tunnel has been created! Visit it at:      |
2026-10-27T12:00:01Z INF |  https://algum-nome-aleatorio.trycloudflare.com        |
2026-10-27T12:00:01Z INF +--------------------------------------------------------+
"""
REGISTERED = "2026-10-27T12:00:02Z INF Registered tunnel connection connIndex=0 location=gru\n"
NO_INTERNET = (
    "2026-10-27T12:00:00Z ERR Error unmarshaling QuickTunnel response: "
    "dial tcp: lookup api.trycloudflare.com: no such host\n"
)


def fake_cloudflared(tmp_path, output: str, *, then: str = "sleep") -> list[str]:
    """Escreve `output` no stderr e depois fica rodando (`sleep`) ou sai com erro (`exit`)."""
    script = tmp_path / "cloudflared.py"
    script.write_text(
        textwrap.dedent(f"""\
            import sys, time
            assert sys.argv[1:4] == ["tunnel", "--no-autoupdate", "--url"], sys.argv
            sys.stderr.write({output!r})
            sys.stderr.flush()
            if {then!r} == "exit":
                sys.exit(1)
            time.sleep(60)
        """),
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


async def test_returns_url_after_connection_is_registered(tmp_path):
    tunnel = Tunnel(command=fake_cloudflared(tmp_path, BANNER + REGISTERED), dns_timeout=0)
    try:
        url = await tunnel.start("http://127.0.0.1:8080")
        assert url == "https://algum-nome-aleatorio.trycloudflare.com"
        assert tunnel.url == url
    finally:
        await tunnel.stop()
    await tunnel.wait_closed()


async def test_url_without_connection_times_out(tmp_path):
    tunnel = Tunnel(command=fake_cloudflared(tmp_path, BANNER), timeout=1.0)
    with pytest.raises(TunnelError, match="tempo esgotado"):
        await tunnel.start("http://127.0.0.1:8080")
    assert tunnel._process is None  # o processo foi encerrado


async def test_exit_before_url_reports_last_error(tmp_path):
    tunnel = Tunnel(command=fake_cloudflared(tmp_path, NO_INTERNET, then="exit"))
    with pytest.raises(TunnelError, match="no such host"):
        await tunnel.start("http://127.0.0.1:8080")


async def test_unexpected_exit_closes_tunnel(tmp_path):
    tunnel = Tunnel(command=fake_cloudflared(tmp_path, BANNER + REGISTERED), dns_timeout=0)
    await tunnel.start("http://127.0.0.1:8080")
    tunnel._process.kill()  # cloudflared caiu sozinho
    await tunnel.wait_closed()
    assert not tunnel.stopping
    await tunnel.stop()


async def test_missing_executable(tmp_path):
    tunnel = Tunnel(command=[str(tmp_path / "nao-existe.exe")])
    with pytest.raises(TunnelError, match="não foi possível iniciar"):
        await tunnel.start("http://127.0.0.1:8080")


@pytest.mark.skipif(sys.platform != "win32", reason="job object é do Windows")
def test_cloudflared_dies_with_peek(tmp_path):
    """Se o Peek for fechado à força, o cloudflared não pode ficar rodando sozinho."""
    pid_file = tmp_path / "pid"
    command = fake_cloudflared(tmp_path, BANNER + REGISTERED)
    peek = tmp_path / "peek.py"
    peek.write_text(
        textwrap.dedent(f"""\
            import asyncio, os, sys
            sys.path.insert(0, {str(Path.cwd())!r})
            from host.tunnel import Tunnel
            async def main():
                t = Tunnel(command={command!r}, dns_timeout=0)
                await t.start("http://127.0.0.1:8080")
                open({str(pid_file)!r}, "w").write(str(t._process.pid))
                os._exit(0)  # fechamento abrupto: sem stop()
            asyncio.run(main())
        """),
        encoding="utf-8",
    )
    subprocess.run([sys.executable, str(peek)], check=True, timeout=30)
    child = int(pid_file.read_text())

    for _ in range(50):
        if not _running(child):
            break
        time.sleep(0.1)
    assert not _running(child)


def _running(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
    ).stdout
    return str(pid) in out
