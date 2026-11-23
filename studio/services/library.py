"""Application operations for library."""

import json
from typing import Literal

from studio import artwork, cartridge, skillbook
from studio import context as project_context
from studio.domain.commands import KnowledgeVerdict
from studio.infra.repositories import evidence as evidence_db
from studio.infra.repositories import games as games_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import Problem, db
from studio.services import review
from studio.settings import BASE_RULES


async def skills():
    skills = await skillbook.read()
    for s in skills:
        s["roles"] = [
            role
            for role in skillbook.ROUTING
            if any(
                s["name"] in skillbook.routes(role, task)
                for task in (None, *skillbook.TASK)
            )
        ]
        s["tasks"] = [
            task for task, name in skillbook.TASK.items() if name == s["name"]
        ]
    return skills


def inspect_agent_input(run, node, fingerprint):
    with db() as con:
        return project_context.inspect_input(con, run, node, fingerprint)


def archived_reference(run, digest):
    with db() as con:
        media = evidence_db.selected_image(con, run, digest)
        return media["content"]


def memory():
    with db() as con:
        entries = evidence_db.knowledge_entries(con)
        for k in entries:
            k["evidence"] = json.loads(k["evidence"])
        return {
            "rules": BASE_RULES,
            "entries": entries,
            "games": games_db.list_goals(con),
            "history": evidence_db.recent_decisions(con),
        }


def review_memory(kid, body: KnowledgeVerdict):
    with db(True) as con:
        review.review_knowledge(con, kid, body.accept, body.supersede)
    return {"saved": True}


def design_media(
    rid,
    asset: Literal["sprite", "hit", "miss", "win", "ui", "bgm"],
    entity: str | None = None,
):
    with db() as con:
        rev = revisions_db.design(con, rid)
    art = json.loads(rev["docs"]).get("art")
    if not art:
        raise Problem("本版本尚未产出视听方案", 404)
    if asset == "sprite":
        if entity and entity not in {s["id"] for s in art.get("sprites", [])}:
            raise Problem("未找到图形资源", 404)
        return artwork.sprite(art, entity)
    return artwork.sound(art, asset)


def download(rid):
    with db() as con:
        r = revisions_db.download(con, rid)
    return r["num"], cartridge.bundle_zip(r["bundle"])
