"""Fly.io Machines API client — never logs tokens."""

from __future__ import annotations
import asyncio
import logging
import re
from typing import Any
import httpx

from app.config import FLY_API_HOST, FLY_GRAPHQL

log = logging.getLogger("flyio")

class FlyIoError(Exception):
    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body

class FlyIoService:
    def __init__(self, token: str, timeout: float = 90.0):
        token = (token or "").strip()
        if not token:
            raise FlyIoError("Missing Fly token")
        if re.match(r"^\d{8,12}:[A-Za-z0-9_-]{30,}$", token):
            raise FlyIoError("That looks like a Telegram bot token, not a Fly.io token")
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict:
        # macaroon tokens ("FlyV1 ...") are sent as-is, personal/org tokens as Bearer
        auth = self._token if self._token.startswith("FlyV1") else f"Bearer {self._token}"
        return {"Authorization": auth, "Content-Type": "application/json"}

    async def _req(self, method: str, path: str, json: dict | None = None) -> Any:
        url = f"{FLY_API_HOST}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.request(method, url, headers=self._headers(), json=json)
            if r.status_code >= 400:
                raise FlyIoError(
                    f"Fly API {r.status_code}: {r.text[:400]}",
                    status=r.status_code,
                    body=r.text[:600],
                )
            if r.status_code == 204 or not r.content:
                return None
            return r.json()

    async def validate_token(self) -> dict:
        query = "{ viewer { email id } organizations { nodes { id name slug } } }"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(FLY_GRAPHQL, headers=self._headers(), json={"query": query})
            if r.status_code >= 400:
                raise FlyIoError("Fly authorization failed. Check token permissions.", r.status_code)
            data = r.json()
            if data.get("errors"):
                raise FlyIoError("Fly authorization failed: invalid or insufficient token.")
            return data.get("data") or {}

    async def list_organizations(self) -> list[dict]:
        data = await self.validate_token()
        return (data.get("organizations") or {}).get("nodes") or []

    async def get_regions(self) -> list[dict]:
        query = "{ platform { regions { code name gatewayAvailable } } }"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(FLY_GRAPHQL, headers=self._headers(), json={"query": query})
                data = r.json().get("data") or {}
                regions = (data.get("platform") or {}).get("regions") or []
                return [{"code": x["code"], "name": x.get("name") or x["code"]} for x in regions if x.get("code")]
        except Exception:
            return []

    async def create_app(self, app_name: str, org_slug: str = "personal") -> dict:
        return await self._req("POST", "/v1/apps", {"app_name": app_name, "org_slug": org_slug})

    async def get_app(self, app_name: str) -> dict:
        return await self._req("GET", f"/v1/apps/{app_name}")

    async def delete_app(self, app_name: str) -> None:
        await self._req("DELETE", f"/v1/apps/{app_name}")

    async def create_machine(
        self, app_name: str, config: dict, region: str, name: str | None = None, skip_launch: bool = False
    ) -> dict:
        body: dict[str, Any] = {
            "region": region,
            "config": config,
            "skip_launch": skip_launch,
        }
        if name:
            body["name"] = name
        return await self._req("POST", f"/v1/apps/{app_name}/machines", body)

    async def get_machine(self, app_name: str, machine_id: str) -> dict:
        return await self._req("GET", f"/v1/apps/{app_name}/machines/{machine_id}")

    async def list_machines(self, app_name: str) -> list:
        data = await self._req("GET", f"/v1/apps/{app_name}/machines")
        return data if isinstance(data, list) else []

    async def start_machine(self, app_name: str, machine_id: str) -> Any:
        return await self._req("POST", f"/v1/apps/{app_name}/machines/{machine_id}/start")

    async def stop_machine(self, app_name: str, machine_id: str) -> Any:
        return await self._req("POST", f"/v1/apps/{app_name}/machines/{machine_id}/stop", {"timeout": 30})

    async def restart_machine(self, app_name: str, machine_id: str) -> Any:
        try:
            await self.stop_machine(app_name, machine_id)
        except Exception:
            pass
        await asyncio.sleep(2)
        return await self.start_machine(app_name, machine_id)

    async def delete_machine(self, app_name: str, machine_id: str, force: bool = True) -> None:
        q = "?force=true" if force else ""
        await self._req("DELETE", f"/v1/apps/{app_name}/machines/{machine_id}{q}")

    async def wait_machine(self, app_name: str, machine_id: str, state: str = "started", timeout: int = 180) -> dict:
        import time
        deadline = time.time() + timeout
        last: dict = {}
        while time.time() < deadline:
            last = await self.get_machine(app_name, machine_id)
            st = (last.get("state") or "").lower()
            if st == state or (state == "started" and st in ("started", "running")):
                return last
            if st in ("destroyed", "dead"):
                raise FlyIoError(f"Machine entered terminal state: {st}")
            # keep trying start if stopped/created
            if st in ("stopped", "created", "suspended"):
                try:
                    await self.start_machine(app_name, machine_id)
                except Exception:
                    pass
            await asyncio.sleep(4)
        st = (last.get("state") or "unknown")
        raise FlyIoError(f"Timeout waiting for started (last state={st})")


    async def create_volume(self, app_name: str, name: str, region: str, size_gb: int) -> dict:
        return await self._req("POST", f"/v1/apps/{app_name}/volumes", {
            "name": name,
            "region": region,
            "size_gb": int(size_gb),
        })

    async def allocate_ip(self, app_name: str, ip_type: str = "shared_v4") -> dict:
        mutation = """
        mutation($input: AllocateIPAddressInput!) {
          allocateIpAddress(input: $input) {
            ipAddress { id address type region }
            app { sharedIpAddress }
          }
        }
        """
        variables = {"input": {"appId": app_name, "type": ip_type}}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                FLY_GRAPHQL, headers=self._headers(),
                json={"query": mutation, "variables": variables},
            )
            data = r.json()
            if data.get("errors"):
                raise FlyIoError(f"IP allocate failed: {data['errors'][0].get('message', 'error')}")
            return (data.get("data") or {}).get("allocateIpAddress") or {}

    async def list_ips(self, app_name: str) -> list:
        query = """
        query($app: String!) {
          app(name: $app) {
            ipAddresses { nodes { id address type region } }
            sharedIpAddress
          }
        }
        """
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                FLY_GRAPHQL, headers=self._headers(),
                json={"query": query, "variables": {"app": app_name}},
            )
            data = r.json().get("data") or {}
            app = data.get("app") or {}
            nodes = (app.get("ipAddresses") or {}).get("nodes") or []
            shared = app.get("sharedIpAddress")
            if shared and not any(n.get("address") == shared for n in nodes):
                nodes.append({"address": shared, "type": "shared_v4"})
            return nodes
