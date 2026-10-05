#!/usr/bin/env bash
# Cockpit-Py installer for RHEL (rootless Podman + Quadlet).
# AIT HENDI
# Run as the SAME non-root user that owns the rootless cloudflared container / global_net network,
# from the repository root, in a real login session (ssh user@server, not `sudo su - user`):
#
#   ./deploy/dep.sh
#
# Every run pulls the latest code (when the repo is a git checkout with an upstream), rebuilds the
# image from it and restarts the container on the new image, so re-running this script is also how
# you update. Updates need no sudo.
#
# The one-time host setup (management account, sudoers, authorized_keys — all via sudo) runs only on
# the first install, or when forced:
#
#   ./deploy/dep.sh --setup
#
# Options (env vars):
#   LOCAL_SSH_USER=cockpit-mgr  host account the container SSHes into. Default: a dedicated user with
#                               passwordless sudo (every command lands in the host's sudo log).
#                               Set to root to log in as root directly (not recommended).
#   NETWORK=global_net      podman network shared with cloudflared
#   CLOUDFLARED_HOST=cloudflared  name of the cloudflared container on that network: the only peer whose
#                               CF-Connecting-IP header is trusted as the visitor's address
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_SSH_USER="${LOCAL_SSH_USER:-cockpit-mgr}"
if [ "$LOCAL_SSH_USER" = "root" ]; then LOCAL_SSH_SUDO=false; else LOCAL_SSH_SUDO=true; fi
NETWORK="${NETWORK:-global_net}"
CLOUDFLARED_HOST="${CLOUDFLARED_HOST:-cloudflared}"
QUADLET_DIR="$HOME/.config/containers/systemd"
IMAGE="localhost/cockpit-py:latest"

green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }
die() { printf '\033[0;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n\033[0;34m==> %s\033[0m\n' "$*"; }

SETUP=0
for arg in "$@"; do
  case "$arg" in
    --setup) SETUP=1 ;;
    *) die "Unknown option: $arg (only --setup is supported)" ;;
  esac
done
# First install (or a half-finished one) needs the host setup too
if [ ! -f "$QUADLET_DIR/cockpit-py.container" ] || ! getent passwd "$LOCAL_SSH_USER" >/dev/null; then
  SETUP=1
fi
for s in cockpit-py-admin-password cockpit-py-data-key cockpit-py-ssh-key; do
  podman secret exists "$s" 2>/dev/null || SETUP=1
done

# ---------------------------------------------------------------- preflight
step "Preflight checks"
[ "$(id -u)" -ne 0 ] || die "Run as the rootless user, not root."
command -v podman >/dev/null || die "podman not installed (sudo dnf install -y podman)"
[ -n "${XDG_RUNTIME_DIR:-}" ] && systemctl --user show-environment >/dev/null 2>&1 \
  || die "No systemd user session. Log in directly via SSH as $(whoami) (not 'sudo su')."

PODMAN_VER="$(podman version --format '{{.Client.Version}}')"
# Quadlet Secret=/HealthCmd=/ReadOnly= need Podman >= 4.6 (RHEL 9.3+)
if [ "$(printf '%s\n4.6.0\n' "$PODMAN_VER" | sort -V | head -1)" != "4.6.0" ]; then
  die "Podman $PODMAN_VER is too old; need >= 4.6 (RHEL 9.3+). Run: sudo dnf update podman"
fi
green "podman $PODMAN_VER OK"

podman network exists "$NETWORK" \
  || die "Network '$NETWORK' not found for user $(whoami). It must be owned by the same rootless user as cloudflared."
green "network $NETWORK OK"

if [ "$(loginctl show-user "$(whoami)" -p Linger --value 2>/dev/null)" != "yes" ]; then
  yellow "Enabling linger so the service survives logout/reboot (needs sudo)..."
  sudo loginctl enable-linger "$(whoami)"
fi
green "linger OK"

# ---------------------------------------------------------------- source
step "Updating source"
if git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
   && git -C "$REPO_DIR" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  git -C "$REPO_DIR" pull --ff-only || die "git pull failed (local commits or conflicts?). Resolve it, then re-run."
  green "source at $(git -C "$REPO_DIR" log -1 --format='%h %s')"
else
  yellow "No git upstream; building from the files currently in $REPO_DIR"
fi
REVISION="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || date +build-%Y%m%d-%H%M%S)"
[ -z "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ] || REVISION="$REVISION-dirty"

# ---------------------------------------------------------------- image
step "Building $IMAGE (revision $REVISION)"
OLD_IMAGE_ID="$(podman image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || true)"
podman build -t "$IMAGE" -f "$REPO_DIR/Containerfile" \
  --label "org.opencontainers.image.revision=$REVISION" \
  --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$REPO_DIR" || die "Image build failed; the running service was left untouched."
NEW_IMAGE_ID="$(podman image inspect "$IMAGE" --format '{{.Id}}')"
green "built $IMAGE ${NEW_IMAGE_ID:0:12}"

# ---------------------------------------------------------------- secrets
step "Secrets"
if podman secret exists cockpit-py-admin-password 2>/dev/null; then
  green "cockpit-py-admin-password already exists (kept)"
else
  read -rsp "Initial password for Cockpit-Py user 'admin' (min 12 chars): " ADMIN_PW; echo
  [ "${#ADMIN_PW}" -ge 12 ] || die "Password too short (min 12)."
  printf '%s' "$ADMIN_PW" | podman secret create cockpit-py-admin-password - >/dev/null
  unset ADMIN_PW
  green "cockpit-py-admin-password created"
fi

if podman secret exists cockpit-py-data-key 2>/dev/null; then
  green "cockpit-py-data-key already exists (kept)"
else
  DATA_KEY="$(podman run --rm "$IMAGE" python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  printf '%s' "$DATA_KEY" | podman secret create cockpit-py-data-key - >/dev/null
  BACKUP="$HOME/cockpit-py-data-key.backup"
  ( umask 077; printf '%s\n' "$DATA_KEY" > "$BACKUP" )
  unset DATA_KEY
  green "cockpit-py-data-key created"
  yellow "A copy is in $BACKUP — move it to your password manager / vault, then delete it."
  yellow "Without this key, stored server credentials and MFA secrets cannot be decrypted."
fi

if podman secret exists cockpit-py-ssh-key 2>/dev/null; then
  green "cockpit-py-ssh-key already exists (kept)"
else
  TMPKEY="$(mktemp -d)/cockpit-py"
  ssh-keygen -q -t ed25519 -N '' -C "cockpit-py@$(hostname)" -f "$TMPKEY"
  podman secret create cockpit-py-ssh-key "$TMPKEY" >/dev/null
  rm -rf "$(dirname "$TMPKEY")"
  green "cockpit-py-ssh-key created"
fi

# Writes exactly one authorized_keys line for our key (replacing any previous one) with given options
authorize_key() {
  local user="$1" opts="$2" home auth tmp
  home="$(getent passwd "$user" | cut -d: -f6)"
  auth="$home/.ssh/authorized_keys"
  sudo install -d -m 700 -o "$user" -g "$(id -gn "$user")" "$home/.ssh"
  tmp="$(mktemp)"
  sudo sh -c "cat '$auth' 2>/dev/null || true" | grep -vF "$KEY_BODY" > "$tmp" || true
  if [ -n "$opts" ]; then
    printf '%s %s %s cockpit-py@%s\n' "$opts" "$KEY_TYPE" "$KEY_BODY" "$(hostname)" >> "$tmp"
  fi
  sudo install -m 600 -o "$user" -g "$(id -gn "$user")" "$tmp" "$auth"
  rm -f "$tmp"
  sudo restorecon -R "$home/.ssh" 2>/dev/null || true   # SELinux label for sshd
}

if [ "$SETUP" = "1" ]; then
# Public half of the key, read back from the secret (so re-runs are idempotent)
PUBKEY="$(podman run --rm --secret cockpit-py-ssh-key,type=mount,target=/run/secrets/k,uid=1000,mode=0400 "$IMAGE" \
  python -c "import asyncssh; print(asyncssh.read_private_key('/run/secrets/k').export_public_key().decode().strip())")"
KEY_TYPE="$(echo "$PUBKEY" | awk '{print $1}')"
KEY_BODY="$(echo "$PUBKEY" | awk '{print $2}')"
[ -n "$KEY_BODY" ] || die "Could not read the public key from cockpit-py-ssh-key."

# ---------------------------------------------------------------- host management account
step "Host management account ($LOCAL_SSH_USER)"
if [ "$LOCAL_SSH_USER" != "root" ]; then
  if ! getent passwd "$LOCAL_SSH_USER" >/dev/null; then
    sudo useradd -m -s /bin/bash -c "Cockpit-Py management (SSH from container only)" "$LOCAL_SSH_USER"
    # '*' = no password can ever match (key-only). Not 'passwd -l': sshd without PAM treats a '!' lock
    # as a fully locked account and refuses public-key logins too.
    sudo usermod -p '*' "$LOCAL_SSH_USER"
    green "created user $LOCAL_SSH_USER (no password, key-only)"
  fi
  SUDOERS_TMP="$(mktemp)"
  cat > "$SUDOERS_TMP" <<SUDOERS
# Managed by the Cockpit-Py installer.
# Cockpit-Py logs in as $LOCAL_SSH_USER and elevates with sudo; each command is recorded by sudo
# (journalctl _COMM=sudo). Remove this file to revoke Cockpit-Py's administrative access.
Defaults:$LOCAL_SSH_USER !requiretty
$LOCAL_SSH_USER ALL=(ALL) NOPASSWD: ALL
SUDOERS
  sudo visudo -cf "$SUDOERS_TMP" >/dev/null || die "Generated sudoers file is invalid."
  sudo install -m 0440 -o root -g root "$SUDOERS_TMP" /etc/sudoers.d/cockpit-py
  rm -f "$SUDOERS_TMP"
  green "sudoers entry /etc/sudoers.d/cockpit-py OK"
fi

# restrict = no port/agent/X11 forwarding; pty re-enabled for the web terminal
authorize_key "$LOCAL_SSH_USER" "restrict,pty"
if [ "$LOCAL_SSH_USER" != "root" ] && sudo grep -qF "$KEY_BODY" /root/.ssh/authorized_keys 2>/dev/null; then
  authorize_key root ""   # remove the key from root left by an older install
  green "removed legacy root authorization for this key"
fi
green "key authorized for $LOCAL_SSH_USER (restrict,pty)"
else
  step "Host setup"
  green "already set up (skipped; run with --setup to redo it)"
fi

# ---------------------------------------------------------------- quadlet
step "Installing Quadlet"
mkdir -p "$QUADLET_DIR"
sed -e "s/^Network=.*/Network=$NETWORK/" \
    -e "s/^Environment=LOCAL_SSH_USER=.*/Environment=LOCAL_SSH_USER=$LOCAL_SSH_USER/" \
    -e "s/^Environment=LOCAL_SSH_SUDO=.*/Environment=LOCAL_SSH_SUDO=$LOCAL_SSH_SUDO/" \
    -e "s/^Environment=TRUSTED_PROXIES=.*/Environment=TRUSTED_PROXIES=$CLOUDFLARED_HOST/" \
    "$REPO_DIR/deploy/cockpit-py.container" > "$QUADLET_DIR/cockpit-py.container"

QUADLET_BIN="$(command -v /usr/libexec/podman/quadlet || true)"
if [ -n "$QUADLET_BIN" ]; then
  "$QUADLET_BIN" --user --dryrun >/dev/null 2>"/tmp/cockpit-py-quadlet.err" \
    || { cat /tmp/cockpit-py-quadlet.err; die "Quadlet validation failed."; }
fi

systemctl --user daemon-reload
# Quadlet runs the container with --replace, so a restart recreates it from the newly built image
systemctl --user restart cockpit-py.service
green "cockpit-py.service restarted"

# ---------------------------------------------------------------- verify
step "Verifying"
for _ in $(seq 1 30); do
  podman exec cockpit-py python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2)" 2>/dev/null && break
  sleep 1
done
podman exec cockpit-py python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2)" \
  || { journalctl --user -u cockpit-py -n 30 --no-pager; die "App did not become healthy."; }
green "HTTP health OK"

RUNNING_IMAGE_ID="$(podman inspect cockpit-py --format '{{.Image}}')"
[ "$RUNNING_IMAGE_ID" = "$NEW_IMAGE_ID" ] \
  || die "cockpit-py is running image ${RUNNING_IMAGE_ID:0:12}, not the new build ${NEW_IMAGE_ID:0:12}."
green "running the new image (revision $REVISION)"

if podman exec cockpit-py python -c "import socket,sys; socket.getaddrinfo(sys.argv[1], None)" "$CLOUDFLARED_HOST" 2>/dev/null; then
  green "trusted proxy '$CLOUDFLARED_HOST' resolves on $NETWORK"
else
  yellow "Cannot resolve '$CLOUDFLARED_HOST' from cockpit-py: visitor IPs (rate limiting, audit) will all show as the"
  yellow "  tunnel's address. Re-run with CLOUDFLARED_HOST=<your cloudflared container name>."
fi

# The previous build is now untagged and unused; drop it so rebuilds don't pile up on disk
if [ -n "$OLD_IMAGE_ID" ] && [ "$OLD_IMAGE_ID" != "$NEW_IMAGE_ID" ]; then
  podman rmi "$OLD_IMAGE_ID" >/dev/null 2>&1 && green "removed previous image ${OLD_IMAGE_ID:0:12}" || true
fi

# Runs a command on the host over the same SSH path the app uses; prints its stdout
host_ssh() {
  podman exec cockpit-py python -c "
import asyncio, asyncssh, sys
async def main():
    async with asyncssh.connect('host.containers.internal', username='$LOCAL_SSH_USER',
            client_keys=['/run/secrets/host_ssh_key'], known_hosts=None) as c:
        r = await c.run(sys.argv[1])
        print(r.stdout.strip()); sys.exit(r.exit_status)
asyncio.run(asyncio.wait_for(main(), 10))
" "$1"
}

SSH_CONN="$(host_ssh 'echo $SSH_CONNECTION' 2>/dev/null)" || SSH_CONN=""
if [ -n "$SSH_CONN" ]; then
  green "SSH from container to host OK"
  if [ "$LOCAL_SSH_SUDO" = "true" ]; then
    host_ssh 'sudo -n true' >/dev/null && green "passwordless sudo OK" || yellow "sudo -n failed for $LOCAL_SSH_USER — check /etc/sudoers.d/cockpit-py"
  fi
fi

if [ "$SETUP" = "1" ] && [ -n "$SSH_CONN" ]; then
  # Pin the key to the address the container connects from, so a leaked key is useless elsewhere.
  # If that address is inside the podman network, allow the whole subnet (container IPs can change).
  SRC_IP="$(echo "$SSH_CONN" | awk '{print $1}')"
  SUBNETS="$(podman network inspect "$NETWORK" --format '{{range .Subnets}}{{.Subnet}} {{end}}')"
  FROM="$(podman run --rm "$IMAGE" python -c "
import ipaddress, sys
ip = ipaddress.ip_address(sys.argv[1])
nets = [n for n in sys.argv[2:] if ip in ipaddress.ip_network(n)]
print(nets[0] if nets else sys.argv[1])
" "$SRC_IP" $SUBNETS)"
  authorize_key "$LOCAL_SSH_USER" "restrict,pty,from=\"$FROM\""
  if host_ssh true >/dev/null; then
    green "key restricted to connections from $FROM"
  else
    authorize_key "$LOCAL_SSH_USER" "restrict,pty"
    yellow "Restricting the key to $FROM broke SSH; reverted to restrict,pty without from=."
  fi
fi
if [ -z "$SSH_CONN" ]; then
  yellow "SSH from container to host FAILED. Check: sudo systemctl status sshd;"
  yellow "  /etc/ssh/sshd_config ListenAddress / AllowUsers; and $LOCAL_SSH_USER's ~/.ssh/authorized_keys."
  yellow "  ./deploy/dep.sh --setup re-authorizes the key."
fi

if [ "$SETUP" != "1" ]; then
  printf '\n%s\n' "$(green "Done. cockpit-py is running revision $REVISION.")"
  exit 0
fi

cat <<EOF

$(green "Done.")
Point your Cloudflare Tunnel public hostname to:   http://cockpit-py:8000
Then log in as 'admin': you will be asked to set up two-factor authentication (MFA_REQUIRED=true).
Change the initial password from the account menu, and create named accounts in Access Control.

Logs:     journalctl --user -u cockpit-py -f
Restart:  systemctl --user restart cockpit-py
Update:   ./deploy/dep.sh   (pulls, rebuilds and restarts on the latest code; no sudo)

Hardening tip: Cockpit-Py no longer needs root SSH logins. Once everything works, consider
'PermitRootLogin no' in /etc/ssh/sshd_config (keep another admin path open while testing!).
EOF
