from datetime import datetime

from fastapi import Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import OWNER_TELEGRAM
from app.database.db import get_session
from app.database.models import User, ApiKey, AuditLog
from app.security import auth
from app.security.ratelimit import hit

USER_COOKIE = "kx_session"
ADMIN_COOKIE = "kx_admin"


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


async def audit(session: AsyncSession, *, user_id=None, actor="user", action: str, vps_id=None, result="ok", detail=""):
    session.add(AuditLog(user_id=user_id, actor=actor, action=action, vps_id=vps_id, result=result, detail=(detail or "")[:500]))
    await session.commit()


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    """Authenticates either an API key (Authorization: Bearer kx_… / X-API-Key) or the website session cookie."""
    key = request.headers.get("x-api-key")
    ah = request.headers.get("authorization", "")
    if not key and ah.lower().startswith("bearer "):
        key = ah[7:].strip()

    if key:
        if not key.startswith("kx_"):
            raise HTTPException(401, "Invalid API key")
        kh = auth.hash_key(key)
        if not hit(f"key:{kh}", 120, 60):
            raise HTTPException(429, "Rate limit exceeded (120 requests/minute)")
        row = (await session.execute(select(ApiKey).where(ApiKey.key_hash == kh))).scalar_one_or_none()
        if not row or row.revoked:
            raise HTTPException(401, "Invalid or revoked API key")
        user = await session.get(User, row.user_id)
        if not user or user.is_blocked:
            raise HTTPException(403, "Account suspended")
        if not user.api_enabled:
            raise HTTPException(403, f"API access is not enabled for this account. Contact @{OWNER_TELEGRAM} on Telegram.")
        row.last_used = datetime.utcnow()
        await session.commit()
        request.state.via = "api"
        return user

    data = auth.verify(request.cookies.get(USER_COOKIE))
    if not data or data.get("r") != "user":
        raise HTTPException(401, "Not logged in")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-kx") != "1":
        raise HTTPException(403, "Missing CSRF header")
    user = await session.get(User, data.get("u"))
    if not user:
        raise HTTPException(401, "Not logged in")
    if user.is_blocked:
        raise HTTPException(403, "Account suspended")
    request.state.via = "session"
    return user


async def session_user(request: Request, user: User = Depends(current_user)) -> User:
    """Endpoints that must NOT be reachable with an API key (e.g. linking a Fly token)."""
    if getattr(request.state, "via", "") != "session":
        raise HTTPException(403, "This action is only available from the website")
    return user


async def admin_required(request: Request) -> None:
    data = auth.verify(request.cookies.get(ADMIN_COOKIE))
    if not data or data.get("r") != "admin":
        raise HTTPException(401, "Admin login required")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-kx") != "1":
        raise HTTPException(403, "Missing CSRF header")
