from fastapi import APIRouter, Depends

from studio.api.auth import admin
from studio.domain.commands import BlueprintEdit
from studio.services import blueprints as blueprint_service

router = APIRouter(dependencies=[Depends(admin)])


@router.get("/api/revisions/{rid}/levels")
def blueprints(rid):
    return blueprint_service.blueprints(rid)


@router.post("/api/revisions/{rid}/levels")
def edit_blueprint(rid, body: BlueprintEdit):
    return blueprint_service.edit_blueprint(rid, body)
