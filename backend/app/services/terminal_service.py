import asyncio
import fcntl
import json
import logging
import os
import pty
import shlex
import struct
import time
import termios
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.server import ServerModel
from app.core.config import is_direct_local
from app.services.ssh_manager import ssh_manager, ServerConnectionInfo

logger = logging.getLogger("terminal_service")

def _clamp(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default

def parse_resize(message: str) -> Optional[dict]:
    """The client's resize control message, or None when the message is keyboard input."""
    if not (message.startswith("{") and "resize" in message):
        return None
    try:
        cmd = json.loads(message)
    except ValueError:
        return None
    return cmd if isinstance(cmd, dict) and cmd.get("type") == "resize" else None

def normalize_cwd(value: Optional[str]) -> Optional[str]:
    """Start directory requested by the client: absolute, bounded, and free of control characters."""
    if not value or len(value) > 4096 or not value.startswith("/"):
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    return value

class TerminalSession:
    """
    Manages an active terminal session (either local PTY or remote SSH process)
    and bridges it bidirectionally to a FastAPI WebSocket client.
    """
    def __init__(self, server_id: str, ws: WebSocket, cols: int = 80, rows: int = 24, cwd: Optional[str] = None):
        self.server_id = server_id
        self.cwd = normalize_cwd(cwd)
        self.ws = ws
        self.cols = cols
        self.rows = rows
        self._master_fd: Optional[int] = None
        self._pid: Optional[int] = None
        self._ssh_process = None
        self._stop_event = asyncio.Event()
        # monotonic time of the last keystroke; counts as session activity
        self.last_input_at = time.monotonic()

    async def run(self):
        if is_direct_local(self.server_id):
            await self._run_local()
        else:
            await self._run_remote()

    def _set_local_winsize(self, rows: int, cols: int):
        if self._master_fd:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    async def _run_local(self):
        loop = asyncio.get_running_loop()
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._set_local_winsize(self.rows, self.cols)

        # Fork process
        pid = os.fork()
        if pid == 0:
            # Child process
            os.close(master_fd)
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)

            shell = os.environ.get("SHELL", "/bin/bash")
            env = dict(os.environ)
            env["TERM"] = "xterm-256color"
            if self.cwd:
                try:
                    os.chdir(self.cwd)
                except OSError:
                    pass  # missing/unreadable: the shell starts in the default directory
            try:
                os.execvpe(shell, [shell], env)
            except Exception:
                os._exit(1)
        
        # Parent process
        os.close(slave_fd)
        self._pid = pid

        # Make master_fd non-blocking
        os.set_blocking(master_fd, False)

        async def read_from_pty():
            try:
                while not self._stop_event.is_set():
                    data = await loop.run_in_executor(None, self._blocking_read_pty, master_fd)
                    if not data:
                        break
                    await self.ws.send_text(data.decode("utf-8", errors="replace"))
            except Exception as e:
                logger.debug(f"Local PTY read stopped: {e}")
            finally:
                self._stop_event.set()

        async def write_to_pty():
            try:
                while not self._stop_event.is_set():
                    message = await self.ws.receive_text()
                    cmd = parse_resize(message)
                    if cmd is not None:
                        # Never forwarded to the shell, even if applying the size fails
                        self.cols = _clamp(cmd.get("cols"), 10, 500, self.cols)
                        self.rows = _clamp(cmd.get("rows"), 5, 200, self.rows)
                        try:
                            self._set_local_winsize(self.rows, self.cols)
                        except OSError as e:
                            logger.debug(f"Local PTY resize failed: {e}")
                        continue

                    self.last_input_at = time.monotonic()
                    os.write(master_fd, message.encode("utf-8"))
            except (WebSocketDisconnect, Exception):
                pass
            finally:
                self._stop_event.set()

        try:
            await asyncio.gather(read_from_pty(), write_to_pty())
        finally:
            self._cleanup_local()

    def _blocking_read_pty(self, fd: int) -> bytes:
        import select
        r, _, _ = select.select([fd], [], [], 0.5)
        if fd in r:
            try:
                return os.read(fd, 4096)
            except OSError:
                return b""
        return b""

    def _cleanup_local(self):
        if self._master_fd:
            try:
                os.close(self._master_fd)
            except Exception:
                pass
            self._master_fd = None
        if self._pid:
            try:
                os.kill(self._pid, 9)
                os.waitpid(self._pid, os.WNOHANG)
            except Exception:
                pass
            self._pid = None

    async def _run_remote(self):
        # Fetch remote server credentials
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(ServerModel).where(ServerModel.id == self.server_id))
            server = res.scalar_one_or_none()
            if not server:
                await self.ws.send_text(f"\r\nServer '{self.server_id}' not found in database.\r\n")
                return

            info = ServerConnectionInfo.from_server(server)

        try:
            conn = await ssh_manager.get_connection(info)
            process = await conn.create_process(
                "sudo -i" if info.use_sudo else None,
                term_type="xterm-256color",
                term_size=(self.cols, self.rows),
                encoding=None
            )
            self._ssh_process = process
            if self.cwd:
                # `sudo -i` always lands in root's home, so change directory as the shell's first input.
                # Leading space keeps it out of history where HISTCONTROL=ignorespace.
                process.stdin.write(f" cd -- {shlex.quote(self.cwd)} && clear\n".encode("utf-8"))
        except Exception as e:
            await self.ws.send_text(f"\r\nFailed to establish SSH session to {info.host}: {e}\r\n")
            return

        async def read_from_ssh():
            try:
                while not self._stop_event.is_set():
                    data = await process.stdout.read(4096)
                    if not data:
                        break
                    await self.ws.send_text(data.decode("utf-8", errors="replace"))
            except Exception:
                pass
            finally:
                self._stop_event.set()

        async def write_to_ssh():
            try:
                while not self._stop_event.is_set():
                    message = await self.ws.receive_text()
                    cmd = parse_resize(message)
                    if cmd is not None:
                        # Never forwarded to the shell, even if applying the size fails
                        self.cols = _clamp(cmd.get("cols"), 10, 500, self.cols)
                        self.rows = _clamp(cmd.get("rows"), 5, 200, self.rows)
                        try:
                            process.change_terminal_size(self.cols, self.rows)
                        except Exception as e:
                            logger.debug(f"SSH terminal resize failed: {e}")
                        continue

                    self.last_input_at = time.monotonic()
                    process.stdin.write(message.encode("utf-8"))
            except (WebSocketDisconnect, Exception):
                pass
            finally:
                self._stop_event.set()

        try:
            await asyncio.gather(read_from_ssh(), write_to_ssh())
        finally:
            if self._ssh_process:
                self._ssh_process.close()
