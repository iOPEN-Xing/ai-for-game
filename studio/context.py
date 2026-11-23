"""Durable, explicitly scoped preferences and evidence supplied to each role."""

import json
import secrets
import zlib

from studio.domain.context_policy import FIELDS
from studio.domain.context_policy import bounded as bounded
from studio.domain.context_policy import clean_handoff as clean_handoff
from studio.domain.context_policy import evidence_for as evidence_for
from studio.domain.context_policy import memory_for as memory_for
from studio.domain.fingerprints import digest
from studio.infra.repositories import memory as memory_db

from .infra.store import Problem, db, encode, now, uid


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
        subject = digest(token)
        if memory_db.known_editor(con, subject):
            return subject
    token = secrets.token_hex(32)
    subject = digest(token)
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


def capture(con, game, cutoff=None):
    return {
        "id": uid(),
        "game": game,
        "captured": now(),
        "evidence_before": cutoff,
        "preferences": preferences(con, "project", game),
        "knowledge": memory_db.active_knowledge(con, game, cutoff),
        "decisions": memory_db.past_decisions(con, game, cutoff),
    }


def archive_input(run, node, visible, image_hashes, *, role, prompt):
    payload = {
        "input": visible,
        "images": image_hashes,
        "role": role,
        "prompt_sha256": digest(prompt),
    }
    fingerprint = digest(payload)
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
    if digest(payload) != fingerprint:
        raise Problem("归档输入摘要校验失败")
    prompt = memory_db.prompt_snapshot(con, run, node, payload.get("role"))
    if (
        "prompt_sha256" in payload
        and digest(prompt["prompt"]) != payload["prompt_sha256"]
    ):
        raise Problem("归档系统提示与本次输入不匹配")
    return {**payload, **prompt, "created": record["created"]}
