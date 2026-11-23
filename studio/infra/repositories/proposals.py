"""SQLite access for proposals. Transactions are owned by the calling use case."""

from studio.infra.store import need, one, rows


def get(con, proposal_id):
    return need(con, "SELECT * FROM proposals WHERE id=?", proposal_id)


def other_iteration(con, proposal_id, game_id):
    return one(
        con,
        """SELECT id FROM proposals WHERE id!=? AND game=? AND kind='iteration'
        AND status IN ('analyzing','review','production','experiment')""",
        proposal_id,
        game_id,
    )


def archive(con, proposal_id, evidence, doc, reason, at):
    con.execute(
        "INSERT INTO proposal_history(proposal,evidence,doc,reason,at) VALUES(?,?,?,?,?)",
        (proposal_id, evidence, doc, reason, at),
    )


def replace_evidence(con, evidence, base, proposal_id):
    con.execute(
        "UPDATE proposals SET doc='{}',evidence=?,base=? WHERE id=?",
        (evidence, base, proposal_id),
    )


def resume(con, proposal_id):
    con.execute("UPDATE proposals SET status='analyzing' WHERE id=?", (proposal_id,))


def active_iteration(con, game_id, kind):
    return one(
        con,
        """SELECT id FROM proposals WHERE game=? AND kind=?
        AND status IN ('analyzing','review','production','experiment')""",
        game_id,
        kind,
    )


def for_batch(con, game_id, day, kind):
    return one(
        con,
        "SELECT id FROM proposals WHERE game=? AND day=? AND kind=?",
        game_id,
        day,
        kind,
    )


def create(con, proposal_id, game_id, base, kind, day, evidence, created):
    con.execute(
        "INSERT INTO proposals VALUES(?,?,?,?,?,'analyzing','{}',?,?)",
        (proposal_id, game_id, base, kind, day, evidence, created),
    )


def find(con, proposal_id):
    return one(con, "SELECT * FROM proposals WHERE id=?", proposal_id)


def start_experiment(con, proposal_id):
    con.execute("UPDATE proposals SET status='experiment' WHERE id=?", (proposal_id,))


def delivered(con, proposal_id):
    con.execute("UPDATE proposals SET status='delivered' WHERE id=?", (proposal_id,))


def rebase(con, base, evidence, proposal_id):
    con.execute(
        "UPDATE proposals SET base=?,evidence=? WHERE id=?",
        (base, evidence, proposal_id),
    )


def save_evidence(con, evidence, proposal_id):
    con.execute("UPDATE proposals SET evidence=? WHERE id=?", (evidence, proposal_id))


def save_checkpoint(con, doc, proposal_id):
    con.execute(
        "UPDATE proposals SET doc=? WHERE id=? AND status='analyzing'",
        (doc, proposal_id),
    )


def finish_analysis(con, status, proposal_id):
    con.execute(
        "UPDATE proposals SET status=? WHERE id=? AND status='analyzing'",
        (status, proposal_id),
    )


def has_prior_evidence(con, proposal_id):
    return one(con, "SELECT 1 FROM proposal_history WHERE proposal=?", proposal_id)


def set_status(con, status, proposal_id):
    con.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal_id))


def settled(con, proposal_id):
    con.execute("UPDATE proposals SET status='settled' WHERE id=?", (proposal_id,))


def outcome(con, proposal_id):
    return one(
        con, "SELECT status,kind,doc,evidence FROM proposals WHERE id=?", proposal_id
    )


def decision(con, proposal_id):
    return need(con, "SELECT doc FROM proposals WHERE id=?", proposal_id)


def find_decision(con, proposal_id):
    return one(con, "SELECT doc FROM proposals WHERE id=?", proposal_id)


def approval(con, proposal_id):
    return need(con, "SELECT doc,evidence FROM proposals WHERE id=?", proposal_id)


def fail_analysis(con, proposal_id):
    con.execute(
        "UPDATE proposals SET status='failed' WHERE id=? AND status='analyzing'",
        (proposal_id,),
    )


def require_evidence(con, proposal_id):
    con.execute(
        "UPDATE proposals SET status='needs_evidence' WHERE id=?", (proposal_id,)
    )


def fail(con, proposal_id):
    con.execute("UPDATE proposals SET status='failed' WHERE id=?", (proposal_id,))


def proposal_summaries(con, game_id=None):
    return rows(
        con,
        "SELECT p.id,p.game,p.kind,p.status,p.created,p.day,p.doc,g.title FROM proposals p JOIN games g ON g.id=p.game WHERE (? IS NULL OR p.game=?) ORDER BY p.created DESC,p.rowid DESC",
        game_id,
        game_id,
    )


def count_created_since(con, start) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM proposals WHERE created>=?", (start,)
    ).fetchone()[0]
