#!/usr/bin/env bash
# Auto-sync this working copy to the server on every save (needs entr + rsync, SSH key login).
# WSL: files under /mnt/* edited from Windows apps raise no inotify events; edit via Remote-WSL.
set -u
# Always sync the repository this script lives in (with --delete, syncing the wrong cwd would be destructive)
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

# Server details live in .sync.env (gitignored); see .sync.env.example
[ -f .sync.env ] || { echo "Buat .sync.env dulu: cp .sync.env.example .sync.env, lalu isi nilainya"; exit 1; }
# shellcheck source=/dev/null
. ./.sync.env
: "${REMOTE_USER:?REMOTE_USER belum diisi di .sync.env}"
: "${REMOTE_HOST:?REMOTE_HOST belum diisi di .sync.env}"
: "${REMOTE_DIR:?REMOTE_DIR belum diisi di .sync.env}"

command -v entr >/dev/null || { echo "entr belum terpasang: sudo apt install entr"; exit 1; }
command -v rsync >/dev/null || { echo "rsync belum terpasang: sudo apt install rsync"; exit 1; }

# Never leaves this machine (and, being excluded, never deleted on the server by --delete):
# secrets, local runtime data (dev DB + its encryption key), caches, build output
EXCLUDES=(
  --exclude '.git/' --exclude '.vscode/' --exclude '.claude/' --exclude '.env' --exclude '.env.*' --exclude '/.sync.env'
  --exclude 'node_modules/' --exclude '__pycache__/' --exclude '.pytest_cache/'
  --exclude '/backend/data/' --exclude '/frontend/dist/' --exclude '*.tsbuildinfo'
)

trap 'exit 0' INT
echo "🚀 Watching files and auto-syncing to $REMOTE_HOST..."

# Monitor perubahan file dan sync otomatis saat ada file yang di-save
while true; do
  # entr -d exits when a file is added, so the watch list is rebuilt on each pass
  find . \( -name .git -o -name .vscode -o -name .claude -o -name node_modules -o -name __pycache__ \
            -o -name .pytest_cache -o -path ./backend/data -o -path ./frontend/dist \) -prune -o -type f -print |
    entr -d rsync -az --delete "${EXCLUDES[@]}" ./ "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR"
  sleep 1
done
