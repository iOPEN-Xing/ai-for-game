"""Run the expert panel and apply human decisions."""

import asyncio
import json

from studio import agents, skillbook
from studio import context as project_context
from studio.domain import deliberation
from studio.domain.deliberation import (
    feedback_summary,
    validate_candidates,
    visible_sources,
)
from studio.infra.reporting import report
from studio.infra.repositories import evidence as evidence_db
from studio.infra.repositories import games as games_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import Problem, db, encode, log, now
from studio.services import debate, revisions
from studio.services.evidence import frozen_evidence
from studio.settings import METRICS


async def analyze(pid):
    with db() as con:
        p = proposals_db.get(con, pid)
        if p["status"] != "analyzing":
            return
        g = games_db.get(con, p["game"])
    evidence = json.loads(p["evidence"])
    checkpoint = json.loads(p["doc"])
    if "sources" not in evidence:
        with db(True) as con:
            evidence = frozen_evidence(con, g, report(con, *evidence["period"]))
            proposals_db.rebase(con, g["live"], encode(evidence), pid)
        checkpoint = {}
    if any(
        set(item) - {"level", "rating", "responses"}
        for item in evidence.get("feedback", [])
    ):
        # Restart old, unfinished discussions from aggregates before supplying any prior opinions.
        evidence["sources"] = visible_sources("Reviewer", evidence)
        evidence["feedback"] = feedback_summary(evidence["feedback"])
        checkpoint = {}
        with db(True) as con:
            proposals_db.save_evidence(con, encode(evidence), pid)
            proposals_db.save_checkpoint(con, encode(checkpoint), pid)
    if "memory" not in evidence:
        with db(True) as con:
            evidence["memory"] = project_context.capture(
                con, g["id"], evidence["period"][1]
            )
            proposals_db.save_evidence(con, encode(evidence), pid)
    snapshot = evidence["memory"]
    binding = await skillbook.pin("proposal:" + snapshot["id"], p["kind"])
    if checkpoint.get("protocol") != deliberation.PROTOCOL:
        checkpoint = {"protocol": deliberation.PROTOCOL}
    base = {
        "task": p["kind"],
        "metric": METRICS[g["metric"]],
        "action_bounds": g["bounds"],
        "_memory": snapshot,
        "_run_binding": binding,
        "_evidence_hash": skillbook.digest(evidence),
    }

    slots = asyncio.Semaphore(3)

    async def get(label, role, schema, phase, **context):
        if label in checkpoint:
            return
        view = project_context.evidence_for(role, evidence)
        context = {**base, **context, "evidence": view, "phase": phase, "_node": label}
        for attempt in range(2):
            async with slots:
                value, provider = await agents.consult(role, schema, context)
            try:
                schema.model_validate(value, context=view)
                deliberation.validate_refs(value, set(view["sources"]))
                if schema is deliberation.DeadEndAudit and set(value["examined"]) != {
                    i["id"] for i in evidence["dead_ends"]
                }:
                    raise ValueError(
                        "examined 必须覆盖本次已知死路的所有 ID，空清单填 []"
                    )
                if (
                    phase in ("constraints", "independent")
                    and role == "Engineer"
                    and not set(value["refs"]).intersection(
                        {"game.js", "level-generator.js"}
                    )
                ):
                    raise ValueError("开发评审必须引用实际读取的源码")
                if schema is deliberation.Candidates:
                    validate_candidates(value["candidates"], view["sources"])
                if (
                    schema is deliberation.Challenge
                    and p["kind"] == "new_game"
                    and not any(q["owner"] == "GameDesigner" for q in value["issues"])
                ):
                    raise ValueError("分析师必须至少向设计师提出一次候选质询")
                if label == "bet":
                    value["resolutions"] = [
                        dict(checkpoint["resolve_" + q], issue=q)
                        for q in deliberation.issue_ids(checkpoint)
                    ]
                    deliberation.validate_decision(
                        p["kind"], {**checkpoint, "bet": value}, evidence
                    )
                if label == "final_review":
                    value["rulings"] = [
                        dict(checkpoint["verify_" + q], issue=q)
                        for q in deliberation.issue_ids(checkpoint)
                    ]
                break
            except (KeyError, TypeError, ValueError) as exc:
                if attempt:
                    raise
                context["correction"] = str(exc)[:500]
                context["previous_submission"] = project_context.clean_handoff(value)
        checkpoint[label] = value
        with db(True) as con:
            proposals_db.save_checkpoint(con, encode(checkpoint), pid)
            log(
                con,
                g["id"],
                evidence["version"]["id"],
                role,
                f"{phase} 已保存 [{provider}]",
                "analysis",
            )

    ready = await debate.conduct(p["kind"], checkpoint, evidence, get)
    with db(True) as con:
        proposals_db.finish_analysis(con, "review" if ready else "needs_evidence", pid)


def review_proposal(con, pid, accept, note):
    p = proposals_db.get(con, pid)
    if p["status"] != "review" and not (p["status"] == "needs_evidence" and not accept):
        raise Problem("提案不在待评审状态")
    g = games_db.get(con, p["game"])
    doc = json.loads(p["doc"])
    bet = doc.get("bet") or {"title": g["title"] + " · 补证评审"}
    target = None
    if accept:
        if not deliberation.reviewable(p["kind"], doc, json.loads(p["evidence"])):
            raise Problem("论证未通过终审，请补证并重新分析")
        if g["live"] != p["base"]:
            raise Problem("提案基线已改变，请重新分析")
        brief = bet["change"] + "\n预期：" + bet["falsifier"] + "\n审核意见：" + note
        if p["kind"] == "iteration":
            # An approved legacy draft can be replaced only after the new contract has been reviewed.
            if proposals_db.has_prior_evidence(con, pid):
                revisions_db.supersede_proposal_drafts(con, pid)
            if revisions_db.active_draft(con, g["id"]):
                raise Problem("请先完成当前草稿")
            target = {
                "game": g["id"],
                "rev": revisions.new_revision(con, g["id"], p["base"], pid, brief),
            }
        else:
            old = games_db.from_proposal(con, pid)
            if old:
                if old["live"]:
                    raise Problem("立项游戏已经发布")
                gid = old["id"]
                revisions_db.supersede_game_drafts(con, gid)
                games_db.update_brief(con, bet["title"], brief, gid)
                rid = revisions.new_revision(con, gid, proposal=pid)
            else:
                gid, rid = revisions.new_game(
                    con,
                    bet["title"],
                    brief,
                    g["metric"],
                    g["bounds"],
                    pid,
                    json.loads(p["evidence"])
                    .get("memory", {})
                    .get("preferences", {})
                    .get("values", {}),
                )
            target = {"game": gid, "rev": rid}
    if not accept:
        evidence_db.record_dead_end(
            con, pid, now(), bet["title"], note.strip() or "团队驳回，未填写理由。"
        )
    proposals_db.set_status(con, "production" if accept else "rejected", pid)
    log(
        con,
        g["id"],
        p["base"],
        "运营评审",
        ("通过" if accept else "驳回") + " · " + bet["title"] + " " + note,
        "review",
    )
    return target


def review_knowledge(con, kid, accept, supersede=(), note=""):
    k = evidence_db.get_knowledge(con, kid)
    if k["status"] != "pending":
        raise Problem("知识已评审")
    evidence = json.loads(k["evidence"])
    if supersede and (
        not accept
        or evidence.get("attribution") != "假设错"
        or set(supersede) - set(evidence["citations"])
    ):
        raise Problem("只能逐条复核本次被证伪假设引用的知识")
    status = (
        "active"
        if accept and k["grade"] != "未验证推断"
        else "unverified"
        if accept
        else "rejected"
    )
    if supersede and status != "active":
        raise Problem("只有采纳的已验证记录能替代旧知识")
    for prior in set(supersede):
        entry = evidence_db.get_knowledge(con, prior)
        if entry["game"] != k["game"] or entry["status"] != "active":
            raise Problem("待替代的知识已失效或属于其他项目，请刷新后复核")
    at = now()
    evidence_db.record_knowledge_review(con, kid, status, at, note.strip())
    for prior in sorted(set(supersede)):
        evidence_db.record_knowledge_review(
            con, prior, "superseded", at, note.strip(), kid
        )
