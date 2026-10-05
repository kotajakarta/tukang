import asyncio
import os
import tempfile
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import init_db

def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

@pytest_asyncio.fixture
async def dirs():
    await init_db()
    with tempfile.TemporaryDirectory(prefix="cockpit-remotes-") as d:
        a, b = os.path.join(d, "project-a"), os.path.join(d, "deploy-b")
        os.makedirs(f"{a}/src/node_modules/lib")
        os.makedirs(b)
        for rel, body in {"src/app.py": "v2", "src/node_modules/lib/x.js": "dep", ".env": "LOCAL", "README.md": "readme"}.items():
            with open(f"{a}/{rel}", "w") as f:
                f.write(body)
        yield a, b

async def make_remote(c, a, b, **extra):
    body = {"name": "Prod", "local_server_id": "local", "local_path": a, "remote_server_id": "local",
            "remote_path": b, "ignore": ["node_modules", ".env"], **extra}
    return await c.post("/api/v1/files/remotes", json=body)

async def wait_job(c, job):
    for _ in range(200):
        if job["state"] != "running":
            return job
        await asyncio.sleep(0.05)
        job = (await c.get(f"/api/v1/files/transfers/{job['id']}")).json()
    raise AssertionError("transfer did not finish")

@pytest.mark.asyncio
async def test_remote_crud_and_validation(dirs):
    a, b = dirs
    async with client() as c:
        r = await make_remote(c, a, b, ignore=[" *.log ", "*.log", ""])
        assert r.status_code == 201, r.text
        remote = r.json()
        assert remote["ignore"] == ["*.log"]  # trimmed, de-duplicated, blanks dropped

        r = await c.put(f"/api/v1/files/remotes/{remote['id']}", json={**remote, "name": "Production"})
        assert r.status_code == 200 and r.json()["name"] == "Production"
        assert any(x["id"] == remote["id"] for x in (await c.get("/api/v1/files/remotes")).json())

        for bad in ({"remote_path": "/etc"}, {"local_path": "/"}, {"remote_path": f"{a}/sub"},
                    {"remote_server_id": "nope"}, {"local_path": "relative"}, {"ignore": ["a\nb"]}):
            r = await make_remote(c, a, b, **bad)
            assert r.status_code in (400, 422), (bad, r.text)

        assert (await c.delete(f"/api/v1/files/remotes/{remote['id']}")).status_code == 204
        assert (await c.delete(f"/api/v1/files/remotes/{remote['id']}")).status_code == 404

@pytest.mark.asyncio
async def test_upload_then_download_roundtrip(dirs):
    a, b = dirs
    with open(f"{b}/.env", "w") as f:
        f.write("PRODUCTION")
    with open(f"{b}/uploads.txt", "w") as f:
        f.write("user data")
    async with client() as c:
        remote = (await make_remote(c, a, b)).json()
        base = f"/api/v1/files/remotes/{remote['id']}"

        scan = (await c.post(f"{base}/scan", json={"direction": "upload", "paths": [a]})).json()
        assert scan["files"] == 2 and scan["ignored"] == 2 and scan["dest_root"] == b

        r = await c.post(f"{base}/transfer", json={"direction": "upload", "paths": [a]})
        assert r.status_code == 200, r.text
        job = await wait_job(c, r.json())
        assert job["state"] == "done", job
        assert job["result"]["files"] == 2 and job["sent_bytes"] > 0
        assert open(f"{b}/src/app.py").read() == "v2"
        assert open(f"{b}/.env").read() == "PRODUCTION"  # ignored both ways
        assert open(f"{b}/uploads.txt").read() == "user data"  # never deleted
        assert not os.path.exists(f"{b}/src/node_modules")

        # Hotfix made on B, pulled back into A (only the selected file)
        with open(f"{b}/src/app.py", "w") as f:
            f.write("hotfix")
        job = await wait_job(c, (await c.post(f"{base}/transfer", json={"direction": "download", "paths": [f"{a}/src/app.py"]})).json())
        assert job["state"] == "done" and job["source_server_id"] == "local" and job["dest_root"] == a
        assert open(f"{a}/src/app.py").read() == "hotfix"
        assert open(f"{a}/.env").read() == "LOCAL"
        assert not os.path.exists(f"{a}/uploads.txt")

        entries = (await c.get("/api/v1/audit", params={"action": "files.sync.download"})).json()
        assert entries and entries[0]["success"] and "1 files" in entries[0]["detail"]

@pytest.mark.asyncio
async def test_transfer_rejections(dirs):
    a, b = dirs
    async with client() as c:
        remote = (await make_remote(c, a, b)).json()
        base = f"/api/v1/files/remotes/{remote['id']}"
        r = await c.post(f"{base}/transfer", json={"direction": "upload", "paths": [f"{a}/.env"]})
        assert r.status_code == 400 and "ignored" in r.json()["detail"]
        r = await c.post(f"{base}/transfer", json={"direction": "upload", "paths": ["/tmp"]})
        assert r.status_code == 400 and "outside" in r.json()["detail"]
        r = await c.post(f"{base}/scan", json={"direction": "download", "paths": [f"{a}/src"]})
        assert r.status_code == 400  # not on the remote side yet
        assert (await c.get("/api/v1/files/transfers/nope")).status_code == 404

@pytest.mark.asyncio
async def test_destination_failure_reported(dirs):
    a, b = dirs
    os.makedirs(f"{b}/README.md")  # a directory where a file must go
    async with client() as c:
        remote = (await make_remote(c, a, b)).json()
        r = await c.post(f"/api/v1/files/remotes/{remote['id']}/transfer", json={"direction": "upload", "paths": [a]})
        job = await wait_job(c, r.json())
    assert job["state"] == "error" and job["error"].startswith("Destination:") and "README.md" in job["error"]
    assert not [n for n in os.listdir(b) if n.startswith(".cockpit-py-sync")]

@pytest.mark.asyncio
async def test_deleting_server_deletes_its_remotes(dirs):
    a, b = dirs
    async with client() as c:
        srv = (await c.post("/api/v1/servers", json={"name": "B", "host": "192.0.2.10"})).json()
        remote = (await make_remote(c, a, b, remote_server_id=srv["id"])).json()
        assert (await c.delete(f"/api/v1/servers/{srv['id']}")).status_code == 204
        assert all(x["id"] != remote["id"] for x in (await c.get("/api/v1/files/remotes")).json())

def test_remotes_admin_only():
    from app.core import policy
    assert policy.required_role("GET", "/files/remotes") == "admin"
    assert policy.required_role("GET", "/files/transfers/{job_id}") == "admin"
    assert policy.required_role("POST", "/files/remotes/{remote_id}/transfer") == "admin"

@pytest.mark.asyncio
async def test_cancel_stops_both_sides(monkeypatch, dirs):
    import time
    from app.services import executor, transfer_service

    a, b = dirs
    opened = []

    async def fake_open(server_id, cmd):
        # Source: sends a few bytes, then hangs; destination: the real agent waiting for the rest
        opened.append(server_id)
        if len(opened) == 1:
            return await executor.open_process(server_id, "cat >/dev/null; printf 'partial'; sleep 60")
        return await executor.open_process(server_id, cmd)

    monkeypatch.setattr(transfer_service, "open_process", fake_open)
    job = transfer_service.TransferJob(
        remote_id=-1, remote_name="t", direction="upload", source_server_id="local", source_root=a,
        dest_server_id="local", dest_root=b, rels=["."], ignore=[], username="test", total_bytes=1, total_files=1,
    )
    finished = []

    async def on_finish(j):
        finished.append(j.state)

    transfer_service.start(job, on_finish)
    for _ in range(100):
        if job.sent_bytes:
            break
        await asyncio.sleep(0.02)
    assert job.sent_bytes == len("partial")
    t0 = time.monotonic()
    transfer_service.cancel(job)
    await asyncio.wait_for(job.task, timeout=10)
    assert job.state == "cancelled" and finished == ["cancelled"]
    assert time.monotonic() - t0 < 6
    assert os.listdir(b) == []
