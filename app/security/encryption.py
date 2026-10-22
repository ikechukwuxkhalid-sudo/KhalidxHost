"""Encrypt secrets at rest. Never log plaintext tokens/passwords."""

import base64
import hashlib
from cryptography.fernet import Fernet
from app.config import ENCRYPTION_KEY

def _fernet() -> Fernet:
    # Derive 32-byte url-safe key from ENCRYPTION_KEY
    digest = hashlib.sha256(ENCRYPTION_KEY.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)

def encrypt(text: str) -> str:
    if not text:
        return ""
    return _fernet().encrypt(text.encode()).decode()

def decrypt(token: str) -> str:
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()

def mask(secret: str, show: int = 4) -> str:
    if not secret or len(secret) <= show * 2:
        return "****"
    return secret[:show] + "…" + secret[-show:]
