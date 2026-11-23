"""Internal team sessions. The public gateway does not expose these routes."""

import hashlib
import hmac
import os
import re
from ipaddress import ip_address

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from studio.domain.commands import Login
from studio.infra.store import Problem, now
from studio.settings import deployed

router = APIRouter()


def signed_session(stamp, key):
    return hmac.new(
        key.encode(), ("loop:" + stamp).encode(), hashlib.sha256
    ).hexdigest()


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
    parts = re.fullmatch(r"([0-9]{1,12})\.([a-f0-9]{64})", token)
    if not parts or not key:
        raise Problem("请使用制作台口令登录", 401)
    stamp, signature = parts.groups()
    if not now() <= int(stamp) <= now() + 86400 or not hmac.compare_digest(
        signature, signed_session(stamp, key)
    ):
        raise Problem("请使用制作台口令登录", 401)


Private = [Depends(admin)]


@router.post("/api/login")
def login(body: Login, request: Request):
    key = os.getenv("STUDIO_ACCESS_KEY", "")
    if not key or not hmac.compare_digest(body.key.encode(), key.encode()):
        raise Problem("口令无效", 401)
    stamp = str(now() + 12 * 3600)
    token = stamp + "." + signed_session(stamp, key)
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


def editor_identity(request: Request, response: Response) -> str:
    from studio import context
    from studio.infra.store import db

    with db(True) as con:
        return context.editor(con, request, response)
