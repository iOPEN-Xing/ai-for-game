"""Free expired intake records without changing historical reporting denominators."""

from studio.domain.limits import REPLAY_RETENTION_DAYS
from studio.infra.store import db


def sweep(at, batch_size=500):
    # Release the writer between batches so a delayed worker can catch up without
    # monopolising the player database. Keep scalar results for cohort/experiment analysis.
    cutoff = at - REPLAY_RETENTION_DAYS * 86400
    for _ in range(48):
        with db(write=True) as con:
            limits = con.execute(
                "DELETE FROM request_limits WHERE rowid IN (SELECT rowid FROM request_limits WHERE expires<=? ORDER BY expires LIMIT ?)",
                (at, batch_size),
            ).rowcount
            sessions = con.execute(
                "DELETE FROM team_sessions WHERE rowid IN (SELECT rowid FROM team_sessions WHERE expires<=? ORDER BY expires LIMIT ?)",
                (at, batch_size),
            ).rowcount
            replays = con.execute(
                "UPDATE rounds SET replay=NULL WHERE rowid IN (SELECT rowid FROM rounds WHERE replay IS NOT NULL AND ended<=? ORDER BY ended LIMIT ?)",
                (cutoff, batch_size),
            ).rowcount
        if max(limits, sessions, replays) < batch_size:
            break
