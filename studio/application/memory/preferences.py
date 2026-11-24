"""Versioned editor/project preferences and persistent editor identity."""

import json
import secrets

from studio.application.memory.projection import FIELDS
from studio.domain.fingerprints import digest
from studio.infra.repositories import memory as memory_db
from studio.infra.store import Problem, encode


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


def resolve_editor(con, token):
    """Return the editor's subject and a token only when issuing an identity."""
    if len(token) == 64 and token.isalnum():
        subject = digest(token)
        if memory_db.known_editor(con, subject):
            return subject, None
    token = secrets.token_hex(32)
    subject = digest(token)
    memory_db.create_editor(con, subject)
    return subject, token
