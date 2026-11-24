"""Freeze source code, level data and observations from the same release."""

import datetime as dt
import json

from studio.application.memory import snapshots
from studio.application.tools import acceptance, cartridge
from studio.domain import limits
from studio.domain.evidence_sources import source_catalog
from studio.domain.metrics import METRIC_HELP
from studio.infra.reporting import report
from studio.infra.repositories import evidence as evidence_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import Problem, encode, enqueue, now, uid
from studio.settings import ZONE


def frozen_evidence(con, g, snapshot):
    if not g["live"]:
        raise Problem("先发布一个可收集对局数据的版本")
    r = revisions_db.for_game(con, g["live"], g["id"])
    current = report(
        con, snapshot["start"], snapshot["end"], g["id"], r["id"], r["bundle"]
    )
    item = current["total"]
    if not item["starts"]:
        raise Problem(f"观察窗内线上 V{r['num']} 没有正式开局，需等待该构建获得样本")
    if g["metric"] == "action_rate" and not item.get("action_visitors"):
        raise Problem("选定指标需要带行动按钮的活动入口和实际访问")
    if g["metric"] == "d1_rate" and not item.get("d1_eligible"):
        raise Problem("当前构建尚无完整观察过次日的首玩队列")
    docs = json.loads(r["docs"])
    notes = evidence_db.recent_feedback(
        con, r["id"], r["bundle"], snapshot["start"], snapshot["end"]
    )
    family = docs["levels"]["game_type"]
    candidates = evidence_db.comparable_knowledge(con, snapshot["end"])
    knowledge = []
    for k in candidates:
        same_family = k.pop("family") == family
        if k["game"] == g["id"] or same_family:
            k["match_score"] = round(
                (1 if k["game"] == g["id"] else 0.55) * k["confidence"], 3
            )
            knowledge.append(k)
    knowledge = sorted(knowledge, key=lambda k: -k["match_score"])[:8]
    history = evidence_db.history(con, g["id"], snapshot["end"])
    evidence = {
        "memory": snapshots.capture(con, g["id"], snapshot["end"]),
        "inference_mode": "descriptive",
        "period": [snapshot["start"], snapshot["end"]],
        "definitions": METRIC_HELP,
        "center": snapshot["total"],
        "game": {**item, "game": g["id"], "rev": r["id"], "bundle": r["bundle"]},
        "levels": current["levels"],
        "channels": current["channels"],
        "arms": current["versions"],
        "quadrants": current["quadrants"],
        "quadrant_definition": "仅统计可回放且支持失误计数的自然完局。时长达到关卡时限一半记为长局，至少两次失误记为多失误。低样本只作线索。rescue_observed 是提供救援计数的局数。",
        "historical_versions": [
            v
            for v in snapshot.get("versions", [])
            if v["game"] == g["id"] and v["rev"] != r["id"]
        ],
        "priority": next(
            (v for v in snapshot.get("priorities", []) if v["game"] == g["id"]), None
        ),
        "feedback": notes,
        "history": history,
        "external_changes": evidence_db.changes_in_window(
            con, g["id"], snapshot["start"], snapshot["end"]
        ),
        "version": {"id": r["id"], "number": r["num"], "bundle": r["bundle"]},
        "knowledge": knowledge,
        "gdd": docs["gdd"],
        "game_code": docs["game_code"]["source"],
        "level_code": docs["level_code"]["source"],
    }
    pack = acceptance.read_pack(r["bundle"])
    evidence["level_pack"] = {
        k: pack[k] for k in ("seed", "mode", "family", "levels", "proof")
    }
    evidence["assets"] = json.loads(
        (cartridge.folder(r["bundle"]) / "asset.json").read_bytes()
    )
    evidence["probes"] = acceptance.probes(r["bundle"], pack["levels"])
    evidence["dead_ends"] = evidence_db.dead_ends(con, g["id"], snapshot["end"])
    evidence["portfolio"] = [
        v["title"] for v in evidence_db.portfolio_titles(con, snapshot["end"])
    ]
    evidence["portfolio_designs"] = evidence_db.portfolio_designs(con, snapshot["end"])
    versions = snapshot.get("versions", [])
    peer_ids = {
        v["id"]
        for v in evidence_db.peer_versions(
            con, [v["rev"] for v in versions], g["id"], family
        )
    }
    evidence["peers"] = [v for v in versions if v["rev"] in peer_ids][:20]
    evidence["sources"] = source_catalog(evidence)
    return evidence


def freeze(con, g, kind, day, snapshot):
    if kind == "iteration" and proposals_db.active_iteration(con, g["id"], kind):
        raise Problem("此游戏已有进行中的迭代提案")
    if proposals_db.for_batch(con, g["id"], day, kind):
        raise Problem("本批次已生成同类提案")
    midnight = dt.datetime.fromtimestamp(now(), ZONE).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if (
        proposals_db.count_created_since(con, int(midnight.timestamp()))
        >= limits.NEW_ANALYSES_PER_DAY
    ):
        tomorrow = int((midnight + dt.timedelta(days=1)).timestamp())
        raise Problem(
            "制作室今日新建分析任务已达上限",
            429,
            code="QUOTA_EXCEEDED",
            retry_after=max(1, tomorrow - now()),
        )
    evidence = frozen_evidence(con, g, snapshot)
    pid = uid()
    proposals_db.create(
        con, pid, g["id"], evidence["version"]["id"], kind, day, encode(evidence), now()
    )
    enqueue(con, "analysis", pid, "discuss")
    return pid
