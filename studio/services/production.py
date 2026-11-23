"""Execute production nodes and persist successful handoffs independently."""

import asyncio
import json

import quickjs

from studio import acceptance, agents, cartridge, skillbook
from studio import context as project_context
from studio.domain.revision import NEXT, STEPS
from studio.infra.repositories import games as games_db
from studio.infra.repositories import proposals as proposals_db
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import db, encode, log
from studio.services.production_nodes import prepare_request, produce_artifact
from studio.services.revisions import checkpoint
from studio.settings import BASE_RULES


async def produce(rev_id, stage):
    with db() as con:
        revision = revisions_db.get(con, rev_id)
        if revision["stage"] != stage:
            return
        game = games_db.get(con, revision["game"])
        parent = (
            revisions_db.find_design(con, revision["parent"])
            if revision["parent"]
            else None
        )
        proposal = (
            proposals_db.find_decision(con, revision["proposal"])
            if revision["proposal"]
            else None
        )
    prior = json.loads(parent["docs"]) if parent else {}
    docs = json.loads(revision["docs"])
    context = await stage_context(revision, game, docs, prior, proposal)
    revision["project_title"] = game["title"]
    if stage == "design" and docs.get("impact_request") and "impact" not in docs:
        await apply_impact(revision, docs, context)

    for key in STEPS[stage]:
        if key in docs:
            continue
        if key == "validation":
            try:
                bundle, proof = await build_revision(revision, docs)
            except (ValueError, TypeError, KeyError, quickjs.JSException) as exc:
                return await repair_build(revision, docs, "构建回归：" + str(exc)[:400])
            checkpoint(rev_id, stage, key, proof, "构建服务", bundle=bundle)
            docs[key] = proof
            continue
        role, schema, data = await prepare_request(key, revision, docs, prior, context)
        value, provider = await produce_artifact(
            key, role, schema, data, revision, game, docs
        )
        if key == "quality_report" and value["blockers"]:
            return await repair_build(
                revision, docs, "独立评审：" + "；".join(value["blockers"])
            )
        checkpoint(rev_id, stage, key, value, role, provider)
        docs[key] = value
    advance_stage(revision, stage)


async def stage_context(revision, game, docs, prior, proposal):
    stage, rev_id = revision["stage"], revision["id"]
    if "context_snapshot" not in docs:
        with db(True) as con:
            docs["context_snapshot"] = project_context.capture(con, revision["game"])
            revisions_db.save_docs(con, encode(docs), rev_id)
    snapshot = docs["context_snapshot"]
    binding = await skillbook.pin("revision:" + snapshot["id"], "production")
    context = {
        "_memory": snapshot,
        "_run_binding": binding,
        "task": "production",
        "title": game["title"],
        "brief": game["brief"],
        "metric": game["metric"],
        "bounds": game["bounds"],
        "review_notes": revision["notes"],
        "request_stage": stage,
        "rules": BASE_RULES,
    }
    if docs.get("build_feedback"):
        context["mandatory_fix"] = docs["build_feedback"]["summary"]
    if proposal:
        context["approved_proposal"] = json.loads(proposal["doc"]).get("bet")
    if prior:
        context["previous_design"] = prior.get("gdd")
    if "research" in docs:
        context["research_report"] = {
            k: v for k, v in docs["research"].items() if k != "_run"
        }
    return context


async def apply_impact(revision, docs, context):
    rev_id = revision["id"]
    impact, provider = await agents.consult(
        "Producer",
        agents.Impact,
        {
            **context,
            "request": docs["impact_request"],
            "available": list(docs),
            "design": docs.get("gdd"),
            "entities": [s["id"] for s in docs.get("art", {}).get("sprites", [])],
        },
    )
    affected = set(impact["affected"])
    if impact["entities"]:
        affected.update(("gdd", "art", "game_code"))
    if "levels" in affected:
        affected.add("level_code")
    if "art" in affected:
        docs.pop("art_spec", None)
    for key in affected | {
        "route_design",
        "route_build",
        "validation",
        "quality_report",
    }:
        docs.pop(key, None)
    docs["impact"] = impact
    docs.pop("impact_request", None)
    with db(True) as con:
        revisions_db.invalidate_design(con, encode(docs), rev_id)
        log(
            con,
            revision["game"],
            rev_id,
            "Producer",
            impact["reason"] + " [" + provider + "]",
            "artifact",
        )


async def build_revision(revision, docs):
    bundle, result = await asyncio.to_thread(cartridge.compile_bundle, revision, docs)
    if revision["parent"] and revision["proposal"]:
        with db() as con:
            approval = proposals_db.approval(con, revision["proposal"])
            control = revisions_db.bundle(con, revision["parent"])["bundle"]
        result["approved_checks"] = await asyncio.to_thread(
            acceptance.verify,
            control,
            bundle,
            json.loads(approval["doc"])["bet"],
            json.loads(approval["evidence"]),
        )
    return bundle, result


def advance_stage(revision, stage):
    rev_id = revision["id"]
    with db(True) as con:
        cur = revisions_db.delivery(con, rev_id)
        if cur["stage"] != stage:
            return
        if not all(k in json.loads(cur["docs"]) for k in STEPS[stage]) or (
            stage == "build" and not cur["bundle"]
        ):
            raise RuntimeError("缺少阶段交付物")
        revisions_db.finish_stage(con, NEXT[stage], rev_id)
        log(
            con,
            revision["game"],
            rev_id,
            "制作人",
            {
                "research": "请选择调研参考图。",
                "interpret": "调研报告已完成，请选择玩法方向。",
                "design": "策划、美术与关卡方案已备齐，等待审阅。",
                "build": "构建与逐关验证通过，等待试玩验收。",
            }[stage],
            "gate",
        )


async def repair_build(rev, docs, diagnostic):
    attempts = docs.get("build_feedback", {}).get("attempts", 0)
    if attempts >= 2:
        raise ValueError(diagnostic)
    repairs = {"game_code", "level_code", "validation", "quality_report"}
    if rev.get("proposal") and rev.get("parent"):
        with db() as con:
            bet = json.loads(proposals_db.decision(con, rev["proposal"])["doc"])["bet"]
        kinds = {c["kind"] for c in bet.get("checks", [])}
        if kinds == {"parameter"}:
            repairs.discard("game_code")
        elif kinds and "parameter" not in kinds:
            repairs.discard("level_code")
    sources = {
        key: docs[key]["source"] for key in ("game_code", "level_code") if key in docs
    }
    for key in repairs:
        docs.pop(key, None)
    docs["build_feedback"] = {
        "attempts": attempts + 1,
        "summary": diagnostic,
        "sources": sources,
    }
    with db(True) as con:
        revisions_db.invalidate_repair(con, encode(docs), rev["id"])
        log(con, rev["game"], rev["id"], "质量评审", diagnostic, "repair")
    await produce(rev["id"], "build")
