"""SQLite access for memory. Transactions are owned by the calling use case."""

from studio.infra.store import need, one, rows


def preferences(con, scope, subject):
    return one(
        con,
        "SELECT version,settings FROM preferences WHERE scope=? AND subject=?",
        scope,
        subject,
    )


def save_preferences(con, scope, subject, version, settings):
    con.execute(
        """INSERT INTO preferences VALUES(?,?,?,?)
        ON CONFLICT(scope,subject) DO UPDATE SET version=excluded.version,settings=excluded.settings""",
        (scope, subject, version, settings),
    )


def known_editor(con, subject):
    return one(
        con, "SELECT 1 FROM preferences WHERE scope='editor' AND subject=?", subject
    )


def create_editor(con, subject):
    con.execute("INSERT INTO preferences VALUES('editor',?,0,'{}')", (subject,))


def active_knowledge(con, game_id):
    return rows(
        con,
        """SELECT id,text,grade,confidence FROM knowledge WHERE game=? AND status='active'
        ORDER BY confidence DESC,created DESC LIMIT 8""",
        game_id,
    )


def past_decisions(con, game_id):
    return rows(
        con,
        """SELECT id,rev,role,substr(text,1,650) text,at FROM history
        WHERE game=? AND kind IN ('review','comment','gate','preference') ORDER BY id DESC LIMIT 8""",
        game_id,
    )


def save_input(con, run_id, node, fingerprint, payload, created):
    con.execute(
        "INSERT OR IGNORE INTO agent_inputs VALUES(?,?,?,?,?)",
        (run_id, node, fingerprint, payload, created),
    )


def input_snapshot(con, run_id, node, fingerprint):
    return need(
        con,
        "SELECT payload,created FROM agent_inputs WHERE run=? AND node=? AND context_hash=?",
        run_id,
        node,
        fingerprint,
    )


def prompt_snapshot(con, run_id, node):
    return need(
        con,
        "SELECT role,prompt FROM agent_prompts WHERE run=? AND node=?",
        run_id,
        node,
    )
