"""Internal team sessions. The public gateway does not expose these routes."""

import hashlib
import hmac
import os
import re
import secrets
from ipaddress import ip_address

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from studio.domain.commands import Login
from studio.infra.repositories import sessions
from studio.infra.store import Problem, db, now
from studio.settings import deployed

router = APIRouter()


def session_digest(token, key):
    return hmac.new(key.encode(), token.encode(), hashlib.sha256).hexdigest()


def admin(request: Request):
    key = os.getenv("STUDIO_ACCESS_KEY", "")
    if not key and not deployed() and request.client:
        try:
            local_peer = ip_address(request.client.host).is_loopback
        except ValueError:
            local_peer = False
        if local_peer and request.url.hostname in {"localhost", "127.0.0.1", "::1"}:
            return
    token = request.headers.get("x-atelier-session") or request.cookies.get(
        "loop_session", ""
    )
    if key and re.fullmatch("[a-f0-9]{64}", token):
        digest = session_digest(token, key)
        with db() as con:
            if sessions.valid(con, digest, now()):
                return digest
    raise Problem("请使用制作台口令登录", 401)


Private = [Depends(admin)]


@router.post("/api/login")
def login(body: Login, request: Request):
    key = os.getenv("STUDIO_ACCESS_KEY", "")
    if not key or not hmac.compare_digest(body.key.encode(), key.encode()):
        raise Problem("口令无效", 401)
    token = secrets.token_hex(32)
    with db(True) as con:
        sessions.issue(con, session_digest(token, key), now() + 12 * 3600)
    response = JSONResponse({"session": token})
    secure = request.url.scheme == "https"
    response.set_cookie(
        "loop_session",
        token,
        max_age=12 * 3600,
        httponly=True,
        secure=secure,
        samesite="strict",
    )
    return response


@router.post("/api/logout")
def logout(request: Request, digest: str | None = Depends(admin)):
    if digest:
        with db(True) as con:
            sessions.revoke(con, digest)
    response = JSONResponse({"signed_out": True})
    for name in ("loop_session", "loop_editor"):
        response.delete_cookie(
            name, httponly=True, secure=request.url.scheme == "https", samesite="strict"
        )
    return response


def editor_identity(request: Request, response: Response) -> str:
    from studio import context

    with db(True) as con:
        return context.editor(con, request, response)
