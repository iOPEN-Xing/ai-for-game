"""SQLite access for experiments. Transactions are owned by the calling use case."""

from studio.infra.store import need, one, rows


def undecided(con, game_id):
    return one(
        con,
        "SELECT 1 FROM experiments WHERE game=? AND status IN ('running','decide')",
        game_id,
    )


def save_scope(con, experiment_id, scope, policy):
    con.execute(
        "INSERT INTO experiment_progress VALUES(?,?,?)", (experiment_id, scope, policy)
    )


def create(con, experiment_id, game_id, proposal_id, control, treatment, started, due):
    con.execute(
        "INSERT INTO experiments VALUES(?,?,?,?,?,?,?,'running',NULL)",
        (experiment_id, game_id, proposal_id, control, treatment, started, due),
    )


def current(con, game_id, at):
    return one(
        con,
        "SELECT * FROM experiments WHERE game=? AND status='running' AND due>?",
        game_id,
        at,
    )


def scope(con, experiment_id):
    return one(
        con, "SELECT scope FROM experiment_progress WHERE experiment=?", experiment_id
    )


def active_control_scope(con, revision_id):
    return one(
        con,
        """SELECT p.scope FROM experiment_progress p JOIN experiments e ON e.id=p.experiment
        WHERE e.control=? AND e.status IN ('running','decide')""",
        revision_id,
    )


def revision_scope(con, revision_id):
    return one(con, "SELECT scope FROM revision_progress WHERE rev=?", revision_id)


def save_result(con, result, experiment_id):
    con.execute(
        "UPDATE experiments SET status='decide',result=? WHERE id=?",
        (result, experiment_id),
    )


def get(con, experiment_id):
    return need(con, "SELECT * FROM experiments WHERE id=?", experiment_id)


def record_progress(con, revision_id, scope):
    con.execute(
        "INSERT OR REPLACE INTO revision_progress VALUES(?,?)", (revision_id, scope)
    )


def finish(con, status, experiment_id):
    con.execute("UPDATE experiments SET status=? WHERE id=?", (status, experiment_id))


def due(con, at):
    return rows(con, "SELECT * FROM experiments WHERE status='running' AND due<=?", at)


def for_dashboard(con, game_id=None):
    return rows(
        con,
        "SELECT e.*,g.title FROM experiments e JOIN games g ON e.game=g.id WHERE (? IS NULL OR e.game=?) ORDER BY started DESC",
        game_id,
        game_id,
    )
