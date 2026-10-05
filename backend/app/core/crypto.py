"""
Encryption at rest for stored credentials (SSH passwords, private keys, TOTP secrets).

Key source, in order: DATA_ENCRYPTION_KEY env (a Fernet key; in the container this comes from a
podman secret so the key never sits next to the database), else DATA_DIR/.data_key (auto-created).
"""
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator
from app.core.config import settings

PREFIX = "enc:v1:"

def _load_fernet() -> Fernet:
    key = settings.DATA_ENCRYPTION_KEY
    if not key:
        key_file = settings.DATA_DIR / ".data_key"
        if not key_file.exists():
            key_file.write_text(Fernet.generate_key().decode())
            key_file.chmod(0o600)
        key = key_file.read_text().strip()
    return Fernet(key.encode() if isinstance(key, str) else key)

_fernet = _load_fernet()

def encrypt(value: Optional[str]) -> Optional[str]:
    if value is None or value == "" or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet.encrypt(value.encode("utf-8")).decode("ascii")

def decrypt(value: Optional[str]) -> Optional[str]:
    if not value or not value.startswith(PREFIX):
        return value  # legacy plaintext (migrated at startup) or empty
    try:
        return _fernet.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise RuntimeError(
            "Cannot decrypt stored credential: DATA_ENCRYPTION_KEY does not match the key used to encrypt it."
        ) from None

class EncryptedText(TypeDecorator):
    """Text column transparently encrypted with Fernet."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
