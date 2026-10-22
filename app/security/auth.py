"""Password hashing, signed session tokens, API keys (stdlib only)."""
import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config import SECRET_KEY


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(body: str) -> str:
    return _b64(hmac.new(SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())


def sign(payload: dict, max_age: int) -> str:
    data = dict(payload)
    data["exp"] = int(time.time()) + max_age
    body = _b64(json.dumps(data, separators=(",", ":")).encode())
    return f"{body}.{_mac(body)}"


def verify(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _mac(body)):
            return None
        data = json.loads(_unb64(body))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


# ---- passwords (PBKDF2-SHA256) ----
_ITERS = 240_000


def _hash_sync(password: str, salt: bytes | None = None, iters: int = _ITERS) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters)
    return f"pbkdf2${iters}${_b64(salt)}${_b64(dk)}"


def _verify_sync(password: str, stored: str) -> bool:
    try:
        _, iters, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(iters))
        return hmac.compare_digest(calc, _unb64(dk))
    except Exception:
        return False


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hash_sync, password)


async def verify_password(password: str, stored: str) -> bool:
    return await asyncio.to_thread(_verify_sync, password, stored)


# ---- API keys ----
def generate_api_key() -> tuple[str, str, str]:
    """returns (full_key, prefix, sha256_hash). Full key is shown once and never stored."""
    full = "kx_" + secrets.token_urlsafe(32)
    return full, full[:10], hash_key(full)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
