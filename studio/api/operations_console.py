from fastapi import APIRouter, Depends, Query

from studio.api.auth import admin
from studio.domain.commands import Analysis, ExternalChange, Supplement, Verdict
from studio.services import operations_console

router = APIRouter(dependencies=[Depends(admin)])


@router.get("/api/operations")
def ops(game: str | None = None, days: int | None = Query(None, ge=1, le=90)):
    return operations_console.ops(game, days)


@router.post("/api/operations/changes")
def external_change(body: ExternalChange):
    return operations_console.external_change(body)


@router.get("/api/operations/batches/{day}")
def batch_details(day):
    return operations_console.batch_details(day)


@router.post("/api/operations/analyze")
def analysis(body: Analysis):
    return operations_console.analysis(body)


@router.post("/api/operations/batch")
def batch():
    return operations_console.batch()


@router.get("/api/proposals/{pid}")
def proposal(pid):
    return operations_console.proposal(pid)


@router.post("/api/proposals/{pid}/review")
def review_proposal(pid, body: Verdict):
    return operations_console.review_proposal(pid, body)


@router.post("/api/proposals/{pid}/retry")
def retry_proposal(pid, body: Supplement | None = None):
    return operations_console.retry_proposal(pid, body)


@router.post("/api/experiments/{eid}/decision")
def exp_decision(eid, body: Verdict):
    return operations_console.exp_decision(eid, body)
