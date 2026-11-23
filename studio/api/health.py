from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from studio.infra import monitoring
from studio.infra.store import Problem

from .auth import admin

router = APIRouter()


@router.get("/healthz")
def healthy():
    if not monitoring.available():
        raise Problem("数据存储暂不可用", 503)
    return {"status": "ok"}


@router.get("/readyz")
def ready(request: Request):
    worker = getattr(request.app.state, "worker", None)
    report = monitoring.readiness(worker is not None and not worker.done())
    return JSONResponse(report, status_code=200 if report["status"] == "ready" else 503)


@router.get("/metrics", dependencies=[Depends(admin)], response_class=PlainTextResponse)
def metrics():
    return monitoring.metrics()
