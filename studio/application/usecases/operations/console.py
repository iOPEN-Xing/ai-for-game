"""Application operations for operations console."""

import datetime as dt
import json

from studio.application.usecases.operations import batches, decisions
from studio.application.usecases.operations import evidence as evidence_service
from studio.application.usecases.operations import experiments as experiment_service
from studio.domain import deliberation
from studio.domain.commands import Analysis, ExternalChange, Supplement, Verdict
from studio.domain.metrics import METRIC_HELP
from studio.infra import reporting
from studio.infra.repositories import batches as batches_db
from studio.infra.repositories import evidence as evidence_db
from studio.infra.repositories import experiments as experiments_db
from studio.infra.repositories import games as games_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.store import Problem, db, encode, enqueue, log, now, uid
from studio.settings import ZONE


def ops(game: str | None = None, days: int | None = None):
    with db() as con:
        end = now() + 1
        start = end - days * 86400 if days else 0
        proposals = proposals_db.proposal_summaries(con, game)
        experiments = experiments_db.for_dashboard(con, game)
        for p in proposals:
            p["doc"] = json.loads(p["doc"])
        for e in experiments:
            e["result"] = json.loads(e["result"]) if e["result"] else None
            e["arms"] = reporting.exp_stats(con, e["id"], min(now() + 1, e["due"]))
        return {
            "report": reporting.report(con, start=start, end=end, game=game),
            "campaigns": games_db.campaigns(con, game),
            "proposals": proposals,
            "experiments": experiments,
            "definitions": METRIC_HELP,
            "changes": evidence_db.recent_changes(con, game, game),
            "batches": batches_db.recent(con),
        }


def external_change(body: ExternalChange):
    with db(True) as con:
        g = games_db.find_live_game(con, body.game)
        evidence_db.add_external_change(
            con, uid(), g["id"], body.text, int(body.affects_measurement), now()
        )
        log(con, g["id"], g["live"], "外部变更", body.text, "external")
        return {"saved": True}


def batch_details(day):
    with db() as con:
        b = batches_db.get(con, day)
        b["doc"] = json.loads(b["doc"])
        return b


def analysis(body: Analysis):
    with db(True) as con:
        g = games_db.get(con, body.game)
        snapshot = reporting.report(con, start=now() - 7 * 86400)
        return {
            "id": evidence_service.freeze(
                con,
                g,
                body.kind,
                "manual-" + dt.datetime.now(ZONE).date().isoformat(),
                snapshot,
            )
        }


def batch():
    return batches.run_batch(dt.datetime.now(ZONE).date() - dt.timedelta(days=1))


def proposal(pid):
    with db() as con:
        p = proposals_db.get(con, pid)
        p["doc"], p["evidence"] = json.loads(p["doc"]), json.loads(p["evidence"])
        p["current_protocol"] = deliberation.PROTOCOL
        return p


def review_proposal(pid, body: Verdict):
    with db(True) as con:
        return {
            "production": decisions.review_proposal(con, pid, body.accept, body.note)
        }


def retry_proposal(pid, body: Supplement | None = None):
    with db(True) as con:
        p = proposals_db.get(con, pid)
        legacy = json.loads(p["doc"]).get("protocol") != deliberation.PROTOCOL
        if p["status"] == "needs_evidence" or (
            legacy and p["status"] in ("review", "production")
        ):
            g = games_db.get(con, p["game"])
            if p["kind"] == "iteration" and proposals_db.other_iteration(
                con, pid, g["id"]
            ):
                raise Problem("请先完成当前迭代提案")
            evidence = evidence_service.frozen_evidence(
                con, g, reporting.report(con, start=now() - 7 * 86400)
            )
            note = body.note.strip() if body else ""
            if note:
                evidence["supplement"] = note
                evidence["sources"].append("supplement")
            proposals_db.archive(
                con,
                pid,
                p["evidence"],
                p["doc"],
                note or "按当前版本和样本重新论证",
                now(),
            )
            proposals_db.replace_evidence(con, encode(evidence), g["live"], pid)
        elif p["status"] != "failed":
            raise Problem("当前状态不能重新分析")
        proposals_db.resume(con, pid)
        batches_db.requeue_for_proposal(con, pid)
        enqueue(con, "analysis", pid, "discuss")
        return {"queued": True}


def exp_decision(eid, body: Verdict):
    with db(True) as con:
        experiment_service.decide_experiment(con, eid, body.accept)
    return {"saved": True}
