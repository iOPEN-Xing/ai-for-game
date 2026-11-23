"""SQLite access for evidence. Transactions are owned by the calling use case."""

import json

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
        """SELECT k.*,g.title, r.note AS review_note,r.at AS reviewed_at,r.replacement FROM knowledge k
        JOIN games g ON g.id=k.game LEFT JOIN knowledge_reviews r ON r.id=(
        SELECT id FROM knowledge_reviews WHERE entry=k.id ORDER BY at DESC,id DESC LIMIT 1)
        ORDER BY k.created DESC""",
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
        """SELECT k.id,k.game,k.text,k.grade,k.confidence,a.admitted,a.note AS review_note,
        json_extract(r.docs,'$.levels.game_type') AS family FROM knowledge k
        JOIN knowledge_admissions a ON a.entry=k.id
        JOIN experiments e ON k.experiment=e.id JOIN revisions r ON r.id=e.treatment
        WHERE a.admitted<? AND (a.withdrawn IS NULL OR a.withdrawn>=?)
        ORDER BY k.confidence DESC,k.created DESC,k.id LIMIT 150""",
        cutoff,
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


def record_dead_end(con, proposal, at, title, reason):
    con.execute(
        "INSERT INTO dead_end_records(proposal,at,title,reason) VALUES(?,?,?,?)",
        (proposal, at, title, reason),
    )


def dead_ends(con, game_id, cutoff):
    return rows(
        con,
        """SELECT p.id,p.kind,d.title,d.reason,d.at FROM dead_end_records d
        JOIN proposals p ON p.id=d.proposal WHERE p.game=? AND d.at<?
        ORDER BY d.at DESC,p.id LIMIT 12""",
        game_id,
        cutoff,
    )


def portfolio_titles(con, cutoff):
    return rows(
        con, "SELECT DISTINCT title FROM games WHERE created<? ORDER BY title", cutoff
    )


def portfolio_designs(con, cutoff):
    return rows(
        con,
        """SELECT g.title,json_extract(r.docs,'$.levels.game_type') AS family,
        substr(json_extract(r.docs,'$.gdd.core_loop'),1,450) AS core_loop FROM games g
        JOIN revisions r ON r.id=(SELECT h.rev FROM history h WHERE h.game=g.id AND h.kind='release'
        AND h.at<? ORDER BY h.at DESC,h.id DESC LIMIT 1)
        WHERE g.created<? ORDER BY g.created DESC,g.id LIMIT 30""",
        cutoff,
        cutoff,
    )


def peer_versions(con, revision_ids, game_id, family):
    return rows(
        con,
        """SELECT id FROM revisions WHERE id IN (SELECT value FROM json_each(?))
        AND game!=? AND json_extract(docs,'$.levels.game_type')=?""",
        json.dumps(revision_ids),
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


def record_knowledge_review(con, entry_id, status, at, note, replacement=None):
    con.execute("UPDATE knowledge SET status=? WHERE id=?", (status, entry_id))
    con.execute(
        """INSERT INTO knowledge_reviews(entry,status,at,note,replacement)
        VALUES(?,?,?,?,?)""",
        (entry_id, status, at, note, replacement),
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
    link_reference(con, run, reference, digest)
    return reference_for_run(con, run, reference)


def link_reference(con, run, reference, digest):
    con.execute(
        "INSERT OR IGNORE INTO reference_selections VALUES(?,?,?)",
        (run, reference, digest),
    )
    return need(
        con,
        "SELECT digest FROM reference_selections WHERE run=? AND ref=?",
        run,
        reference,
    )["digest"]
