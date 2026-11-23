"""Health probes for the single-instance SQLite and worker deployment."""

import shutil
import sqlite3

from studio.settings import data_dir, studio_day_start

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
        "worker": {"ok": False},
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
            leader = one(con, "SELECT * FROM worker_health WHERE singleton=1")
            if leader:
                age = max(0, now() - leader["heartbeat"])
                checked = leader["last_reconciled"]
                checks["worker"] = {
                    "ok": bool(
                        worker_running
                        and age <= 45
                        and checked
                        and now() - checked <= 3700
                        and leader["failures"] < 3
                    ),
                    "heartbeat_age_seconds": age,
                    "last_reconciled": checked,
                    "consecutive_failures": leader["failures"],
                }
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
        model_totals = rows(
            con, "SELECT * FROM model_call_totals ORDER BY role,provider,outcome"
        )
        jobs = rows(con, "SELECT state,count(*) AS n FROM jobs GROUP BY state")
        usage = (
            one(con, "SELECT * FROM player_intake WHERE day=?", studio_day_start(now()))
            or {}
        )
    model_lines = []
    for column in (
        "calls",
        "elapsed_ms",
        "usage_reports",
        "input_tokens",
        "output_tokens",
    ):
        name = f"studio_model_{column}_total"
        model_lines.append(f"# TYPE {name} counter")
        for row in model_totals:
            labels = ",".join(
                f'{key}="{row[key]}"' for key in ("role", "provider", "outcome")
            )
            model_lines.append(f"{name}{{{labels}}} {row[column]}")
    return (
        "\n".join(model_lines)
        + "\n"
        + "# TYPE studio_jobs gauge\n"
        + "".join(f'studio_jobs{{state="{r["state"]}"}} {r["n"]}\n' for r in jobs)
        + "".join(
            f"# TYPE studio_today_{name} gauge\nstudio_today_{name} {usage.get(name, 0)}\n"
            for name in ("opens", "replay_bytes", "omitted_replays")
        )
        + f"# TYPE studio_volume_free_bytes gauge\nstudio_volume_free_bytes {shutil.disk_usage(data_dir()).free}\n"
    )
