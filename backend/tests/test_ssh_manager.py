import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.ssh_manager import SSHConnectionManager, ServerConnectionInfo

@pytest.mark.asyncio
async def test_ssh_manager_connection_pooling():
    manager = SSHConnectionManager()
    info = ServerConnectionInfo(
        server_id="test-srv",
        host="192.168.1.50",
        port=22,
        username="root"
    )

    mock_conn = MagicMock()
    mock_conn.is_closed.return_value = False
    mock_conn.get_server_host_key.return_value = None
    mock_conn.run = AsyncMock()
    mock_result = MagicMock()
    mock_result.exit_status = 0
    mock_result.stdout = "Linux Rocky 10"
    mock_result.stderr = ""
    mock_conn.run.return_value = mock_result

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_conn

        # First call creates connection
        conn1 = await manager.get_connection(info)
        assert conn1 == mock_conn
        assert mock_connect.call_count == 1

        # Second call reuses existing connection from pool
        conn2 = await manager.get_connection(info)
        assert conn2 == mock_conn
        assert mock_connect.call_count == 1

        # Test command execution
        exit_code, stdout, stderr = await manager.run_command(info, "uname -a")
        assert exit_code == 0
        assert stdout == "Linux Rocky 10"

        # Test close
        await manager.close_all()
        assert len(manager._connections) == 0

@pytest.mark.asyncio
async def test_ssh_manager_reconnect_when_closed():
    manager = SSHConnectionManager()
    info = ServerConnectionInfo(server_id="srv-reconnect", host="10.0.0.1")

    mock_conn_old = MagicMock()
    mock_conn_old.is_closed.return_value = True
    mock_conn_old.get_server_host_key.return_value = None

    mock_conn_new = MagicMock()
    mock_conn_new.is_closed.return_value = False
    mock_conn_new.get_server_host_key.return_value = None

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = [mock_conn_old, mock_conn_new]

        conn1 = await manager.get_connection(info)
        # conn1 is closed, so next call should reconnect
        conn2 = await manager.get_connection(info)
        assert conn2 == mock_conn_new
        assert mock_connect.call_count == 2

@pytest.mark.asyncio
async def test_use_sudo_wraps_commands_but_not_metrics_probe():
    manager = SSHConnectionManager()
    info = ServerConnectionInfo(server_id="srv-sudo", host="10.0.0.2", username="tukang-mgr", use_sudo=True)
    mock_conn = MagicMock()
    mock_conn.is_closed.return_value = False
    mock_conn.get_server_host_key.return_value = None
    mock_conn.run = AsyncMock(return_value=MagicMock(exit_status=0, stdout="", stderr=""))
    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=mock_conn):
        await manager.run_command(info, "systemctl restart 'a b.service'")
        sent = mock_conn.run.call_args.args[0]
        assert sent == "sudo -n -- sh -c 'systemctl restart '\"'\"'a b.service'\"'\"''"
        await manager.run_command(info, "cat /proc/stat", elevate=False)
        assert mock_conn.run.call_args.args[0] == "cat /proc/stat"
