# tuKang: Agentless Multi-Server Linux Administration Platform

A modern, high-performance web-based Linux system administration platform, built as an independent alternative to web consoles such as [Cockpit](https://cockpit-project.org/), with **Python (FastAPI)** on the backend and **React (Vite + TypeScript + Ant Design + Tailwind CSS)** on the frontend.

Designed with native, first-class **Multi-Server Management** from day one using an **Agentless Central Controller** architecture.

---

## 🌟 Key Features

1. **Centralized Agentless Architecture:**
   - The master controller connects to remote nodes over SSH using public key authentication (via `asyncssh`). No software agent needs to be installed on remote nodes.
   - Global **Server Selector** switches the context of all dashboard metrics, systemd services, Podman containers, and terminals with a single click.

2. **Real-time System Dashboard:**
   - Live CPU, RAM, Disk I/O, and Network traffic graphs streamed over WebSockets (`/ws/metrics`).
   - Host information: OS details, kernel version, hostname, uptime, CPU model, and load averages.

3. **Systemd Service Management:**
   - List services, timers, and sockets across local and remote nodes.
   - Start, stop, restart, enable, and disable units.
   - Live `journalctl` log viewer with configurable line history.

4. **Podman Container & Systemd Quadlet Management:**
   - Native Podman integration (both root and rootless containers).
   - Full management and in-browser editor for Systemd Quadlet files (`.container`, `.network`, `.volume`).
   - Auto-triggers `systemctl daemon-reload` upon saving Quadlets.

5. **Storage & Disks:**
   - Block device and partition tree (`lsblk`).
   - Filesystem mount points with visual disk capacity progress bars.
   - SMART health diagnostics.

6. **Networking & Firewall:**
   - Network interfaces, MAC addresses, MTU, IPv4 and IPv6 addresses.
   - Active listening ports and TCP/UDP sockets (`ss`).
   - Firewall management with automatic detection for `firewalld` and `ufw`.

7. **Interactive Web Terminal:**
   - Full root/user interactive shell in the browser powered by `xterm.js`.
   - Bridges to local PTY (`pty.openpty`) for the master node and remote interactive SSH sessions (`asyncssh`) for managed nodes.
   - Supports window resize events (`fitAddon`).

8. **Files (web file manager):**
   - Browse, filter, list/grid view, bookmarks, hidden files, details panel, right-click menu & keyboard shortcuts.
   - Create, edit (text), rename, copy/cut/paste, symlink, delete, permissions & ownership, streaming upload/download.
   - Built-in media viewer/player (images, video, audio, PDF) in a modal, with prev/next across the folder and seekable streaming (HTTP Range).
   - Image & video thumbnails in list/grid view and the details panel (images resized on the controller with Pillow and cached; video frames captured in the browser, so nodes need no ffmpeg).

9. **User & SSH Key Management:**
   - View system and human user accounts.
   - Create and delete users with sudo privileges (`wheel`/`sudo`).
   - Manage `~/.ssh/authorized_keys` for instant passwordless SSH setup.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Node.js 18+ (tested on Node.js 24)

### 1. Install Backend Dependencies
```bash
python3 -m pip install -r backend/requirements-dev.txt
```

### 2. Install Frontend Dependencies
```bash
cd frontend
npm install
cd ..
```

### 3. Launch Development Server
You can launch both the backend API and frontend dev server together using the helper script:
```bash
./run.sh
```

Or run them individually in separate terminals:

**Backend:**
```bash
export PYTHONPATH=backend
python3 -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 3000
```

Open your browser at `http://localhost:3000`.

> ⚠️ **Development only.** `run.sh` listens on all interfaces over plain HTTP, with API docs on and MFA
> optional, and in this mode commands run as the user who started the backend. Do not run it on an
> untrusted network; for real use, deploy the container (see [docs/DEPLOY.md](docs/DEPLOY.md)).

### Login

All pages, APIs, and WebSockets require a login (server-side sessions, roles `viewer`/`operator`/`admin`,
optional or mandatory TOTP MFA, audit log). On first start an `admin` account is created from
`ADMIN_PASSWORD` (or a random password printed in the backend log if unset). Change it from the
account menu in the top-right corner. See the security section of [docs/DEPLOY.md](docs/DEPLOY.md).

### Production (Podman Quadlet + Cloudflare Tunnel)

See [docs/DEPLOY.md](docs/DEPLOY.md) for the container image, `deploy/tukang.container`, and tunnel setup.
Upgrading a server that still runs the old **Cockpit-Py** container: see "Migrasi dari Cockpit-Py" in the same document.

---

## 🧪 Testing Backend Services

Run the full pytest test suite:
```bash
PYTHONPATH=backend python3 -m pytest backend/tests/ -v
```

The suite covers, among others:
- Server inventory CRUD & SQLite persistence
- Multi-server SSH connection pooling & reconnects
- System metrics harvester & WebSocket hub
- Interactive Web Terminal PTY session lifecycle
- Systemd units parser & journalctl runner
- Podman containers & Quadlet file lifecycle
- Storage, network, and user management APIs

---

## 📄 License

Copyright © 2026 AIT HENDI

tuKang is free software, licensed under the **GNU Affero General Public License v3.0 only**
([LICENSE](LICENSE)). You may use it for any purpose, including commercially, modify it, and
redistribute it. If you modify it and let others use it over a network (e.g. host it for customers),
you must offer them the complete source code of your modified version under the same license.

**Commercial license:** if you want to build on tuKang without the AGPL's obligations (for example
in a closed-source product or service), a separate commercial license is available from the copyright
holder. Open an issue on this repository to get in touch.

**Third-party software:** tuKang uses open-source components under their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). These notices must be kept in every distribution,
including commercially licensed ones.

**Contributions** are welcome. Because tuKang is dual-licensed, contributions can only be accepted
after signing the [Contributor License Agreement](CLA.md); see [CONTRIBUTING.md](CONTRIBUTING.md).

## ™ Trademarks

"tuKang" and the AiT logo are trademarks of AIT HENDI. The AGPL license covers the code, not the
name or logo: forks and modified versions must use a different name.

tuKang is an independent project and is not affiliated with, endorsed by, or sponsored by Red Hat,
Inc. or the Cockpit project. Cockpit, Red Hat, and RHEL are trademarks of their respective owners and
are mentioned only to describe compatibility and comparison.
