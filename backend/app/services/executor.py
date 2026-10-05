import asyncio
import logging
from typing import AsyncIterator, Optional, Tuple
from sqlalchemy import select
from app.core.config import is_direct_local
from app.core.database import AsyncSessionLocal
from app.models.server import ServerModel
from app.services.ssh_manager import ssh_manager, ServerConnectionInfo

logger = logging.getLogger("executor")

async def run_on_server(
    server_id: str,
    cmd: str,
    timeout: float = 15.0,
    stdin: Optional[str] = None,
    elevate: bool = True,
) -> Tuple[int, str, str]:
    """
    Runs a shell command on a managed node (in-process for the direct local node, SSH otherwise)
    and returns (exit_status, stdout, stderr).

    `cmd` must only contain constants and shlex.quote()d, validated values (see app.core.validation).
    Pass untrusted free-form data via `stdin`.
    elevate=False runs it as the SSH login user even when the node is set to use sudo.
    """
    if is_direct_local(server_id):
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin.encode("utf-8") if stdin is not None else None), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return (-1, "", f"Command timed out after {timeout} seconds")
        return (
            proc.returncode if proc.returncode is not None else -1,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(ServerModel).where(ServerModel.id == server_id))
        server = res.scalar_one_or_none()
    if not server:
        return (-1, "", f"Server {server_id} not found")
    info = ServerConnectionInfo.from_server(server)
    return await ssh_manager.run_command(info, cmd, timeout=timeout, stdin=stdin, elevate=elevate)


async def _connection_info(server_id: str) -> Optional[ServerConnectionInfo]:
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(ServerModel).where(ServerModel.id == server_id))
        server = res.scalar_one_or_none()
    return ServerConnectionInfo.from_server(server) if server else None

async def stream_output(server_id: str, cmd: str, chunk_size: int = 256 * 1024) -> AsyncIterator[bytes]:
    """Streams a command's stdout without buffering it all (file downloads)."""
    if is_direct_local(server_id):
        proc = await asyncio.create_subprocess_shell(
            cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            while chunk := await proc.stdout.read(chunk_size):
                yield chunk
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        return

    info = await _connection_info(server_id)
    if not info:
        return
    conn = await ssh_manager.get_connection(info)
    process = await conn.create_process(ssh_manager.elevated(info, cmd), encoding=None)
    if prefix := ssh_manager.sudo_stdin(info):
        process.stdin.write(prefix.encode("utf-8"))
        process.stdin.write_eof()
    try:
        while chunk := await process.stdout.read(chunk_size):
            yield chunk
    finally:
        process.close()

class StreamProcess:
    """A command on a node with streaming binary stdin/stdout (in-process subprocess or SSH channel).
    Any sudo password prefix has already been written to stdin when `open_process` returns it."""

    def __init__(self, proc, ssh: bool):
        self._proc = proc
        self._ssh = ssh

    def write(self, data: bytes):
        self._proc.stdin.write(data)

    async def drain(self):
        await self._proc.stdin.drain()

    def write_eof(self):
        if self._ssh:
            self._proc.stdin.write_eof()
        elif not self._proc.stdin.is_closing():
            self._proc.stdin.close()

    async def read(self, n: int) -> bytes:
        return await self._proc.stdout.read(n)

    async def wait(self) -> Tuple[int, str, str]:
        """Waits for exit; returns (exit_status, remaining stdout, stderr)."""
        if self._ssh:
            result = await self._proc.wait()
            out = result.stdout.decode(errors="replace") if result.stdout else ""
            err = result.stderr.decode(errors="replace") if result.stderr else ""
            return result.exit_status if result.exit_status is not None else -1, out, err
        out, err = await self._proc.communicate()
        return self._proc.returncode if self._proc.returncode is not None else -1, out.decode(errors="replace"), err.decode(errors="replace")

    async def close(self, grace: float = 5.0):
        """Ends the process: EOF first so it can clean up, then force after `grace` seconds."""
        try:
            self.write_eof()
        except Exception:
            pass
        if self._ssh:
            try:
                await asyncio.wait_for(self._proc.wait_closed(), timeout=grace)
            except Exception:
                pass
            self._proc.close()
            return
        if self._proc.returncode is None:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=grace)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()

async def open_process(server_id: str, cmd: str) -> StreamProcess:
    """Starts `cmd` (elevated like run_on_server) with piped stdin/stdout/stderr for streaming."""
    if is_direct_local(server_id):
        proc = await asyncio.create_subprocess_shell(
            cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        return StreamProcess(proc, ssh=False)
    info = await _connection_info(server_id)
    if not info:
        raise RuntimeError(f"Server {server_id} not found")
    conn = await ssh_manager.get_connection(info)
    process = await conn.create_process(ssh_manager.elevated(info, cmd), encoding=None)
    if prefix := ssh_manager.sudo_stdin(info):
        process.stdin.write(prefix.encode("utf-8"))
    return StreamProcess(process, ssh=True)
