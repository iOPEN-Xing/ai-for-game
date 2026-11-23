"""Pinned role instructions and prompts for resumable AgentScope runs."""

from studio.infra.store import need, one


def instruction(con, name, revision):
    return need(
        con,
        """SELECT name,description,body,revision FROM skill_revisions
                        WHERE name=? AND revision=?""",
        name,
        revision,
    )


def binding(con, run_id):
    return one(con, "SELECT model,manifest FROM agent_runs WHERE id=?", run_id)


def pin(con, run_id, model, manifest, skills, at):
    con.executemany(
        "INSERT OR IGNORE INTO skill_revisions VALUES(:name,:revision,:description,:body)",
        skills,
    )
    con.execute(
        "INSERT OR IGNORE INTO agent_runs VALUES(?,?,?,?)",
        (run_id, model, manifest, at),
    )
    return binding(con, run_id)


def bind_prompt(con, run_id, role, node, signature, prompt):
    con.execute(
        "INSERT OR IGNORE INTO agent_prompts VALUES(?,?,?,?,?)",
        (run_id, role, node, signature, prompt),
    )
    return need(
        con,
        """SELECT schema_hash,prompt FROM agent_prompts
                        WHERE run=? AND role=? AND node=?""",
        run_id,
        role,
        node,
    )
