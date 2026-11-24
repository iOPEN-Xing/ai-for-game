"""Verify deliveries, assign players and settle pre-registered experiments."""

import hashlib
import json

from studio.application.tools import acceptance, cartridge
from studio.domain import deliberation
from studio.domain.evaluation import adjudicate
from studio.infra.reporting import exp_stats
from studio.infra.repositories import evidence as evidence_db
from studio.infra.repositories import experiments as experiments_db
from studio.infra.repositories import games as games_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import Problem, encode, log, now, uid


def delivery_diff(control, treatment):
    before, after = cartridge.folder(control), cartridge.folder(treatment)
    names = {
        "game.js",
        "level-generator.js",
        "asset.json",
        "sprite.png",
        "hit.wav",
        "miss.wav",
        "win.wav",
        "bgm.wav",
        "ui.wav",
    }
    names.update(
        p.name for folder in (before, after) for p in folder.glob("sprite-*.png")
    )
    changed = [
        name
        for name in sorted(names)
        if not (before / name).is_file()
        or not (after / name).is_file()
        or (before / name).read_bytes() != (after / name).read_bytes()
    ]
    if (
        json.loads((before / "Level_Pack.json").read_bytes())["levels"]
        != json.loads((after / "Level_Pack.json").read_bytes())["levels"]
    ):
        changed.append("Level_Pack.json")
    return changed


def release(con, g, r):
    if (
        not r["bundle"]
        or not (cartridge.folder(r["bundle"]) / "manifest.json").is_file()
    ):
        raise Problem("缺少可发布的构建")
    if g["live"] != r["parent"]:
        raise Problem("线上基线已经改变，需要重新基于当前版本制作")
    if experiments_db.undecided(con, g["id"]):
        raise Problem("请先完成当前实验决策")
    p = proposals_db.find(con, r["proposal"])
    if p and not deliberation.reviewable(
        p["kind"], json.loads(p["doc"]), json.loads(p["evidence"])
    ):
        raise Problem("发布前复核未通过，请根据当前证据重新论证提案")
    if p and p["kind"] == "iteration":
        bet = json.loads(p["doc"])["bet"]
        if p["status"] != "production" or p["base"] != g["live"]:
            raise Problem("提案与线上基线不符")
        control = revisions_db.bundle(con, g["live"])
        if r["bundle"] == control["bundle"] or not delivery_diff(
            control["bundle"], r["bundle"]
        ):
            raise Problem("实验版本须包含实际构建变更")
        try:
            acceptance.verify(
                control["bundle"], r["bundle"], bet, json.loads(p["evidence"])
            )
        except (ValueError, KeyError, IndexError) as exc:
            raise Problem("批准项验收未通过：" + str(exc)[:400]) from None
        started = now()
        eid = uid()
        compatible = acceptance.compatible_progress(
            acceptance.read_pack(control["bundle"]), acceptance.read_pack(r["bundle"])
        )
        scope = progress_scope(con, g["live"]) if compatible else "experiment-" + eid
        experiments_db.save_scope(
            con, eid, scope, "inherit" if compatible else "reset_both"
        )
        experiments_db.create(
            con,
            eid,
            g["id"],
            p["id"],
            g["live"],
            r["id"],
            started,
            started + bet["days"] * 86400,
        )
        proposals_db.start_experiment(con, p["id"])
        log(
            con,
            g["id"],
            r["id"],
            "发布服务",
            "A/B 实验开始，按玩家稳定分流，对照版本继续在线。",
            "release",
        )
    else:
        games_db.publish(con, r["id"], g["id"])
        if p:
            proposals_db.delivered(con, p["id"])
        log(
            con,
            g["id"],
            r["id"],
            "发布服务",
            "版本已全量发布，开放玩家入口。",
            "release",
        )


def distribution(con, g, player):
    exp = experiments_db.current(con, g["id"], now())
    if not exp:
        return g["live"], None, None
    arm = ("control", "treatment")[
        hashlib.sha256((exp["id"] + player).encode()).digest()[0] % 2
    ]
    return exp[arm], exp["id"], arm


def progress_scope(con, rev, experiment=None):
    if experiment:
        entry = experiments_db.scope(con, experiment)
        if entry:
            return entry["scope"]
    entry = experiments_db.active_control_scope(con, rev)
    if entry:
        return entry["scope"]
    entry = experiments_db.revision_scope(con, rev)
    return entry["scope"] if entry else rev


def settle(con, exp):
    if exp["status"] != "running" or exp["due"] > now():
        raise Problem("尚未到结算时间")
    p = proposals_db.get(con, exp["proposal"])
    g = games_db.get(con, exp["game"])
    doc = json.loads(p["doc"])
    evidence = json.loads(p["evidence"])
    bet = doc["bet"]
    arms = exp_stats(con, exp["id"], exp["due"])
    versions = [revisions_db.identity(con, exp[k]) for k in ("control", "treatment")]
    delivery_ok = (
        versions[0]["id"] == p["base"]
        and versions[0]["bundle"] != versions[1]["bundle"]
        and all(
            (cartridge.folder(v["bundle"]) / "manifest.json").exists() for v in versions
        )
    )
    diff = (
        delivery_diff(versions[0]["bundle"], versions[1]["bundle"])
        if delivery_ok
        else []
    )
    delivery_ok = delivery_ok and bool(diff)
    criteria_error = None
    if delivery_ok and not deliberation.reviewable(p["kind"], doc, evidence):
        delivery_ok, criteria_error = False, "批准记录缺少完整、已关闭的审议依据"
    if delivery_ok:
        try:
            acceptance.verify(
                versions[0]["bundle"],
                versions[1]["bundle"],
                bet,
                evidence,
            )
        except (ValueError, KeyError, IndexError) as exc:
            delivery_ok, criteria_error = False, str(exc)[:400]
    changes = evidence_db.changes_during_experiment(
        con, g["id"], exp["started"], exp["due"]
    )
    judgment = adjudicate(
        g["metric"],
        bet,
        arms,
        delivery_ok=delivery_ok,
        confounded=any(c["affects_measurement"] for c in changes),
    )
    grade, conclusion = judgment["grade"], judgment["conclusion"]
    result = {
        **judgment,
        "arms": arms,
        "versions": versions,
        "tested_change": bet["change"],
        "objections": bet["objections"],
        "falsifier": bet["falsifier"],
        "citations": bet["citations"],
        "changed_files": diff,
        "acceptance_error": criteria_error,
        "external_changes": changes,
    }
    if judgment["attribution"] == "假设错":
        evidence_db.record_dead_end(con, p["id"], now(), bet["title"], conclusion)
    experiments_db.save_result(con, encode(result), exp["id"])
    proposals_db.settled(con, p["id"])
    evidence_db.propose_knowledge(
        con,
        uid(),
        g["id"],
        exp["id"],
        f"{bet['title']}。改动：{bet['change']}。{conclusion}"
        + (
            f" {g['metric']} 观察差值 {judgment['delta']}，预注册范围 {judgment['expected']}。"
            if judgment["delta"] is not None
            else ""
        ),
        encode(result),
        grade,
        0.2 if grade == "未验证推断" else 0.65,
        bet["citations"][0] if bet["citations"] else None,
        now(),
    )
    log(con, g["id"], exp["treatment"], "实验结算", conclusion, "experiment")


def decide_experiment(con, eid, rollout):
    e = experiments_db.get(con, eid)
    if e["status"] != "decide":
        raise Problem("实验尚未结算，或已决策")
    rev = e["treatment"] if rollout else e["control"]
    scope = experiments_db.scope(con, eid)
    if scope:
        experiments_db.record_progress(con, rev, scope["scope"])
    games_db.publish(con, rev, e["game"])
    experiments_db.finish(con, "promoted" if rollout else "rolled_back", eid)
    log(
        con,
        e["game"],
        rev,
        "发布服务",
        "实验版本已全量发布" if rollout else "已回到对照版本",
        "release",
    )
