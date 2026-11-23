"""Health probes for the single-instance SQLite and worker deployment."""

import shutil
import sqlite3

from studio.settings import data_dir

from .store import db, now, one, rows


def available() -> bool:
    try:
        with db() as con:
            con.execute("SELECT 1")
    except sqlite3.Error:
        return False
    return True


def readiness(worker_running: bool) -> dict:
    checks = {
        "database": {"ok": False},
        "volume": {"ok": False},
        "queue": {"ok": False},
    }
    try:
        usage = shutil.disk_usage(data_dir())
        checks["volume"] = {
            "ok": usage.free >= usage.total * 0.1,
            "free_bytes": usage.free,
        }
        with db(write=True) as con:
            con.execute("UPDATE jobs SET heartbeat=heartbeat WHERE 0")
            checks["database"]["ok"] = True
            backlog = one(
                con,
                "SELECT count(*) AS depth, MIN(created) AS oldest FROM jobs WHERE state='queued'",
            )
            age = max(0, now() - (backlog["oldest"] or now()))
            checks["queue"] = {
                "ok": worker_running and age <= 1800,
                "depth": backlog["depth"],
                "oldest_seconds": age,
            }
    except (sqlite3.Error, OSError):
        pass
    return {
        "status": "ready" if all(c["ok"] for c in checks.values()) else "unavailable",
        "checks": checks,
    }


def metrics() -> str:
    with db() as con:
        jobs = rows(con, "SELECT state,count(*) AS n FROM jobs GROUP BY state")
    return (
        "# TYPE studio_jobs gauge\n"
        + "".join(f'studio_jobs{{state="{r["state"]}"}} {r["n"]}\n' for r in jobs)
        + f"# TYPE studio_volume_free_bytes gauge\nstudio_volume_free_bytes {shutil.disk_usage(data_dir()).free}\n"
    )
