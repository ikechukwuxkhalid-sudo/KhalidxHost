"""KhalidXHost — Fly VPS Manager (web version). Built by @khalid_dev."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, ADMIN_PATH, ADMIN_PASSWORD, OWNER_TELEGRAM, SITE_NAME
from app.database.db import init_db
from app.routes import auth as auth_routes, vps as vps_routes, admin as admin_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("khalidxhost")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if not ADMIN_PASSWORD:
        log.warning("ADMIN_PASSWORD is not set — the admin page login is disabled until you set it.")
    log.info("%s started. Admin path: /%s", SITE_NAME, ADMIN_PATH)
    yield


app = FastAPI(title=SITE_NAME, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

app.include_router(auth_routes.router)
app.include_router(vps_routes.router)
app.include_router(admin_routes.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = CSP
    p = request.url.path
    if p.startswith(f"/{ADMIN_PATH}") or p.startswith("/api/") or p.startswith("/auth/"):
        resp.headers["Cache-Control"] = "no-store"
    if p.startswith(f"/{ADMIN_PATH}"):
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


def _page(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name, media_type="text/html")


@app.get("/", include_in_schema=False)
async def index():
    return _page("index.html")


@app.get("/login", include_in_schema=False)
@app.get("/register", include_in_schema=False)
async def auth_page():
    return _page("auth.html")


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return _page("dashboard.html")


@app.get("/docs", include_in_schema=False)
async def docs():
    return _page("docs.html")


@app.get(f"/{ADMIN_PATH}", include_in_schema=False)
@app.get(f"/{ADMIN_PATH}/", include_in_schema=False)
async def admin_page():
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8").replace("__ADMIN_PATH__", ADMIN_PATH)
    return HTMLResponse(html)


@app.get("/config.json", include_in_schema=False)
async def public_config():
    return {"site": SITE_NAME, "owner": OWNER_TELEGRAM}


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    # intentionally does NOT mention the admin path
    return PlainTextResponse("User-agent: *\nAllow: /\n")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith(("/api/", "/auth/")) or request.url.path.startswith(f"/{ADMIN_PATH}/api/"):
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)
    return FileResponse(STATIC_DIR / "404.html", status_code=404, media_type="text/html")
