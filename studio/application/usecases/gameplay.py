"""Application operations for gameplay."""

import zlib

import quickjs

from studio.application.tools import cartridge
from studio.application.usecases.operations import experiments
from studio.domain import limits
from studio.domain.commands import Feedback, RoundEvent, RoundRequest
from studio.infra import bundles
from studio.infra.repositories import games as games_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.repositories import rounds as rounds_db
from studio.infra.store import Problem, db, encode, now, uid
from studio.settings import studio_day_start


def _assigned_version(con, gid, body):
    game = games_db.get(con, gid)
    rid, experiment, arm = (
        (body.preview, None, None)
        if body.preview
        else experiments.distribution(con, game, body.player)
    )
    revision = revisions_db.playable(con, rid, gid)
    if revision["stage"] not in ("quality", "ready", "released"):
        raise Problem("该版本尚未完成构建")
    return game, revision, experiment, arm


def open_round(gid, body: RoundRequest):
    if body.campaign and body.preview:
        raise Problem("验收试玩不能关联活动入口", 422)
    inline = body.delivery != "cached" or body.preview
    for _ in range(3):
        with db() as con:
            _, selected, _, _ = _assigned_version(con, gid, body)
            controls = revisions_db.play_controls(con, selected["id"])
        key = selected["bundle"]
        manifest = bundles.manifest(key)
        config = bundles.level_config(key)
        assets = cartridge.player_data(key) if inline else None
        # Re-resolve rollout and unlocks at insertion time. A concurrent publication
        # can change the target while the immutable files are being read.
        with db(True) as con:
            g, r, exp, arm = _assigned_version(con, gid, body)
            if (selected["id"], key) != (r["id"], r["bundle"]):
                continue
            action_label = (
                games_db.campaign_action(con, body.campaign, gid)["action_label"]
                if body.campaign
                else None
            )
            rid = r["id"]
            scope = rid if body.preview else experiments.progress_scope(con, rid, exp)
            preview = int(bool(body.preview))
            previous = (
                rounds_db.last_won_level(con, gid, scope, body.player, preview)["lv"]
                or 0
            )
            unlocked = min(previous + 1, manifest["count"])
            level = body.level or unlocked
            if level > manifest["count"] or (not preview and level > unlocked):
                raise Problem("关卡尚未解锁", 422)
            issued = now()
            day = studio_day_start(issued)
            if not preview and not rounds_db.charge_open(
                con, day, limits.OPEN_PER_STUDIO_DAY
            ):
                raise Problem(
                    "今日试玩容量已满",
                    429,
                    code="QUOTA_EXCEEDED",
                    retry_after=day + 86400 - issued,
                )
            token = uid()
            rounds_db.create(
                con,
                token,
                gid,
                rid,
                body.player,
                level,
                preview,
                exp,
                arm,
                key,
                issued,
                body.campaign,
                scope,
            )
        break
    else:
        raise Problem("试玩版本正在切换，请重新开局", 503, retry_after=1)
    info = {"title": g["title"], "controls": controls or manifest["controls"]}
    if config is not None:
        info["level_entry"] = config["entries"][level - 1]
    result = {
        "round": token,
        "version": r["num"],
        "level": level,
        "action_label": action_label,
    }
    if assets is None:
        return {
            **result,
            "game_url": f"/cartridges/v1/{r['bundle']}.json",
            "game_info": info,
        }
    return {**result, "game": {**assets, **info}}


def visit_activity(token):
    with db(True) as con:
        completed = rounds_db.activity(con, token)
        if completed["ended"] is None or completed["finish"] != "natural":
            raise Problem("自然完局后可打开活动页")
        rounds_db.record_action(con, now(), token)
    return completed["action_url"]


def event(token, body: RoundEvent):
    if body.event == "start":
        with db(True) as con:
            rounds_db.require_round(con, token)
            rounds_db.start(con, now(), token)
        return {"saved": True}
    with db() as con:
        r = rounds_db.get(con, token)
    if r["started"] is None:
        raise Problem("对局尚未开始")
    if r["ended"] is not None:
        return {"saved": True}
    replay = None
    state = {}
    if body.finish == "natural":
        inputs = body.model_dump(mode="json", exclude_none=True)["inputs"]
        encoded = encode(inputs).encode()
        if not inputs or len(encoded) > limits.PLAYER_BODY_BYTES:
            raise Problem("对局输入为空或超过回放容量", 422)
        try:
            state = cartridge.replay(r["bundle"], r["level"], inputs)
        except (ValueError, TypeError, KeyError, quickjs.JSException):
            raise Problem("对局输入未通过版本回放", 422) from None
        if (
            not state["done"]
            or bool(state["won"]) != body.won
            or int(state["score"]) != body.score
        ):
            raise Problem("上报结果与实际规则回放不符", 422)
        replay = zlib.compress(encoded)
    with db(True) as con:
        at = now()
        rounds_db.record_end(
            con,
            token=token,
            at=at,
            won=int(body.won and body.finish == "natural"),
            score=body.score if body.finish == "natural" else 0,
            finish=body.finish,
            replay=replay,
            state=state,
            day=studio_day_start(at),
            budget=limits.REPLAY_BYTES_PER_DAY,
        )
    return {"saved": True}


def show_hint(token):
    with db(True) as con:
        r = rounds_db.timing(con, token)
        if r["started"] is None or r["ended"] is not None:
            raise Problem("只能在游戏进行中查看提示")
        rounds_db.hint(con, now(), token)
    return {"saved": True}


def feedback(token, body: Feedback):
    with db(True) as con:
        r = rounds_db.completion(con, token)
        if r["ended"] is None:
            raise Problem("请在完局后评价")
        rounds_db.save_feedback(con, uid(), token, body.rating, body.comment, now())
    return {"saved": True}
