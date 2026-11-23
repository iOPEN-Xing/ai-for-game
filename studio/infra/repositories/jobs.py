"""SQLite access for jobs. Transactions are owned by the calling use case."""

from studio.infra.store import need, one, rows


def production_status(con, revision_id, stage):
    return one(
        con,
        "SELECT state,stage,error,attempts FROM jobs WHERE kind='production' AND target=? AND stage=?",
        revision_id,
        stage,
    )


def latest_production(con, revision_id):
    return one(
        con,
        "SELECT state,stage,error,attempts FROM jobs WHERE kind='production' AND target=? ORDER BY heartbeat DESC,rowid DESC LIMIT 1",
        revision_id,
    )


def failed_production(con, revision_id, stage):
    return one(
        con,
        "SELECT 1 FROM jobs WHERE kind='production' AND target=? AND stage=? AND state='failed'",
        revision_id,
        stage,
    )


def production(con, revision_id, stage):
    return need(
        con,
        "SELECT * FROM jobs WHERE kind='production' AND target=? AND stage=?",
        revision_id,
        stage,
    )


def next_in_queue(con):
    return one(
        con,
        """SELECT * FROM jobs WHERE state='queued'
               AND (kind!='analysis' OR NOT EXISTS
                  (SELECT 1 FROM jobs WHERE kind='analysis' AND state='running'))
               ORDER BY created,rowid LIMIT 1""",
    )


def start(con, at, job_id):
    con.execute(
        "UPDATE jobs SET state='running',attempts=attempts+1,heartbeat=? WHERE id=?",
        (at, job_id),
    )


def heartbeat(con, at, job_id):
    con.execute(
        "UPDATE jobs SET heartbeat=? WHERE id=? AND state='running'", (at, job_id)
    )


def complete(con, job_id):
    con.execute("UPDATE jobs SET state='done',error=NULL WHERE id=?", (job_id,))


def retry_running(con, job_id):
    con.execute(
        "UPDATE jobs SET state='queued' WHERE id=? AND state='running'", (job_id,)
    )


def record_failure(con, state, error, job_id):
    con.execute("UPDATE jobs SET state=?,error=? WHERE id=?", (state, error, job_id))


def active_revisions(con):
    return rows(
        con,
        "SELECT id,stage FROM revisions WHERE stage IN ('research','interpret','design','build')",
    )


def pending_analyses(con):
    return rows(
        con,
        "SELECT id,status,kind,doc,evidence FROM proposals WHERE status IN ('analyzing','review')",
    )


def find(con, kind, target, stage):
    return one(
        con,
        "SELECT * FROM jobs WHERE kind=? AND target=? AND stage=?",
        kind,
        target,
        stage,
    )


def recover(con, state, reason, job_id):
    con.execute(
        "UPDATE jobs SET state=?,recoveries=recoveries+1,error=? WHERE id=?",
        (state, reason, job_id),
    )


def recover_stale(con, cutoff):
    con.execute(
        "UPDATE jobs SET state='queued' WHERE state='running' AND heartbeat<?",
        (cutoff,),
    )


def recover_owned(con):
    con.execute("UPDATE jobs SET state='queued' WHERE state='running'")
