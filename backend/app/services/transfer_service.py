"""
Server-to-server folder transfers for Files remote mappings.

The controller relays a tar stream from `files_agent` op `pack` on the source node into op `unpack` on
the destination node, chunk by chunk: nothing is staged on the controller's disk, and the two nodes
never connect to each other. Jobs live in memory (the controller runs as a single process).
"""
import asyncio
import json
import logging
import shlex
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional
from app.services.executor import open_process

logger = logging.getLogger("transfer_service")

AGENT_CMD = f"python3 -c {shlex.quote((Path(__file__).resolve().parent / 'files_agent.py').read_text())}"
CHUNK = 256 * 1024
KEEP_FINISHED_SECONDS = 3600

class TransferError(Exception):
    pass

@dataclass
class TransferJob:
    remote_id: int
    remote_name: str
    direction: str  # "upload" (local -> remote) or "download" (remote -> local)
    source_server_id: str
    source_root: str
    dest_server_id: str
    dest_root: str
    rels: List[str]
    ignore: List[str]
    username: str
    total_bytes: int  # estimated tar stream size, for progress
    total_files: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    state: str = "running"  # running | done | error | cancelled
    sent_bytes: int = 0
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    task: Optional[asyncio.Task] = field(default=None, repr=False)

    def public(self) -> dict:
        return {
            "id": self.id, "remote_id": self.remote_id, "remote_name": self.remote_name,
            "direction": self.direction, "state": self.state,
            "source_server_id": self.source_server_id, "source_root": self.source_root,
            "dest_server_id": self.dest_server_id, "dest_root": self.dest_root, "rels": self.rels,
            "sent_bytes": self.sent_bytes, "total_bytes": self.total_bytes, "total_files": self.total_files,
            "result": self.result, "error": self.error,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }

_jobs: Dict[str, TransferJob] = {}

def get_job(job_id: str) -> Optional[TransferJob]:
    return _jobs.get(job_id)

def running_for(remote_id: int) -> Optional[TransferJob]:
    return next((j for j in _jobs.values() if j.remote_id == remote_id and j.state == "running"), None)

def start(job: TransferJob, on_finish: Callable[[TransferJob], Awaitable[None]]) -> TransferJob:
    cutoff = time.time() - KEEP_FINISHED_SECONDS
    for old in [j for j in _jobs.values() if j.finished_at and j.finished_at < cutoff]:
        del _jobs[old.id]
    _jobs[job.id] = job
    job.task = asyncio.create_task(_run(job, on_finish))
    return job

def cancel(job: TransferJob):
    if job.task and not job.task.done():
        job.task.cancel()

async def _run(job: TransferJob, on_finish: Callable[[TransferJob], Awaitable[None]]):
    try:
        job.result = await relay(job)
        job.state = "done"
    except asyncio.CancelledError:
        job.state, job.error = "cancelled", "Cancelled"
    except Exception as e:
        job.state, job.error = "error", str(e) or e.__class__.__name__
        logger.warning(f"Transfer {job.id} ({job.source_server_id} -> {job.dest_server_id}) failed: {job.error}")
    finally:
        job.finished_at = time.time()
    try:
        await on_finish(job)
    except Exception as e:
        logger.error(f"Transfer {job.id} completion hook failed: {e}")

def _agent_error(text: str) -> str:
    try:
        return json.loads(text)["error"]
    except (ValueError, KeyError, TypeError):
        return text.strip()[:500] or "no output"

async def relay(job: TransferJob) -> dict:
    """Streams source `pack` into destination `unpack`; returns the destination's counts."""
    src = await open_process(job.source_server_id, AGENT_CMD)
    try:
        dst = await open_process(job.dest_server_id, AGENT_CMD)
    except BaseException:
        await src.close(grace=0)
        raise
    finished = False
    try:
        request = {"op": "pack", "root": job.source_root, "rels": job.rels, "ignore": job.ignore}
        src.write(json.dumps(request).encode() + b"\n")
        src.write_eof()
        dst.write(json.dumps({"op": "unpack", "root": job.dest_root}).encode() + b"\n")

        dest_gone = False
        while chunk := await src.read(CHUNK):
            try:
                dst.write(chunk)
                await dst.drain()
            except Exception:  # destination exited early; its own reply says why
                dest_gone = True
                break
            job.sent_bytes += len(chunk)

        if dest_gone:
            await src.close(grace=0)
            src_code, src_err = 0, ""
        else:
            dst.write_eof()
            src_code, _, src_err = await src.wait()
        dst_code, dst_out, dst_err = await dst.wait()
        finished = True
    finally:
        if not finished:  # cancelled or failed mid-stream: EOF lets unpack remove its temp file
            await src.close(grace=0)
            await dst.close()

    if src_code != 0:
        # A failed source truncates the archive, so its reason beats the destination's complaint
        raise TransferError(f"Source: {_agent_error(src_err)}")
    try:
        reply = json.loads(dst_out)
    except ValueError:
        raise TransferError(f"Destination: {_agent_error(dst_err or dst_out)}")
    if not reply.get("ok"):
        raise TransferError(f"Destination: {reply.get('error', 'unpack failed')}")
    return reply["result"]
