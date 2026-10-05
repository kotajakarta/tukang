# Cockpit-Py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete, web-based, agentless multi-server Linux administration platform (Cockpit alternative) with Python FastAPI backend and React + Vite + TypeScript + Ant Design + Tailwind CSS frontend.

**Architecture:** Master controller node communicates directly with local system via `psutil`/system utilities and with remote managed nodes via key-based `asyncssh`. Centralized WebSocket hub multiplexes live metrics streaming and terminal PTY sessions per active server context.

**Tech Stack:** Python 3.12, FastAPI, AsyncSSH, Psutil, SQLite/AioSQLite, React 18, Vite, TypeScript, Ant Design 5, Tailwind CSS, xterm.js, Recharts.

**Spec:** [Cockpit-Py Design Spec](file:///mnt/d/htdocs/cockpit-py/docs/superpowers/specs/2026-10-01-cockpit-py-design.md)

## Global Constraints
- Linux master node (WSL2/Ubuntu Linux 3.12+).
- Agentless remote node management over standard SSH.
- Keepalive and persistent connection pooling for remote SSH.
- Terminal sessions run over raw WebSocket using xterm.js.
- Clean separation between local host execution and remote SSH execution.

---

### Task 1: Backend Foundation & Server Inventory Database

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/database.py`
- Create: `backend/app/models/server.py`
- Create: `backend/app/api/v1/servers.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_servers_api.py`

**Interfaces:**
- Produces: `app.core.database.get_db()`, `app.models.server.ServerNode`, `app.api.v1.servers.router`, `app.main.app`
- Consumes: FastAPI, SQLAlchemy, aiosqlite, Pydantic

- [x] **Step 1: Create requirements.txt**
Define the backend dependencies: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `psutil`, `asyncssh`, `websockets`, `cryptography`, `sqlalchemy`, `aiosqlite`, `pytest`, `httpx`, `pytest-asyncio`.

- [x] **Step 2: Write failing test for Server Inventory API**
Write `backend/tests/test_servers_api.py` verifying adding a server, listing servers (including default local server), and deleting a server.

- [x] **Step 3: Implement config, database, server models, and server CRUD router**
Implement SQLite database with auto-migration to store server inventory (id, name, host, port, username, key_path, created_at). Default seed includes `local` ("Local Controller Host").

- [x] **Step 4: Implement main.py and mount servers router**
Wire CORS, lifespan, and `/api/v1/servers` endpoints into `backend/app/main.py`.

- [x] **Step 5: Run tests and verify they pass**
Run `pytest backend/tests/test_servers_api.py -v`.

---

### Task 2: Multi-Server SSH Connection Pool & Remote Execution

**Files:**
- Create: `backend/app/services/ssh_manager.py`
- Create: `backend/tests/test_ssh_manager.py`

**Interfaces:**
- Produces: `ssh_manager.get_connection(info)`, `ssh_manager.run_command(info, cmd)`, `ssh_manager.close_all()`
- Consumes: `asyncssh`, `asyncio`, ServerNode credentials

- [x] **Step 1: Write unit test for SSH Connection Manager**
Create `backend/tests/test_ssh_manager.py` using mock/loopback SSH connections to test connection reuse, command execution, and timeout handling.

- [x] **Step 2: Implement SSHConnectionManager**
Implement thread-safe connection pooling, key authentication (file path or in-memory private key), keepalive packets, auto-reconnect on dropped sockets, and command execution helper.

- [x] **Step 3: Run test and verify it passes**
Run `pytest backend/tests/test_ssh_manager.py -v`.

---

### Task 3: Local & Remote System Metrics Collectors & WebSocket Multiplexing Hub

**Files:**
- Create: `backend/app/models/metrics.py`
- Create: `backend/app/services/local_collector.py`
- Create: `backend/app/services/remote_collector.py`
- Create: `backend/app/websockets/hub.py`
- Create: `backend/app/websockets/metrics_ws.py`
- Create: `backend/tests/test_metrics.py`

**Interfaces:**
- Produces: `LocalCollector.get_metrics()`, `RemoteCollector.get_metrics()`, `ws_hub.subscribe(websocket, server_id)`, `/ws/metrics`
- Consumes: `psutil`, `ssh_manager`, `ServerNode`

- [x] **Step 1: Write test for metrics collector and hub**
Create `backend/tests/test_metrics.py` verifying CPU, Memory, Disk, and Network telemetry schemas and websocket subscription registration.

- [x] **Step 2: Implement LocalCollector & RemoteCollector**
Local collector uses `psutil` for CPU/RAM/Disk/Network. Remote collector executes a single compact python/bash one-liner reading `/proc/stat`, `/proc/meminfo`, `/proc/diskstats`, `/proc/net/dev`.

- [x] **Step 3: Implement WebSocketHub with lazy background harvester**
Tracks active WebSocket clients per `server_id`. Periodically samples metrics only for servers with at least 1 active subscriber and broadcasts JSON updates.

- [x] **Step 4: Mount `/ws/metrics` in main.py**
Enable client subscription commands (`{"action": "subscribe", "server_id": "..."}`).

- [x] **Step 5: Run tests and verify**
Run `pytest backend/tests/test_metrics.py -v`.

---

### Task 4: Interactive Web Terminal WebSocket & PTY/SSH Bridge

**Files:**
- Create: `backend/app/services/terminal_service.py`
- Create: `backend/app/websockets/terminal_ws.py`
- Create: `backend/tests/test_terminal_service.py`

**Interfaces:**
- Produces: `terminal_service.create_session(server_id, cols, rows)`, `/ws/terminal/{server_id}`
- Consumes: Python `pty`, `os.openpty`, `asyncssh.SSHClientConnection.create_process`

- [x] **Step 1: Write test for terminal session lifecycle**
Write `backend/tests/test_terminal_service.py` verifying session creation, terminal resize, and session termination.

- [x] **Step 2: Implement TerminalService**
For `local`: spawn `/bin/bash` with `pty.openpty()`, pipe stdin/stdout asynchronously to WebSocket.
For `remote`: create an interactive SSH process (`term_type='xterm-256color'`) via `asyncssh`, pipe streams to WebSocket, handle window resize events (`{"type": "resize", "cols": N, "rows": N}`).

- [x] **Step 3: Mount `/ws/terminal/{server_id}` in main.py**
Connect WebSocket directly to the terminal session reader/writer loop.

- [x] **Step 4: Run tests and verify**
Run `pytest backend/tests/test_terminal_service.py -v`.

---

### Task 5: Systemd Management & Real-time Journalctl Streaming API

**Files:**
- Create: `backend/app/models/systemd.py`
- Create: `backend/app/services/systemd_service.py`
- Create: `backend/app/api/v1/services.py`
- Create: `backend/tests/test_systemd_service.py`

**Interfaces:**
- Produces: `systemd_service.list_units(server_id)`, `systemd_service.unit_action(server_id, unit, action)`, `/api/v1/services`
- Consumes: `systemctl`, `journalctl` via local subprocess or remote `ssh_manager`

- [x] **Step 1: Write unit tests for systemd parser and commands**
Verify parsing of `systemctl list-units --type=service,timer --all --output=json` or formatted list, and unit actions (start, stop, restart, enable, disable).

- [x] **Step 2: Implement SystemdService & Journalctl streaming**
Support local execution via `asyncio.create_subprocess_exec` and remote execution via `ssh_manager.run_command`. Implement journalctl log fetching with `-n 100 --no-pager` or real-time follow.

- [x] **Step 3: Create API endpoints in `backend/app/api/v1/services.py`**
Expose GET `/units`, POST `/{unit}/{action}`, and GET `/{unit}/logs`. Mount in `main.py`.

- [x] **Step 4: Run tests and verify**
Run `pytest backend/tests/test_systemd_service.py -v`.

---

### Task 6: Podman Containers & Quadlet Management API

**Files:**
- Create: `backend/app/models/podman.py`
- Create: `backend/app/services/podman_service.py`
- Create: `backend/app/api/v1/containers.py`
- Create: `backend/tests/test_podman_service.py`

**Interfaces:**
- Produces: `podman_service.list_containers()`, `podman_service.list_quadlets()`, `podman_service.save_quadlet()`, `/api/v1/containers`
- Consumes: `podman ps -a --format json`, Quadlet file I/O (`/etc/containers/systemd`, `~/.config/containers/systemd`)

- [x] **Step 1: Write unit tests for Podman & Quadlet parser**
Test container inspection parser and Quadlet ini-style file parsing (`.container`, `.network`, `.volume`).

- [x] **Step 2: Implement PodmanService**
Handle rootless & system Podman container lifecycle (start, stop, restart, logs, inspect). Handle Systemd Quadlet file CRUD and `systemctl daemon-reload`.

- [x] **Step 3: Create API endpoints in `backend/app/api/v1/containers.py`**
Endpoints for containers list, logs, actions, and quadlet list, view, save, delete. Mount in `main.py`.

- [x] **Step 4: Run tests and verify**
Run `pytest backend/tests/test_podman_service.py -v`.

---

### Task 7: Storage, Network & User Management APIs

**Files:**
- Create: `backend/app/services/storage_service.py`
- Create: `backend/app/api/v1/storage.py`
- Create: `backend/app/services/network_service.py`
- Create: `backend/app/api/v1/network.py`
- Create: `backend/app/services/user_service.py`
- Create: `backend/app/api/v1/users.py`
- Create: `backend/tests/test_admin_services.py`

**Interfaces:**
- Produces: Storage endpoints (`lsblk --json`, `smartctl`), Network endpoints (`ip --json`, `firewall-cmd`/`ufw`), User endpoints (`/etc/passwd`, `useradd`, `usermod`, `authorized_keys`).

- [x] **Step 1: Write tests for Storage, Network, and User inspectors**
- [x] **Step 2: Implement Storage, Network, and User services**
- [x] **Step 3: Wire routers in `main.py`**
- [x] **Step 4: Run tests and verify**

---

### Task 8: Frontend Scaffolding, Theme & Global Server Context Switcher

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/src/index.css`
- Create: `frontend/src/types/server.ts`
- Create: `frontend/src/context/ServerContext.tsx`
- Create: `frontend/src/components/common/ServerSelector.tsx`
- Create: `frontend/src/components/common/AppHeader.tsx`
- Create: `frontend/src/components/common/AppSidebar.tsx`

- [x] **Step 1: Scaffold Vite + React + TS project files**
Configure Vite proxy to `http://localhost:8000` for `/api` and `ws://localhost:8000` for `/ws`.
Configure Tailwind CSS and Ant Design ConfigProvider (dark enterprise theme matching modern Cockpit).

- [x] **Step 2: Implement ServerContext & ServerSelector**
Global React context managing active server (`server_id`), server list, add/remove server modals.

- [x] **Step 3: Implement AppHeader & AppSidebar**
Navigation tabs: Dashboard, Services, Containers, Storage, Networking, Terminal, Users, Settings.

---

### Task 9: Frontend Real-time Dashboard & System Info

**Files:**
- Create: `frontend/src/hooks/useMetricsStream.ts`
- Create: `frontend/src/components/dashboard/MetricsOverview.tsx`
- Create: `frontend/src/components/dashboard/HostInfoCard.tsx`
- Create: `frontend/src/components/dashboard/RealtimeCharts.tsx`

- [x] **Step 1: Implement `useMetricsStream` hook**
Connect to `/ws/metrics`, subscribe to `activeServer.id`, maintain historical rolling buffer (last 30 seconds) for graphs.

- [x] **Step 2: Build Real-time Gauges and Recharts charts**
Live CPU % chart, RAM gauge, Disk I/O (Read/Write MB/s) area chart, Network (In/Out KB/s) area chart.

- [x] **Step 3: Build HostInfoCard**
Display OS release, kernel version, hostname, architecture, uptime, and load averages.

---

### Task 10: Frontend Web Terminal with xterm.js & Server Switching

**Files:**
- Create: `frontend/src/components/terminal/WebTerminal.tsx`

- [x] **Step 1: Implement WebTerminal using xterm.js**
Integrate `Terminal`, `FitAddon`, `WebLinksAddon`.
Connect to `ws://.../ws/terminal/{activeServer.id}`.
Send input on data, handle resize events with `fitAddon` on window resize.
Seamlessly reconnect and switch session when `activeServer` changes.

---

### Task 11: Frontend Systemd Services & Live Journal Viewer

**Files:**
- Create: `frontend/src/components/services/ServiceTable.tsx`
- Create: `frontend/src/components/services/JournalViewerModal.tsx`

- [x] **Step 1: Implement ServiceTable**
Ant Design Table with search by unit name, filter by status (active, failed, inactive), start, stop, restart, enable, disable buttons with confirmation.

- [x] **Step 2: Implement JournalViewerModal**
Modal showing real-time service logs with colored terminal styling and auto-scroll.

---

### Task 12: Frontend Podman Containers & Quadlet Editor

**Files:**
- Create: `frontend/src/components/containers/ContainerList.tsx`
- Create: `frontend/src/components/containers/QuadletManager.tsx`

- [x] **Step 1: Implement ContainerList**
Cards/table of running & stopped containers, image name, ports, container actions (start/stop/restart/logs).

- [x] **Step 2: Implement QuadletManager**
Editor for `.container`, `.network`, `.volume` quadlet files, with templates and direct save & daemon-reload trigger.

---

### Task 13: Frontend Storage, Networking & User Management Views

**Files:**
- Create: `frontend/src/components/storage/StorageView.tsx`
- Create: `frontend/src/components/network/NetworkView.tsx`
- Create: `frontend/src/components/users/UsersView.tsx`

- [x] **Step 1: Implement StorageView**
Partition visualizer, filesystem usage progress bars, mount points, and SMART health badges.

- [x] **Step 2: Implement NetworkView**
Network interfaces table (IPs, MAC, RX/TX bytes), Firewall status and port allowance manager.

- [x] **Step 3: Implement UsersView**
Local users table, add user modal, sudo privileges toggle, and SSH key manager.

---

### Task 14: End-to-End Integration, Verification & Launch Script

**Files:**
- Create: `frontend/src/App.tsx`
- Create: `scripts/run_dev.sh`
- Create: `README.md`

- [x] **Step 1: Wire App.tsx with all modules and React Router / Tabs**
- [x] **Step 2: Write `scripts/run_dev.sh` to run backend uvicorn and frontend vite concurrently**
- [x] **Step 3: Verify all APIs and build bundle**
- [x] **Step 4: Update README.md with architecture and getting started guide**
