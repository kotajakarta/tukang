import pytest
from app.services.network_service import network_service

SHOW_FIREWALLD = "LoadState=loaded\nActiveState=active\n\nLoadState=not-found\nActiveState=inactive\n\nLoadState=not-found\nActiveState=inactive\n"
SHOW_NONE = "LoadState=not-found\nActiveState=inactive\n\n" * 3

def fake_node(monkeypatch, show_output, rules=(0, "public\n  ports: 22/tcp", ""), action=(0, "success", "")):
    calls = []

    async def run(server_id, cmd, stdin=None):
        calls.append((cmd, stdin))
        if cmd.startswith("systemctl show"):
            return 0, show_output, ""
        if "--list-all" in cmd or "ufw status" in cmd:
            return rules
        return action

    monkeypatch.setattr(network_service, "_run_command", run)
    return calls

@pytest.mark.asyncio
async def test_firewall_status_unprivileged_still_reports_engine(monkeypatch):
    fake_node(monkeypatch, SHOW_FIREWALLD, rules=(1, "", "Authorization failed."))
    st = await network_service._firewall_status("x")
    assert st["type"] == "firewalld" and st["active"] is True
    assert st["rules"] == [] and st["needs_sudo"] is True and "sudo password" in st["note"]

@pytest.mark.asyncio
async def test_allow_port_firewalld_runtime_and_permanent(monkeypatch):
    calls = fake_node(monkeypatch, SHOW_FIREWALLD)
    res = await network_service.allow_port("x", 8000, 8010, "udp")
    assert res["success"] is True
    cmd = next(c for c, _ in calls if "--add-port" in c)
    assert "firewall-cmd --add-port=8000-8010/udp" in cmd
    assert "firewall-cmd --permanent --add-port=8000-8010/udp" in cmd

@pytest.mark.asyncio
async def test_allow_port_reports_missing_sudo(monkeypatch):
    fake_node(monkeypatch, SHOW_FIREWALLD, action=(1, "sudo: a password is required", ""))
    res = await network_service.allow_port("x", 8080, None, "tcp")
    assert res["success"] is False and res["needs_sudo"] is True
    assert "sudo password" in res["message"]

@pytest.mark.asyncio
async def test_allow_port_without_firewall(monkeypatch):
    calls = fake_node(monkeypatch, SHOW_NONE)
    res = await network_service.allow_port("x", 8080, None, "tcp")
    assert res["success"] is False
    assert not any("add-port" in c or "ufw allow" in c for c, _ in calls)

@pytest.mark.asyncio
async def test_allow_port_rejects_bad_input():
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for body in ({"port": 0}, {"port": 80, "end_port": 70}, {"port": 80, "protocol": "icmp"}, {"port": "80;id"}):
            assert (await client.post("/api/v1/network/local/firewall/ports", json=body)).status_code == 422

@pytest.mark.asyncio
async def test_rules_with_one_off_sudo_password(monkeypatch):
    calls = fake_node(monkeypatch, SHOW_FIREWALLD)
    st = await network_service.read_firewall("x", "p w")
    # Still flagged, so the next change prompts for the password again
    assert st["rules"] and st["needs_sudo"] is True
    cmd, stdin = next((c, i) for c, i in calls if "--list-all" in c)
    assert "sudo -k -A" in cmd and "p w" not in cmd and stdin == "p w\n"

@pytest.mark.asyncio
async def test_allow_port_with_password_returns_fresh_rules(monkeypatch):
    calls = fake_node(monkeypatch, SHOW_FIREWALLD)
    res = await network_service.allow_port("x", 8080, None, "tcp", "pw")
    assert res["success"] is True and res["firewall"]["rules"]
    assert all(i == "pw\n" for c, i in calls if "--add-port" in c or "--list-all" in c)

@pytest.mark.asyncio
async def test_allow_port_wrong_password(monkeypatch):
    fake_node(monkeypatch, SHOW_FIREWALLD, action=(1, "Sorry, try again.\nsudo: 1 incorrect password attempt", ""))
    res = await network_service.allow_port("x", 8080, None, "tcp", "bad")
    assert res["success"] is False and res["message"] == "The sudo password is incorrect."

def test_sudo_messages_forced_to_english():
    # Remote locales translate sudo's refusals (e.g. id_ID: "kata sandi diperlukan"); detection matches English
    from app.services.network_service import as_root
    assert "LC_MESSAGES=C sudo -n" in as_root("true", None)[0]
    assert "LC_MESSAGES=C SUDO_ASKPASS" in as_root("true", "pw")[0]

FIREWALLD_LIST_ALL = """public (active)
  target: default
  icmp-block-inversion: no
  interfaces: eth0
  sources: 
  services: cockpit ssh
  ports: 8080/tcp 8000-8010/udp
  protocols: 
  rich rules: 
"""
FIREWALLD_SERVICE_FILES = """== cockpit
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>Cockpit</short>
  <port protocol="tcp" port="9090"/>
</service>
== ssh
<service>
  <port port="22" protocol="tcp"/>
</service>
"""
UFW_STATUS = """Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
Nginx Full                 ALLOW IN    Anywhere
8000:8010/tcp              ALLOW IN    10.0.0.0/8
3000                       ALLOW IN    Anywhere
25/tcp                     DENY IN     Anywhere
53/udp                     ALLOW OUT   Anywhere
22/tcp (v6)                ALLOW IN    Anywhere (v6)
Nginx Full (v6)            ALLOW IN    Anywhere (v6)
"""
UFW_APP_FILES = """[Nginx Full]
title=Web Server (Nginx, HTTP + HTTPS)
ports=80,443/tcp

[OpenSSH]
ports=22/tcp
"""
SHOW_UFW = "LoadState=not-found\nActiveState=inactive\n\nLoadState=loaded\nActiveState=active\n\nLoadState=not-found\nActiveState=inactive\n"
SHOW_NFT = "LoadState=not-found\nActiveState=inactive\n\n" * 2 + "LoadState=loaded\nActiveState=active\n"

def fake_files(monkeypatch, show_output, rules, files):
    calls = []

    async def run(server_id, cmd, stdin=None):
        calls.append((cmd, stdin))
        if cmd.startswith("systemctl show"):
            return 0, show_output, ""
        if "firewalld/services" in cmd or "applications.d" in cmd:
            return 0, files, ""
        return 0, rules, ""

    monkeypatch.setattr(network_service, "_run_command", run)
    return calls

def port(p, end=None, proto="tcp", source=None, name=None):
    return {"port": p, "end_port": end or p, "protocol": proto, "source": source, "name": name}

@pytest.mark.asyncio
async def test_allowed_ports_firewalld_resolves_services(monkeypatch):
    calls = fake_files(monkeypatch, SHOW_FIREWALLD, FIREWALLD_LIST_ALL, FIREWALLD_SERVICE_FILES)
    st = await network_service._firewall_status("x")
    assert st["allow_all"] is False
    assert st["allowed_ports"] == [
        port(9090, name="cockpit"), port(22, name="ssh"), port(8080), port(8000, 8010, "udp"),
    ]
    # Service definitions are world-readable: no sudo for that lookup
    lookup = next(c for c, _ in calls if "firewalld/services" in c)
    assert "sudo" not in lookup and "cockpit" in lookup

@pytest.mark.asyncio
async def test_allowed_ports_firewalld_accept_target(monkeypatch):
    rules = FIREWALLD_LIST_ALL.replace("target: default", "target: ACCEPT")
    fake_files(monkeypatch, SHOW_FIREWALLD, rules, FIREWALLD_SERVICE_FILES)
    assert (await network_service._firewall_status("x"))["allow_all"] is True

@pytest.mark.asyncio
async def test_allowed_ports_firewalld_zone_sources(monkeypatch):
    rules = FIREWALLD_LIST_ALL.replace("sources: ", "sources: 10.0.0.0/8 192.168.1.0/24")
    fake_files(monkeypatch, SHOW_FIREWALLD, rules, FIREWALLD_SERVICE_FILES)
    st = await network_service._firewall_status("x")
    assert {p["source"] for p in st["allowed_ports"]} == {"10.0.0.0/8 192.168.1.0/24"}

@pytest.mark.asyncio
async def test_allowed_ports_ufw(monkeypatch):
    fake_files(monkeypatch, SHOW_UFW, UFW_STATUS, UFW_APP_FILES)
    st = await network_service._firewall_status("x")
    assert st["allow_all"] is False
    # DENY / OUT rules skipped, (v6) duplicates merged, app profiles resolved
    assert st["allowed_ports"] == [
        port(22), port(80, name="Nginx Full"), port(443, name="Nginx Full"),
        port(8000, 8010, source="10.0.0.0/8"), port(3000, proto="any"),
    ]

@pytest.mark.asyncio
async def test_allowed_ports_ufw_default_allow(monkeypatch):
    rules = UFW_STATUS.replace("Default: deny (incoming)", "Default: allow (incoming)")
    fake_files(monkeypatch, SHOW_UFW, rules, UFW_APP_FILES)
    assert (await network_service._firewall_status("x"))["allow_all"] is True

@pytest.mark.asyncio
async def test_allowed_ports_unknown_when_unreadable_or_nftables(monkeypatch):
    fake_node(monkeypatch, SHOW_FIREWALLD, rules=(1, "", "Authorization failed."))
    assert (await network_service._firewall_status("x"))["allowed_ports"] is None
    fake_files(monkeypatch, SHOW_NFT, "table inet filter {\n}", "")
    assert (await network_service._firewall_status("x"))["allowed_ports"] is None

def test_firewalld_service_names_are_validated():
    from app.services.network_service import parse_firewalld_allowed
    _, services, _ = parse_firewalld_allowed(["  services: ssh $(reboot) a;b ok-1.x"])
    assert services == ["ssh", "ok-1.x"]
