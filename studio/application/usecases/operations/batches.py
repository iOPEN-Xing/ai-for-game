"""Daily ranking, experiment reconciliation and delivery audits."""

import datetime as dt
import json

from studio.application.usecases.operations.evidence import freeze
from studio.application.usecases.operations.experiments import settle
from studio.domain import deliberation
from studio.domain.metrics import attach_retention, rates, sample_unit
from studio.infra.reporting import game_baselines, report, retention
from studio.infra.repositories import batches as batches_db
from studio.infra.repositories import experiments as experiments_db
from studio.infra.repositories import games as games_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.store import Problem, db, encode, now
from studio.settings import ZONE


def daily_priorities(con, snapshot):
    end = snapshot["start"]
    baselines = {r["game"]: rates(r) for r in game_baselines(con, end - 7 * 86400, end)}
    cohorts, period = retention(con, end - 7 * 86400, end)
    for gid, row in baselines.items():
        attach_retention(row, [v for v in cohorts if v["game"] == gid], period)
    metrics = {g["id"]: g["metric"] for g in games_db.live_metrics(con)}
    ranked = []
    for item in snapshot["games"]:
        gid = item["game"]
        metric = metrics.get(gid)
        if not item["starts"] or metric is None or item[metric] is None:
            continue
        previous = baselines.get(gid, {}).get(metric)
        decline = round((previous - item[metric]) / previous, 4) if previous else None
        basis = sample_unit(metric)
        ranked.append(
            {
                "game": gid,
                "metric": metric,
                "value": item[metric],
                "baseline": previous,
                "baseline_days": 7,
                "relative_decline": decline,
                "sample": item[basis],
            }
        )
    return sorted(
        ranked,
        key=lambda v: (-max(0, v["relative_decline"] or 0), -v["sample"], v["game"]),
    )


def schedule_candidates(con, doc):
    pending = []
    ids = doc["proposals"]
    for candidate in doc["pending"]:
        gid, kind = candidate["game"], candidate["kind"]
        existing = proposals_db.for_batch(con, gid, doc["day"], kind)
        if existing:
            if existing["id"] not in ids:
                ids.append(existing["id"])
            continue
        game = games_db.get(con, gid)
        if game["live"] != candidate["revision"]:
            doc["skipped"].append({**candidate, "reason": "观察窗冻结后线上版本已切换"})
            continue
        try:
            ids.append(freeze(con, game, kind, doc["day"], doc["report"]))
        except Problem as exc:
            if exc.code == "QUOTA_EXCEEDED":
                pending.append(candidate)
                doc["retry_at"] = now() + exc.retry_after
            elif exc.status == 409:
                doc["skipped"].append({**candidate, "reason": str(exc)})
            else:
                raise
    doc["pending"] = pending
    if not pending:
        doc.pop("retry_at", None)
    status = "deferred" if pending else "queued" if ids else "complete"
    batches_db.save(con, doc["day"], status, encode(doc), now())
    return doc


def run_batch(day):
    end = int(
        dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), ZONE).timestamp()
    )
    if end > now():
        raise Problem("日报只处理已结束的自然日")
    key = day.isoformat()
    try:
        with db(True) as con:
            existing = batches_db.find(con, key)
            if existing and existing["status"] in (
                "queued",
                "complete",
                "needs_review",
            ):
                return json.loads(existing["doc"])
            if existing and existing["status"] == "deferred":
                doc = json.loads(existing["doc"])
                return doc if doc["retry_at"] > now() else schedule_candidates(con, doc)
            snapshot = report(con, end - 86400, end)
            if (
                sum(g["starts"] for g in snapshot["games"])
                != snapshot["total"]["starts"]
                or sum(level["starts"] for level in snapshot["levels"])
                != snapshot["total"]["starts"]
            ):
                raise RuntimeError("三级报表口径不一致")
            settlements = []
            for exp in experiments_db.due(con, now()):
                settle(con, exp)
                settlements.append(exp["id"])
            ranked = daily_priorities(con, snapshot)
            snapshot["priorities"] = ranked
            releases = batches_db.releases_in_window(con, end - 86400, end)
            launches = batches_db.launch_reconciliation(con, end, end, end)
            for launch in launches:
                doc = json.loads(launch.pop("doc"))
                bet = doc["bet"]
                due = launch["launch_at"] + bet["days"] * 86400
                stats = report(
                    con,
                    launch["launch_at"],
                    min(end, due),
                    launch["game"],
                    launch["rev"],
                    launch["bundle"],
                )["total"]
                value, n = stats[launch["metric"]], stats[sample_unit(launch["metric"])]
                status = (
                    "旧版预期口径待核"
                    if doc.get("protocol") != deliberation.PROTOCOL
                    else "观察中"
                    if end < due
                    else "样本不足"
                    if n < bet["min_players"] or value is None
                    else "在预期内"
                    if bet["low"] <= value <= bet["high"]
                    else "偏离预期"
                )
                launch.update(
                    expected=[bet["low"], bet["high"]],
                    due=due,
                    observed=value,
                    sample=n,
                    assessment=status,
                )
            doc = {
                "launch_reconciliation": launches,
                "day": key,
                "report": snapshot,
                "proposals": [],
                "pending": [],
                "skipped": [],
                "settlements": settlements,
                "releases": releases,
                "top": [i["game"] for i in ranked[:3]],
            }
            for rank, item in enumerate(ranked[:3]):
                game = games_db.get(con, item["game"])
                kinds = ("iteration", "new_game") if rank == 0 else ("iteration",)
                for kind in kinds:
                    doc["pending"].append(
                        {"game": game["id"], "revision": game["live"], "kind": kind}
                    )
            return schedule_candidates(con, doc)
    except Exception as exc:
        with db(True) as con:
            batches_db.fail(con, key, encode({"error": type(exc).__name__}), now())
        raise


def audit_batches(con):
    for batch in batches_db.queued(con):
        ids = json.loads(batch["doc"])["proposals"]
        states = [proposals_db.outcome(con, pid) for pid in ids]
        if all(
            p
            and "bet" in json.loads(p["doc"])
            and p["status"] not in ("analyzing", "failed", "needs_evidence")
            and (
                p["status"] != "review"
                or deliberation.reviewable(
                    p["kind"], json.loads(p["doc"]), json.loads(p["evidence"])
                )
            )
            for p in states
        ):
            batches_db.complete(con, batch["day"])
        elif any(
            p is None or p["status"] in ("failed", "needs_evidence") for p in states
        ):
            batches_db.require_review(con, batch["day"])
