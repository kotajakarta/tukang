import os
import shutil
import stat
import subprocess
import tempfile
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.podman_service import podman_service

@pytest.mark.asyncio
async def test_podman_containers_list():
    containers = await podman_service.list_containers("local")
    assert isinstance(containers, list)

@pytest.mark.asyncio
async def test_podman_quadlet_lifecycle():
    # Test saving a dummy quadlet container
    test_content = """[Container]
Image=alpine:latest
Exec=echo hello
"""
    res = await podman_service.save_quadlet("local", "test-dummy.container", test_content, is_user=True)
    assert res.success is True
    assert "test-dummy.container" in res.path

    # List quadlets
    quadlets = await podman_service.list_quadlets("local")
    assert any(q.name == "test-dummy.container" for q in quadlets)

    # Get content
    content = await podman_service.get_quadlet_content("local", res.path)
    assert "Image=alpine:latest" in content

    # Clean up / delete
    del_ok = await podman_service.delete_quadlet("local", res.path, is_user=True)
    assert del_ok is True

@pytest.mark.asyncio
async def test_podman_api_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/containers/local")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        q_resp = await client.get("/api/v1/containers/local/quadlets/list")
        assert q_resp.status_code == 200
        assert isinstance(q_resp.json(), list)

@pytest.mark.asyncio
async def test_podman_containers_systemd_unit(monkeypatch):
    # The discovery script only sets _systemd_unit once systemd confirms the unit exists and runs the container;
    # a bare PODMAN_SYSTEMD_UNIT label (podman-compose stamps one on everything) must not count
    import json
    data = [
        {"Id": "a" * 64, "Names": ["web"], "Image": "nginx", "State": "running",
         "Labels": {"PODMAN_SYSTEMD_UNIT": "web.service"}, "_is_rootless": True, "_systemd_unit": "web.service"},
        {"Id": "b" * 64, "Names": ["proj_app_1"], "Image": "alpine", "State": "running",
         "Labels": {"PODMAN_SYSTEMD_UNIT": "podman-compose@proj.service"}, "_is_rootless": True},
    ]

    async def fake_run(server_id, cmd, timeout=15.0, stdin=None, elevate=True):
        return 0, json.dumps({"uid": 1000, "containers": data if not elevate else []}), ""

    from app.services import podman_service as podman_module
    monkeypatch.setattr(podman_module, "run_on_server", fake_run)
    containers = {c.names[0]: c for c in await podman_service.list_containers("local")}
    assert containers["web"].systemd_unit == "web.service"
    assert containers["proj_app_1"].systemd_unit is None

# --- scopes & actions --------------------------------------------------------------------------------------------
# Rootless = the login user's podman, run without the node's sudo setting; system = root's, run as root.

import json as _json
from app.services import podman_service as podman_module


def _scope_output(uid, containers):
    return 0, _json.dumps({"uid": uid, "containers": containers}), ""


def _container(cid, name, unit=None, state="running"):
    item = {"Id": cid * 64, "Names": [name], "Image": "img", "State": state}
    if unit:
        item["_systemd_unit"] = unit
    return item


class FakeServer:
    """Records every command and answers discovery per scope (user / system)."""

    def __init__(self, user_uid=1000, user=(), system=(), action_result=(0, "", "")):
        self.user_uid, self.user, self.system, self.action_result = user_uid, list(user), list(system), action_result
        self.calls = []

    async def __call__(self, server_id, cmd, timeout=15.0, stdin=None, elevate=True):
        self.calls.append({"cmd": cmd, "timeout": timeout, "elevate": elevate})
        if "podman-discovery" in cmd:
            if not elevate:
                return _scope_output(self.user_uid, self.user)
            return _scope_output(0, self.system)
        return self.action_result

    def actions(self):
        return [c for c in self.calls if "podman-discovery" not in c["cmd"]]


@pytest.mark.asyncio
async def test_list_containers_labels_scopes(monkeypatch):
    fake = FakeServer(user=[_container("a", "mine")], system=[_container("b", "rootful")])
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    containers = {c.names[0]: c for c in await podman_service.list_containers("srv")}
    assert containers["mine"].is_rootless is True
    assert containers["rootful"].is_rootless is False
    discovery = {("user" if c["elevate"] is False else "system"): c for c in fake.calls}
    # The user scope must not go through the node's sudo setting, or it would list root's containers as rootless
    assert discovery["user"]["elevate"] is False
    assert "sudo -n" in discovery["system"]["cmd"] and "id -u" in discovery["system"]["cmd"]


@pytest.mark.asyncio
async def test_list_containers_root_login_not_listed_twice(monkeypatch):
    # Logged in as root: the "user" scope is root's own podman, already covered by the system scope
    fake = FakeServer(user_uid=0, user=[_container("b", "rootful")], system=[_container("b", "rootful")])
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    containers = await podman_service.list_containers("srv")
    assert len(containers) == 1 and containers[0].is_rootless is False


@pytest.mark.asyncio
async def test_action_on_quadlet_container_goes_through_systemd(monkeypatch):
    fake = FakeServer(user=[_container("a", "web", unit="web.service")])
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    res = await podman_service.container_action("srv", "a" * 12, "stop")
    assert res.success is True
    [call] = fake.actions()
    # `podman stop` would be undone at once by the unit's Restart= policy
    assert call["cmd"].startswith("systemctl --user stop -- web.service")
    assert call["elevate"] is False
    assert call["timeout"] >= 60


@pytest.mark.asyncio
async def test_action_on_system_quadlet_runs_systemctl_as_root(monkeypatch):
    fake = FakeServer(system=[_container("b", "db", unit="db.service")])
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    await podman_service.container_action("srv", "b" * 12, "restart")
    [call] = fake.actions()
    assert "systemctl restart -- db.service" in call["cmd"] and "--user" not in call["cmd"]
    assert "sudo -n" in call["cmd"]


@pytest.mark.asyncio
async def test_action_on_plain_container_uses_its_own_scope(monkeypatch):
    fake = FakeServer(system=[_container("b", "rootful")])
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    res = await podman_service.container_action("srv", "rootful", "stop")
    assert res.success is True
    [call] = fake.actions()
    assert "podman stop -- " + "b" * 12 in call["cmd"] and "sudo -n" in call["cmd"]
    assert call["timeout"] >= 60


@pytest.mark.asyncio
async def test_remove_refused_for_quadlet_container(monkeypatch):
    fake = FakeServer(user=[_container("a", "web", unit="web.service")])
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    res = await podman_service.container_action("srv", "a" * 12, "remove")
    assert res.success is False and "web.service" in res.message
    assert fake.actions() == []


@pytest.mark.asyncio
async def test_action_on_unknown_container(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    res = await podman_service.container_action("srv", "c" * 12, "stop")
    assert res.success is False and "not found" in res.message.lower()
    assert fake.actions() == []


@pytest.mark.asyncio
async def test_stopped_quadlet_service_can_be_started(monkeypatch):
    # Quadlet removes the container on stop (--rm); discovery reports the unit with no Id, by its container name
    stopped = {"Id": "", "Names": ["systemd-web"], "Image": "nginx", "State": "inactive",
               "Status": "Service inactive", "_systemd_unit": "web.service"}
    fake = FakeServer(user=[stopped])
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    [c] = await podman_service.list_containers("srv")
    assert c.id == "systemd-web" and c.systemd_unit == "web.service" and c.is_rootless
    res = await podman_service.container_action("srv", c.id, "start")
    assert res.success is True
    [call] = fake.actions()
    assert call["cmd"].startswith("systemctl --user start -- web.service")


# --- Quadlet files by scope --------------------------------------------------------------------------------------
# Files in the login user's own dirs are handled as that user; everything else (/etc, /run, /usr) as root.

class FakeQuadletServer:
    def __init__(self, user_files=(), system_files=(), result=(0, "", "")):
        self.user_files, self.system_files, self.result = list(user_files), list(system_files), result
        self.calls = []

    async def __call__(self, server_id, cmd, timeout=15.0, stdin=None, elevate=True):
        self.calls.append({"cmd": cmd, "elevate": elevate, "stdin": stdin})
        if "quadlet-listing" in cmd:
            return 0, _json.dumps(self.user_files if not elevate else self.system_files), ""
        if "python3 -c" in cmd and "req = json.load" in cmd:
            return 0, "/written/path\n", ""
        return self.result


def _qfile(path, is_user):
    return {"name": path.rsplit("/", 1)[1], "path": path, "unit_type": "container", "is_user": is_user}


@pytest.mark.asyncio
async def test_list_quadlets_reads_user_dirs_as_login_user(monkeypatch):
    fake = FakeQuadletServer(
        user_files=[_qfile("/home/me/.config/containers/systemd/web.container", True)],
        system_files=[_qfile("/etc/containers/systemd/db.container", False)],
    )
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    quadlets = {q.name: q for q in await podman_service.list_quadlets("srv")}
    assert quadlets["web.container"].is_user and not quadlets["db.container"].is_user
    user_call = next(c for c in fake.calls if not c["elevate"])
    assert "quadlet-listing" in user_call["cmd"] and " user" in user_call["cmd"]


@pytest.mark.asyncio
async def test_save_user_quadlet_as_login_user(monkeypatch):
    fake = FakeQuadletServer()
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    res = await podman_service.save_quadlet("srv", "web.container", "[Container]\n", is_user=True)
    assert res.success
    write, reload = fake.calls
    # Through sudo, ~ would be root's home and the file would land in root's user units
    assert write["elevate"] is False and "sudo" not in write["cmd"]
    assert reload["elevate"] is False and reload["cmd"].startswith("systemctl --user daemon-reload")


@pytest.mark.asyncio
async def test_save_system_quadlet_as_root(monkeypatch):
    fake = FakeQuadletServer()
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    res = await podman_service.save_quadlet("srv", "db.container", "[Container]\n", is_user=False)
    assert res.success
    write, reload = fake.calls
    assert write["elevate"] is True and "sudo -n" in write["cmd"] and write["stdin"]
    assert "systemctl daemon-reload" in reload["cmd"] and "--user" not in reload["cmd"]


@pytest.mark.asyncio
async def test_save_quadlet_reports_failed_reload(monkeypatch):
    fake = FakeQuadletServer(result=(1, "", "Failed to connect to bus"))
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    res = await podman_service.save_quadlet("srv", "web.container", "[Container]\n", is_user=True)
    assert res.success and "daemon-reload" in res.warning and "Failed to connect to bus" in res.warning


@pytest.mark.asyncio
async def test_quadlet_file_access_follows_its_directory(monkeypatch):
    fake = FakeQuadletServer(result=(0, "[Container]\n", ""))
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    await podman_service.get_quadlet_content("srv", "/home/me/.config/containers/systemd/web.container")
    await podman_service.get_quadlet_content("srv", "/etc/containers/systemd/db.container")
    await podman_service.delete_quadlet("srv", "/etc/containers/systemd/users/1000/x.container", is_user=True)
    home_read, etc_read, rm, reload = fake.calls
    assert home_read["elevate"] is False and "sudo" not in home_read["cmd"]
    assert "sudo -n" in etc_read["cmd"]
    # Root owns /etc/containers/systemd/users/, but the units belong to the user's systemd
    assert "rm -f" in rm["cmd"] and "sudo -n" in rm["cmd"]
    assert reload["elevate"] is False and reload["cmd"].startswith("systemctl --user daemon-reload")


@pytest.mark.asyncio
async def test_action_message_explains_sigkill(monkeypatch):
    warning = 'time="..." level=warning msg="StopSignal SIGTERM failed to stop container db in 10 seconds, resorting to SIGKILL"\nbbbbbbbbbbbb'
    fake = FakeServer(system=[_container("b", "db")], action_result=(0, warning, ""))
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    res = await podman_service.container_action("srv", "db", "stop")
    assert res.success and "level=warning" not in res.message and "ignored SIGTERM" in res.message


@pytest.mark.asyncio
async def test_edit_quadlet_writes_back_in_place(monkeypatch):
    # Editing /etc/containers/systemd/users/1000/x.container must not create ~/.config/.../x.container instead
    fake = FakeQuadletServer()
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    path = "/etc/containers/systemd/users/1000/x.container"
    res = await podman_service.save_quadlet("srv", "x.container", "[Container]\n", is_user=True, path=path)
    assert res.success
    write, reload = fake.calls
    assert _json.loads(write["stdin"])["path"] == path
    assert "sudo -n" in write["cmd"]  # root owns /etc
    assert reload["elevate"] is False and reload["cmd"].startswith("systemctl --user daemon-reload")


@pytest.mark.asyncio
async def test_edit_quadlet_rejects_paths_outside_quadlet_dirs(monkeypatch):
    from fastapi import HTTPException
    fake = FakeQuadletServer()
    monkeypatch.setattr(podman_module, "run_on_server", fake)
    with pytest.raises(HTTPException):
        await podman_service.save_quadlet("srv", "x.container", "", is_user=False, path="/etc/passwd")
    assert fake.calls == []

def _run_quadlet_writer(path, content):
    import json, subprocess
    from app.services.podman_service import QUADLET_WRITER_SCRIPT
    req = {"filename": os.path.basename(path), "content": content, "is_user": True, "path": path}
    return subprocess.run(["python3", "-c", QUADLET_WRITER_SCRIPT], input=json.dumps(req),
                          capture_output=True, text=True)

def test_quadlet_writer_never_writes_through_planted_symlink(tmp_path):
    # A user who owns the quadlet directory can plant links next to the file; the writer may run as root
    victim = tmp_path / "shadow"
    victim.write_text("ORIGINAL\n")
    victim.chmod(0o600)
    qdir = tmp_path / "systemd"
    qdir.mkdir()
    (qdir / "web.container.tukang-tmp").symlink_to(victim)
    res = _run_quadlet_writer(str(qdir / "web.container"), "[Container]\nImage=x\n")
    assert res.returncode == 0, res.stderr
    assert victim.read_text() == "ORIGINAL\n"
    assert stat.S_IMODE(victim.stat().st_mode) == 0o600
    target = qdir / "web.container"
    assert not target.is_symlink() and target.read_text() == "[Container]\nImage=x\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644

def _userns_with_subuids() -> bool:
    try:
        return subprocess.run(["unshare", "--map-root-user", "--map-auto", "true"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False

@pytest.mark.skipif(not _userns_with_subuids(), reason="needs user namespaces with a subuid range")
def test_quadlet_read_as_root_stays_within_what_the_dir_owner_can_read():
    # Inside the namespace uid 0 plays root and uid 1000 the user owning the quadlet dir. That user
    # plants a link to a root-only file; reading it as root must not leak the file to an operator.
    from app.services.podman_service import quadlet_read_cmd
    base = tempfile.mkdtemp()
    os.chmod(base, 0o755)
    try:
        victim = f"{base}/shadow"
        with open(victim, "w") as f:
            f.write("root:HASH\n")
        os.chmod(victim, 0o600)
        home = f"{base}/home/bob"
        qdir = f"{home}/.config/containers/systemd"
        os.makedirs(qdir)
        os.symlink(victim, f"{qdir}/evil.container")
        with open(f"{qdir}/own.container", "w") as f:
            f.write("[Container]\nImage=x\n")
        script = (
            f"chmod 755 {base}/home && chown -hR 1000:1000 {home} && "
            f"{{ {quadlet_read_cmd(qdir + '/evil.container')}; echo \"evil-rc=$?\"; }}; "
            f"{{ {quadlet_read_cmd(qdir + '/own.container')}; echo \"own-rc=$?\"; }}; "
            f"chown -hR 0:0 {home}"
        )
        res = subprocess.run(["unshare", "--map-root-user", "--map-auto", "sh", "-c", script],
                             capture_output=True, text=True)
        assert "HASH" not in res.stdout
        assert "evil-rc=0" not in res.stdout
        assert "Image=x" in res.stdout and "own-rc=0" in res.stdout
    finally:
        shutil.rmtree(base)
