from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from studio.api.auth import admin
from studio.domain.commands import Feedback, RoundEvent, RoundRequest
from studio.services import gameplay

router = APIRouter()


@router.post("/api/play/{gid}/open")
def open_round(gid, body: RoundRequest, request: Request):
    if body.preview:
        admin(request)
    return gameplay.open_round(gid, body)


@router.post("/go/{token}")
def visit_activity(token):
    return RedirectResponse(
        gameplay.visit_activity(token),
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/api/rounds/{token}/event")
def event(token, body: RoundEvent):
    return gameplay.event(token, body)


@router.post("/api/rounds/{token}/hint")
def show_hint(token):
    return gameplay.show_hint(token)


@router.post("/api/rounds/{token}/feedback")
def feedback(token, body: Feedback):
    return gameplay.feedback(token, body)
