import io
import os
import stat
import struct
import tempfile
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import init_db
from app.services import files_agent

def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

@pytest.fixture
def workdir():
    with tempfile.TemporaryDirectory(prefix="cockpit-files-") as d:
        yield d

async def act(c, **body):
    return await c.post("/api/v1/files/local/action", json=body)

@pytest.mark.asyncio
async def test_list_create_edit_rename_delete(workdir):
    await init_db()
    nasty = "we$(id)ird 'name\".txt"
    async with client() as c:
        r = await act(c, op="write", path=f"{workdir}/{nasty}", content="hello\n", create=True)
        assert r.status_code == 200, r.text
        assert os.path.exists(os.path.join(workdir, nasty))  # literal name, nothing executed

        r = await act(c, op="write", path=f"{workdir}/{nasty}", content="again", create=True)
        assert r.status_code == 400 and "exists" in r.json()["detail"]

        assert (await act(c, op="mkdir", path=f"{workdir}/sub")).status_code == 200
        await act(c, op="write", path=f"{workdir}/.hidden", content="", create=True)

        listing = (await c.get("/api/v1/files/local/list", params={"path": workdir})).json()
        names = {e["name"]: e for e in listing["entries"]}
        assert set(names) == {nasty, "sub"}
        assert names["sub"]["type"] == "directory" and names[nasty]["size"] == 6
        hidden = (await c.get("/api/v1/files/local/list", params={"path": workdir, "show_hidden": True})).json()
        assert ".hidden" in {e["name"] for e in hidden["entries"]}

        read = (await c.get("/api/v1/files/local/read", params={"path": f"{workdir}/{nasty}"})).json()
        assert read["content"] == "hello\n"
        # Optimistic concurrency: stale mtime is refused
        r = await act(c, op="write", path=f"{workdir}/{nasty}", content="x", expected_mtime=read["mtime"] - 100)
        assert r.status_code == 400 and "changed on disk" in r.json()["detail"]
        r = await act(c, op="write", path=f"{workdir}/{nasty}", content="edited", expected_mtime=read["mtime"])
        assert r.status_code == 200

        r = await act(c, op="rename", path=f"{workdir}/{nasty}", new_path=f"{workdir}/sub/renamed.txt")
        assert r.status_code == 200
        assert open(f"{workdir}/sub/renamed.txt").read() == "edited"

        assert (await act(c, op="delete", paths=[f"{workdir}/sub"])).status_code == 200
        assert not os.path.exists(f"{workdir}/sub")

@pytest.mark.asyncio
async def test_copy_move_symlink_chmod(workdir):
    os.makedirs(f"{workdir}/a/inner")
    open(f"{workdir}/a/inner/f.sh", "w").write("#!/bin/sh\n")
    os.makedirs(f"{workdir}/dest")
    async with client() as c:
        r = await act(c, op="paste", paths=[f"{workdir}/a"], dest_dir=f"{workdir}/dest", mode="copy")
        assert r.status_code == 200 and os.path.exists(f"{workdir}/dest/a/inner/f.sh")
        # Second copy gets a unique name instead of overwriting
        r = await act(c, op="paste", paths=[f"{workdir}/a"], dest_dir=f"{workdir}/dest", mode="copy")
        assert r.json()["paths"][0].endswith("a (copy)")
        # Pasting a directory into itself is refused
        r = await act(c, op="paste", paths=[f"{workdir}/a"], dest_dir=f"{workdir}/a/inner", mode="move")
        assert r.status_code == 400

        r = await act(c, op="paste", paths=[f"{workdir}/dest/a (copy)"], dest_dir=workdir, mode="move")
        assert r.status_code == 200 and os.path.isdir(f"{workdir}/a (copy)")

        r = await act(c, op="symlink", path=f"{workdir}/link", target="a/inner/f.sh")
        assert r.status_code == 200 and r.json()["type"] == "link" and r.json()["target_type"] == "file"

        r = await act(c, op="chmod", paths=[f"{workdir}/a"], mode=0o750, recursive=True)
        assert r.status_code == 200
        assert stat.S_IMODE(os.stat(f"{workdir}/a/inner").st_mode) == 0o750
        # Recursive chmod doesn't make plain files executable
        assert stat.S_IMODE(os.stat(f"{workdir}/a/inner/f.sh").st_mode) & 0o111 == 0

@pytest.mark.asyncio
async def test_upload_and_download_stream(workdir):
    payload = os.urandom(3 * 1024 * 1024 + 7)
    async with client() as c:
        r = await c.post("/api/v1/files/local/upload", params={"dir": workdir, "name": "blob.bin"}, content=payload)
        assert r.status_code == 200, r.text
        assert r.json()["size"] == len(payload)
        r = await c.post("/api/v1/files/local/upload", params={"dir": workdir, "name": "blob.bin"}, content=b"x")
        assert r.status_code == 409
        r = await c.post("/api/v1/files/local/upload", params={"dir": workdir, "name": "blob.bin", "overwrite": True}, content=b"x")
        assert r.status_code == 200 and open(f"{workdir}/blob.bin", "rb").read() == b"x"
        r = await c.post("/api/v1/files/local/upload", params={"dir": workdir, "name": "../escape"}, content=b"x")
        assert r.status_code == 400

        open(f"{workdir}/big.bin", "wb").write(payload)
        r = await c.get("/api/v1/files/local/download", params={"path": f"{workdir}/big.bin"})
        assert r.status_code == 200 and r.content == payload
        assert "attachment" in r.headers["content-disposition"]
        assert not [f for f in os.listdir(workdir) if "cockpit-py" in f]  # no temp leftovers

@pytest.mark.asyncio
async def test_upload_never_writes_through_planted_symlink(workdir):
    # Whoever can write the target directory may plant links at guessable temp names; the upload runs
    # as root, so following one would overwrite (and chown) any file on the node.
    os.makedirs(f"{workdir}/shared")
    os.makedirs(f"{workdir}/protected")
    victim = f"{workdir}/protected/sudoers"
    open(victim, "w").write("ORIGINAL\n")
    os.symlink(victim, f"{workdir}/shared/.report.pdf.cockpit-py-upload")
    async with client() as c:
        r = await c.post("/api/v1/files/local/upload", params={"dir": f"{workdir}/shared", "name": "report.pdf"},
                         content=b"attacker ALL=(ALL) NOPASSWD: ALL\n")
        assert r.status_code == 200, r.text
    assert open(victim).read() == "ORIGINAL\n"
    dest = f"{workdir}/shared/report.pdf"
    assert not os.path.islink(dest) and open(dest, "rb").read() == b"attacker ALL=(ALL) NOPASSWD: ALL\n"

def _framed(*chunks, end=True):
    data = b"".join(struct.pack(">I", len(c)) + c for c in chunks)
    return io.BytesIO(data + (struct.pack(">I", 0) if end else b""))

def test_agent_upload_refuses_planted_temp_file(workdir, monkeypatch):
    # Even when the temp name is guessed, an entry planted there is never opened through
    victim = f"{workdir}/victim"
    open(victim, "w").write("ORIGINAL\n")
    planted = f"{workdir}/.planted"
    os.symlink(victim, planted)
    monkeypatch.setattr(files_agent, "_private_tmp_name", lambda directory: planted)
    with pytest.raises(FileExistsError):
        files_agent.op_upload({"dir": workdir, "name": "out.txt"}, _framed(b"evil\n"))
    assert open(victim).read() == "ORIGINAL\n"
    assert not os.path.lexists(f"{workdir}/out.txt")

def test_agent_write_never_reuses_planted_temp_file(workdir):
    # A hardlink planted at the old fixed temp name would receive the content (and chmod) of the edited file
    open(f"{workdir}/app.conf", "w").write("old\n")
    os.chmod(f"{workdir}/app.conf", 0o600)
    open(f"{workdir}/mine", "w").write("mine\n")
    os.chmod(f"{workdir}/mine", 0o664)
    os.link(f"{workdir}/mine", f"{workdir}/app.conf.cockpit-py-tmp")
    files_agent.op_write({"path": f"{workdir}/app.conf", "content": "password=SECRET\n"})
    assert open(f"{workdir}/app.conf").read() == "password=SECRET\n"
    assert stat.S_IMODE(os.stat(f"{workdir}/app.conf").st_mode) == 0o600
    assert open(f"{workdir}/mine").read() == "mine\n"
    assert stat.S_IMODE(os.stat(f"{workdir}/mine").st_mode) == 0o664

def test_agent_write_refuses_planted_temp_name(workdir, monkeypatch):
    open(f"{workdir}/victim", "w").write("ORIGINAL\n")
    os.symlink(f"{workdir}/victim", f"{workdir}/.planted")
    monkeypatch.setattr(files_agent, "_private_tmp_name", lambda directory: f"{workdir}/.planted")
    with pytest.raises(FileExistsError):
        files_agent.op_write({"path": f"{workdir}/new.txt", "content": "evil\n"})
    assert open(f"{workdir}/victim").read() == "ORIGINAL\n"

def test_agent_upload_discards_truncated_stream(workdir):
    open(f"{workdir}/out.txt", "w").write("keep\n")
    with pytest.raises(files_agent.AgentError):
        files_agent.op_upload({"dir": workdir, "name": "out.txt", "overwrite": True}, _framed(b"partial", end=False))
    assert open(f"{workdir}/out.txt").read() == "keep\n"
    assert os.listdir(workdir) == ["out.txt"]  # temp file removed

def test_agent_upload_writes_complete_stream(workdir):
    entry = files_agent.op_upload({"dir": workdir, "name": "out.txt"}, _framed(b"hello ", b"world"))
    assert open(f"{workdir}/out.txt", "rb").read() == b"hello world"
    assert entry["size"] == 11 and entry["mode"] == 0o644

@pytest.mark.asyncio
async def test_upload_too_large_keeps_existing_file(workdir, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "FILES_MAX_UPLOAD_MB", 1)
    open(f"{workdir}/data.bin", "wb").write(b"keep")
    async with client() as c:
        r = await c.post("/api/v1/files/local/upload", params={"dir": workdir, "name": "data.bin", "overwrite": True},
                         content=os.urandom(2 * 1024 * 1024))
        assert r.status_code == 413
    assert open(f"{workdir}/data.bin", "rb").read() == b"keep"
    assert os.listdir(workdir) == ["data.bin"]

@pytest.mark.asyncio
async def test_upload_does_not_replace_existing_symlink_target(workdir):
    # Without overwrite, an existing link at the destination counts as "exists" (it is never followed)
    open(f"{workdir}/real.txt", "w").write("keep\n")
    os.symlink(f"{workdir}/real.txt", f"{workdir}/link.txt")
    async with client() as c:
        r = await c.post("/api/v1/files/local/upload", params={"dir": workdir, "name": "link.txt"}, content=b"x")
        assert r.status_code == 409
    assert open(f"{workdir}/real.txt").read() == "keep\n"

@pytest.mark.asyncio
async def test_view_inline_media_with_ranges(workdir):
    payload = bytes(range(256)) * 40
    open(f"{workdir}/clip.mp4", "wb").write(payload)
    open(f"{workdir}/doc.pdf", "wb").write(b"%PDF-1.4\n")
    open(f"{workdir}/page.html", "w").write("<script>alert(1)</script>")
    os.symlink("clip.mp4", f"{workdir}/clip-link.mp4")
    url = "/api/v1/files/local/view"
    async with client() as c:
        r = await c.get(url, params={"path": f"{workdir}/clip.mp4"})
        assert r.status_code == 200 and r.content == payload
        assert r.headers["content-type"] == "video/mp4"
        assert r.headers["content-disposition"].startswith("inline")
        assert r.headers["accept-ranges"] == "bytes"
        assert "sandbox" in r.headers["content-security-policy"]

        r = await c.get(url, params={"path": f"{workdir}/clip-link.mp4"}, headers={"Range": "bytes=100-299"})
        assert r.status_code == 206 and r.content == payload[100:300]
        assert r.headers["content-range"] == f"bytes 100-299/{len(payload)}"
        r = await c.get(url, params={"path": f"{workdir}/clip.mp4"}, headers={"Range": "bytes=10000-"})
        assert r.status_code == 206 and r.content == payload[10000:]
        r = await c.get(url, params={"path": f"{workdir}/clip.mp4"}, headers={"Range": "bytes=-16"})
        assert r.status_code == 206 and r.content == payload[-16:]
        r = await c.get(url, params={"path": f"{workdir}/clip.mp4"}, headers={"Range": f"bytes={len(payload)}-"})
        assert r.status_code == 416

        # PDFs may be framed by the app itself (the viewer), and only by it
        r = await c.get(url, params={"path": f"{workdir}/doc.pdf"})
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        assert r.headers["x-frame-options"] == "SAMEORIGIN"
        assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'self'"
        assert r.headers.get_list("content-security-policy") == [r.headers["content-security-policy"]]

        # Anything that could execute as this origin is never served inline
        r = await c.get(url, params={"path": f"{workdir}/page.html"})
        assert r.status_code == 415
        r = await c.get(url, params={"path": workdir + ".pdf"})
        assert r.status_code == 400

@pytest.mark.asyncio
async def test_thumbnails(workdir):
    import io
    from PIL import Image
    from app.services import thumbnails
    Image.new("RGB", (1600, 900), (200, 30, 30)).save(f"{workdir}/photo.jpg")
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(f"{workdir}/icon.png")
    open(f"{workdir}/broken.png", "wb").write(b"not an image")
    open(f"{workdir}/logo.svg", "w").write('<svg xmlns="http://www.w3.org/2000/svg"/>')
    payload = bytes(range(256)) * 8
    open(f"{workdir}/clip.webm", "wb").write(payload)
    url = "/api/v1/files/local/thumb"
    async with client() as c:
        r = await c.get(url, params={"path": f"{workdir}/photo.jpg", "v": "1"})
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
        assert "max-age" in r.headers["cache-control"] and "sandbox" in r.headers["content-security-policy"]
        assert Image.open(io.BytesIO(r.content)).size == thumbnails.THUMB_SIZE
        r = await c.get(url, params={"path": f"{workdir}/icon.png", "v": "1"})
        assert Image.open(io.BytesIO(r.content)).mode == "RGBA"  # transparency kept

        r = await c.get(url, params={"path": f"{workdir}/logo.svg"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        assert r.content.startswith(b"<svg")

        # Videos are streamed (seekable) for the browser to grab a frame
        r = await c.get(url, params={"path": f"{workdir}/clip.webm"}, headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and r.content == payload[:100]

        r = await c.get(url, params={"path": f"{workdir}/broken.png"})
        assert r.status_code == 415
        r = await c.get(url, params={"path": f"{workdir}/missing.png"})
        assert r.status_code == 415
        r = await c.get(url, params={"path": f"{workdir}/notes.txt"})
        assert r.status_code == 415

        # Thumbnails don't flood the audit log
        entries = (await c.get("/api/v1/audit", params={"action": "files.view"})).json()
        assert not any(e["target"].startswith(workdir) for e in entries)

@pytest.mark.asyncio
async def test_protected_paths_and_binary_read(workdir):
    open(f"{workdir}/bin.dat", "wb").write(b"\x00\x01binary")
    async with client() as c:
        for p in ("/", "/etc", "/usr"):
            r = await act(c, op="delete", paths=[p])
            assert r.status_code == 400 and "protected" in r.json()["detail"]
        r = await c.get("/api/v1/files/local/read", params={"path": f"{workdir}/bin.dat"})
        assert r.status_code == 400 and "Binary" in r.json()["detail"]
        r = await c.get("/api/v1/files/local/list", params={"path": "relative/path"})
        assert r.status_code == 400

@pytest.mark.asyncio
async def test_files_audited(workdir):
    async with client() as c:
        await act(c, op="mkdir", path=f"{workdir}/audited-dir")
        entries = (await c.get("/api/v1/audit", params={"action": "files.mkdir"})).json()
    assert any(e["target"] == f"{workdir}/audited-dir" for e in entries)

def test_files_admin_only():
    from app.core import policy
    assert policy.required_role("GET", "/files/{server_id}/list") == "admin"
    assert policy.required_role("GET", "/files/{server_id}/thumb") == "admin"
    assert policy.required_role("POST", "/files/{server_id}/action") == "admin"
