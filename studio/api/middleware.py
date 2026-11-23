"""HTTP error envelopes, request correlation, origin validation and public intake limits."""

import re
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from studio.infra import rate_limits
from studio.infra.store import Problem
from studio.settings import deployed

REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,80}")
PLAYER_WRITE = re.compile(
    r"/api/(play/[^/]+/open|rounds/[^/]+/(event|hint|feedback))/?$"
)
CODES = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "INVALID_INPUT",
    429: "RATE_LIMITED",
    503: "UNAVAILABLE",
}


def failure(
    request: Request, status: int, message: str, headers=None, *, code=None
) -> JSONResponse:
    return JSONResponse(
        {
            "code": code or CODES.get(status, "ERROR"),
            "message": message,
            "detail": message,
            "request_id": request.state.request_id,
        },
        status_code=status,
        headers=headers,
    )


def limits_for(path: str, ip: str) -> list[tuple[str, str, int, int]]:
    if path.rstrip("/") == "/api/login":
        return [("login", ip, 10, 60)]
    if path.startswith("/go/"):
        return [("activity", ip, 120, 60)]
    if not PLAYER_WRITE.fullmatch(path):
        return []
    _, _, _, token, action = path.rstrip("/").split("/")
    if action == "open":
        return [("open_ip", ip, 120, 60), ("open_game", ip + ":" + token, 60, 60)]
    if action == "feedback":
        return [("feedback", ip, 10, 86400)]
    return [("player_events", ip, 600, 60), ("round_events", token, 60, 60)]


def install(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def problem(request, exc):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return failure(request, exc.status, str(exc)[:350], headers, code=exc.code)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return failure(request, exc.status_code, str(exc.detail)[:350], exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        fields = ", ".join(
            ".".join(map(str, error["loc"])) for error in exc.errors()[:4]
        )
        return failure(request, 422, "请求字段无效：" + fields[:250])

    @app.middleware("http")
    async def headers(request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = (
            incoming if REQUEST_ID.fullmatch(incoming) else uuid4().hex
        )
        origin = request.headers.get("origin")
        response = None
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            try:
                source = urlsplit(origin)
                same_origin = (
                    source.netloc == request.headers.get("host")
                    and source.scheme == request.url.scheme
                )
            except ValueError:
                same_origin = False
            if not same_origin:
                response = failure(request, 403, "请求来源不匹配")
        if response is None and deployed() and request.method == "POST":
            limits = limits_for(
                request.url.path, request.client.host if request.client else "local"
            )
            if limits:
                retry = await run_in_threadpool(rate_limits.consume, limits)
                if retry:
                    response = failure(
                        request,
                        429,
                        "请求过于频繁，请稍后重试",
                        {"Retry-After": str(retry)},
                    )
        if response is None:
            response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/") or request.url.path in (
            "/readyz",
            "/metrics",
        ):
            response.headers["Cache-Control"] = "no-store"
        return response
