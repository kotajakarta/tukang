"""
Role-based access policy. One table, evaluated for every authenticated HTTP request and WebSocket.

Defaults are deny-leaning: reads need `viewer`, every write needs `admin`, unless a rule below says
otherwise. Paths are FastAPI route templates relative to /api/v1.
"""
import re
from typing import List, Tuple
from app.models.user import ROLE_RANK

# (method, route template regex, minimum role) — first match wins
RULES: List[Tuple[str, str, str]] = [
    # Day-to-day operations
    ("POST", r"^/services/\{server_id\}/\{unit\}/action$", "operator"),
    ("POST", r"^/containers/\{server_id\}/\{container_id\}/action$", "operator"),
    ("POST", r"^/servers/\{server_id\}/test$", "operator"),
    # Reads that may expose secrets (env vars in logs/unit files) need operator
    ("GET", r"^/services/\{server_id\}/\{unit\}/logs$", "operator"),
    ("GET", r"^/containers/\{server_id\}/\{container_id\}/logs$", "operator"),
    ("GET", r"^/containers/\{server_id\}/quadlets/content$", "operator"),
    # File manager acts as root on the node: browsing/reading files is root-equivalent
    ("GET", r"^/files/", "admin"),
    # Governance
    ("GET", r"^/audit", "admin"),
    ("GET", r"^/app-users", "admin"),
]

WEBSOCKET_ROLES = {
    "/ws/terminal": "admin",  # a shell on the node is root-equivalent
    "/ws/metrics": "viewer",
}

def required_role(method: str, route_path: str) -> str:
    for rule_method, pattern, role in RULES:
        if method == rule_method and re.search(pattern, route_path):
            return role
    return "viewer" if method in ("GET", "HEAD") else "admin"

def has_role(user_role: str, needed: str) -> bool:
    return ROLE_RANK.get(user_role, 0) >= ROLE_RANK[needed]
