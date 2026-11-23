"""Persistent, atomic request counters for the public player gateway and team login."""

import hashlib

from .store import db, now


def consume(limits: list[tuple[str, str, int, int]]) -> int:
    """Return retry delay, or debit all applicable counters in one transaction."""
    if not limits:
        return 0
    current = now()
    pending = []
    with db(write=True) as con:
        con.execute("DELETE FROM request_limits WHERE expires<=?", (current,))
        for scope, identity, maximum, seconds in limits:
            subject = hashlib.sha256(identity.encode()).hexdigest()
            row = con.execute(
                "SELECT used, expires FROM request_limits WHERE scope=? AND subject=?",
                (scope, subject),
            ).fetchone()
            if row and row["used"] >= maximum:
                return max(1, row["expires"] - current)
            pending.append((scope, subject, current + seconds))
        con.executemany(
            """INSERT INTO request_limits(scope, subject, expires, used) VALUES(?,?,?,1)
               ON CONFLICT(scope,subject) DO UPDATE SET used=used+1""",
            pending,
        )
    return 0
