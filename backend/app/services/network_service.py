import json
import logging
import re
import shlex
from typing import Dict, Any, List, Tuple, Optional
from app.services.executor import run_on_server
from app.services.ssh_manager import askpass_sudo

logger = logging.getLogger("network_service")

# Checked in this order; the first running one is reported
FIREWALL_ENGINES = ("firewalld.service", "ufw.service", "nftables.service")
FIREWALL_RULES_CMD = {
    "firewalld": "firewall-cmd --list-all",
    "ufw": "ufw status verbose",
    "nftables": "nft list ruleset",
}
# Runtime + permanent, so the port is open now and survives reboot (no --reload: it would drop runtime-only rules)
FIREWALL_ALLOW_CMDS = {
    "firewalld": "firewall-cmd --add-port={spec} && firewall-cmd --permanent --add-port={spec}",
    "ufw": "ufw allow {spec}",
}

def as_root(cmd: str, sudo_password: Optional[str]) -> Tuple[str, Optional[str]]:
    """(command, stdin) running `cmd` as root: with the given one-off sudo password, else directly when
    already root (root login or a sudo-enabled node), else via passwordless sudo."""
    if sudo_password:
        return askpass_sudo(cmd), f"{sudo_password}\n"
    q = shlex.quote(cmd)
    return f'if [ "$(id -u)" = 0 ]; then sh -c {q}; else LC_MESSAGES=C sudo -n -- sh -c {q}; fi', None

def sudo_problem(output: str, sudo_password: Optional[str]) -> Optional[str]:
    """Readable reason when sudo itself refused, else None."""
    if "incorrect password" in output:
        return "The sudo password is incorrect."
    if "not in the sudoers" in output or "not allowed to" in output:
        return "This account is not allowed to use sudo."
    if "password is required" in output and not sudo_password:
        return "Root access needed: enter the sudo password."
    return None

# Allowed-port entries: {"port", "end_port", "protocol" (tcp|udp|any|...), "source" (None = anywhere), "name"}
SERVICE_NAME = re.compile(r"^[\w.+-]+$")
# ufw "To" port specs: 22, 22/tcp, 80,443/tcp, 8000:8010/udp
UFW_PORT_SPEC = re.compile(r"^[\d,:]+(?:/\w+)?$")
UFW_RULE = re.compile(r"^(?P<to>.+?)\s+(?P<action>ALLOW|LIMIT)(?:\s+(?P<dir>IN|OUT|FWD))?\s+(?P<src>.+)$")

def _port_entries(spec: str, protocol: str = "any", source: Optional[str] = None,
                  name: Optional[str] = None) -> List[Dict[str, Any]]:
    """`80,443` / `8000:8010` / `8000-8010` (comma list of ports or ranges) -> entries."""
    entries = []
    for part in spec.split(","):
        lo, _, hi = part.replace(":", "-").partition("-")
        if lo.isdigit() and (not hi or hi.isdigit()):
            entries.append({"port": int(lo), "end_port": int(hi or lo), "protocol": protocol,
                            "source": source, "name": name})
    return entries

def _split_proto(spec: str) -> Tuple[str, str]:
    ports, _, proto = spec.partition("/")
    return ports, proto or "any"

def firewalld_fields(lines: List[str]) -> Dict[str, str]:
    """`firewall-cmd --list-all` `  key: value` lines -> {key: value}."""
    fields = {}
    for line in lines:
        key, sep, value = line.strip().partition(":")
        if sep:
            fields[key] = value.strip()
    return fields

def parse_firewalld_allowed(lines: List[str]) -> Tuple[List[Dict[str, Any]], List[str], bool]:
    """`firewall-cmd --list-all` -> (explicit port entries, service names to resolve, zone accepts everything).
    A zone bound to `sources:` only applies to traffic from them."""
    fields = firewalld_fields(lines)
    source = fields.get("sources") or None
    ports = []
    for spec in fields.get("ports", "").split():
        p, proto = _split_proto(spec)
        ports += _port_entries(p, proto, source)
    services = [s for s in fields.get("services", "").split() if SERVICE_NAME.match(s)]
    return ports, services, fields.get("target") == "ACCEPT"

def parse_firewalld_services(output: str, source: Optional[str]) -> List[Dict[str, Any]]:
    """`== name` headers each followed by that service's XML -> its port entries."""
    entries, name = [], None
    for line in output.splitlines():
        if line.startswith("== "):
            name = line[3:].strip()
            continue
        for tag in re.findall(r"<port\b[^>]*>", line):
            port = re.search(r'\bport="([\d-]+)"', tag)
            proto = re.search(r'\bprotocol="(\w+)"', tag)
            if name and port and proto:
                entries += _port_entries(port.group(1), proto.group(1), source, name)
    return entries

def parse_ufw_apps(output: str) -> Dict[str, List[Tuple[str, str]]]:
    """/etc/ufw/applications.d profiles -> {name: [(ports, proto)]} (`ports=80,443/tcp|53/udp`)."""
    apps: Dict[str, List[Tuple[str, str]]] = {}
    name = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1]
        elif name and line.startswith("ports="):
            apps[name] = [_split_proto(spec) for spec in line[len("ports="):].split("|")]
    return apps

def parse_ufw_allowed(lines: List[str]) -> Tuple[List[Tuple[str, Optional[str]]], bool]:
    """`ufw status verbose` -> ([(To, source)] of incoming ALLOW/LIMIT rules, default incoming is allow)."""
    rules, allow_all = [], False
    for line in lines:
        if line.startswith("Default:"):
            allow_all = "allow (incoming)" in line
            continue
        m = UFW_RULE.match(line.strip())
        if not m or m.group("dir") in ("OUT", "FWD"):
            continue
        to = re.sub(r"\s+on\s+\S+$", "", m.group("to").replace(" (v6)", "")).strip()
        src = m.group("src").replace(" (v6)", "").strip()
        rules.append((to, None if src == "Anywhere" else src))
    return rules, allow_all

def _dedupe(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for e in entries:
        key = tuple(e.values())
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out

class NetworkService:
    async def _run_command(self, server_id: str, cmd: str, stdin: Optional[str] = None) -> Tuple[int, str, str]:
        return await run_on_server(server_id, cmd, timeout=15.0, stdin=stdin)

    async def get_network_overview(self, server_id: str) -> Dict[str, Any]:
        # 1. Interfaces
        exit_code, stdout, _ = await self._run_command(server_id, "ip -j addr 2>/dev/null")
        interfaces = []
        if exit_code == 0 and stdout.strip():
            try:
                interfaces = json.loads(stdout)
            except Exception as e:
                logger.error(f"Failed to parse ip -j addr: {e}")

        # 2. Listening sockets
        ss_cmd = "ss -tulnH 2>/dev/null"
        exit_code_ss, stdout_ss, _ = await self._run_command(server_id, ss_cmd)
        listening_sockets = []
        for line in stdout_ss.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                proto = parts[0]
                state = parts[1]
                local_addr = parts[4]
                listening_sockets.append({
                    "proto": proto,
                    "state": state,
                    "local_address": local_addr
                })

        # 3. Firewall status
        firewall = await self._firewall_status(server_id)

        return {
            "server_id": server_id,
            "interfaces": interfaces,
            "listening_sockets": listening_sockets[:50],
            "firewall": firewall
        }

    async def _firewall_status(
        self, server_id: str, sudo_password: Optional[str] = None, read_rules: bool = True
    ) -> Dict[str, Any]:
        # Ask systemd which engine runs: unlike firewall-cmd/ufw/nft this needs no root, so an
        # unprivileged node (polkit refuses firewall-cmd over SSH) still reports the right engine.
        exit_code, stdout, _ = await self._run_command(
            server_id, "systemctl show --property=LoadState,ActiveState -- " + " ".join(FIREWALL_ENGINES) + " 2>/dev/null"
        )
        blocks = stdout.strip().split("\n\n") if stdout.strip() else []
        states: Dict[str, Dict[str, str]] = {}
        if len(blocks) == len(FIREWALL_ENGINES):
            for unit, block in zip(FIREWALL_ENGINES, blocks):
                states[unit[:-len(".service")]] = dict(
                    line.split("=", 1) for line in block.splitlines() if "=" in line
                )

        active = [e for e, st in states.items() if st.get("ActiveState") == "active"]
        installed = [e for e, st in states.items() if st.get("LoadState") == "loaded"]
        engine = (active or installed or [None])[0]
        if engine is None:
            return {"type": "none", "active": False, "rules": [], "needs_sudo": False,
                    "note": "No firewalld, ufw or nftables service found."}

        # needs_sudo: root actions on this node need a sudo password (stays true after one worked)
        result: Dict[str, Any] = {
            "type": engine, "active": engine in active, "rules": [], "note": None, "needs_sudo": bool(sudo_password),
            # allowed_ports: None = unknown (rules unread, or a hand-written nftables ruleset)
            "allowed_ports": None, "allow_all": False,
        }
        if not result["active"]:
            result["note"] = f"{engine} is installed but not running."
            return result
        if not read_rules:
            return result

        # Reading rules needs root
        cmd, stdin = as_root(f"{FIREWALL_RULES_CMD[engine]} 2>&1", sudo_password)
        code, out, err = await self._run_command(server_id, cmd, stdin=stdin)
        if code == 0 and out.strip():
            result["rules"] = out.splitlines()
            if engine == "ufw":
                # ufw.service stays active even when ufw itself is disabled
                result["active"] = any(l.strip().lower() == "status: active" for l in result["rules"])
            if result["active"] and engine in ("firewalld", "ufw"):
                result["allowed_ports"], result["allow_all"] = await self._allowed_ports(
                    server_id, engine, result["rules"]
                )
        else:
            problem = sudo_problem(out + err, sudo_password)
            result["needs_sudo"] = True
            result["note"] = f"{engine} is running, but its rules need root to read. " + (
                problem if problem and sudo_password else "Enter the sudo password to show them."
            )
        return result

    async def _allowed_ports(self, server_id: str, engine: str, rules: List[str]) -> Tuple[List[Dict[str, Any]], bool]:
        """Ports the firewall lets in, with named services / app profiles resolved from their
        world-readable definition files (no root needed for that lookup)."""
        if engine == "firewalld":
            ports, services, allow_all = parse_firewalld_allowed(rules)
            if services:
                names = " ".join(shlex.quote(s) for s in services)
                _, out, _ = await self._run_command(
                    server_id,
                    f'for s in {names}; do echo "== $s"; cat "/etc/firewalld/services/$s.xml" 2>/dev/null'
                    f' || cat "/usr/lib/firewalld/services/$s.xml" 2>/dev/null; done',
                )
                ports = parse_firewalld_services(out, firewalld_fields(rules).get("sources") or None) + ports
            return _dedupe(ports), allow_all

        to_rules, allow_all = parse_ufw_allowed(rules)
        apps: Dict[str, List[Tuple[str, str]]] = {}
        if any(not UFW_PORT_SPEC.match(to.split()[-1]) and to != "Anywhere" for to, _ in to_rules):
            _, out, _ = await self._run_command(server_id, "cat /etc/ufw/applications.d/* 2>/dev/null")
            apps = parse_ufw_apps(out)
        ports: List[Dict[str, Any]] = []
        for to, source in to_rules:
            if to == "Anywhere":
                # Everything from one source
                ports += _port_entries("1-65535", "any", source)
            elif UFW_PORT_SPEC.match(to.split()[-1]):
                ports += _port_entries(*_split_proto(to.split()[-1]), source)
            else:
                for p, proto in apps.get(to, []):
                    ports += _port_entries(p, proto, source, to)
        return _dedupe(ports), allow_all

    async def read_firewall(self, server_id: str, sudo_password: Optional[str]) -> Dict[str, Any]:
        return await self._firewall_status(server_id, sudo_password=sudo_password)

    async def allow_port(
        self, server_id: str, port: int, end_port: Optional[int], protocol: str, sudo_password: Optional[str] = None
    ) -> Dict[str, Any]:
        # port/end_port are range-checked ints and protocol is tcp|udp (FirewallPortRequest), so the
        # command below holds no free-form input
        status = await self._firewall_status(server_id, read_rules=False)
        engine = status["type"]
        if engine not in FIREWALL_ALLOW_CMDS or not status["active"]:
            return {"success": False, "message": f"Adding ports needs a running firewalld or ufw (found: {engine})."}

        sep = "-" if engine == "firewalld" else ":"
        spec = f"{port}{sep}{end_port}/{protocol}" if end_port and end_port != port else f"{port}/{protocol}"
        cmd, stdin = as_root(FIREWALL_ALLOW_CMDS[engine].format(spec=spec) + " 2>&1", sudo_password)
        code, out, err = await self._run_command(server_id, cmd, stdin=stdin)
        output = (out + err).strip()
        if code != 0:
            problem = sudo_problem(output, sudo_password)
            return {"success": False, "message": problem or f"Failed to allow {spec}: {output}", "needs_sudo": bool(problem)}
        # The password just worked, so reuse it once to show the updated rules
        return {
            "success": True,
            "message": f"Allowed {spec} ({engine}).",
            "firewall": await self._firewall_status(server_id, sudo_password=sudo_password),
        }

network_service = NetworkService()
