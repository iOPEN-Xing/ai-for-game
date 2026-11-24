"""A reconnecting subscriber reads only the latest private revision snapshot."""

from studio.domain.fingerprints import digest
from studio.domain.revision import STEPS
from studio.infra.repositories import revisions, sessions
from studio.infra.store import Problem, db, now


def snapshot(revision, session):
    with db() as con:
        if session and not sessions.valid(con, session, now()):
            raise Problem("制作台会话已结束", 401)
        state = revisions.progress(con, revision)
    state["terminal"] = state["stage"] not in STEPS or state["job_state"] == "failed"
    return digest(state), state
