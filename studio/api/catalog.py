import asyncio
import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from studio.api.auth import admin, editor_identity
from studio.domain.commands import Campaign, Decision, Idea, Note, PreferenceUpdate
from studio.infra.store import Problem
from studio.services import catalog, progress

router = APIRouter(dependencies=[Depends(admin)])


@router.get("/api/studio")
def overview(request: Request):
    return {
        **catalog.overview(),
        "can_sign_out": bool(request.cookies.get("loop_session")),
    }


@router.post("/api/games", status_code=201)
def create(body: Idea, request: Request, response: Response):
    return catalog.create(body, editor_identity(request, response))


@router.get("/api/preferences")
def personal_preferences(request: Request, response: Response):
    return catalog.personal_preferences(editor_identity(request, response))


@router.put("/api/preferences")
def edit_personal_preferences(
    body: PreferenceUpdate, request: Request, response: Response
):
    return catalog.edit_personal_preferences(body, editor_identity(request, response))


@router.get("/api/games/{gid}/preferences")
def project_preferences(gid):
    return catalog.project_preferences(gid)


@router.put("/api/games/{gid}/preferences")
def edit_project_preferences(gid, body: PreferenceUpdate):
    return catalog.edit_project_preferences(gid, body)


@router.get("/api/games/{gid}")
def game(gid, rev: str | None = None):
    return catalog.game(gid, rev)


@router.post("/api/games/{gid}/campaigns")
def create_campaign(gid, body: Campaign):
    return catalog.create_campaign(gid, body)


@router.post("/api/revisions/{rid}/decision")
def decision(rid, body: Decision):
    return catalog.decision(rid, body)


@router.post("/api/revisions/{rid}/note")
def note(rid, body: Note):
    return catalog.note(rid, body)


@router.get("/api/revisions/{rid}/events", response_class=StreamingResponse)
async def revision_events(rid: str, request: Request, session=Depends(admin)):
    first = await asyncio.to_thread(progress.snapshot, rid, session)

    async def updates():
        previous = request.headers.get("last-event-id")
        current = first
        heartbeat = started = time.monotonic()
        yield "retry: 2000\n\n"
        while True:
            cursor, state = current
            if cursor != previous or state["terminal"]:
                yield f"id: {cursor}\nevent: progress\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
                previous = cursor
            if state["terminal"] or time.monotonic() - started >= 60:
                return
            if time.monotonic() - heartbeat >= 12:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(1)
            if await request.is_disconnected():
                return
            try:
                current = await asyncio.to_thread(progress.snapshot, rid, session)
            except Problem as exc:
                if exc.status != 401:
                    raise
                yield "event: session_closed\ndata: {}\n\n"
                return

    return StreamingResponse(
        updates(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
