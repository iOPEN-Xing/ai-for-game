from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from studio.api.auth import admin, editor_identity
from studio.domain.commands import Campaign, Decision, Idea, Note, PreferenceUpdate
from studio.services import catalog

router = APIRouter(dependencies=[Depends(admin)])


@router.get("/api/studio")
def overview():
    return catalog.overview()


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
