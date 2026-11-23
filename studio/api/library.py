from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from studio.api.auth import admin
from studio.domain.commands import KnowledgeVerdict
from studio.services import library

router = APIRouter(dependencies=[Depends(admin)])


@router.get("/api/skills")
async def skills():
    return await library.skills()


@router.get("/api/agent-runs/{run}/nodes/{node}/contexts/{fingerprint}")
def inspect_agent_input(run, node, fingerprint):
    return library.inspect_agent_input(run, node, fingerprint)


@router.get("/api/agent-runs/{run}/media/{digest}")
def archived_reference(run, digest):
    return Response(library.archived_reference(run, digest), media_type="image/jpeg")


@router.get("/api/memory")
def memory():
    return library.memory()


@router.post("/api/knowledge/{kid}/review")
def review_memory(kid, body: KnowledgeVerdict):
    return library.review_memory(kid, body)


@router.get("/api/revisions/{rid}/design-media/{asset}")
def design_media(
    rid,
    asset: Literal["sprite", "hit", "miss", "win", "ui", "bgm"],
    entity: str | None = None,
):
    return Response(
        library.design_media(rid, asset, entity),
        media_type="image/png" if asset == "sprite" else "audio/wav",
    )


@router.get("/api/revisions/{rid}/download")
def download(rid):
    num, payload = library.download(rid)
    return Response(
        payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="game-v{num}.zip"'},
    )
