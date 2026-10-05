import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.terminal_service import TerminalSession

@pytest.mark.asyncio
async def test_terminal_session_init():
    mock_ws = AsyncMock()
    session = TerminalSession(server_id="local", ws=mock_ws, cols=100, rows=40)
    assert session.server_id == "local"
    assert session.cols == 100
    assert session.rows == 40


def test_normalize_cwd_accepts_absolute_paths():
    from app.services.terminal_service import normalize_cwd
    assert normalize_cwd("/var/www/my site") == "/var/www/my site"
    assert normalize_cwd("/") == "/"

@pytest.mark.parametrize("value", [None, "", "relative/dir", "/tmp\n; rm -rf /", "/tmp\x00x", "/tmp\x1b[2J", "/" + "a" * 4096])
def test_normalize_cwd_rejects_unsafe_values(value):
    from app.services.terminal_service import normalize_cwd
    assert normalize_cwd(value) is None

def test_terminal_session_drops_invalid_cwd():
    session = TerminalSession(server_id="local", ws=AsyncMock(), cwd="../etc")
    assert session.cwd is None

@pytest.mark.asyncio
async def test_remote_session_changes_into_quoted_cwd(monkeypatch):
    from app.services import terminal_service

    process = MagicMock()
    process.stdout.read = AsyncMock(return_value=b"")
    conn = MagicMock()
    conn.create_process = AsyncMock(return_value=process)
    monkeypatch.setattr(terminal_service.ssh_manager, "get_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(terminal_service.ServerConnectionInfo, "from_server", staticmethod(lambda s: MagicMock(use_sudo=True)))

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=object())))
    db_ctx = MagicMock(__aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=False))
    monkeypatch.setattr(terminal_service, "AsyncSessionLocal", lambda: db_ctx)

    ws = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=Exception("closed"))
    session = TerminalSession(server_id="srv1", ws=ws, cwd="/srv/it's here")
    await session._run_remote()

    process.stdin.write.assert_called_once_with(b" cd -- '/srv/it'\"'\"'s here' && clear\n")

def test_parse_resize_recognises_only_resize_messages():
    from app.services.terminal_service import parse_resize
    assert parse_resize('{"type":"resize","cols":47,"rows":31}') == {"type": "resize", "cols": 47, "rows": 31}
    assert parse_resize('ls\r') is None
    assert parse_resize('{"type":"resize"') is None  # pasted fragment is typed, not swallowed
    assert parse_resize('["resize"]') is None

def _remote_session(monkeypatch, process, messages):
    from app.services import terminal_service

    async def idle_read(n):
        await asyncio.sleep(0.05)  # stay open until the client's messages are handled
        return b""
    process.stdout.read = idle_read
    conn = MagicMock()
    conn.create_process = AsyncMock(return_value=process)
    monkeypatch.setattr(terminal_service.ssh_manager, "get_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(terminal_service.ServerConnectionInfo, "from_server", staticmethod(lambda s: MagicMock(use_sudo=False)))

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=object())))
    db_ctx = MagicMock(__aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=False))
    monkeypatch.setattr(terminal_service, "AsyncSessionLocal", lambda: db_ctx)

    ws = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=[*messages, Exception("closed")])
    return TerminalSession(server_id="srv1", ws=ws)

@pytest.mark.asyncio
async def test_remote_resize_changes_pty_size_and_is_not_typed(monkeypatch):
    import asyncssh
    # spec: calling a method asyncssh's client process lacks fails like it would in production
    process = MagicMock(spec=asyncssh.SSHClientProcess)
    session = _remote_session(monkeypatch, process, ['{"type":"resize","cols":47,"rows":31}', "ls\r"])
    await session._run_remote()

    process.change_terminal_size.assert_called_once_with(47, 31)
    process.stdin.write.assert_called_once_with(b"ls\r")

@pytest.mark.asyncio
async def test_remote_resize_failure_is_not_typed(monkeypatch):
    import asyncssh
    process = MagicMock(spec=asyncssh.SSHClientProcess)
    process.change_terminal_size.side_effect = asyncssh.ChannelOpenError(2, "closed")
    session = _remote_session(monkeypatch, process, ['{"type":"resize","cols":47,"rows":31}'])
    await session._run_remote()

    process.stdin.write.assert_not_called()
