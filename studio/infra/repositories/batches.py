"""SQLite access for batches. Transactions are owned by the calling use case."""

from studio.infra.store import need, one, rows


def recent(con):
    return rows(con, "SELECT day,status,at FROM batches ORDER BY day DESC LIMIT 7")


def get(con, day):
    return need(con, "SELECT * FROM batches WHERE day=?", day)


def requeue_for_proposal(con, proposal_id):
    con.execute(
        "UPDATE batches SET status='queued' WHERE day=(SELECT day FROM proposals WHERE id=?) AND status='needs_review'",
        (proposal_id,),
    )


def find(con, day):
    return one(con, "SELECT * FROM batches WHERE day=?", day)


def releases_in_window(con, start, end):
    return rows(
        con,
        "SELECT id,game,rev,at FROM history WHERE kind='release' AND at>=? AND at<?",
        start,
        end,
    )


def launch_reconciliation(con, launched_before, created_before, published_before):
    return rows(
        con,
        """SELECT p.id proposal,r.game,r.id rev,g.live,g.metric,r.bundle,p.doc,
        (SELECT MIN(at) FROM history h WHERE h.rev=r.id AND h.kind='release') launch_at,
        (SELECT MIN(issued) FROM rounds t WHERE t.rev=r.id AND t.preview=0 AND t.issued<?) first_exposure
        FROM proposals p JOIN revisions r ON r.proposal=p.id JOIN games g ON g.id=r.game
        WHERE p.kind='new_game' AND p.status='delivered' AND r.created<? AND launch_at<?""",
        launched_before,
        created_before,
        published_before,
    )


def save(con, day, status, doc, at):
    con.execute(
        "INSERT OR REPLACE INTO batches VALUES(?,?,?,?)", (day, status, doc, at)
    )


def fail(con, day, doc, at):
    con.execute("INSERT OR REPLACE INTO batches VALUES(?,'failed',?,?)", (day, doc, at))


def queued(con):
    return rows(con, "SELECT * FROM batches WHERE status='queued'")


def complete(con, day):
    con.execute("UPDATE batches SET status='complete' WHERE day=?", (day,))


def require_review(con, day):
    con.execute("UPDATE batches SET status='needs_review' WHERE day=?", (day,))


def last_successful_day(con):
    return one(con, "SELECT MAX(day) day FROM batches WHERE status!='failed'")


def retryable_days(con):
    return rows(
        con, "SELECT day FROM batches WHERE status='failed' ORDER BY day LIMIT 4"
    )
