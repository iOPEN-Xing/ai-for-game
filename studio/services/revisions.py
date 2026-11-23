"""Revision lifecycle and the human gates for research, design, playtest and release."""

import json
import secrets

from studio import context as project_context
from studio.domain import limits
from studio.domain.artifacts import DOCS
from studio.domain.revision import HUMAN_GATES, STEPS
from studio.infra.repositories import games as games_db
from studio.infra.repositories import jobs as jobs_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import Problem, db, encode, enqueue, log, now, uid


def new_game(con, title, brief, metric, bounds, proposal=None, preferences=None):
    if games_db.count(con) >= limits.GAMES_PER_STUDIO:
        raise Problem("已达到制作室游戏数量上限", 429, code="QUOTA_EXCEEDED")
    game = uid()
    games_db.create(con, game, title, brief, metric, bounds, now())
    if preferences:
        project_context.save_preferences(con, "project", game, 0, preferences)
    return game, new_revision(con, game, proposal=proposal)


def new_revision(con, game, parent=None, proposal=None, note=""):
    rev = uid()
    n = revisions_db.next_number(con, game)["n"]
    if n > limits.REVISIONS_PER_GAME:
        raise Problem("已达到此游戏的版本数量上限", 429, code="QUOTA_EXCEEDED")
    stage, docs, seed, choice = "research", {}, secrets.randbits(31), None
    if parent:
        old = revisions_db.for_game(con, parent, game)
        inherited = json.loads(old["docs"])
        docs = {
            k: inherited[k]
            for k in (
                "route_research",
                "research",
                "discovery",
                "visual_analysis",
                "selected_references",
            )
            if k in inherited
        }
        stage, seed, choice = "design", old["seed"], old["choice"]
        if proposal:
            plan = json.loads(proposals_db.decision(con, proposal)["doc"])["bet"]
            kinds = {c["kind"] for c in plan.get("checks", [])}
            if kinds:
                reuse = set()
                if "asset" not in kinds:
                    reuse.add("art")
                if "parameter" not in kinds:
                    reuse.update(("levels", "level_code"))
                if kinds == {"parameter"}:
                    reuse.update(("route_design", "gdd", "game_code", "levels"))
                docs.update({key: inherited[key] for key in reuse})
    docs["context_snapshot"] = project_context.capture(con, game)
    revisions_db.create(
        con,
        rev,
        game,
        n,
        stage,
        seed,
        parent,
        proposal,
        choice,
        note,
        encode(docs),
        now(),
    )
    log(con, game, rev, "制作人", note or "已收到游戏创意，准备玩法调研。")
    enqueue(con, "production", rev, stage)
    return rev


def detail(con, game, rev_id=None):
    g = games_db.get(con, game)
    versions = revisions_db.versions(con, game)
    r = revisions_db.for_game(con, rev_id or versions[0]["id"], game)
    r["docs"] = json.loads(r["docs"])
    if r["stage"] in STEPS:
        job = jobs_db.production_status(con, r["id"], r["stage"])
    else:
        job = jobs_db.latest_production(con, r["id"])
    preview = revisions_db.preview_count(con, r["id"], r["bundle"])
    return {
        "game": g,
        "revision": r,
        "versions": versions,
        "history": revisions_db.history(con, r["id"]),
        "job": job,
        "tested": preview["n"],
        "artifacts": DOCS,
    }


def change(
    con, rev_id, action, serial, choice=None, note="", target=None, reference_ids=None
):
    r = revisions_db.get(con, rev_id)
    g = games_db.get(con, r["game"])
    if r["serial"] != serial:
        raise Problem("版本状态已更新，请刷新后再操作")
    stage = r["stage"]
    failed = jobs_db.failed_production(con, rev_id, stage)
    docs = json.loads(r["docs"])
    gate = HUMAN_GATES.get(action)
    if gate and stage != gate[0]:
        raise Problem("当前阶段不允许此操作")
    next_stage = gate[1] if gate else stage
    if action == "retry":
        job = jobs_db.production(con, rev_id, stage)
        if job["state"] != "failed":
            raise Problem("只有失败的任务可以重试")
        enqueue(con, "production", rev_id, stage)
        next_stage = stage
    elif action == "select_references":
        ids = reference_ids or []
        allowed_ids = {ref["id"] for ref in docs["discovery"]["references"]}
        if (
            not 1 <= len(ids) <= 4
            or len(set(ids)) != len(ids)
            or set(ids) - allowed_ids
        ):
            raise Problem("请选择本次检索中的 1 至 4 张不同参考图", 422)
        docs["selected_references"] = ids
        revisions_db.save_docs(con, encode(docs), rev_id)
    elif action == "choose":
        if type(choice) is not int or not 0 <= choice < len(
            docs["research"]["directions"]
        ):
            raise Problem("请选择一个有效方向", 422)
        revisions_db.choose(con, choice, rev_id)
    elif action == "accept":
        if not revisions_db.accepted_playtest(con, rev_id, r["bundle"]):
            raise Problem("请先完成本次构建的一局试玩")
    elif action == "publish":
        from studio.services.experiments import release

        release(con, g, r)
    elif action == "revise" and (
        stage in ("references", "direction", "plan", "quality", "ready") or failed
    ):
        allowed = {
            "references": ["research"],
            "direction": ["research"],
            "plan": ["research", "design"],
            "quality": ["research", "design", "build"],
            "ready": ["research", "design", "build"],
        }
        if failed:
            allowed[stage] = list(STEPS)[: list(STEPS).index(stage) + 1]
        scoped = {
            "art": "design",
            "levels": "design",
            "level_code": "build",
            "game_code": "build",
        }
        group = (
            (
                "research"
                if stage in ("research", "references", "interpret", "direction")
                else "design"
            )
            if target == "auto"
            else scoped.get(target, target)
        )
        if group not in allowed[stage] or not note.strip():
            raise Problem("请选择返工环节并填写修改意见", 422)
        next_stage = group
        if previous := docs.get("context_snapshot"):
            docs.setdefault("context_history", []).append(
                {
                    "id": previous["id"],
                    "preference_version": previous["preferences"]["version"],
                    "stage": stage,
                    "reason": note,
                    "at": now(),
                }
            )
        docs["context_snapshot"] = project_context.capture(con, r["game"])
        docs.pop("build_feedback", None)
        ordered = list(STEPS)
        if target == "auto" and group == "design":
            docs["impact_request"] = note
            docs.pop("impact", None)
        if "art" in docs and (
            target in ("art", "design", "auto") or group == "research"
        ):
            docs["prior_art"] = docs["art"]
        for key in (
            []
            if target == "auto" and group == "design"
            else ordered[ordered.index(group) :]
        ):
            for doc in STEPS[key]:
                if (
                    target not in scoped
                    or key != group
                    or doc.startswith("route_")
                    or doc == target
                ):
                    docs.pop(doc, None)
        if target in ("art", "design", "auto", "research"):
            docs.pop("art_spec", None)
        if group == "research":
            docs.pop("selected_references", None)
            docs.pop("rule_sources", None)
        if group == "build":
            docs.pop("validation", None)
            docs.pop("quality_report", None)
            if target == "game_code":
                docs.pop("level_code", None)
        revisions_db.invalidate_build(con, encode(docs), rev_id)
        if group == "research":
            revisions_db.clear_choice(con, rev_id)
    elif action != "approve":
        raise Problem("当前阶段不允许此操作")
    labels = {
        "select_references": "确认调研参考图",
        "choose": "确认玩法方向",
        "approve": "确认生产方案",
        "accept": "通过试玩验收",
        "publish": "确认发布",
        "revise": "要求返工",
        "retry": "重试任务",
    }
    message = labels[action] + (" · " + note.strip() if note.strip() else "")
    if action == "choose":
        message += " · " + docs["research"]["directions"][choice]["title"]
    log(con, r["game"], rev_id, "制作团队", message, "review")
    if not revisions_db.transition(
        con,
        next_stage,
        (r["notes"] + "\n" + note).strip()[-4800:],
        rev_id,
        serial,
        stage,
    ):
        raise Problem("版本状态已更新，请刷新后再操作")
    if next_stage in STEPS:
        enqueue(con, "production", rev_id, next_stage)
    return next_stage


def checkpoint(rev, stage, key, value, role, provider=None, bundle=None):
    with db(True) as con:
        r = revisions_db.get(con, rev)
        if r["stage"] != stage:
            raise Problem("任务已被新版本取代")
        docs = json.loads(r["docs"])
        docs[key] = value
        revisions_db.checkpoint(con, encode(docs), bundle, rev)
        summary = (
            value.get("summary")
            or value.get("core_loop")
            or value.get("style")
            or value.get("curve")
            or ""
        )
        log(
            con,
            r["game"],
            rev,
            role,
            DOCS[key]
            + "已就绪"
            + (" · " + summary[:300] if summary else "")
            + (" [" + provider + "]" if provider else ""),
            "artifact",
        )
