"""RFC 6238 TOTP (SHA-1, 6 digits, 30 s) — compatible with Google Authenticator, Authy, 1Password, etc."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6

def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)

def current_step(now: Optional[float] = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)

def verify(secret: str, code: str, last_used_step: Optional[int] = None, window: int = 1) -> Optional[int]:
    """
    Returns the matched time step if `code` is valid within ±window steps and newer than
    `last_used_step` (prevents replaying a code that was already used), else None.
    """
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = current_step()
    for step in range(now - window, now + window + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(_code_at(secret, step), code):
            return step
    return None

def provisioning_uri(secret: str, account: str, issuer: str = "Cockpit-Py") -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP_SECONDS}"
