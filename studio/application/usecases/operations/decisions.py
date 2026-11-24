"""Apply team decisions to proposals and reviewed knowledge."""

import json

from studio.application.usecases.games import revisions
from studio.domain import deliberation
from studio.infra.repositories import evidence as evidence_db
from studio.infra.repositories import games as games_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import Problem, log, now


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
