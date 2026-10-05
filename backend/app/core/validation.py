"""
Input validators for values that end up in shell commands on managed nodes.

Every value interpolated into a command must be (1) validated here and (2) passed through
shlex.quote. Free-form data (file contents, SSH keys) must go through stdin, never the command line.
"""
import posixpath
import re
from fastapi import HTTPException, status

UNIT_TYPES = ("service", "timer", "socket", "target", "mount", "path", "slice", "scope")
QUADLET_EXTENSIONS = (".container", ".network", ".volume", ".image", ".kube", ".pod", ".build")

# systemd unit names: ASCII letters, digits, ":-_.\@" (systemd.unit(5)); must not look like an option
_UNIT_RE = re.compile(r"^[A-Za-z0-9:_.@\\][A-Za-z0-9:_.@\\-]{0,255}$")
# podman container IDs / names
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,253}$")
# POSIX-ish login names (useradd default NAME_REGEX, plus optional trailing $ for machine accounts)
_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\$?$")
_SHELL_RE = re.compile(r"^/[A-Za-z0-9/_.-]{1,127}$")
# Block device names under /dev, e.g. sda, nvme0n1, mapper/rhel-root
_DEVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}(/[A-Za-z0-9][A-Za-z0-9_.-]{0,127})?$")
_QUADLET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,200}$")
_SSH_PUBKEY_RE = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|"
    r"sk-ecdsa-sha2-nistp256@openssh\.com) [A-Za-z0-9+/]+={0,3}( [^\r\n]{0,256})?$"
)

# Directories Quadlet reads from (podman-systemd.unit(5)); user dirs are matched by suffix.
_SYSTEM_QUADLET_DIRS = (
    "/etc/containers/systemd/",
    "/run/containers/systemd/",
    "/usr/share/containers/systemd/",
    "/usr/local/share/containers/systemd/",
)
_USER_QUADLET_DIR_RE = re.compile(
    r"^(/root|/home/[^/]+|/var/home/[^/]+)/(\.config|\.local/share)/containers/systemd/"
    r"|^/run/user/\d+/containers/systemd/"
    r"|^/etc/containers/systemd/users/(\d+/)?"
)

def _bad(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {what}")

def unit_name(value: str) -> str:
    if not _UNIT_RE.match(value or ""):
        raise _bad("unit name")
    return value

def unit_type(value: str) -> str:
    if value not in UNIT_TYPES:
        raise _bad("unit type")
    return value

def container_ref(value: str) -> str:
    if not _CONTAINER_RE.match(value or ""):
        raise _bad("container id")
    return value

def username(value: str) -> str:
    if not _USERNAME_RE.match(value or ""):
        raise _bad("username")
    return value

def login_shell(value: str) -> str:
    if not _SHELL_RE.match(value or "") or ".." in value:
        raise _bad("shell")
    return value

def block_device(value: str) -> str:
    if not _DEVICE_RE.match(value or "") or ".." in value:
        raise _bad("device")
    return value

def ssh_public_key(value: str) -> str:
    value = (value or "").strip()
    if not _SSH_PUBKEY_RE.match(value):
        raise _bad("SSH public key (expected one line: '<type> <base64> [comment]')")
    return value

def quadlet_filename(value: str) -> str:
    if (
        not _QUADLET_NAME_RE.match(value or "")
        or ".." in value
        or not value.endswith(QUADLET_EXTENSIONS)
    ):
        raise _bad("quadlet filename")
    return value

def quadlet_path(value: str) -> str:
    """Absolute path to an existing quadlet file inside a directory Quadlet actually reads."""
    if not value or "\x00" in value or not value.startswith("/"):
        raise _bad("quadlet path")
    norm = posixpath.normpath(value)
    if norm != value or not norm.endswith(QUADLET_EXTENSIONS):
        raise _bad("quadlet path")
    if not (norm.startswith(_SYSTEM_QUADLET_DIRS) or _USER_QUADLET_DIR_RE.match(norm)):
        raise _bad("quadlet path")
    return norm
