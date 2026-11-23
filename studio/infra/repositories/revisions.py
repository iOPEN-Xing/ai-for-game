"""SQLite access for revisions. Transactions are owned by the calling use case."""

from studio.infra.store import need, one, rows


def require_published_bundle(con, bundle):
    return need(
        con,
        "SELECT 1 FROM revisions WHERE bundle=? AND stage='released' LIMIT 1",
        bundle,
    )


def notes(con, revision_id):
    return need(con, "SELECT game,notes,stage FROM revisions WHERE id=?", revision_id)


def update_notes(con, notes, revision_id):
    con.execute("UPDATE revisions SET notes=? WHERE id=?", (notes, revision_id))


def built_revision(con, revision_id):
    return need(
        con,
        "SELECT bundle,parent FROM revisions WHERE id=? AND bundle IS NOT NULL",
        revision_id,
    )


def find_bundle(con, revision_id):
    return one(con, "SELECT bundle FROM revisions WHERE id=?", revision_id)


def get(con, revision_id):
    return need(con, "SELECT * FROM revisions WHERE id=?", revision_id)


def rebuild_blueprint(con, seed, docs, revision_id):
    con.execute(
        "UPDATE revisions SET seed=?,docs=?,bundle=NULL,stage='build',serial=serial+1 WHERE id=?",
        (seed, docs, revision_id),
    )


def design(con, revision_id):
    return need(con, "SELECT docs FROM revisions WHERE id=?", revision_id)


def download(con, revision_id):
    return need(
        con,
        "SELECT bundle,num FROM revisions WHERE id=? AND bundle IS NOT NULL",
        revision_id,
    )


def playable(con, revision_id, game_id):
    return need(
        con,
        "SELECT id,bundle,num,stage,docs FROM revisions WHERE id=? AND game=? AND bundle IS NOT NULL",
        revision_id,
        game_id,
    )


def for_game(con, revision_id, game_id):
    return need(
        con, "SELECT * FROM revisions WHERE id=? AND game=?", revision_id, game_id
    )


def bundle(con, revision_id):
    return need(con, "SELECT bundle FROM revisions WHERE id=?", revision_id)


def supersede_proposal_drafts(con, proposal_id):
    con.execute(
        "UPDATE revisions SET stage='superseded',serial=serial+1 WHERE proposal=? AND stage NOT IN ('released','superseded')",
        (proposal_id,),
    )


def active_draft(con, game_id):
    return one(
        con,
        "SELECT id FROM revisions WHERE game=? AND stage NOT IN ('released','superseded')",
        game_id,
    )


def supersede_game_drafts(con, game_id):
    con.execute(
        "UPDATE revisions SET stage='superseded',serial=serial+1 WHERE game=? AND stage!='superseded'",
        (game_id,),
    )


def identity(con, revision_id):
    return need(con, "SELECT id,bundle FROM revisions WHERE id=?", revision_id)


def next_number(con, game_id):
    return one(
        con, "SELECT COALESCE(MAX(num),0)+1 n FROM revisions WHERE game=?", game_id
    )


def create(
    con,
    revision_id,
    game_id,
    number,
    stage,
    seed,
    parent,
    proposal,
    choice,
    notes,
    docs,
    created,
):
    con.execute(
        """INSERT INTO revisions(id,game,num,stage,seed,parent,proposal,choice,notes,docs,created)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            revision_id,
            game_id,
            number,
            stage,
            seed,
            parent,
            proposal,
            choice,
            notes,
            docs,
            created,
        ),
    )


def versions(con, game_id):
    return rows(
        con,
        "SELECT id,num,stage,created,bundle FROM revisions WHERE game=? ORDER BY num DESC",
        game_id,
    )


def preview_count(con, revision_id, bundle):
    return one(
        con,
        "SELECT count(*) AS n FROM rounds WHERE rev=? AND bundle=? AND preview=1 AND ended IS NOT NULL AND COALESCE(finish,'natural')='natural'",
        revision_id,
        bundle,
    )


def history(con, revision_id):
    return rows(con, "SELECT * FROM history WHERE rev=? ORDER BY id", revision_id)


def save_docs(con, docs, revision_id):
    con.execute("UPDATE revisions SET docs=? WHERE id=?", (docs, revision_id))


def choose(con, choice, revision_id):
    con.execute("UPDATE revisions SET choice=? WHERE id=?", (choice, revision_id))


def accepted_playtest(con, revision_id, bundle):
    return one(
        con,
        "SELECT 1 FROM rounds WHERE rev=? AND bundle=? AND preview=1 AND ended IS NOT NULL AND COALESCE(finish,'natural')='natural'",
        revision_id,
        bundle,
    )


def invalidate_build(con, docs, revision_id):
    con.execute(
        "UPDATE revisions SET docs=?,bundle=NULL WHERE id=?", (docs, revision_id)
    )


def clear_choice(con, revision_id):
    con.execute("UPDATE revisions SET choice=NULL WHERE id=?", (revision_id,))


def transition(con, stage, notes, revision_id, expected_serial, expected_stage):
    return (
        con.execute(
            "UPDATE revisions SET stage=?,serial=serial+1,notes=? WHERE id=? AND serial=? AND stage=?",
            (stage, notes, revision_id, expected_serial, expected_stage),
        ).rowcount
        == 1
    )


def checkpoint(con, docs, bundle, revision_id):
    con.execute(
        "UPDATE revisions SET docs=?,bundle=COALESCE(?,bundle) WHERE id=?",
        (docs, bundle, revision_id),
    )


def find_design(con, revision_id):
    return one(con, "SELECT docs FROM revisions WHERE id=?", revision_id)


def invalidate_design(con, docs, revision_id):
    con.execute(
        "UPDATE revisions SET docs=?,bundle=NULL WHERE id=? AND stage='design'",
        (docs, revision_id),
    )


def current_notes(con, revision_id):
    return need(con, "SELECT notes FROM revisions WHERE id=?", revision_id)


def stream_research(con, summary, revision_id):
    con.execute(
        "UPDATE revisions SET docs=json_set(docs,'$.research_draft',?) WHERE id=? AND stage='interpret'",
        (summary, revision_id),
    )


def delivery(con, revision_id):
    return need(con, "SELECT docs,bundle,stage FROM revisions WHERE id=?", revision_id)


def finish_stage(con, stage, revision_id):
    con.execute(
        "UPDATE revisions SET stage=?,serial=serial+1 WHERE id=?", (stage, revision_id)
    )


def invalidate_repair(con, docs, revision_id):
    con.execute(
        "UPDATE revisions SET docs=?,bundle=NULL WHERE id=? AND stage='build'",
        (docs, revision_id),
    )


def find_owner(con, revision_id):
    return one(con, "SELECT game FROM revisions WHERE id=?", revision_id)
