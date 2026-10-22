import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR = BASE_DIR / "static"


def _persisted_secret(name: str) -> str:
    """Fallback so the app still boots without env vars (local dev).
    On Render set SECRET_KEY / ENCRYPTION_KEY as env vars instead (render.yaml does it)."""
    p = DATA_DIR / f".{name}"
    if p.exists():
        return p.read_text().strip()
    val = secrets.token_urlsafe(48)
    p.write_text(val)
    return val


SECRET_KEY = os.getenv("SECRET_KEY") or _persisted_secret("secret_key")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY") or _persisted_secret("enc_key")

# --- Owner / admin ---
ADMIN_PATH = os.getenv("ADMIN_PATH", "khalid").strip().strip("/") or "khalid"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
OWNER_TELEGRAM = os.getenv("OWNER_TELEGRAM", "khalid_dev").lstrip("@")
SITE_NAME = os.getenv("SITE_NAME", "KhalidXHost")

# --- Database ---
_raw_db = os.getenv("DATABASE_URL", "").strip()
if _raw_db:
    if _raw_db.startswith("postgres://"):
        _raw_db = "postgresql+asyncpg://" + _raw_db[len("postgres://"):]
    elif _raw_db.startswith("postgresql://"):
        _raw_db = "postgresql+asyncpg://" + _raw_db[len("postgresql://"):]
    _raw_db = _raw_db.replace("sslmode=", "ssl=")
    DATABASE_URL = _raw_db
else:
    DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR}/flyvps.db"

# --- Fly ---
FLY_API_HOST = os.getenv("FLY_API_HOST", "https://api.machines.dev").rstrip("/")
FLY_GRAPHQL = "https://api.fly.io/graphql"
DEFAULT_IMAGE = os.getenv("DEFAULT_IMAGE", "registry-1.docker.io/library/ubuntu:24.04")
MAX_VPS_PER_USER = int(os.getenv("MAX_VPS_PER_USER", "5"))

CPU_OPTIONS = [1, 2, 4, 8, 16]
RAM_OPTIONS_MB = [1024, 2048, 4096, 8192, 16384, 32768, 65536]
STORAGE_OPTIONS_GB = [1, 3, 5, 10, 20, 40, 50, 100, 200]

FALLBACK_REGIONS = [
    ("iad", "Ashburn, Virginia (US)"),
    ("ord", "Chicago, Illinois (US)"),
    ("ewr", "Secaucus, NJ (US)"),
    ("lax", "Los Angeles, California (US)"),
    ("lhr", "London, England"),
    ("fra", "Frankfurt, Germany"),
    ("ams", "Amsterdam, Netherlands"),
    ("cdg", "Paris, France"),
    ("sin", "Singapore"),
    ("nrt", "Tokyo, Japan"),
    ("syd", "Sydney, Australia"),
    ("gru", "Sao Paulo, Brazil"),
    ("bom", "Mumbai, India"),
    ("jnb", "Johannesburg, South Africa"),
]
