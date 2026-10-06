# tuKang (formerly Cockpit-Py): Agentless Multi-Server Linux Administration Platform - Design Spec

**Date:** 2026-10-01  
**Status:** Approved  
**Author:** AI System Architect & Full-Stack Engineer  

## 1. Overview & Goals
The goal of tuKang is to provide a 100% feature-matched, agentless alternative to RHEL Cockpit, built on Python (FastAPI) for the backend and React (Vite + TypeScript + Ant Design + Tailwind CSS) for the frontend, with native, first-class Multi-Server Management built-in from day one.

### Core Objectives:
- **Centralized Controller & Agentless Architecture:** Master controller connects to managed nodes over SSH using public key authentication (via `asyncssh`). No custom agent needs to be installed on remote nodes.
- **Unified Multi-Server Context:** Single frontend interface where a global `ServerSelector` switches metrics, services, containers, storage, network, and interactive web terminal to the chosen server seamlessly.
- **High-Performance Streaming:** WebSocket multiplexing to stream CPU, RAM, Disk I/O, and Network metrics at ~1s intervals with lazy-polling for inactive hosts.
- **Rich Cockpit-Parity Features:**
  - System Dashboard with real-time metrics & OS specs.
  - Systemd Service Management with real-time `journalctl` streaming.
  - Podman Container Management with full Systemd Quadlet file editing and lifecycle control.
  - Storage Management with disk/partition trees, LVM, mounts, and SMART health monitoring.
  - Network Configuration with interfaces, IPs, firewall rules (`firewalld`/`ufw`), and active sockets.
  - Interactive Web Terminal using `xterm.js` over WebSocket bridged to local PTY or remote SSH pseudo-terminal.
  - User and SSH key management.

---

## 2. Architecture & Data Flow

### 2.1 Backend Architecture
The backend is structured into modular layers:
- **`app/api/v1/`**: REST endpoints for host inventory, systemd operations, podman containers, storage, network, and users.
- **`app/core/`**: Configuration (`pydantic-settings`), SQLite database initialization (`aiosqlite`/`SQLAlchemy`), and cryptographic helpers for stored SSH keys.
- **`app/services/`**:
  - `ssh_manager.py`: Persistent connection pool using `asyncssh.connect()`, health checks, keepalives, and remote execution.
  - `local_collector.py`: Metrics collector for the master node using `psutil`, `/proc`, and native system utilities.
  - `remote_collector.py`: Remote metrics collector executing compact command probes (`/proc` parsers) over `asyncssh`.
  - `systemd_service.py`: Inspects and controls systemd units (`systemctl`, `journalctl`) on local and remote nodes.
  - `podman_service.py`: Inspects containers, quadlets, and logs (`podman`, quadlet files in `/etc/containers/systemd/` and `~/.config/containers/systemd/`).
  - `terminal_service.py`: Bridges WebSocket streams with local PTYs (`pty.openpty()`) or remote interactive SSH sessions (`conn.create_process(term_type='xterm-256color')`).
- **`app/websockets/`**:
  - `hub.py`: Pub/sub hub tracking active WebSocket subscribers per `server_id`. Runs background metrics harvester tasks.
  - `metrics_ws.py`: Multiplexed metrics stream endpoint (`/ws/metrics`).
  - `terminal_ws.py`: Low-latency interactive shell endpoint (`/ws/terminal/{server_id}`).

### 2.2 Frontend Architecture
The frontend is built with React 18/19, Vite, TypeScript, Ant Design 5, and Tailwind CSS:
- **`ServerContext`**: Tracks registered servers, active server (`server_id`), health status, and broadcasts context changes across all tabs/views.
- **`useMetricsStream`**: Subscribes to `/ws/metrics` and maintains a circular buffer of metric datapoints for live Recharts graphs.
- **`WebTerminal`**: Mounts an `xterm.js` instance with `@xterm/addon-fit` and `@xterm/addon-web-links`, streaming input and output over `/ws/terminal/{server_id}` and propagating resize events.
- **Views**:
  - **Dashboard**: Hardware summary, live CPU/Memory gauges, Disk I/O & Network line charts.
  - **Services**: Ant Design `Table` of systemd units with search, status filters (active, failed, inactive), start/stop/restart/enable/disable buttons, and a live log viewer drawer.
  - **Containers**: Podman container manager + Quadlet config viewer/editor.
  - **Storage**: Disk and partition hierarchy, filesystem usage bars, and SMART status.
  - **Networking**: Network interface cards, IP addresses, MTU, rx/tx stats, and firewall status.
  - **Users**: Local user accounts, UID/GID, shell, sudo rights, and authorized SSH keys.

---

## 3. Communication Protocols

### 3.1 Metrics WebSocket Protocol (`/ws/metrics`)
- **Client -> Server:**
  - `{"action": "subscribe", "server_id": "remote-node-01"}`
  - `{"action": "unsubscribe", "server_id": "remote-node-01"}`
- **Server -> Client:**
  ```json
  {
    "type": "metrics_update",
    "server_id": "remote-node-01",
    "timestamp": 1727800000.123,
    "cpu": {
      "usage_percent": 14.5,
      "cores": 4,
      "load_avg": [0.42, 0.55, 0.31]
    },
    "memory": {
      "total": 16777216,
      "used": 8388608,
      "free": 4194304,
      "percent": 50.0
    },
    "disk_io": {
      "read_bytes_sec": 1048576,
      "write_bytes_sec": 524288
    },
    "network": {
      "rx_bytes_sec": 204800,
      "tx_bytes_sec": 102400
    }
  }
  ```

### 3.2 Terminal WebSocket Protocol (`/ws/terminal/{server_id}`)
- Text/Binary frames: Raw terminal input/output.
- Control frame: `{"type": "resize", "cols": 120, "rows": 35}`.

---

## 4. Security & Error Handling
- Private keys stored locally are encrypted with AES-256-GCM.
- Host key verification supported with custom `known_hosts` or strict prompt options.
- SSH connections run with configurable timeouts and auto-reconnect backoff.
- Failures on remote nodes output structured error diagnostics without crashing controller workers.
