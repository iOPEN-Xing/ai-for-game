"""SQLite access for evidence. Transactions are owned by the calling use case."""

from studio.infra.store import need, one, rows


def recent_changes(con, game_id, match_game):
    return rows(
        con,
        "SELECT * FROM external_changes WHERE (? IS NULL OR game=?) ORDER BY at DESC LIMIT 20",
        game_id,
        match_game,
    )


def add_external_change(con, change_id, game_id, description, affects_measurement, at):
    con.execute(
        "INSERT INTO external_changes VALUES(?,?,?,?,?)",
        (change_id, game_id, description, affects_measurement, at),
    )


def selected_image(con, run_id, digest):
    return need(
        con,
        """SELECT b.content FROM reference_selections s JOIN reference_blobs b ON s.digest=b.digest
        WHERE s.run=? AND b.digest=? LIMIT 1""",
        run_id,
        digest,
    )


def knowledge_entries(con):
    return rows(
        con,
        "SELECT k.*,g.title FROM knowledge k JOIN games g ON g.id=k.game ORDER BY k.created DESC",
    )


def recent_decisions(con):
    return rows(
        con,
        "SELECT h.*,g.title FROM history h JOIN games g ON h.game=g.id ORDER BY h.id DESC LIMIT 80",
    )


def recent_feedback(con, revision_id, bundle, start, cutoff):
    return rows(
        con,
        """SELECT r.level, f.rating, COUNT(*) AS responses
        FROM feedback f JOIN rounds r ON r.id=f.round
        WHERE r.rev=? AND r.bundle=? AND r.preview=0 AND r.issued>=? AND r.issued<? AND f.at<?
        GROUP BY r.level,f.rating ORDER BY r.level,f.rating""",
        revision_id,
        bundle,
        start,
        cutoff,
        cutoff,
    )


def comparable_knowledge(con, cutoff):
    return rows(
        con,
        """SELECT k.id,k.game,k.text,k.grade,k.confidence,r.docs FROM knowledge k
        JOIN experiments e ON k.experiment=e.id JOIN revisions r ON r.id=e.treatment
        WHERE k.status='active' AND k.created<? ORDER BY k.confidence DESC,k.created DESC LIMIT 150""",
        cutoff,
    )


def history(con, game_id, cutoff):
    return rows(
        con,
        "SELECT id,rev,role,text,kind,at FROM history WHERE game=? AND at<? ORDER BY id DESC LIMIT 24",
        game_id,
        cutoff,
    )


def changes_in_window(con, game_id, start, end):
    return rows(
        con,
        "SELECT * FROM external_changes WHERE game=? AND at>=? AND at<? ORDER BY at DESC",
        game_id,
        start,
        end,
    )


def dead_ends(con, settled_before, game_id, created_before, rejected_before):
    return rows(
        con,
        """SELECT p.id,p.kind,json_extract(p.doc,'$.bet.title') title,
        coalesce(json_extract(e.result,'$.conclusion'),(SELECT text FROM history h WHERE h.game=p.game
        AND h.kind='review' AND instr(h.text,json_extract(p.doc,'$.bet.title'))>0 AND h.at<? ORDER BY h.id DESC LIMIT 1)) reason
        FROM proposals p LEFT JOIN experiments e ON e.proposal=p.id WHERE p.game=? AND p.created<?
        AND (p.status='rejected' OR (e.due<? AND json_extract(e.result,'$.attribution')='假设错'))
        ORDER BY p.created DESC LIMIT 12""",
        settled_before,
        game_id,
        created_before,
        rejected_before,
    )


def portfolio_titles(con, cutoff):
    return rows(
        con, "SELECT DISTINCT title FROM games WHERE created<? ORDER BY title", cutoff
    )


def portfolio_designs(con, cutoff):
    return rows(
        con,
        """SELECT g.title,json_extract(r.docs,'$.levels.game_type') family,
        substr(json_extract(r.docs,'$.gdd.core_loop'),1,450) core_loop FROM games g JOIN revisions r ON g.live=r.id
        WHERE g.created<? ORDER BY g.created DESC LIMIT 30""",
        cutoff,
    )


def peer_games(con, game_id, family):
    return rows(
        con,
        """SELECT g.id FROM games g JOIN revisions r ON r.id=g.live
        WHERE g.id!=? AND json_extract(r.docs,'$.levels.game_type')=?""",
        game_id,
        family,
    )


def changes_during_experiment(con, game_id, start, due):
    return rows(
        con,
        "SELECT * FROM external_changes WHERE game=? AND at>=? AND at<=? ORDER BY at",
        game_id,
        start,
        due,
    )


def propose_knowledge(
    con,
    entry_id,
    game_id,
    experiment_id,
    description,
    evidence,
    grade,
    confidence,
    cited,
    created,
):
    con.execute(
        "INSERT INTO knowledge VALUES(?,?,?,?,?,?,'pending',?,?,?)",
        (
            entry_id,
            game_id,
            experiment_id,
            description,
            evidence,
            grade,
            confidence,
            cited,
            created,
        ),
    )


def get_knowledge(con, entry_id):
    return need(con, "SELECT * FROM knowledge WHERE id=?", entry_id)


def set_knowledge_status(con, status, entry_id):
    con.execute("UPDATE knowledge SET status=? WHERE id=?", (status, entry_id))


def supersede_knowledge(con, entry_id, game_id):
    con.execute(
        "UPDATE knowledge SET status='superseded' WHERE id=? AND game=? AND status='active'",
        (entry_id, game_id),
    )


def reference_for_run(con, run, reference):
    return one(
        con,
        """SELECT b.digest,b.content FROM reference_selections s
                       JOIN reference_blobs b ON s.digest=b.digest WHERE s.run=? AND s.ref=?""",
        run,
        reference,
    )


def select_reference(con, run, reference, digest, content):
    con.execute("INSERT OR IGNORE INTO reference_blobs VALUES(?,?)", (digest, content))
    con.execute(
        "INSERT OR IGNORE INTO reference_selections VALUES(?,?,?)",
        (run, reference, digest),
    )
    return reference_for_run(con, run, reference)
