import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from studio.settings import data_dir


class Problem(Exception):
    def __init__(self, message, status=409, *, code=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after


def uid():
    return secrets.token_hex(12)


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def now():
    return int(time.time())


@contextmanager
def db(write=False):
    con = sqlite3.connect(
        data_dir() / "studio.sqlite3", timeout=10, isolation_level=None
    )
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def one(con, query, *params):
    row = con.execute(query, params).fetchone()
    return dict(row) if row else None


def rows(con, query, *params):
    return [dict(row) for row in con.execute(query, params)]


def need(con, query, *params):
    row = one(con, query, *params)
    if not row:
        raise Problem("记录不存在", 404)
    return row


def log(con, game, rev, role, text, kind="event"):
    con.execute(
        "INSERT INTO history(game,rev,role,text,kind,at) VALUES(?,?,?,?,?,?)",
        (game, rev, role, text, kind, now()),
    )


def enqueue(con, kind, target, stage):
    con.execute(
        """INSERT INTO jobs(id,kind,target,stage,state,created) VALUES(?,?,?,?, 'queued',?)
                   ON CONFLICT(kind,target,stage) DO UPDATE SET state='queued',attempts=0,recoveries=0,error=NULL,
                   heartbeat=0 WHERE jobs.state IN ('done','failed')""",
        (uid(), kind, target, stage, now()),
    )


def init():
    data_dir().mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.commit()
        con.execute("PRAGMA journal_mode=WAL")
        migrations = Path(__file__).with_name("migrations")
        con.executescript((migrations / "baseline.sql").read_text(encoding="utf-8"))
        con.execute("BEGIN IMMEDIATE")
        columns = {c[1] for c in con.execute("PRAGMA table_info(rounds)")}
        if "finish" not in columns:
            con.execute("ALTER TABLE rounds ADD COLUMN finish TEXT")
        if "replay" not in columns:
            con.execute("ALTER TABLE rounds ADD COLUMN replay BLOB")
        if "campaign" not in columns:
            con.execute(
                "ALTER TABLE rounds ADD COLUMN campaign TEXT REFERENCES campaigns(id)"
            )
        if "action_at" not in columns:
            con.execute("ALTER TABLE rounds ADD COLUMN action_at INTEGER")
        if "progress_scope" not in columns:
            con.execute("ALTER TABLE rounds ADD COLUMN progress_scope TEXT")
        for name in ("hint_at", "mistakes", "rescues", "slow_round"):
            if name not in columns:
                con.execute("ALTER TABLE rounds ADD COLUMN " + name + " INTEGER")
        con.execute(
            "CREATE INDEX IF NOT EXISTS rounds_progress ON rounds(game,player,preview,COALESCE(progress_scope,rev),level) WHERE won=1"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS rounds_player_cohort ON rounds(game,player,started) WHERE preview=0"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS rounds_public_window ON rounds(issued,game) WHERE preview=0"
        )
        if "recoveries" not in {c[1] for c in con.execute("PRAGMA table_info(jobs)")}:
            con.execute(
                "ALTER TABLE jobs ADD COLUMN recoveries INTEGER NOT NULL DEFAULT 0"
            )
        con.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY)"
        )
        for path in sorted(migrations.glob("migrate_*.sql")):
            if one(con, "SELECT 1 FROM schema_migrations WHERE name=?", path.name):
                continue
            # executescript commits implicitly. Execute complete statements within this transaction.
            statement = ""
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    con.execute(statement)
                    statement = ""
            if statement.strip():
                raise RuntimeError(f"Incomplete SQL migration: {path.name}")
            con.execute("INSERT INTO schema_migrations VALUES(?)", (path.name,))
