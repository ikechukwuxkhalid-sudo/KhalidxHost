import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ADMIN_PATH, ADMIN_PASSWORD
from app.database.db import get_session
from app.database.models import User, FlyAccount, ApiKey, VpsInstance, AuditLog
from app.deps import admin_required, client_ip, is_https, audit, ADMIN_COOKIE
from app.security import auth
from app.security.ratelimit import hit

router = APIRouter(prefix=f"/{ADMIN_PATH}/api", tags=["admin"])
ADMIN_AGE = 60 * 60 * 8


def _iso(d):
    return d.isoformat() + "Z" if d else None


class LoginBody(BaseModel):
    password: str = Field(max_length=256)


@router.post("/login")
async def admin_login(body: LoginBody, request: Request, response: Response):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "ADMIN_PASSWORD is not configured on the server")
    # per-IP limit + a global limit so spoofed IPs can't be used to brute-force
    if not hit(f"adm:{client_ip(request)}", 5, 600) or not hit("adm:global", 30, 600):
        raise HTTPException(429, "Too many attempts. Try again later.")
    a = hashlib.sha256(body.password.encode()).digest()
    b = hashlib.sha256(ADMIN_PASSWORD.encode()).digest()
    if not hmac.compare_digest(a, b):
        raise HTTPException(401, "Wrong password")
    token = auth.sign({"r": "admin"}, ADMIN_AGE)
    response.set_cookie(ADMIN_COOKIE, token, max_age=ADMIN_AGE, httponly=True, samesite="strict", secure=is_https(request), path=f"/{ADMIN_PATH}")
    return {"ok": True}


@router.post("/logout")
async def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE, path=f"/{ADMIN_PATH}")
    return {"ok": True}


@router.get("/me", dependencies=[Depends(admin_required)])
async def admin_me():
    return {"ok": True}


@router.get("/stats", dependencies=[Depends(admin_required)])
async def stats(session: AsyncSession = Depends(get_session)):
    async def count(q):
        return (await session.execute(q)).scalar_one()
    return {
        "users": await count(select(func.count()).select_from(User)),
        "api_enabled": await count(select(func.count()).select_from(User).where(User.api_enabled == True)),  # noqa: E712
        "blocked": await count(select(func.count()).select_from(User).where(User.is_blocked == True)),  # noqa: E712
        "keys": await count(select(func.count()).select_from(ApiKey).where(ApiKey.revoked == False)),  # noqa: E712
        "vps": await count(select(func.count()).select_from(VpsInstance)),
        "running": await count(select(func.count()).select_from(VpsInstance).where(VpsInstance.status.in_(["RUNNING", "STARTED"]))),
        "deploying": await count(select(func.count()).select_from(VpsInstance).where(VpsInstance.status == "DEPLOYING")),
    }


@router.get("/users", dependencies=[Depends(admin_required)])
async def users(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(User).order_by(User.id.desc()))).scalars().all()
    vps_counts = dict((await session.execute(select(VpsInstance.user_id, func.count()).group_by(VpsInstance.user_id))).all())
    key_counts = dict((await session.execute(select(ApiKey.user_id, func.count()).where(ApiKey.revoked == False).group_by(ApiKey.user_id))).all())  # noqa: E712
    fly_ids = {r for r in (await session.execute(select(FlyAccount.user_id))).scalars().all()}
    return {"users": [{
        "id": u.id, "username": u.username, "telegram": u.telegram, "api_enabled": u.api_enabled, "blocked": u.is_blocked,
        "vps": vps_counts.get(u.id, 0), "keys": key_counts.get(u.id, 0), "fly_linked": u.id in fly_ids,
        "created_at": _iso(u.created_at), "last_login": _iso(u.last_login),
    } for u in rows]}


async def _user(session: AsyncSession, uid: int) -> User:
    u = await session.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


class ToggleBody(BaseModel):
    value: bool


@router.post("/users/{uid}/api", dependencies=[Depends(admin_required)])
async def set_api(uid: int, body: ToggleBody, session: AsyncSession = Depends(get_session)):
    u = await _user(session, uid)
    u.api_enabled = body.value
    await session.commit()
    await audit(session, user_id=u.id, actor="admin", action="api_grant" if body.value else "api_revoke", detail=u.username)
    return {"ok": True}


@router.post("/users/{uid}/block", dependencies=[Depends(admin_required)])
async def set_block(uid: int, body: ToggleBody, session: AsyncSession = Depends(get_session)):
    u = await _user(session, uid)
    u.is_blocked = body.value
    await session.commit()
    await audit(session, user_id=u.id, actor="admin", action="block" if body.value else "unblock", detail=u.username)
    return {"ok": True}


class PwBody(BaseModel):
    password: str = Field(min_length=8, max_length=128)


@router.post("/users/{uid}/password", dependencies=[Depends(admin_required)])
async def reset_pw(uid: int, body: PwBody, session: AsyncSession = Depends(get_session)):
    u = await _user(session, uid)
    u.password_hash = await auth.hash_password(body.password)
    await session.commit()
    await audit(session, user_id=u.id, actor="admin", action="password_reset", detail=u.username)
    return {"ok": True}


@router.delete("/users/{uid}", dependencies=[Depends(admin_required)])
async def delete_user(uid: int, session: AsyncSession = Depends(get_session)):
    u = await _user(session, uid)
    name = u.username
    await session.execute(delete(ApiKey).where(ApiKey.user_id == uid))
    await session.execute(delete(FlyAccount).where(FlyAccount.user_id == uid))
    await session.execute(delete(VpsInstance).where(VpsInstance.user_id == uid))
    await session.delete(u)
    await session.commit()
    await audit(session, actor="admin", action="user_delete", detail=name)
    return {"ok": True}


class KeyBody(BaseModel):
    label: str | None = Field(default=None, max_length=64)


@router.post("/users/{uid}/keys", dependencies=[Depends(admin_required)])
async def create_key(uid: int, body: KeyBody, session: AsyncSession = Depends(get_session)):
    u = await _user(session, uid)
    full, prefix, kh = auth.generate_api_key()
    session.add(ApiKey(user_id=u.id, label=(body.label or "").strip() or None, prefix=prefix, key_hash=kh))
    u.api_enabled = True  # issuing a key = granting API access
    await session.commit()
    await audit(session, user_id=u.id, actor="admin", action="key_create", detail=f"{u.username} {prefix}")
    return {"key": full, "prefix": prefix, "username": u.username}


@router.get("/keys", dependencies=[Depends(admin_required)])
async def list_keys(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(ApiKey, User.username).join(User, User.id == ApiKey.user_id).order_by(ApiKey.id.desc()))).all()
    return {"keys": [{
        "id": k.id, "username": name, "prefix": k.prefix, "label": k.label, "revoked": k.revoked,
        "created_at": _iso(k.created_at), "last_used": _iso(k.last_used),
    } for k, name in rows]}


@router.delete("/keys/{kid}", dependencies=[Depends(admin_required)])
async def revoke_key(kid: int, session: AsyncSession = Depends(get_session)):
    k = await session.get(ApiKey, kid)
    if not k:
        raise HTTPException(404, "Key not found")
    k.revoked = True
    await session.commit()
    await audit(session, user_id=k.user_id, actor="admin", action="key_revoke", detail=k.prefix)
    return {"ok": True}


@router.get("/vps", dependencies=[Depends(admin_required)])
async def all_vps(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(VpsInstance, User.username).join(User, User.id == VpsInstance.user_id).order_by(VpsInstance.id.desc()).limit(300))).all()
    return {"vps": [{
        "id": v.id, "owner": name, "name": v.fly_app_name, "status": "RUNNING" if (v.status or "").upper() == "STARTED" else (v.status or "").upper(),
        "region": v.region, "cpus": v.cpu, "memory_mb": v.memory_mb, "storage_gb": v.storage_gb, "ipv4": v.public_ipv4, "created_at": _iso(v.created_at),
    } for v, name in rows]}


@router.get("/logs", dependencies=[Depends(admin_required)])
async def logs(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(150))).scalars().all()
    names = dict((await session.execute(select(User.id, User.username))).all())
    return {"logs": [{
        "time": _iso(l.timestamp), "user": names.get(l.user_id), "actor": l.actor, "action": l.action,
        "result": l.result, "detail": l.detail,
    } for l in rows]}
