#!/usr/bin/env bash
# One-time migration of a pre-rebrand install (Cockpit-Py) to tuKang, keeping all data.
# AIT HENDI
#
# deploy/dep.sh runs this automatically when it finds the old Quadlet; you can also run it by hand,
# as the same rootless user, from the repository root:
#
#   ./deploy/migrate-from-cockpit-py.sh
#
# What it does (nothing old is deleted; cleanup commands are printed at the end):
#   1. stops cockpit-py.service
#   2. copies podman secrets  cockpit-py-{admin-password,data-key,ssh-key} -> tukang-*
#   3. copies volume          cockpit-py-data -> tukang-data   (the app renames cockpit.db -> tukang.db)
#   4. renames host account   cockpit-mgr -> tukang-mgr  and drops /etc/sudoers.d/cockpit-py
#                             (dep.sh --setup then writes /etc/sudoers.d/tukang and authorized_keys)
#   5. moves the old Quadlet out of ~/.config/containers/systemd
set -euo pipefail

QUADLET_DIR="$HOME/.config/containers/systemd"
OLD_QUADLET="$QUADLET_DIR/cockpit-py.container"
OLD_IMAGE="localhost/cockpit-py:latest"
OLD_USER="cockpit-mgr"
NEW_USER="tukang-mgr"

green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }
die() { printf '\033[0;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n\033[0;34m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" -ne 0 ] || die "Run as the rootless user that owns the cockpit-py container, not root."
[ -f "$OLD_QUADLET" ] || podman volume exists cockpit-py-data 2>/dev/null \
  || { green "No Cockpit-Py install found for $(whoami); nothing to migrate."; exit 0; }

# ---------------------------------------------------------------- stop
step "Stopping cockpit-py"
# Stopped before copying so SQLite is not written to mid-copy (Quadlet containers are --rm: this removes it)
systemctl --user stop cockpit-py.service 2>/dev/null || true
podman container exists cockpit-py 2>/dev/null && podman rm -f cockpit-py >/dev/null
green "stopped"

# ---------------------------------------------------------------- secrets
step "Secrets"
copy_secret() {
  local old="$1" new="$2" trailing_newline="$3" value
  if podman secret exists "$new" 2>/dev/null; then
    green "$new already exists (kept)"; return
  fi
  podman secret exists "$old" 2>/dev/null || { yellow "$old not found; dep.sh will create $new"; return; }
  # $(...) drops the newline `inspect` appends; printf is a builtin, so the value never shows up in `ps`
  value="$(podman secret inspect --showsecret --format '{{.SecretData}}' "$old")" \
    || die "Cannot read $old (needs Podman >= 4.5 for --showsecret). Recreate $new by hand, see docs/DEPLOY.md."
  if [ "$trailing_newline" = "1" ]; then
    printf '%s\n' "$value" | podman secret create "$new" - >/dev/null
  else
    printf '%s' "$value" | podman secret create "$new" - >/dev/null
  fi
  unset value
  green "$old -> $new"
}
copy_secret cockpit-py-admin-password tukang-admin-password 0
copy_secret cockpit-py-data-key       tukang-data-key       0
copy_secret cockpit-py-ssh-key        tukang-ssh-key        1   # OpenSSH key files end with a newline

if [ -f "$HOME/cockpit-py-data-key.backup" ] && [ ! -e "$HOME/tukang-data-key.backup" ]; then
  mv "$HOME/cockpit-py-data-key.backup" "$HOME/tukang-data-key.backup"
  green "~/cockpit-py-data-key.backup -> ~/tukang-data-key.backup"
fi

# ---------------------------------------------------------------- data volume
step "Data volume"
if podman volume exists tukang-data 2>/dev/null; then
  green "tukang-data already exists (kept)"
elif podman volume exists cockpit-py-data 2>/dev/null; then
  podman image exists "$OLD_IMAGE" \
    || die "$OLD_IMAGE is gone, so the volume cannot be copied with ownership intact. Rebuild it from the old revision first."
  podman volume create tukang-data >/dev/null
  # cp -a as root inside the user namespace keeps the app's uid 1000 ownership and modes
  if ! podman run --rm --user 0 --network none \
      -v cockpit-py-data:/from:ro,Z -v tukang-data:/to:Z \
      "$OLD_IMAGE" cp -a /from/. /to/; then
    podman volume rm tukang-data >/dev/null 2>&1 || true
    die "Copying cockpit-py-data failed; tukang-data was removed again, cockpit-py-data is untouched."
  fi
  green "cockpit-py-data -> tukang-data (the app renames cockpit.db to tukang.db on first start)"
else
  yellow "cockpit-py-data not found; tuKang will start with an empty database"
fi

# ---------------------------------------------------------------- host account
step "Host management account"
if getent passwd "$OLD_USER" >/dev/null && ! getent passwd "$NEW_USER" >/dev/null; then
  OLD_HOME="$(getent passwd "$OLD_USER" | cut -d: -f6)"
  NEW_HOME="$(dirname "$OLD_HOME")/$NEW_USER"
  # usermod refuses to rename an account that still runs processes (e.g. a leftover SSH session)
  sudo pkill -u "$OLD_USER" 2>/dev/null && sleep 1 || true
  sudo usermod -l "$NEW_USER" -d "$NEW_HOME" -m -c "tuKang management (SSH from container only)" "$OLD_USER"
  if getent group "$OLD_USER" >/dev/null; then sudo groupmod -n "$NEW_USER" "$OLD_USER"; fi
  sudo restorecon -R "$NEW_HOME" 2>/dev/null || true   # SELinux label for sshd after the move
  green "$OLD_USER -> $NEW_USER (home $NEW_HOME, authorized_keys kept)"
elif getent passwd "$NEW_USER" >/dev/null; then
  green "$NEW_USER already exists (kept)"
else
  yellow "$OLD_USER not found (custom LOCAL_SSH_USER?); keep passing LOCAL_SSH_USER=<user> to dep.sh"
fi
if sudo test -e /etc/sudoers.d/cockpit-py; then
  sudo rm -f /etc/sudoers.d/cockpit-py
  green "removed /etc/sudoers.d/cockpit-py (dep.sh --setup writes /etc/sudoers.d/tukang)"
fi

# ---------------------------------------------------------------- quadlet
step "Old Quadlet"
if [ -f "$OLD_QUADLET" ]; then
  BAK="$HOME/cockpit-py.container.bak-$(date +%Y%m%d-%H%M%S)"
  mv "$OLD_QUADLET" "$BAK"
  systemctl --user daemon-reload
  green "moved to $BAK"
fi

cat <<EOF

$(green "Migration done. Kept as backup (remove once tuKang works):")
  podman volume rm cockpit-py-data
  podman secret rm cockpit-py-admin-password cockpit-py-data-key cockpit-py-ssh-key
  podman rmi $OLD_IMAGE
  rm ~/cockpit-py.container.bak-*

$(yellow "ACTION NEEDED: the container is now called 'tukang'. Point your Cloudflare Tunnel public hostname")
$(yellow "to http://tukang:8000 (it was http://cockpit-py:8000), or the site stays offline.")
$(yellow "Servers you added with username '$OLD_USER' on OTHER hosts are not touched and keep working.")
$(yellow "Everyone is signed out once (new session cookie name).")
EOF
