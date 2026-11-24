"""Freeze project memory and archive the exact input and prompt used by a node."""

import json
import zlib

from studio.application.memory.preferences import preferences
from studio.domain.fingerprints import digest
from studio.infra.repositories import memory as memory_db
from studio.infra.store import Problem, db, encode, now, uid


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
