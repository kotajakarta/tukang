from pathlib import Path
import json
from typing import Annotated, List, Literal, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Cockpit-Py Master Controller"
    API_V1_STR: str = "/api/v1"
    # Fernet key encrypting stored credentials. If unset, generated once into DATA_DIR/.data_key.
    DATA_ENCRYPTION_KEY: Optional[str] = None

    # Storage paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"

    # SQLite Async DB
    DATABASE_URL: str = ""

    # CORS is off by default: the UI is served from the same origin (Vite proxy in dev, FastAPI in prod).
    # Never use "*" here: with cookie auth that would let any site read the API.
    CORS_ORIGINS: List[str] = []
    # Extra origins allowed to make state-changing requests / open WebSockets
    # (e.g. "https://cockpit.example.com" if a proxy rewrites the Host header).
    TRUSTED_ORIGINS: List[str] = []

    # Authentication
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: Optional[str] = None  # Initial admin password (only used when no user exists)
    SESSION_HOURS: int = 12  # absolute session lifetime
    SESSION_IDLE_MINUTES: int = 30  # signed out after this long without activity
    SESSION_COOKIE_NAME: str = "cockpit_session"
    COOKIE_SECURE: bool = False  # Set true when served over HTTPS (e.g. behind Cloudflare Tunnel)
    LOGIN_MAX_ATTEMPTS: int = 5  # failures per client IP within the lockout window
    LOGIN_ACCOUNT_MAX_ATTEMPTS: int = 10  # failures per account (any IP) within the window
    LOGIN_LOCKOUT_SECONDS: int = 900
    # An address the account signed in from within this many days is exempt from the per-account limit
    # (still per-IP limited), so failures from elsewhere cannot lock the owner out
    LOGIN_KNOWN_IP_DAYS: int = 30
    # Trust CF-Connecting-IP / X-Forwarded-For for the client address. Enable ONLY behind a proxy
    # that overwrites these headers (Cloudflare Tunnel); otherwise clients can spoof their IP.
    TRUST_PROXY_HEADERS: bool = False
    # Peers allowed to set those headers: IPs, CIDRs or hostnames (e.g. the cloudflared container name,
    # resolved and cached for a minute). Empty = any peer, which lets anything that can reach the app
    # directly (e.g. another container on the same network) choose its client IP.
    # JSON list or comma-separated (systemd's Environment= strips double quotes).
    TRUSTED_PROXIES: Annotated[List[str], NoDecode] = []
    AUDIT_RETENTION_DAYS: int = 365
    ENABLE_API_DOCS: bool = True
    # Force every account to enroll TOTP before it can use anything besides /auth
    MFA_REQUIRED: bool = False
    PASSWORD_MIN_LENGTH: int = 12
    # Files: max upload size. Cloudflare's free plan caps request bodies at 100 MB.
    FILES_MAX_UPLOAD_MB: int = 100
    # Files: images larger than this get an icon instead of a thumbnail (they are read whole to resize)
    FILES_THUMB_MAX_MB: int = 25

    # How the "local" node is managed:
    #  - direct: run commands/PTY/psutil inside this process (bare-metal install)
    #  - ssh:    reach the host over SSH (container install)
    LOCAL_MODE: Literal["direct", "ssh"] = "direct"
    LOCAL_SSH_HOST: str = "host.containers.internal"
    LOCAL_SSH_PORT: int = 22
    LOCAL_SSH_USER: str = "root"
    LOCAL_SSH_KEY_PATH: Optional[str] = None
    # Elevate with `sudo -n` instead of logging in as root (recommended: dedicated user + sudoers entry)
    LOCAL_SSH_SUDO: bool = False

    # Built frontend (served by FastAPI when present, e.g. inside the container)
    FRONTEND_DIST: Path = BASE_DIR.parent / "frontend" / "dist"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("TRUSTED_PROXIES", mode="before")
    @classmethod
    def _list_or_csv(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return json.loads(value) if value.startswith("[") else [v.strip() for v in value.split(",") if v.strip()]
        return value

    def __init__(self, **values):
        super().__init__(**values)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.DATABASE_URL:
            db_path = self.DATA_DIR / "cockpit.db"
            self.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

settings = Settings()

def is_direct_local(server_id: str) -> bool:
    """True when the server should be handled in-process instead of over SSH."""
    return server_id == "local" and settings.LOCAL_MODE == "direct"
