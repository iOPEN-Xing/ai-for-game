"""SQLite access for rounds. Transactions are owned by the calling use case."""

from studio.infra.store import need, one


def last_won_level(con, game_id, progress_scope, player_id, preview):
    return one(
        con,
        "SELECT MAX(level) lv FROM rounds WHERE game=? AND COALESCE(progress_scope,rev)=? AND player=? AND won=1 AND preview=?",
        game_id,
        progress_scope,
        player_id,
        preview,
    )


def create(
    con,
    round_id,
    game_id,
    revision_id,
    player_id,
    level,
    preview,
    experiment,
    arm,
    bundle,
    issued,
    campaign,
    scope,
):
    con.execute(
        """INSERT INTO rounds(id,game,rev,player,level,preview,experiment,arm,bundle,issued,campaign,progress_scope)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            round_id,
            game_id,
            revision_id,
            player_id,
            level,
            preview,
            experiment,
            arm,
            bundle,
            issued,
            campaign,
            scope,
        ),
    )


def activity(con, round_id):
    return need(
        con,
        """SELECT c.action_url,r.ended,r.finish FROM rounds r
        JOIN campaigns c ON c.id=r.campaign WHERE r.id=? AND r.preview=0 AND c.action_url IS NOT NULL""",
        round_id,
    )


def record_action(con, at, round_id):
    con.execute(
        "UPDATE rounds SET action_at=COALESCE(action_at,?) WHERE id=?", (at, round_id)
    )


def require_round(con, round_id):
    return need(con, "SELECT id FROM rounds WHERE id=?", round_id)


def start(con, at, round_id):
    con.execute(
        "UPDATE rounds SET started=COALESCE(started,?) WHERE id=?", (at, round_id)
    )


def get(con, round_id):
    return need(con, "SELECT * FROM rounds WHERE id=?", round_id)


def finish(con, ended, won, score, finish, replay, mistakes, rescues, slow, round_id):
    con.execute(
        "UPDATE rounds SET ended=?,won=?,score=?,finish=?,replay=?,mistakes=?,rescues=?,slow_round=? WHERE id=? AND ended IS NULL",
        (ended, won, score, finish, replay, mistakes, rescues, slow, round_id),
    )


def timing(con, round_id):
    return need(con, "SELECT started,ended FROM rounds WHERE id=?", round_id)


def hint(con, at, round_id):
    con.execute(
        "UPDATE rounds SET hint_at=COALESCE(hint_at,?) WHERE id=?", (at, round_id)
    )


def completion(con, round_id):
    return need(con, "SELECT ended FROM rounds WHERE id=?", round_id)


def save_feedback(con, feedback_id, round_id, rating, comment, at):
    con.execute(
        """INSERT INTO feedback VALUES(?,?,?,?,?) ON CONFLICT(round) DO UPDATE SET
        rating=excluded.rating,comment=excluded.comment,at=excluded.at""",
        (feedback_id, round_id, rating, comment, at),
    )
