"""Prepare role-scoped production inputs and validate each returned artifact."""

import asyncio

import quickjs

from studio.application.agents import gateway
from studio.application.tools import acceptance, cartridge, image_service, research
from studio.application.usecases.games.revisions import checkpoint
from studio.domain import agent_outputs as outputs
from studio.domain.artifacts import DOCS, REFERENCE
from studio.domain.levels import level_count_range, sample_level_indices
from studio.domain.revision import STEPS, production_steps
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import db

# The producer routes to the author of the next outstanding deliverable.
DELIVERABLES = {
    "discovery": ("GameplayResearch", outputs.SearchBrief),
    "visual_analysis": ("GameplayResearch", outputs.VisualAnalysis),
    "research": ("GameplayResearch", outputs.Research),
    "gdd": ("Planner", outputs.Design),
    "art": ("ArtDesigner", outputs.ArtSpec),
    "levels": ("LevelDesigner", outputs.Levels),
    "game_code": ("GameCoder", outputs.Source),
    "level_code": ("LevelCoder", outputs.Source),
}
AGENT_NODES = {
    **DELIVERABLES,
    **{
        node: ("Producer", outputs.Route)
        for stage in STEPS.values()
        for node in stage
        if node.startswith("route_")
    },
    "impact": ("Producer", outputs.Impact),
    "quality_report": ("QualityReviewer", outputs.Quality),
}


def next_required_role(stage, completed):
    deliverables = [
        key for key in production_steps(stage, completed) if key in DELIVERABLES
    ]
    key = next((key for key in deliverables if key not in completed), deliverables[0])
    return DELIVERABLES[key][0]


async def prepare_request(key, revision, docs, prior, context):
    stage, rev_id = revision["stage"], revision["id"]
    try:
        role, schema = AGENT_NODES[key]
    except KeyError:
        raise ValueError(f"未知生产节点 {key}") from None
    data = {**context, "_node": key}
    if "level_brief" in docs:
        data["level_brief"] = docs["level_brief"]
        schema = {"gdd": outputs.GameDesign, "levels": outputs.ChapterLevels}.get(
            key, schema
        )
    last_source = docs.get("build_feedback", {}).get("sources", {}).get(key)
    if last_source:
        data["previous_submission"] = {"source": last_source}
    with db() as con:
        data["review_notes"] = revisions_db.current_notes(con, rev_id)["notes"]
    if docs.get("impact"):
        data["impact"] = docs["impact"]
    if revision["choice"] is not None and "research" in docs:
        data["selected_direction"] = docs["research"]["directions"][revision["choice"]]
    for field in ("route_" + stage, "gdd", "art", "levels"):
        if field in docs:
            data[field] = docs[field]
    if key.startswith("route_"):
        data["next_required_role"] = next_required_role(stage, docs)
    elif key in ("visual_analysis", "research"):
        refs = [
            ref
            for ref in docs["discovery"]["references"]
            if ref["id"] in docs["selected_references"]
        ]
        data["selected_references"] = refs
        if key == "visual_analysis":
            data["_image_inputs"] = await asyncio.gather(
                *(
                    research.frozen_image(context["_run_binding"]["id"], ref)
                    for ref in refs
                )
            )
        else:
            data["observations"] = docs["visual_analysis"]
            if "rule_sources" not in docs:
                queries = docs["visual_analysis"]["queries"]
                rules = {
                    "queries": queries,
                    **await research.rule_sources(queries),
                }
                checkpoint(
                    rev_id,
                    stage,
                    "rule_sources",
                    rules,
                    "检索服务",
                    serial=revision["serial"],
                )
                docs["rule_sources"] = rules
            data["rule_sources"] = docs["rule_sources"]["items"]
            data["rule_search"] = {
                k: v for k, v in docs["rule_sources"].items() if k != "items"
            }
            data["rule_search"].setdefault("status", "legacy")
            data["indexed_playable_references"] = REFERENCE

            def stream_summary(summary):
                with db(True) as con:
                    revisions_db.stream_research(
                        con, summary, rev_id, revision["serial"]
                    )

            async def publish_summary(summary):
                await asyncio.to_thread(stream_summary, summary)

            data["_on_summary"] = publish_summary
    elif key == "gdd":
        data["level_parameter_contract"] = cartridge.CURVE_ABI
    elif key == "art":
        direction = data.get("selected_direction", {})
        refs = direction.get("references", [])
        if refs and "art_spec" not in docs:
            analysis = docs.get("visual_analysis", {})
            original_run = analysis.get("reference_run") or analysis.get(
                "_run", {}
            ).get("run_id")
            ids = [ref["id"] for ref in refs]
            if original_run:
                data["_image_inputs"] = research.archived_images(
                    original_run, context["_run_binding"]["id"], ids
                )
            else:
                # Legacy reports may predate frozen pixels. Bind their references once
                # to the current revision and record that provenance explicitly.
                original_run = context["_run_binding"]["id"]
                data["_image_inputs"] = await asyncio.gather(
                    *(research.frozen_image(original_run, ref) for ref in refs)
                )
            data["art_references"] = {
                "run": original_run,
                "ids": ids,
                "observations": {
                    ref: analysis.get("observations", {}).get(ref) for ref in ids
                },
            }
        previous_art = docs.get("prior_art") or prior.get("art")
        if previous_art:
            data["previous_art"] = previous_art
        data["impact"] = docs.get("impact")
    elif key == "levels":
        data["level_parameter_contract"] = cartridge.CURVE_ABI
    elif key == "game_code":
        data.update(
            abi=cartridge.GAME_ABI,
            starter=last_source
            or prior.get(key, {}).get("source")
            or ("" if "level_brief" in docs else cartridge.source("game-template.js")),
            helpers=cartridge.source("base.js"),
            level_example="L.points contains {x,y,lane}; trail grid is a flat array of 0/1.",
        )
        curve = docs.get("level_code", {}).get("source") or cartridge.source(
            "curve-template.js"
        )
        code_levels, _ = await asyncio.to_thread(
            cartridge.levels_for, docs["levels"], revision["seed"], curve
        )
        data["sample_level"] = code_levels[0]
        if docs["levels"].get("chapters"):
            data["chapter_samples"] = [
                code_levels[i] for i in sample_level_indices(docs["levels"])
            ]
            data["level_generator"] = curve
    elif key == "level_code":
        data.update(
            abi=cartridge.CURVE_ABI,
            starter=last_source
            or prior.get(key, {}).get("source", cartridge.source("curve-template.js")),
        )
        if existing := docs.get("game_code") or prior.get("game_code"):
            data["game_module"] = existing["source"]
    elif key == "quality_report":
        with db() as con:
            build = revisions_db.bundle(con, rev_id)["bundle"]
        pack = acceptance.read_pack(build)
        data.update(
            compiled_bundle=build,
            materialized_levels=(
                [pack["levels"][i] for i in sample_level_indices(docs["levels"])]
                if pack.get("chapters")
                else pack["levels"]
            ),
            level_factory=cartridge.source("factory.js"),
            level_parameter_contract=cartridge.CURVE_ABI,
            source=docs["game_code"]["source"],
            parameters=docs["level_code"]["source"],
            verification=docs["validation"],
            chapter_proof=pack.get("chapter_proof", []),
        )
    return role, schema, data


async def produce_artifact(key, role, schema, data, revision, game, docs):
    stage, rev_id = revision["stage"], revision["id"]
    for attempt in range(3):
        if key == "art" and "art_spec" in docs:
            value, provider = (
                docs["art_spec"],
                docs["art_spec"].get("_run", {}).get("provider", "checkpoint"),
            )
        else:
            value, provider = await gateway.consult(role, schema, data)
        if key == "art":
            if "art_spec" not in docs:
                approved_entities = docs["gdd"].get("illustrated_entities")
                if approved_entities and {s["id"] for s in value["sprites"]} != {
                    e["id"] for e in approved_entities
                }:
                    diagnostic = "生图实体须与 GDD 的 illustrated_entities 逐项一致。请使用原 ID，移除代码绘制资源。"
                    if attempt == 2:
                        raise ValueError(diagnostic)
                    data.update(previous_submission=value, build_diagnostic=diagnostic)
                    continue
                checks = data.get("approved_proposal", {}).get("checks", [])
                touched = {c["entity"] for c in checks if c["kind"] == "asset"} or set(
                    (docs.get("impact") or {}).get("entities", [])
                )
                impact = docs.get("impact") or {}
                if data.get("previous_art") and (
                    touched or (impact.get("audio") and impact.get("audio_tracks"))
                ):
                    value = image_service.merge_assets(
                        data["previous_art"],
                        value,
                        touched,
                        impact.get("audio", False),
                        impact.get("audio_tracks"),
                    )
                if "art_references" in data:
                    value["research_references"] = data["art_references"]
                checkpoint(
                    rev_id,
                    stage,
                    "art_spec",
                    value,
                    role,
                    provider,
                    serial=revision["serial"],
                )
                docs["art_spec"] = value
            await image_service.materialize(value)
        try:
            await validate_artifact(key, data, value, revision, game, docs)
            return value, provider
        except (ValueError, TypeError, KeyError, quickjs.JSException) as exc:
            if attempt == 2:
                if key in ("game_code", "level_code"):
                    feedback = dict(docs.get("build_feedback", {}))
                    feedback["summary"] = str(exc)[:650]
                    feedback["sources"] = {
                        **feedback.get("sources", {}),
                        key: value["source"],
                    }
                    checkpoint(
                        rev_id,
                        stage,
                        "build_feedback",
                        feedback,
                        "构建服务",
                        serial=revision["serial"],
                    )
                raise ValueError(
                    DOCS[key] + "未通过构建检查：" + str(exc)[:250]
                ) from None
            data.update(previous_submission=value, build_diagnostic=str(exc)[:500])
    raise RuntimeError("没有获得通过校验的交付物")


async def validate_artifact(key, data, value, revision, game, docs):
    if key.startswith("route_"):
        expected = data["next_required_role"]
        if value["next_role"] != expected:
            raise ValueError("当前门禁后唯一合法路由为 " + expected)
    elif key == "gdd" and value["product_hypothesis"]["metric"] != game["metric"]:
        raise ValueError("产品验证指标必须使用项目选定的北极星 " + game["metric"])
    elif key == "gdd" and len(
        {entity["id"] for entity in value["illustrated_entities"]}
    ) != len(value["illustrated_entities"]):
        raise ValueError("GDD 的生图实体 ID 重复")
    elif key == "discovery":
        value.update(
            await research.discover(
                value["queries"], game["brief"] + " " + revision["notes"]
            )
        )
    elif key == "visual_analysis":
        if set(value["observations"]) != set(docs["selected_references"]):
            raise ValueError("需要逐张记录所选图片的观察，以原参考图 ID 为键")
        value["reference_run"] = data["_run_binding"]["id"]
    elif key == "research":
        research.attach(value["directions"], data["selected_references"])
        value["visual_observations"] = docs["visual_analysis"]["observations"]
        value["rule_sources"] = data["rule_sources"]
        value["rule_search"] = data["rule_search"]
    elif key == "levels":
        family = data["selected_direction"]["mechanic"]
        if value["game_type"] != family or (
            family == "trail" and value["mode"] != "prefab"
        ):
            raise ValueError("game_type 必须匹配方向，trail 必须使用 prefab")
        if "level_brief" in docs:
            low, high = level_count_range(docs["level_brief"])
            if not low <= value["count"] <= high:
                raise ValueError(f"本项目需要 {low} 至 {high} 关，须按创作要求编排章节")
    elif key in ("game_code", "level_code"):
        curve = (
            value["source"]
            if key == "level_code"
            else docs.get("level_code", {}).get(
                "source", cartridge.source("curve-template.js")
            )
        )
        levels, _ = await asyncio.to_thread(
            cartridge.levels_for, docs["levels"], revision["seed"], curve
        )
        game_source = (
            value["source"]
            if key == "game_code"
            else docs.get("game_code", {}).get("source")
        )
        if game_source:
            await asyncio.to_thread(cartridge.verify_game, game_source, levels)
