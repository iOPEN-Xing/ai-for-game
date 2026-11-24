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
    return one(
        con,
        """SELECT a.model,a.manifest,r.routes FROM agent_runs a
           LEFT JOIN agent_run_skill_routes r ON r.run=a.id WHERE a.id=?""",
        run_id,
    )


def pin(con, run_id, model, manifest, routes, skills, at):
    con.executemany(
        "INSERT OR IGNORE INTO skill_revisions VALUES(:name,:revision,:description,:body)",
        skills,
    )
    created = con.execute(
        "INSERT OR IGNORE INTO agent_runs VALUES(?,?,?,?)",
        (run_id, model, manifest, at),
    )
    if created.rowcount:
        con.execute(
            "INSERT INTO agent_run_skill_routes(run,routes) VALUES(?,?)",
            (run_id, routes),
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
