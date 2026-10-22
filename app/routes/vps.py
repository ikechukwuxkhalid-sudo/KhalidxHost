import re
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    CPU_OPTIONS, RAM_OPTIONS_MB, STORAGE_OPTIONS_GB, FALLBACK_REGIONS,
    MAX_VPS_PER_USER, OWNER_TELEGRAM,
)
from app.database.db import get_session
from app.database.models import User, FlyAccount, VpsInstance, ApiKey
from app.deps import current_user, session_user, audit
from app.jobs import spawn, run_deploy
from app.security.encryption import encrypt, decrypt
from app.services.flyio import FlyIoService, FlyIoError
from app.services.provisioning import gen_password, sanitize_app_name, IMAGE

router = APIRouter(prefix="/api/v1", tags=["api"])
REGION_RE = re.compile(r"^[a-z]{3}$")


def _actor(request: Request) -> str:
    return getattr(request.state, "via", "user")


def _norm_status(s: str | None) -> str:
    s = (s or "").upper()
    return "RUNNING" if s == "STARTED" else s


def vps_out(v: VpsInstance, secret: bool = True) -> dict:
    pw = None
    if secret and v.encrypted_password:
        try:
            pw = decrypt(v.encrypted_password)
        except Exception:
            pw = None
    ip = v.public_ipv4
    return {
        "id": v.id,
        "name": v.fly_app_name,
        "status": _norm_status(v.status),
        "region": v.region,
        "cpus": v.cpu,
        "memory_mb": v.memory_mb,
        "storage_gb": v.storage_gb,
        "image": v.image,
        "machine_id": v.machine_id,
        "ipv4": ip,
        "ipv6": v.public_ipv6,
        "ssh": {"host": ip, "port": v.ssh_port, "user": v.username, "password": pw},
        "ssh_command": f"ssh {v.username}@{ip}" if ip else None,
        "progress": (v.progress or "").strip().splitlines()[-40:],
        "error": v.error,
        "created_at": v.created_at.isoformat() + "Z" if v.created_at else None,
    }


async def _fly_account(session: AsyncSession, user: User) -> FlyAccount:
    acc = (await session.execute(select(FlyAccount).where(FlyAccount.user_id == user.id))).scalar_one_or_none()
    if not acc:
        raise HTTPException(400, "Link your Fly.io token first (Dashboard → Fly Account)")
    return acc


def _fly_for(acc: FlyAccount) -> FlyIoService:
    try:
        return FlyIoService(decrypt(acc.encrypted_token))
    except Exception:
        raise HTTPException(400, "Stored Fly token is unreadable — please link it again")


async def _owned(session: AsyncSession, user: User, vps_id: int) -> VpsInstance:
    v = (await session.execute(select(VpsInstance).where(VpsInstance.id == vps_id, VpsInstance.user_id == user.id))).scalar_one_or_none()
    if not v:
        raise HTTPException(404, "VPS not found")
    return v


# ---------------- account ----------------
@router.get("/me")
async def me(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    acc = (await session.execute(select(FlyAccount).where(FlyAccount.user_id == user.id))).scalar_one_or_none()
    keys = (await session.execute(select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked == False))).scalars().all()  # noqa: E712
    n = (await session.execute(select(func.count()).select_from(VpsInstance).where(VpsInstance.user_id == user.id))).scalar_one()
    return {
        "username": user.username,
        "telegram": user.telegram,
        "api_enabled": user.api_enabled,
        "api_keys": [{"id": k.id, "prefix": k.prefix, "label": k.label, "last_used": k.last_used.isoformat() + "Z" if k.last_used else None} for k in keys],
        "fly": {"linked": bool(acc), "email": acc.email if acc else None, "organization": acc.organization if acc else None, "org_slug": acc.org_slug if acc else None},
        "vps_count": n,
        "vps_limit": MAX_VPS_PER_USER,
        "owner_telegram": OWNER_TELEGRAM,
        "via": getattr(request.state, "via", None),
    }


class FlyTokenBody(BaseModel):
    token: str = Field(min_length=10, max_length=4096)


@router.post("/fly/token")
async def link_fly(body: FlyTokenBody, request: Request, user: User = Depends(session_user), session: AsyncSession = Depends(get_session)):
    try:
        fly = FlyIoService(body.token)
        data = await fly.validate_token()
    except FlyIoError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(502, "Could not reach Fly.io. Try again.")
    viewer = data.get("viewer") or {}
    orgs = (data.get("organizations") or {}).get("nodes") or []
    org = orgs[0] if orgs else {}
    acc = (await session.execute(select(FlyAccount).where(FlyAccount.user_id == user.id))).scalar_one_or_none()
    if acc:
        acc.encrypted_token = encrypt(body.token.strip())
        acc.email, acc.organization, acc.org_slug = viewer.get("email"), org.get("name"), org.get("slug")
    else:
        session.add(FlyAccount(user_id=user.id, encrypted_token=encrypt(body.token.strip()), email=viewer.get("email"),
                               organization=org.get("name"), org_slug=org.get("slug")))
    await session.commit()
    await audit(session, user_id=user.id, actor="user", action="fly_link")
    return {"ok": True, "email": viewer.get("email"), "organization": org.get("name"), "org_slug": org.get("slug")}


@router.delete("/fly")
async def unlink_fly(user: User = Depends(session_user), session: AsyncSession = Depends(get_session)):
    acc = (await session.execute(select(FlyAccount).where(FlyAccount.user_id == user.id))).scalar_one_or_none()
    if acc:
        await session.delete(acc)
        await session.commit()
        await audit(session, user_id=user.id, actor="user", action="fly_unlink")
    return {"ok": True}


# ---------------- options ----------------
@router.get("/options")
async def options(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    regions = [{"code": c, "name": n} for c, n in FALLBACK_REGIONS]
    acc = (await session.execute(select(FlyAccount).where(FlyAccount.user_id == user.id))).scalar_one_or_none()
    if acc:
        try:
            api_regs = await _fly_for(acc).get_regions()
            if api_regs:
                regions = [{"code": r["code"], "name": r["name"]} for r in api_regs]
        except Exception:
            pass
    return {"regions": regions, "cpus": CPU_OPTIONS, "memory_mb": RAM_OPTIONS_MB, "storage_gb": STORAGE_OPTIONS_GB, "image": IMAGE}


# ---------------- VPS ----------------
class CreateVps(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    region: str = Field(default="iad", max_length=8)
    cpus: int = 1
    memory_mb: int = 2048
    storage_gb: int = 10


@router.get("/vps")
async def list_vps(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(VpsInstance).where(VpsInstance.user_id == user.id).order_by(VpsInstance.id.desc()))).scalars().all()
    return {"vps": [vps_out(v, secret=False) for v in rows]}


@router.post("/vps", status_code=202)
async def create_vps(body: CreateVps, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    acc = await _fly_account(session, user)
    token = decrypt(acc.encrypted_token)

    if not REGION_RE.match(body.region):
        raise HTTPException(400, "Invalid region code")
    if body.cpus not in CPU_OPTIONS:
        raise HTTPException(400, f"cpus must be one of {CPU_OPTIONS}")
    if body.memory_mb not in RAM_OPTIONS_MB:
        raise HTTPException(400, f"memory_mb must be one of {RAM_OPTIONS_MB}")
    if body.storage_gb not in STORAGE_OPTIONS_GB:
        raise HTTPException(400, f"storage_gb must be one of {STORAGE_OPTIONS_GB}")
    base = sanitize_app_name(body.name)
    if len(base) < 2:
        raise HTTPException(400, "Name must contain letters or numbers")

    total = (await session.execute(select(func.count()).select_from(VpsInstance).where(VpsInstance.user_id == user.id))).scalar_one()
    if total >= MAX_VPS_PER_USER:
        raise HTTPException(429, f"VPS limit reached ({MAX_VPS_PER_USER}). Delete one first.")
    deploying = (await session.execute(select(func.count()).select_from(VpsInstance).where(VpsInstance.user_id == user.id, VpsInstance.status == "DEPLOYING"))).scalar_one()
    if deploying >= 2:
        raise HTTPException(429, "Two deployments are already in progress. Wait for one to finish.")

    app_name = f"{base}-{secrets.token_hex(2)}"  # Fly app names are global -> random suffix
    password = gen_password()
    v = VpsInstance(
        user_id=user.id, fly_app_name=app_name, region=body.region, cpu=body.cpus, memory_mb=body.memory_mb,
        storage_gb=body.storage_gb, image=IMAGE, username="root", ssh_port=22,
        encrypted_password=encrypt(password), status="DEPLOYING", progress="… Queued\n",
    )
    session.add(v)
    await session.commit()
    await session.refresh(v)
    await audit(session, user_id=user.id, actor=_actor(request), action="vps_create", vps_id=v.id, detail=f"{app_name} {body.region} {body.cpus}cpu {body.memory_mb}mb")

    spawn(run_deploy(v.id, token, dict(
        app_name=app_name, region=body.region, cpus=body.cpus, memory_mb=body.memory_mb,
        storage_gb=body.storage_gb, root_password=password, org_slug=acc.org_slug or "personal",
    )))
    return vps_out(v)


@router.get("/vps/{vps_id}")
async def get_vps(vps_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return vps_out(await _owned(session, user, vps_id))


@router.post("/vps/{vps_id}/refresh")
async def refresh_vps(vps_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    v = await _owned(session, user, vps_id)
    if v.status == "DEPLOYING" or not v.machine_id:
        return vps_out(v)
    fly = _fly_for(await _fly_account(session, user))
    try:
        m = await fly.get_machine(v.fly_app_name, v.machine_id)
        v.status = _norm_status(m.get("state") or v.status)
        for ip in await fly.list_ips(v.fly_app_name):
            addr, t = ip.get("address"), (ip.get("type") or "").lower()
            if addr and "v6" not in t:
                v.public_ipv4 = addr
            elif addr:
                v.public_ipv6 = addr
        await session.commit()
    except Exception as e:
        raise HTTPException(502, f"Fly.io refresh failed: {type(e).__name__}")
    return vps_out(v)


@router.post("/vps/{vps_id}/{action}")
async def power(vps_id: int, action: Literal["start", "stop", "restart"], request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    v = await _owned(session, user, vps_id)
    if v.status == "DEPLOYING" or not v.machine_id:
        raise HTTPException(409, "VPS is still deploying")
    fly = _fly_for(await _fly_account(session, user))
    try:
        if action == "start":
            await fly.start_machine(v.fly_app_name, v.machine_id)
            v.status = "STARTING"
        elif action == "stop":
            await fly.stop_machine(v.fly_app_name, v.machine_id)
            v.status = "STOPPING"
        else:
            await fly.restart_machine(v.fly_app_name, v.machine_id)
            v.status = "RESTARTING"
        await session.commit()
    except FlyIoError as e:
        raise HTTPException(502, str(e)[:300])
    await audit(session, user_id=user.id, actor=_actor(request), action=f"vps_{action}", vps_id=v.id)
    return vps_out(v)


@router.delete("/vps/{vps_id}")
async def delete_vps(vps_id: int, request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    v = await _owned(session, user, vps_id)
    if v.status == "DEPLOYING":
        raise HTTPException(409, "Wait for the deployment to finish (or fail) before deleting")
    acc = (await session.execute(select(FlyAccount).where(FlyAccount.user_id == user.id))).scalar_one_or_none()
    if acc:
        try:
            fly = FlyIoService(decrypt(acc.encrypted_token))
            if v.machine_id:
                try:
                    await fly.delete_machine(v.fly_app_name, v.machine_id, force=True)
                except Exception:
                    pass
            await fly.delete_app(v.fly_app_name)
        except Exception:
            pass
    await audit(session, user_id=user.id, actor=_actor(request), action="vps_delete", vps_id=v.id, detail=v.fly_app_name)
    await session.delete(v)
    await session.commit()
    return {"ok": True}
