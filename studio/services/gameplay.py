"""Application operations for gameplay."""

import json
import zlib

import quickjs

from studio import cartridge
from studio.domain.commands import Feedback, RoundEvent, RoundRequest
from studio.infra.repositories import games as games_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.repositories import rounds as rounds_db
from studio.infra.store import Problem, db, encode, now, uid
from studio.services import experiments


def open_round(gid, body: RoundRequest):
    with db(True) as con:
        g = games_db.get(con, gid)
        action_label = None
        if body.campaign:
            if body.preview:
                raise Problem("验收试玩不能关联活动入口", 422)
            action_label = games_db.campaign_action(con, body.campaign, gid)[
                "action_label"
            ]
        if body.preview:
            rid, exp, arm = body.preview, None, None
        else:
            rid, exp, arm = experiments.distribution(con, g, body.player)
        r = revisions_db.playable(con, rid, gid)
        if r["stage"] not in ("quality", "ready", "released"):
            raise Problem("该版本尚未完成构建")
        manifest = json.loads(
            (cartridge.folder(r["bundle"]) / "manifest.json").read_bytes()
        )
        scope = rid if body.preview else experiments.progress_scope(con, rid, exp)
        previous = (
            rounds_db.last_won_level(
                con, gid, scope, body.player, int(bool(body.preview))
            )["lv"]
            or 0
        )
        unlocked = min(previous + 1, manifest["count"])
        level = body.level or unlocked
        if level > manifest["count"] or (not body.preview and level > unlocked):
            raise Problem("关卡尚未解锁", 422)
        token = uid()
        rounds_db.create(
            con,
            token,
            gid,
            rid,
            body.player,
            level,
            int(bool(body.preview)),
            exp,
            arm,
            r["bundle"],
            now(),
            body.campaign,
            scope,
        )
    info = {
        "title": g["title"],
        "controls": json.loads(r["docs"])
        .get("quality_report", {})
        .get("quick_start", manifest["controls"]),
    }
    result = {
        "round": token,
        "version": r["num"],
        "level": level,
        "action_label": action_label,
    }
    if body.delivery == "cached" and not body.preview:
        return {
            **result,
            "game_url": f"/cartridges/v1/{r['bundle']}.json",
            "game_info": info,
        }
    return {**result, "game": {**cartridge.player_data(r["bundle"]), **info}}


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
    inputs = [i.model_dump(exclude_none=True) for i in body.inputs]
    state = {}
    if body.finish == "natural":
        if not inputs or any(
            (
                e["type"] in ("tap", "press", "move", "release")
                and not {"x", "y"} <= e.keys()
            )
            or (e["type"] == "tick" and "dt" not in e)
            or (e["type"] in ("key", "keyup") and "key" not in e)
            for e in inputs
        ):
            raise Problem("缺少有效的试玩输入", 422)
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
    replay = zlib.compress(encode(inputs).encode()) if inputs else None
    with db(True) as con:
        rounds_db.finish(
            con,
            now(),
            int(body.won and body.finish == "natural"),
            body.score,
            body.finish,
            replay,
            state.get("mistakes"),
            state.get("rescues"),
            state.get("slow_round"),
            token,
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
