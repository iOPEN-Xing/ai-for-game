"""Production quality contracts, from a team's level brief through the playable package."""

import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from scripts.build_sample import SAMPLES, build
from studio.application.agents import gateway
from studio.application.harness.production.nodes import next_required_role
from studio.application.prompts.builder import output_schema
from studio.application.tools import cartridge
from studio.domain.agent_outputs import ChapterLevels
from studio.domain.deliberation import ParameterChange
from studio.domain.revision import production_steps
from studio.settings import WEB
from tests.fixtures.model import scripted
from tests.support import IDEA, StudioCase


class ChapterProductionTests(StudioCase):
    def test_explicit_24_levels_reach_authoring_host_blueprint_and_operations(self):
        created = self.post("games", {**IDEA, "level_count": 24}, 201)
        self.game, self.rev = created["game"], created["rev"]
        self.work()
        self.decision("select_references", reference_ids=["beacon", "island"])
        self.work()
        self.decision("choose", choice=0)
        self.work()
        self.decision("approve")
        calls = []

        async def capture(role, schema, context):
            if role in ("GameCoder", "LevelCoder"):
                calls.append(role)
            if role == "GameCoder":
                self.assertIn("level_generator", context)
                self.assertEqual(
                    [entry["index"] for entry in context["chapter_samples"]],
                    [1, 9, 13, 17, 24],
                )
            if role == "QualityReviewer":
                self.assertEqual(
                    [ch["end"] for ch in context["chapter_proof"]], [8, 16, 24]
                )
            return await scripted(role, schema, context)

        with patch.object(gateway, "consult", side_effect=capture):
            self.work()
        self.assertEqual(calls, ["LevelCoder", "GameCoder"])
        endpoint = "revisions/" + self.rev + "/levels"
        pack = self.get(endpoint)
        self.assertEqual(
            pack["levels"][-1]["chapter"], {"number": 3, "level": 8, "length": 8}
        )
        self.assertTrue(
            all(p["idleTimeout"] and p["checkedScenes"] >= 2 for p in pack["proof"])
        )
        game = self.post(
            "play/" + self.game + "/open",
            {"player": "quality-preview-0001", "preview": self.rev, "level": 24},
        )["game"]
        self.assertEqual(
            (game["viewport"], game["count"], len(game["chapters"])), ("square", 24, 3)
        )
        self.assertEqual(game["level_entry"]["chapter"], pack["levels"][-1]["chapter"])
        self.assertEqual(
            ParameterChange(
                kind="parameter", level=24, field="seconds", before=60, after=73
            ).level,
            24,
        )
        rev = self.get("games/" + self.game)["revision"]
        self.post(
            endpoint,
            {
                "serial": rev["serial"],
                "seed": rev["seed"],
                "level": 24,
                "values": {"seconds": 73},
            },
        )
        self.work()
        self.assertEqual(self.get(endpoint)["levels"][23]["seconds"], 73)

    def test_old_revision_order_and_new_or_short_count_contracts(self):
        self.assertEqual(next_required_role("build", {}), "GameCoder")
        self.assertEqual(next_required_role("build", {"level_brief": {}}), "LevelCoder")
        self.assertIn("validation", production_steps("build", {}))
        for requested, expected in ((None, (12, 24)), (5, (5, 5))):
            context = {"level_brief": {"requested_count": requested}}
            limit = output_schema(ChapterLevels, None, context)["properties"]["count"]
            self.assertEqual((limit["minimum"], limit["maximum"]), expected)
        self.post("games", {**IDEA, "level_count": 25}, 422)


class MaterializedQualityTests(unittest.TestCase):
    def setUp(self):
        self.design = {
            "game_type": "custom",
            "count": 12,
            "chapters": [
                {"start": i, "title": t, "goal": "点亮这一段航道", "rule": r}
                for i, t, r in (
                    (1, "教学", "点选目标"),
                    (5, "换线", "判断顺序"),
                    (9, "合流", "规划剩余资源"),
                )
            ],
        }
        self.curve = """function parameters(i,total,seed,chapter) {
            return {quota:3,seconds:60,radius:.09,pace:1.2,size:7,content:{gate:chapter.number}};
        }"""
        self.template = cartridge.source("game-template.js")

    def test_authored_content_is_reproducible_and_flat_or_oversized_data_is_rejected(
        self,
    ):
        levels, entries = cartridge.levels_for(self.design, 7, self.curve)
        self.assertEqual(
            [item["content"]["gate"] for item in levels], [1] * 4 + [2] * 4 + [3] * 4
        )
        self.assertEqual(entries[-1]["chapter"], levels[-1]["chapter"])
        self.assertEqual(levels, cartridge.levels_for(self.design, 7, self.curve)[0])
        with self.assertRaisesRegex(ValueError, "三种实际"):
            cartridge.levels_for(
                self.design, 7, self.curve.replace("gate:chapter.number", "gate:1")
            )
        with self.assertRaisesRegex(ValueError, "2048"):
            cartridge.levels_for(
                self.design, 7, self.curve.replace("chapter.number", "'X'.repeat(3000)")
            )
        raw = {
            **self.design,
            "data_structure": "棋盘",
            "production": "带解生成",
            "verification": "回放",
            "curve": "递进",
            "mode": "runtime",
        }
        ChapterLevels.model_validate(raw)
        with self.assertRaises(ValidationError):
            ChapterLevels.model_validate(
                {**raw, "chapters": list(reversed(raw["chapters"]))}
            )
        with self.assertRaises(ValidationError):
            ChapterLevels.model_validate(
                {**raw, "chapters": [{**c, "goal": "    "} for c in raw["chapters"]]}
            )

    def test_default_loop_static_board_and_non_terminating_idle_cannot_pass(self):
        levels, _ = cartridge.levels_for(self.design, 37, self.curve)
        with self.assertRaisesRegex(ValueError, "默认样板"):
            cartridge.verify_game(self.template, levels)
        static = self.template.replace(
            "return baseDraw(s, L);", "return [{kind:'rect',x:.1,y:.1,w:.5,h:.5}];"
        )
        with self.assertRaisesRegex(ValueError, "visible response"):
            cartridge.verify_game(static, levels[:1])
        no_timeout = self.template.replace(
            "return baseStep(s, e, L);", "return e.type==='tick' ? s : baseStep(s,e,L);"
        )
        with self.assertRaisesRegex(ValueError, "timeout loss"):
            cartridge.verify_game(no_timeout, levels[:1])

    def test_draw_contract_matches_polygon_and_opacity_in_the_player(self):
        levels, _ = cartridge.levels_for(self.design, 37, self.curve)
        marker = "{kind:'polygon',x:.5,y:.5,points:[[0,0],[.1,0],[0,.15]],opacity:.3}"
        code = self.template.replace(
            "return baseDraw(s, L);", "return [...baseDraw(s,L)," + marker + "];"
        )
        (proof,) = cartridge.verify_game(code, levels[:1])
        self.assertFalse(proof["fixedInputWon"])
        self.assertEqual(proof["afterMistake"], "recovered")
        self.assertTrue(proof["touchTapReplay"])
        with self.assertRaisesRegex(ValueError, "coordinate pairs"):
            cartridge.verify_game(code.replace("[0,.15]", "[0]"), levels[:1])
        with self.assertRaisesRegex(ValueError, "opacity"):
            cartridge.verify_game(code.replace("opacity:.3", "opacity:3"), levels[:1])

    def test_public_campaign_matches_a_fresh_release_build(self):
        for slug, filename in SAMPLES.items():
            with self.subTest(slug=slug):
                sample = build(slug)
                self.assertEqual(sample["origin"]["verified_levels"], 12)
                self.assertEqual(sample, json.loads((WEB / filename).read_bytes()))

    def test_perfect_runs_do_not_hide_a_dead_end_after_the_first_mistake(self):
        levels, _ = cartridge.levels_for(self.design, 37, self.curve)
        code = self.template.replace(
            "return baseStep(s, e, L);",
            "return s.mistakes && e.type === 'tap' ? s : baseStep(s, e, L);",
        )
        (proof,) = cartridge.verify_game(code, levels[:1])
        self.assertEqual(proof["afterMistake"], "unfinished")
        self.assertGreater(proof["playerInputs"], 0)

        broken_touch = self.template.replace(
            "return baseStep(s, e, L);",
            "if(e.type === 'press') s.done=true; return baseStep(s,e,L);",
        )
        with self.assertRaisesRegex(ValueError, "real touch"):
            cartridge.verify_game(broken_touch, levels[:1])
