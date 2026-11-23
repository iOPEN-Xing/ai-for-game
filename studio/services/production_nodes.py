"""Prepare role-scoped production inputs and validate each returned artifact."""

import asyncio

import quickjs

from studio import acceptance, agents, cartridge, image_service, research
from studio.domain.artifacts import DOCS, REFERENCE
from studio.domain.revision import STEPS
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import db
from studio.services.revisions import checkpoint


async def prepare_request(key, revision, docs, prior, context):
    stage, rev_id = revision["stage"], revision["id"]
    data = {**context, "_node": key}
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
        names = {
            "discovery": "GameplayResearch",
            "research": "GameplayResearch",
            "gdd": "Planner",
            "art": "ArtDesigner",
            "levels": "LevelDesigner",
            "game_code": "GameCoder",
            "level_code": "LevelCoder",
        }
        data["next_required_role"] = next(
            (names[k] for k in STEPS[stage] if k in names and k not in docs),
            {
                "research": "GameplayResearch",
                "interpret": "GameplayResearch",
                "design": "Planner",
                "build": "GameCoder",
            }[stage],
        )
        role, schema = "Producer", agents.Route
    elif key == "discovery":
        role, schema = "GameplayResearch", agents.SearchBrief
    elif key in ("visual_analysis", "research"):
        refs = [
            ref
            for ref in docs["discovery"]["references"]
            if ref["id"] in docs["selected_references"]
        ]
        data["selected_references"] = refs
        if key == "visual_analysis":
            role, schema = "GameplayResearch", agents.VisualAnalysis
            data["_image_inputs"] = await asyncio.gather(
                *(
                    research.frozen_image(context["_run_binding"]["id"], ref)
                    for ref in refs
                )
            )
        else:
            role, schema = "GameplayResearch", agents.Research
            data["observations"] = docs["visual_analysis"]
            if "rule_sources" not in docs:
                queries = docs["visual_analysis"]["queries"]
                rules = {
                    "queries": queries,
                    "items": await research.rule_sources(queries),
                }
                checkpoint(rev_id, stage, "rule_sources", rules, "检索服务")
                docs["rule_sources"] = rules
            data["rule_sources"] = docs["rule_sources"]["items"]
            data["indexed_playable_references"] = REFERENCE

            def stream_summary(summary):
                with db(True) as con:
                    revisions_db.stream_research(con, summary, rev_id)

            data["_on_summary"] = stream_summary
    elif key == "gdd":
        role, schema = "Planner", agents.Design
        data["level_parameter_contract"] = cartridge.CURVE_ABI
    elif key == "art":
        role, schema = "ArtDesigner", agents.ArtSpec
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
        role, schema = "LevelDesigner", agents.Levels
        data["level_parameter_contract"] = cartridge.CURVE_ABI
    elif key == "game_code":
        role, schema = "GameCoder", agents.Source
        data.update(
            abi=cartridge.GAME_ABI,
            starter=last_source
            or prior.get(key, {}).get("source", cartridge.source("game-template.js")),
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
    elif key == "level_code":
        role, schema = "LevelCoder", agents.Source
        data.update(
            abi=cartridge.CURVE_ABI,
            starter=last_source
            or prior.get(key, {}).get("source", cartridge.source("curve-template.js")),
            game_module=docs["game_code"]["source"],
        )
    elif key == "quality_report":
        role, schema = "QualityReviewer", agents.Quality
        with db() as con:
            build = revisions_db.bundle(con, rev_id)["bundle"]
        pack = acceptance.read_pack(build)
        data.update(
            compiled_bundle=build,
            materialized_levels=pack["levels"],
            level_factory=cartridge.source("factory.js"),
            level_parameter_contract=cartridge.CURVE_ABI,
            source=docs["game_code"]["source"],
            parameters=docs["level_code"]["source"],
            verification=docs["validation"],
        )
    else:
        raise ValueError(f"未知生产节点 {key}")
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
            value, provider = await agents.consult(role, schema, data)
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
                if data.get("previous_art") and touched:
                    value = image_service.merge_assets(
                        data["previous_art"],
                        value,
                        touched,
                        (docs.get("impact") or {}).get("audio", False),
                    )
                if "art_references" in data:
                    value["research_references"] = data["art_references"]
                checkpoint(rev_id, stage, "art_spec", value, role, provider)
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
                    checkpoint(rev_id, stage, "build_feedback", feedback, "构建服务")
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
    elif key == "levels":
        family = data["selected_direction"]["mechanic"]
        if value["game_type"] != family or (
            family == "trail" and value["mode"] != "prefab"
        ):
            raise ValueError("game_type 必须匹配方向，trail 必须使用 prefab")
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
        game = value["source"] if key == "game_code" else docs["game_code"]["source"]
        await asyncio.to_thread(cartridge.verify_game, game, levels)
