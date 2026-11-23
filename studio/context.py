"""Durable, explicitly scoped preferences and evidence supplied to each role."""

import json
import secrets
import zlib

from studio.domain.deliberation import feedback_summary, visible_sources
from studio.infra.repositories import memory as memory_db

from . import skillbook
from .infra.store import Problem, db, encode, now, uid

FIELDS = ("audience", "visual_style", "controls", "audio", "avoid")


def preferences(con, scope, subject):
    record = memory_db.preferences(con, scope, subject)
    if not record:
        return {"version": 0, "values": {}}
    return {"version": record["version"], "values": json.loads(record["settings"])}


def save_preferences(con, scope, subject, expected, values):
    if preferences(con, scope, subject)["version"] != expected:
        raise Problem("偏好已在其他页面更新，请刷新后再保存")
    values = {k: v.strip() for k, v in values.items() if k in FIELDS and v.strip()}
    memory_db.save_preferences(con, scope, subject, expected + 1, encode(values))
    return {"version": expected + 1, "values": values}


def editor(con, request, response):
    token = request.cookies.get("loop_editor", "")
    if len(token) == 64 and token.isalnum():
        subject = skillbook.digest(token)
        if memory_db.known_editor(con, subject):
            return subject
    token = secrets.token_hex(32)
    subject = skillbook.digest(token)
    memory_db.create_editor(con, subject)
    secure = request.url.scheme == "https"
    response.set_cookie(
        "loop_editor",
        token,
        max_age=31536000,
        httponly=True,
        secure=secure,
        samesite="strict",
    )
    return subject


def capture(con, game):
    return {
        "id": uid(),
        "game": game,
        "captured": now(),
        "preferences": preferences(con, "project", game),
        "knowledge": memory_db.active_knowledge(con, game),
        "decisions": memory_db.past_decisions(con, game),
    }


PREFERENCE_FIELDS = {
    "ArtDesigner": ("audience", "visual_style", "audio", "avoid"),
    "LevelCoder": ("audience", "controls", "avoid"),
    "LevelDesigner": ("audience", "controls", "avoid"),
    "Analyst": ("audience", "avoid"),
    "Engineer": ("controls", "audio", "avoid"),
}


def memory_for(role, saved):
    prefs = saved["preferences"]
    return {
        "project": saved["game"],
        "preference_version": prefs["version"],
        "preferences": {
            k: prefs["values"][k]
            for k in PREFERENCE_FIELDS.get(role, FIELDS)
            if k in prefs["values"]
        },
        "approved_knowledge": saved["knowledge"],
        "past_decisions": saved["decisions"],
    }


def evidence_for(role, frozen):
    view = {
        k: v
        for k, v in frozen.items()
        if k
        not in ("memory", "game_code", "level_code", "probes", "level_pack", "assets")
    }
    sources = visible_sources(role, frozen)
    if role in ("Engineer", "Reviewer"):
        view.update(game_code=frozen["game_code"], level_code=frozen["level_code"])
    # Reconstruct safe feedback aggregates when resuming pre-migration evidence snapshots.
    view["feedback"] = feedback_summary(frozen.get("feedback", []))
    view["sources"] = sources
    pack = frozen["level_pack"]
    view["level_pack"] = {k: pack[k] for k in ("seed", "mode", "family")}
    if role == "Engineer":
        view["level_pack"]["levels"] = pack["levels"]
    else:
        view["level_pack"]["levels"] = [
            {k: v for k, v in lv.items() if isinstance(v, (str, int, float, bool))}
            for lv in pack["levels"]
        ]
    view["probes"] = {
        key: {
            "observed": p["observed"],
            "input_count": len(p["inputs"]),
            "input_sha256": skillbook.digest(p["inputs"]),
        }
        for key, p in frozen["probes"].items()
    }
    view["assets"] = {
        k: v
        for k, v in frozen["assets"].items()
        if k in ("style", "palette", "sprites", "audio")
    }
    return view


def clean_handoff(value):
    if isinstance(value, dict):
        return {k: clean_handoff(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [clean_handoff(v) for v in value]
    return value


def bounded(visible, limit=160_000):
    """Keep complete current evidence and code. Trim older comparisons first."""

    def size():
        return len(encode(visible).encode())

    if size() <= limit:
        return visible
    evidence = visible.get("evidence", {})
    omissions = {}
    for key in (
        "portfolio_designs",
        "historical_versions",
        "peers",
        "history",
        "external_changes",
    ):
        items = evidence.get(key, [])
        if len(items) > 3:
            omissions[key] = {"retained": 3, "available": len(items)}
            evidence[key] = items[:3]
        if size() + 800 <= limit:
            break
    if omissions:
        visible["context_sampling"] = omissions
    if size() > limit:
        raise ValueError("当前必要证据和源码超过单次输入预算，请拆小任务后重新发起")
    return visible


def archive_input(run, node, visible, image_hashes):
    payload = {"input": visible, "images": image_hashes}
    fingerprint = skillbook.digest(payload)
    if run:
        with db(True) as con:
            memory_db.save_input(
                con,
                run,
                node,
                fingerprint,
                zlib.compress(encode(payload).encode()),
                now(),
            )
    return fingerprint


def inspect_input(con, run, node, fingerprint):
    record = memory_db.input_snapshot(con, run, node, fingerprint)
    payload = json.loads(zlib.decompress(record["payload"]))
    if skillbook.digest(payload) != fingerprint:
        raise Problem("归档输入摘要校验失败")
    prompt = memory_db.prompt_snapshot(con, run, node)
    return {**payload, **prompt, "created": record["created"]}
