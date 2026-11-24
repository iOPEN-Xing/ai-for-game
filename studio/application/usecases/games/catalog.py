"""Application operations for catalog."""

import hashlib

from studio.application.memory import preferences as preference_store
from studio.application.usecases.games import revisions
from studio.domain import limits
from studio.domain.commands import Campaign, Decision, Idea, Note, PreferenceUpdate
from studio.infra.repositories import games as games_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import Problem, db, encode, log, now, uid
from studio.settings import (
    FAMILIES,
    METRICS,
    STAGES,
    chat_model,
    provider_names,
    public_origin,
)


def overview():
    with db() as con:
        games = games_db.studio_overview(con)
        return {
            "games": games,
            "public_origin": public_origin(),
            "stages": STAGES,
            "metrics": METRICS,
            "families": FAMILIES,
            "providers": provider_names(),
            "model": chat_model(),
            "rounds": games_db.formal_starts(con)["n"],
            "reviews": games_db.proposals_for_review(con)["n"],
            "knowledge_pending": games_db.pending_knowledge(con)["n"],
            "decisions": games_db.pending_experiments(con)["n"],
        }


def create(body: Idea, editor_id: str):
    with db(True) as con:
        fingerprint = hashlib.sha256(
            encode(body.model_dump(exclude={"request_id"}, exclude_none=True)).encode()
        ).hexdigest()
        if body.request_id:
            prior = games_db.find_request(con, body.request_id)
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise Problem("同一创建请求包含不同内容")
                return {"game": prior["game"], "rev": prior["rev"]}
        prefs = preference_store.preferences(con, "editor", editor_id)
        g, r = revisions.new_game(
            con,
            body.title,
            body.brief,
            body.metric,
            body.bounds,
            preferences=prefs["values"],
            level_count=body.level_count,
        )
        if body.request_id:
            games_db.save_request(con, body.request_id, fingerprint, g, r)
        return {"game": g, "rev": r}


def personal_preferences(subject: str):
    with db(True) as con:
        return preference_store.preferences(con, "editor", subject)


def edit_personal_preferences(body: PreferenceUpdate, subject: str):
    with db(True) as con:
        return preference_store.save_preferences(
            con, "editor", subject, body.version, body.values.model_dump()
        )


def project_preferences(gid):
    with db() as con:
        games_db.require_game(con, gid)
        return preference_store.preferences(con, "project", gid)


def edit_project_preferences(gid, body: PreferenceUpdate):
    with db(True) as con:
        games_db.require_game(con, gid)
        saved = preference_store.save_preferences(
            con, "project", gid, body.version, body.values.model_dump()
        )
        log(
            con,
            gid,
            None,
            "制作人",
            f"已更新项目偏好至第 {saved['version']} 版",
            "preference",
        )
        return saved


def game(gid, rev: str | None = None):
    with db() as con:
        return revisions.detail(con, gid, rev)


def create_campaign(gid, body: Campaign):
    url = str(body.action_url) if body.action_url else None
    with db(True) as con:
        if not games_db.live_version(con, gid)["live"]:
            raise Problem("游戏发布后可以创建活动入口")
        existing = games_db.find_campaign(con, gid, body.name)
        if existing:
            if (existing["action_label"], existing["action_url"]) != (
                body.action_label,
                url,
            ):
                raise Problem("这个入口名称已有其他行动目标，请换一个名称")
            cid = existing["id"]
        else:
            if games_db.campaign_count(con, gid) >= limits.CAMPAIGNS_PER_GAME:
                raise Problem("已达到此游戏的活动入口上限", 429, code="QUOTA_EXCEEDED")
            cid = uid()
            games_db.create_campaign(
                con, cid, gid, body.name, body.action_label, url, now()
            )
    return {"id": cid, "path": f"/play/{gid}?entry={cid}"}


def decision(rid, body: Decision):
    with db(True) as con:
        return {"stage": revisions.change(con, rid, **body.model_dump())}


def note(rid, body: Note):
    with db(True) as con:
        r = revisions_db.notes(con, rid)
        log(con, r["game"], rid, "制作团队", body.note, "comment")
        revisions_db.update_notes(con, (r["notes"] + "\n" + body.note)[-4800:], rid)
        return {"saved": True}
