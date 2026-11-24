"""Deterministic role outputs for offline workflow tests."""

from studio.application.tools import cartridge
from studio.domain import agent_outputs as outputs


async def scripted(role, schema, data):
    family = data.get("selected_direction", {}).get("mechanic", "pulse")
    phase = data.get("phase")
    if phase == "challenge":
        out = {
            "issues": [
                {
                    "owner": "GameDesigner",
                    "question": "这个改动如何对应首关表现？",
                    "refs": ["metrics"],
                }
            ]
        }
    elif phase == "reply":
        out = {
            "supported": True,
            "response": "已核对真实计分回放和首关分母。",
            "refs": ["probe:1"],
        }
    elif phase == "hold":
        out = {
            "reason": "需要更多同版本对局",
            "required": ["核对首关正式分母"],
            "refs": ["metrics"],
        }
    elif phase == "adjudicate":
        out = {
            "disposition": "accepted",
            "reason": "核对问题和受众分母",
            "refs": ["metrics"],
        }
    elif phase == "verify_issue":
        out = {"closed": True, "basis": "核对当前裁决与提案", "refs": ["metrics"]}
    elif phase == "final_review":
        out = {
            "approved": True,
            "reason": "已核对提案和实际检验方式",
            "refs": ["metrics"],
            "rulings": [
                {"issue": key, "closed": True, "basis": "已见对应回复"}
                for key in data["questions"]
            ],
        }
        if data["task"] == "new_game":
            known = data["evidence"]["portfolio"]
            out["portfolio_check"] = {
                "closest_title": known[0] if known else None,
                "verdict": "distinct",
                "difference": "核心循环不同",
            }
    elif phase == "candidates":
        out = {
            "evidence": "首关样本与受众",
            "recommendation": "比较两个玩法",
            "objection": "样本有限",
            "refs": ["metrics"],
            "candidates": [
                {
                    "title": t,
                    "audience": "活动访客",
                    "loop": loop,
                    "difference": loop,
                    "evidence": "metrics",
                }
                for t, loop in (
                    ("海岸接力", "点亮移动信标"),
                    ("邮路图", "规划连通路径"),
                )
            ],
        }
    elif phase == "constraints" and role in ("Analyst", "Reviewer"):
        out = {
            "evidence": "已检查观察窗",
            "recommendation": "根据实际指标设定范围",
            "objection": "样本有限",
            "refs": ["dead_ends", "metrics"],
        }
        if role == "Analyst":
            out.update(
                audience="活动访客",
                requirements=["首关可玩"],
                benchmark="按当前分母判断",
            )
        else:
            out.update(
                examined=[i["id"] for i in data["evidence"]["dead_ends"]],
                definition_check="核对正式对局分母",
            )
    elif role == "Producer" and schema is outputs.Impact:
        out = {
            "reason": "只新增一个实体",
            "affected": ["gdd", "art", "game_code"],
            "entities": ["star"],
            "audio": False,
        }
    elif role == "Producer":
        out = {
            "summary": "按门禁调度",
            "focus": ["首次触摸"],
            "next_role": data["next_required_role"],
        }
    elif schema is outputs.SearchBrief:
        out = {"game_name": "信标", "queries": ["beacon game", "lighthouse puzzle"]}
    elif schema is outputs.VisualAnalysis:
        out = {
            "observations": {
                r["id"]: "图中有清晰的点击目标" for r in data["selected_references"]
            },
            "mechanics": "分辨位置并点按",
            "queries": ["tile game rules"],
        }
    elif role == "GameplayResearch":
        out = {
            "summary": "比较实时采集和路径规划",
            "directions": [
                {
                    "title": name,
                    "mechanic": kind,
                    "pitch": "依次抵达灯塔",
                    "interaction": "点按",
                    "visual": "海雾和灯塔",
                    "color": "#e7995a",
                    "reference_ids": [r["id"] for r in data["selected_references"][:2]],
                }
                for kind, name in (("pulse", "逐灯采样"), ("trail", "探路"))
            ],
        }
    elif role == "Planner":
        out = {
            k: "点亮信标"
            for k in (
                "title",
                "core_loop",
                "controls",
                "win_condition",
                "failure_condition",
                "difficulty",
            )
        }
        out["assets"] = ["信标"]
        out["illustrated_entities"] = [
            {"id": "tower", "title": "塔"},
            {"id": "boat", "title": "船"},
        ]
        for entity in (data.get("impact") or {}).get("entities", []):
            if entity not in ("boat", "tower"):
                out["illustrated_entities"].append({"id": entity, "title": entity})
        out["product_hypothesis"] = {
            "audience": "活动访客",
            "player_value": "看见航路连成线",
            "activation": "成功点亮首座信标",
            "metric": data["metric"],
            "validation": "按正式开局观察首局完成情况",
        }
    elif role == "ArtDesigner":
        out = {
            "style": "图形和光圈区分灯塔",
            "base_anchor": "入选的灯塔图",
            "style_anchor": "剪纸海港",
            "entity_anchor": "圆窗和尖顶",
            "background": "#f7e9c7",
            "ink": "#23342a",
            "accent": "#c65e45",
            "motif": "beacon",
            "tempo": 96,
            "root_hz": 300,
            "sprites": [
                {
                    "id": "tower",
                    "title": "塔",
                    "layers": [
                        {
                            "shape": "rect",
                            "points": [[0.2, 0.1], [0.8, 0.9]],
                            "color": "#e46b43",
                        }
                    ],
                },
                {
                    "id": "boat",
                    "title": "船",
                    "layers": [
                        {
                            "shape": "polygon",
                            "points": [[0.1, 0.5], [0.9, 0.5], [0.5, 0.85]],
                            "color": "#397f78",
                        }
                    ],
                },
            ],
            "melody": {
                "bgm": [0, 5, 7, 3],
                "ui": [3],
                "hit": [4, 7],
                "miss": [3, 0],
                "win": [0, 4, 7, 12],
            },
        }
    elif role == "LevelDesigner":
        out = {
            "game_type": family,
            "data_structure": "点位与配额",
            "production": "依据 Seed",
            "verification": "回放输入",
            "curve": "配额递增",
            "mode": "prefab" if family == "trail" else "runtime",
            "count": 4,
        }
    elif role == "GameCoder":
        code = cartridge.source("game-template.js")
        if "approved_proposal" in data:
            code = code.replace(
                "return baseStep(s, e, L);",
                "const hits=s.hits; baseStep(s,e,L); if(s.hits>hits) s.score+=2; return s;",
            )
        out = {"summary": "实现计分逻辑", "source": code}
    elif role == "LevelCoder":
        out = {
            "summary": "编译确定性曲线",
            "source": cartridge.source("curve-template.js"),
        }
    elif role == "QualityReviewer":
        assert all("points" in level for level in data["materialized_levels"])
        assert "makeLevel" in data["level_factory"] and data["compiled_bundle"]
        out = {
            "quick_start": "点按标记完成采样。",
            "evidence": "独立检查输入与胜负",
            "blockers": [],
            "playtest_focus": ["首关触摸反馈"],
        }
    elif role == "Moderator":
        out = {
            "title": "增加首次命中反馈",
            "change": "命中加分",
            "basis": "参考当前开局样本",
            "low": 0,
            "high": 8,
            "falsifier": "实验通关率低于对照",
            "objections": "样本有限",
            "days": 1,
            "min_players": 2,
            "citations": [],
            "refs": ["metrics", "probe:1"],
            "resolutions": [
                {
                    "issue": key,
                    "disposition": "accepted",
                    "reason": "采纳首关证据",
                    "refs": ["metrics"],
                }
                for key in data["questions"]
            ],
        }
        if data["task"] == "new_game":
            out.update(
                title="海岸接力",
                selected="海岸接力",
                discarded=[{"title": "邮路图", "reason": "更偏向规划受众"}],
            )
        else:
            score = data["evidence"]["probes"]["1"]["observed"]["score"]
            out["checks"] = [
                {
                    "kind": "replay",
                    "level": 1,
                    "field": "score",
                    "before": score,
                    "after": score + 2,
                }
            ]
    else:
        out = {
            "evidence": "冻结的真实样本",
            "recommendation": "核对首关",
            "objection": "注意分母",
            "refs": ["metrics", "game.js"] if role == "Engineer" else ["metrics"],
        }
    if "blocker" in schema.model_fields:
        out.setdefault("blocker", None)
    out = schema.model_validate(out).model_dump()
    out["_run"] = {"role": role, "provider": "test", "model": "fixture", "skills": {}}
    return out, "test"
