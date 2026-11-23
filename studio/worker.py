import asyncio
import datetime as dt
import fcntl
import json
import logging
from contextlib import suppress

from studio.domain import deliberation
from studio.infra.repositories import batches as batches_db
from studio.infra.repositories import experiments as experiments_db
from studio.infra.repositories import jobs as jobs_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.repositories import revisions as revisions_db
from studio.services import batches, experiments, production, review

from .infra.store import db, enqueue, log, now
from .settings import ZONE, data_dir


def claim():
    with db(True) as con:
        job = jobs_db.next_in_queue(con)
        if job:
            jobs_db.start(con, now(), job["id"])
        return job


async def run_job(job):
    async def keep_alive():
        while True:
            await asyncio.sleep(15)
            with db(True) as con:
                jobs_db.heartbeat(con, now(), job["id"])

    pulse = asyncio.create_task(keep_alive())
    try:
        if job["kind"] == "production":
            await production.produce(job["target"], job["stage"])
        else:
            await review.analyze(job["target"])
        with db(True) as con:
            jobs_db.complete(con, job["id"])
            batches.audit_batches(con)
    except asyncio.CancelledError:
        with db(True) as con:
            jobs_db.retry_running(con, job["id"])
        raise
    except Exception as exc:  # noqa: BLE001 - persist failures at the background job boundary before retrying.
        cause = exc
        while isinstance(cause, BaseExceptionGroup):
            cause = cause.exceptions[0]
        explanation = (
            str(cause)[:350]
            if isinstance(cause, (ValueError, RuntimeError))
            else type(cause).__name__
        )
        state = "failed" if job["attempts"] + 1 >= 2 else "queued"
        with db(True) as con:
            jobs_db.record_failure(con, state, explanation, job["id"])
            if job["kind"] == "analysis" and state == "failed":
                proposals_db.fail_analysis(con, job["target"])
            if job["kind"] == "production":
                rev = revisions_db.find_owner(con, job["target"])
                if rev:
                    log(
                        con,
                        rev["game"],
                        job["target"],
                        "构建服务",
                        "任务"
                        + ("待重试" if state == "failed" else "将自动续跑")
                        + " · "
                        + explanation,
                        "error",
                    )
            batches.audit_batches(con)
    finally:
        pulse.cancel()
        with suppress(asyncio.CancelledError):
            await pulse


def audit_deliveries(con):
    expected = [
        ("production", r["id"], r["stage"]) for r in jobs_db.active_revisions(con)
    ]
    for p in jobs_db.pending_analyses(con):
        if p["status"] == "review":
            if not deliberation.reviewable(
                p["kind"], json.loads(p["doc"]), json.loads(p["evidence"])
            ):
                proposals_db.require_evidence(con, p["id"])
            continue
        proposals_db.resume(con, p["id"])
        expected.append(("analysis", p["id"], "discuss"))
    for kind, target, stage in expected:
        job = jobs_db.find(con, kind, target, stage)
        if not job:
            enqueue(con, kind, target, stage)
        elif job["state"] == "done":
            state = "queued" if job["recoveries"] < 2 else "failed"
            jobs_db.recover(con, state, "任务退出后缺少交付物", job["id"])
            if kind == "analysis" and state == "failed":
                proposals_db.fail(con, target)


def reconcile():
    local = dt.datetime.now(ZONE)
    latest = local.date() - dt.timedelta(days=1 if local.hour >= 8 else 2)
    with db(True) as con:
        # Only the elected worker owns jobs. Running calls refresh this lease every 15s.
        jobs_db.recover_stale(con, now() - 180)
        audit_deliveries(con)
        batches.audit_batches(con)
        for exp in experiments_db.due(con, now()):
            experiments.settle(con, exp)
        prev = batches_db.last_successful_day(con)
        missing = [
            dt.date.fromisoformat(r["day"]) for r in batches_db.retryable_days(con)
        ]
    start = (
        dt.date.fromisoformat(prev["day"]) + dt.timedelta(days=1)
        if prev["day"]
        else latest
    )
    for i in range(min(14, (latest - start).days + 1)):
        missing.append(start + dt.timedelta(days=i))
    for day in sorted(set(missing)):
        batches.run_batch(day)


async def serve():
    with (data_dir() / "worker.lock").open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(2)
        with db(True) as con:
            jobs_db.recover_owned(con)
        pending = set()
        last_watch = 0
        try:
            while True:
                current = now()
                local = dt.datetime.now(ZONE)
                if current - last_watch >= 1800 or (
                    local.hour == 8 and local.minute == 0 and current - last_watch >= 60
                ):
                    try:
                        await asyncio.to_thread(reconcile)
                    except Exception as exc:  # noqa: BLE001 - a scheduler fault must leave the job loop available.
                        logging.getLogger(__name__).error(
                            "批次巡检失败 (%s)", type(exc).__name__
                        )
                    last_watch = current
                for task in list(pending):
                    if task.done():
                        pending.remove(task)
                        task.result()
                if len(pending) < 2:
                    job = claim()
                    if job:
                        pending.add(asyncio.create_task(run_job(job)))
                        continue
                await asyncio.sleep(0.4)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
