"""Background deployment job — runs after the HTTP request returns, progress is written to the DB."""
import asyncio
import logging

from app.database.db import SessionLocal
from app.database.models import VpsInstance, AuditLog
from app.services.flyio import FlyIoService, FlyIoError
from app.services.provisioning import deploy_vps

log = logging.getLogger("jobs")
_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def run_deploy(vps_id: int, token: str, params: dict) -> None:
    async def progress(line: str):
        async with SessionLocal() as s:
            v = await s.get(VpsInstance, vps_id)
            if v:
                v.progress = ((v.progress or "") + line + "\n")[-4000:]
                await s.commit()

    try:
        fly = FlyIoService(token)
        res = await deploy_vps(fly, progress=progress, **params)
        async with SessionLocal() as s:
            v = await s.get(VpsInstance, vps_id)
            if v:
                v.machine_id = res["machine_id"]
                v.public_ipv4 = res["public_ipv4"]
                v.public_ipv6 = res["public_ipv6"]
                v.cpu = res["cpus"]
                v.memory_mb = res["memory_mb"]
                v.status = res["status"]
                s.add(AuditLog(user_id=v.user_id, actor="system", action="vps_ready", vps_id=v.id, result="ok"))
                await s.commit()
    except Exception as e:
        msg = str(e)[:700] if isinstance(e, FlyIoError) else f"Unexpected error: {type(e).__name__}"
        if not isinstance(e, FlyIoError):
            log.exception("deploy failed")
        async with SessionLocal() as s:
            v = await s.get(VpsInstance, vps_id)
            if v:
                v.status = "FAILED"
                v.error = msg
                s.add(AuditLog(user_id=v.user_id, actor="system", action="vps_failed", vps_id=v.id, result="error", detail=msg[:300]))
                await s.commit()
