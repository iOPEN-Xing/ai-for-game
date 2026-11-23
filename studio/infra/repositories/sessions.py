"""Opaque, revocable team sessions. Only a keyed digest is persisted."""


def issue(con, digest, expires):
    con.execute(
        "INSERT INTO team_sessions(digest, expires) VALUES(?,?)", (digest, expires)
    )


def valid(con, digest, at):
    return (
        con.execute(
            "SELECT 1 FROM team_sessions WHERE digest=? AND expires>?", (digest, at)
        ).fetchone()
        is not None
    )


def revoke(con, digest):
    con.execute("DELETE FROM team_sessions WHERE digest=?", (digest,))
