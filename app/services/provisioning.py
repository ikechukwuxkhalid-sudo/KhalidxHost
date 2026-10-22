"""VPS provisioning — Ubuntu + OpenSSH + Docker on a Fly Machine. Good base for Pterodactyl (Docker), panels, bots, anything."""
from __future__ import annotations
import asyncio
import logging
import secrets
import string
import time
from typing import Callable, Awaitable

from app.services.flyio import FlyIoService, FlyIoError

log = logging.getLogger("provision")

IMAGE = "registry-1.docker.io/library/ubuntu:24.04"
# ports published on the VPS public IP
PUBLISHED_PORTS = [22, 80, 443, 2022, 8080]


def gen_password(length: int = 18) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def sanitize_app_name(name: str) -> str:
    name = (name or "").lower().strip().replace("_", "-").replace(" ", "-")
    s = "".join(c for c in name if c.isalnum() or c == "-").strip("-")
    return s[:24]


def pick_guest(cpus: int, memory_mb: int) -> dict:
    cpus = max(1, min(int(cpus), 16))
    memory_mb = max(256, int(memory_mb))
    if cpus <= 4 and memory_mb <= 8192:
        kind = "shared"
        if memory_mb > 2048 * cpus:
            kind = "performance"
            memory_mb = max(2048, min(memory_mb, 8192 * cpus))
            memory_mb = (memory_mb // 1024) * 1024
        else:
            memory_mb = max(1024, (memory_mb // 256) * 256)
    else:
        kind = "performance"
        memory_mb = max(2048, min(memory_mb, 8192 * cpus))
        memory_mb = (memory_mb // 1024) * 1024
    return {"cpu_kind": kind, "cpus": cpus, "memory_mb": memory_mb}


ProgressCb = Callable[[str], Awaitable[None]]


def _bootstrap_script(password: str) -> str:
    """PID 1 stays alive forever. Installs OpenSSH + Docker CE, enables root password SSH, starts dockerd."""
    pw = password.replace("'", "'\"'\"'")
    return f"""export DEBIAN_FRONTEND=noninteractive
exec > /var/log/vps-bootstrap.log 2>&1

apt-get update -qq
apt-get install -y -qq openssh-server sudo ca-certificates curl gnupg lsb-release \\
  iptables apt-transport-https software-properties-common ufw fail2ban htop nano wget git unzip \\
  || apt-get install -y -qq openssh-server sudo ca-certificates curl

mkdir -p /var/run/sshd /root/.ssh
echo 'root:{pw}' | chpasswd
sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^#\\?Port .*/Port 22/' /etc/ssh/sshd_config
grep -q ClientAliveInterval /etc/ssh/sshd_config || echo 'ClientAliveInterval 30' >> /etc/ssh/sshd_config
grep -q ClientAliveCountMax /etc/ssh/sshd_config || echo 'ClientAliveCountMax 20' >> /etc/ssh/sshd_config
grep -q TCPKeepAlive /etc/ssh/sshd_config || echo 'TCPKeepAlive yes' >> /etc/ssh/sshd_config
ssh-keygen -A >/dev/null 2>&1 || true
/usr/sbin/sshd || true

# Docker CE
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null || true
chmod a+r /etc/apt/keyrings/docker.gpg 2>/dev/null || true
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \\
  || apt-get install -y -qq docker.io docker-compose || true

# no systemd here -> run dockerd directly; keep images/volumes on the persistent /data volume when present
update-alternatives --set iptables /usr/sbin/iptables-legacy >/dev/null 2>&1 || true
update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy >/dev/null 2>&1 || true
mkdir -p /etc/docker /var/lib/docker
if [ -d /data ]; then
  mkdir -p /data/docker
  echo '{{"data-root":"/data/docker"}}' > /etc/docker/daemon.json
fi
mountpoint -q /sys/fs/cgroup || mount -t cgroup2 none /sys/fs/cgroup 2>/dev/null || true
nohup dockerd > /var/log/dockerd.log 2>&1 &
sleep 8

echo READY > /root/.vps_ready
docker --version > /root/.docker_version 2>&1 || echo 'docker missing' > /root/.docker_version

# never exit - keeps the machine STARTED
while true; do sleep 3600; done
"""


async def wait_ssh(host: str, timeout: int = 420) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection(host, 22), 8)
            try:
                banner = await asyncio.wait_for(r.readline(), 8)
            finally:
                w.close()
            if banner.startswith(b"SSH-"):
                return True
        except Exception:
            pass
        await asyncio.sleep(10)
    return False


async def deploy_vps(
    fly: FlyIoService,
    *,
    app_name: str,
    region: str,
    cpus: int,
    memory_mb: int,
    storage_gb: int,
    root_password: str,
    image: str | None = None,
    org_slug: str = "personal",
    progress: ProgressCb | None = None,
) -> dict:
    async def step(msg: str):
        log.info("%s", msg)
        if progress:
            await progress(msg)

    image = image or IMAGE
    storage_gb = max(1, min(int(storage_gb or 10), 500))

    await step("✓ Validating Fly token")
    await fly.validate_token()

    await step("… Creating Fly app")
    await fly.create_app(app_name, org_slug=org_slug or "personal")
    await step("✓ App created")

    guest = pick_guest(cpus, memory_mb)
    await step(f"… Guest: {guest['cpu_kind']} {guest['cpus']} CPU / {guest['memory_mb']} MB")

    volume_id = None
    mounts = []
    vol_name = f"data_{secrets.token_hex(3)}"
    await step(f"… Creating {storage_gb}GB volume in {region}")
    try:
        vol = await fly.create_volume(app_name, vol_name, region, storage_gb)
        volume_id = vol.get("id")
        if volume_id:
            mounts = [{"volume": volume_id, "path": "/data"}]
            await step("✓ Volume mounted at /data")
        else:
            await step("⚠ Volume id missing — continuing without volume")
    except Exception as e:
        await step(f"⚠ Volume skipped: {type(e).__name__}")

    config: dict = {
        "image": image,
        "guest": guest,
        "init": {"exec": ["/bin/bash", "-c", _bootstrap_script(root_password)]},
        "restart": {"policy": "always"},
        "auto_destroy": False,
        "env": {"VPS_HOSTNAME": app_name},
        "services": [
            {
                "protocol": "tcp",
                "internal_port": p,
                "autostart": True,
                "autostop": False,
                "ports": [{"port": p}],
            }
            for p in PUBLISHED_PORTS
        ],
    }
    if mounts:
        config["mounts"] = mounts

    await step("… Creating machine (Ubuntu + Docker + SSH)")
    machine = await fly.create_machine(app_name, config, region=region, name=f"{app_name}-1", skip_launch=False)
    machine_id = machine.get("id")
    if not machine_id:
        raise FlyIoError("No machine ID returned")
    await step(f"✓ Machine: {machine_id}")

    await step("… Starting machine")
    started = False
    for attempt in range(8):
        try:
            await fly.start_machine(app_name, machine_id)
        except Exception:
            pass
        await asyncio.sleep(5)
        m = await fly.get_machine(app_name, machine_id)
        st = (m.get("state") or "").lower()
        await step(f"… State {attempt + 1}: {st}")
        if st in ("started", "running"):
            machine, started = m, True
            break
    if not started:
        try:
            machine = await fly.wait_machine(app_name, machine_id, "started", timeout=300)
        except FlyIoError:
            m = await fly.get_machine(app_name, machine_id)
            raise FlyIoError(
                f"Machine state is {(m.get('state') or 'unknown').upper()}, not ready. "
                "Try region iad/ord/lhr or 2GB+ RAM."
            )
    await step(f"✓ State: {(machine.get('state') or '?').upper()}")

    ipv4 = ipv6 = None
    await step("… Allocating public IP")
    for ip_type in ("v4", "shared_v4"):
        try:
            res = await fly.allocate_ip(app_name, ip_type)
            addr = (res.get("ipAddress") or {}).get("address") or (res.get("app") or {}).get("sharedIpAddress")
            if addr:
                ipv4 = addr
                await step(f"✓ IPv4: {addr}")
                break
        except Exception as e:
            await step(f"⚠ IP {ip_type}: {type(e).__name__}")
    try:
        res6 = await fly.allocate_ip(app_name, "v6")
        ipv6 = (res6.get("ipAddress") or {}).get("address")
    except Exception:
        pass
    if not ipv4:
        try:
            for ip in await fly.list_ips(app_name):
                addr = ip.get("address")
                t = (ip.get("type") or "").lower()
                if addr and "v6" not in t:
                    ipv4 = addr
                elif addr:
                    ipv6 = ipv6 or addr
        except Exception:
            pass

    await step("… Installing OpenSSH + Docker (2–5 min on first boot)")
    if ipv4:
        ready = await wait_ssh(ipv4)
        await step("✓ SSH is answering" if ready else "⚠ SSH not answering yet — it may need another minute or two")
    else:
        await asyncio.sleep(90)

    machine = await fly.get_machine(app_name, machine_id)
    final = (machine.get("state") or "unknown").upper()
    if final not in ("STARTED", "RUNNING"):
        raise FlyIoError(f"Machine state is {final}, not ready.")

    await step("✓ VPS READY")
    return {
        "machine_id": machine_id,
        "public_ipv4": ipv4,
        "public_ipv6": ipv6,
        "cpus": guest["cpus"],
        "memory_mb": guest["memory_mb"],
        "status": "RUNNING",
        "volume_id": volume_id,
    }
