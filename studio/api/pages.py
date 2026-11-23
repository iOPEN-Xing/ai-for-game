from functools import lru_cache

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from markdown_it import MarkdownIt

from studio import cartridge
from studio.infra.repositories import games as games_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import db
from studio.settings import ROOT, WEB

router = APIRouter()


@router.get("/")
def studio():
    return FileResponse(WEB / "index.html")


@router.get("/reference")
@router.get("/original", include_in_schema=False)
def reference():
    return FileResponse(ROOT / "docs/original/index.html")


@router.get("/product", response_class=HTMLResponse)
def product_brief():
    return product_html()


@router.head("/sample", include_in_schema=False)
@router.get("/sample")
def sample():
    return FileResponse(WEB / "play.html")


@router.head("/play/{gid}", include_in_schema=False)
@router.get("/play/{gid}")
def player_page(gid):
    with db() as con:
        games_db.require_published(con, gid)
    return FileResponse(WEB / "play.html")


@router.head("/cartridges/v1/{bundle}.json", include_in_schema=False)
@router.get("/cartridges/v1/{bundle}.json")
def public_cartridge(bundle: str, request: Request):
    with db() as con:
        revisions_db.require_published_bundle(con, bundle)
    etag = f'"{bundle}"'
    headers = {"Cache-Control": "public, max-age=31536000, immutable", "ETag": etag}
    requested = [
        tag.strip().removeprefix("W/")
        for tag in request.headers.get("if-none-match", "").split(",")
    ]
    if "*" in requested or etag in requested:
        return Response(status_code=304, headers=headers)
    return Response(
        cartridge.public_payload(bundle),
        media_type="application/json",
        headers=headers,
    )


@lru_cache(maxsize=1)
def product_html():
    article = (
        MarkdownIt("commonmark", {"html": False})
        .enable("table")
        .render((ROOT / "docs/PILOT.md").read_text(encoding="utf-8"))
    )
    return (
        (WEB / "product.html")
        .read_text(encoding="utf-8")
        .replace("<!--article-->", article)
    )
