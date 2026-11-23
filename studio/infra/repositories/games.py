"""SQLite access for games. Transactions are owned by the calling use case."""

from studio.infra.store import need, one, rows


def require_published(con, game_id):
    return need(con, "SELECT id FROM games WHERE id=? AND live IS NOT NULL", game_id)


def studio_overview(con):
    return rows(
        con,
        """SELECT g.*,r.id rev,r.num,r.stage,r.bundle,
        json_extract(r.docs,'$.levels.game_type') AS family,
           (SELECT j.state FROM jobs j WHERE j.kind='production' AND j.target=r.id AND j.stage=r.stage) AS job_state
           FROM games g JOIN revisions r
        ON r.id=(SELECT id FROM revisions WHERE game=g.id ORDER BY num DESC LIMIT 1)
        ORDER BY g.created DESC,g.rowid DESC""",
    )


def formal_starts(con):
    return one(
        con, "SELECT count(*) n FROM rounds WHERE preview=0 AND started IS NOT NULL"
    )


def proposals_for_review(con):
    return one(con, "SELECT COUNT(*) n FROM proposals WHERE status='review'")


def pending_knowledge(con):
    return one(con, "SELECT COUNT(*) n FROM knowledge WHERE status='pending'")


def pending_experiments(con):
    return one(con, "SELECT COUNT(*) n FROM experiments WHERE status='decide'")


def find_request(con, request_id):
    return one(con, "SELECT * FROM game_requests WHERE request_id=?", request_id)


def save_request(con, request_id, fingerprint, game_id, revision_id):
    con.execute(
        "INSERT INTO game_requests VALUES(?,?,?,?)",
        (request_id, fingerprint, game_id, revision_id),
    )


def require_game(con, game_id):
    return need(con, "SELECT id FROM games WHERE id=?", game_id)


def live_version(con, game_id):
    return need(con, "SELECT live FROM games WHERE id=?", game_id)


def find_campaign(con, game_id, name):
    return one(con, "SELECT * FROM campaigns WHERE game=? AND name=?", game_id, name)


def create_campaign(con, campaign_id, game_id, name, label, url, created):
    con.execute(
        "INSERT INTO campaigns(id,game,name,action_label,action_url,created) VALUES(?,?,?,?,?,?)",
        (campaign_id, game_id, name, label, url, created),
    )


def get(con, game_id):
    return need(con, "SELECT * FROM games WHERE id=?", game_id)


def campaign_action(con, campaign_id, game_id):
    return need(
        con,
        "SELECT action_label FROM campaigns WHERE id=? AND game=?",
        campaign_id,
        game_id,
    )


def find_live_game(con, game_id):
    return need(con, "SELECT id,live FROM games WHERE id=?", game_id)


def list_goals(con):
    return rows(con, "SELECT id,title,metric,bounds FROM games ORDER BY created DESC")


def publish(con, revision_id, game_id):
    con.execute("UPDATE games SET live=? WHERE id=?", (revision_id, game_id))


def from_proposal(con, proposal_id):
    return one(
        con,
        "SELECT g.id,g.live FROM games g JOIN revisions r ON r.game=g.id WHERE r.proposal=? LIMIT 1",
        proposal_id,
    )


def update_brief(con, title, brief, game_id):
    con.execute("UPDATE games SET title=?,brief=? WHERE id=?", (title, brief, game_id))


def live_metrics(con):
    return rows(con, "SELECT id,metric FROM games WHERE live IS NOT NULL")


def create(con, game_id, title, brief, metric, bounds, created):
    con.execute(
        "INSERT INTO games VALUES(?,?,?,?,?,NULL,?)",
        (game_id, title, brief, metric, bounds, created),
    )


def campaigns(con, game_id=None):
    return rows(
        con,
        "SELECT id,game,name,action_label FROM campaigns WHERE (? IS NULL OR game=?) ORDER BY created DESC,rowid DESC",
        game_id,
        game_id,
    )


def count(con) -> int:
    return con.execute("SELECT COUNT(*) FROM games").fetchone()[0]


def campaign_count(con, game_id) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM campaigns WHERE game=?", (game_id,)
    ).fetchone()[0]
