import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_session
from app.database.models import User, FlyAccount
from app.deps import current_user, client_ip, is_https, audit, USER_COOKIE
from app.security import auth
from app.security.ratelimit import hit

router = APIRouter(prefix="/auth", tags=["auth"])

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
SESSION_AGE = 60 * 60 * 24 * 14


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=8, max_length=128)
    telegram: str | None = Field(default=None, max_length=64)


class LoginBody(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=128)


def _set_cookie(request: Request, response: Response, user: User):
    token = auth.sign({"u": user.id, "r": "user"}, SESSION_AGE)
    response.set_cookie(USER_COOKIE, token, max_age=SESSION_AGE, httponly=True, samesite="lax", secure=is_https(request), path="/")


@router.post("/register")
async def register(body: RegisterBody, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    ip = client_ip(request)
    if not hit(f"reg:{ip}", 5, 3600):
        raise HTTPException(429, "Too many sign-ups from this network. Try again later.")
    if not USERNAME_RE.match(body.username):
        raise HTTPException(400, "Username: 3-24 characters, letters, numbers and underscore only")
    uname = body.username.lower()
    exists = (await session.execute(select(User).where(User.username == uname))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "Username already taken")
    tg = (body.telegram or "").strip().lstrip("@")[:64] or None
    user = User(username=uname, password_hash=await auth.hash_password(body.password), telegram=tg)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await audit(session, user_id=user.id, action="register")
    _set_cookie(request, response, user)
    return {"ok": True, "username": user.username}


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    ip = client_ip(request)
    uname = body.username.lower().strip()
    if not hit(f"login:{ip}", 10, 600) or not hit(f"loginu:{uname}", 10, 600):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    user = (await session.execute(select(User).where(User.username == uname))).scalar_one_or_none()
    ok = bool(user) and await auth.verify_password(body.password, user.password_hash)
    if not ok:
        raise HTTPException(401, "Wrong username or password")
    if user.is_blocked:
        raise HTTPException(403, "This account has been suspended")
    user.last_login = datetime.utcnow()
    await session.commit()
    _set_cookie(request, response, user)
    return {"ok": True, "username": user.username}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(USER_COOKIE, path="/")
    return {"ok": True}
