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
        for scope, identity, maximum, seconds in limits:
            subject = hashlib.sha256(identity.encode()).hexdigest()
            row = con.execute(
                "SELECT used, expires FROM request_limits WHERE scope=? AND subject=?",
                (scope, subject),
            ).fetchone()
            active = row and row["expires"] > current
            if active and row["used"] >= maximum:
                return max(1, row["expires"] - current)
            pending.append(
                (
                    scope,
                    subject,
                    row["expires"] if active else current + seconds,
                    row["used"] + 1 if active else 1,
                )
            )
        con.executemany(
            """INSERT INTO request_limits(scope, subject, expires, used) VALUES(?,?,?,?)
               ON CONFLICT(scope,subject) DO UPDATE SET used=excluded.used, expires=excluded.expires""",
            pending,
        )
    return 0
