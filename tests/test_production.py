import asyncio
import io
import json
import zipfile
from unittest.mock import patch

from studio import agents, cartridge, worker
from tests.fixtures.model import scripted
from tests.support import IDEA, StudioCase


class ProductionTests(StudioCase):
    def test_review_gates_revision_replay_and_artifact_download(self):
        self.draft(choice=1)
        doc = self.get("games/" + self.game)
        self.assertEqual(doc["revision"]["stage"], "quality")
        self.assertEqual(
            len(doc["revision"]["docs"]["research"]["directions"][0]["references"]), 2
        )
        self.decision("accept", 409)
        self.play(preview=self.rev, quit=True)
        self.decision("accept", 409)
        pack = self.get("revisions/" + self.rev + "/levels")
        self.assertEqual(pack["mode"], "prefab")
        self.assertEqual(len(pack["regressions"]), 2)
        archive = zipfile.ZipFile(
            io.BytesIO(
                self.client.get("/api/revisions/" + self.rev + "/download").content
            )
        )
        self.assertTrue(
            {
                "asset.json",
                "Core_GDD.md",
                "Difficulty_Config.csv",
                "Level_Pack.json",
                "remoteEntry.js",
                "level-generator.js",
                "game.js",
                "sprite.png",
                "bgm.wav",
            }
            <= set(archive.namelist())
        )
        self.assertIn("sprite-boat.png", archive.namelist())
        self.assertNotEqual(
            archive.read("sprite-boat.png"), archive.read("sprite-tower.png")
        )
        self.assertNotIn("function maze(", archive.read("remoteEntry.js").decode())
        self.assertTrue(
            self.client.get(
                "/api/revisions/" + self.rev + "/design-media/hit"
            ).content.startswith(b"RIFF")
        )
        self.publish()
        self.assertEqual(self.get("operations")["report"]["total"]["starts"], 0)
        self.play()
        self.assertEqual(
            self.get("operations")["report"]["levels"][0]["win_rate"], 100.0
        )
        self.post(
            "play/" + self.game + "/open",
            {"player": "fresh-player-10000", "level": 4},
            422,
        )

    def test_partial_rework_and_stale_decisions(self):
        self.draft()
        before = self.get("games/" + self.game)["revision"]
        self.decision("revise", target="art", note="提高亮部对比")
        mid = self.get("games/" + self.game)["revision"]
        self.assertEqual(mid["docs"]["gdd"], before["docs"]["gdd"])
        self.assertNotIn("art", mid["docs"])
        self.assertIsNone(mid["bundle"])
        self.post(
            "revisions/" + self.rev + "/decision",
            {"serial": before["serial"], "action": "approve"},
            409,
        )
        self.work()
        updated = self.get("games/" + self.game)["revision"]
        self.assertEqual(updated["stage"], "plan")
        self.assertEqual(updated["docs"]["route_design"]["next_role"], "ArtDesigner")

    def test_trail_must_play_the_published_blueprint(self):
        layout = [0] * 25
        for cell in (6, 7, 12):
            layout[cell] = 1
        params = {
            "quota": 3,
            "seconds": 30,
            "radius": 0.08,
            "size": 5,
            "pace": 1,
            "grid": layout,
            "to": 12,
        }
        params["from"] = 6
        design = {"count": 3, "game_type": "trail"}
        curve = "function parameters(){return " + json.dumps(params) + ";}"
        levels, _ = cartridge.levels_for(design, 48, curve)
        game = cartridge.source("game-template.js")
        proof = cartridge.verify_game(game, levels)
        self.assertEqual(cartridge.blueprint_path(levels[0]), [7, 12])
        self.assertTrue(all(case["blueprint_steps"] == 2 for case in proof))

        # This game's own witness wins on a different, hardcoded board.
        wrong_level = {**levels[0], "from": 7, "to": 6}
        wrong = (
            "const fixed="
            + json.dumps(wrong_level)
            + ";\n"
            + game.replace("baseStart(L)", "baseStart(fixed)").replace(
                ", L);", ", fixed);"
            )
        )
        with self.assertRaisesRegex(ValueError, "按蓝图逐格点击"):
            cartridge.verify_game(wrong, levels)

        params["to"] = 24
        with self.assertRaisesRegex(ValueError, "可行走格"):
            cartridge.levels_for(
                design, 48, "function parameters(){return " + json.dumps(params) + ";}"
            )

    def test_failed_playability_has_a_reproducible_trace_and_resumes_from_rejected_source(
        self,
    ):
        self.draft()
        self.decision("revise", target="game_code", note="核查输入回放")
        contexts = []

        async def stalled(role, schema, data):
            val, provider = await scripted(role, schema, data)
            if role == "GameCoder":
                val["source"] = val["source"].replace(
                    "return baseWitness(s, L);",
                    "/* stalled witness */ return {type:'tick',dt:0.1};",
                )
            return val, provider

        with patch.object(agents, "consult", side_effect=stalled):
            job = worker.claim()
            asyncio.run(worker.run_job(job))
        feedback = self.get("games/" + self.game)["revision"]["docs"]["build_feedback"]
        self.assertIn("Seed", feedback["summary"])
        self.assertIn("witness cannot win", feedback["summary"])
        self.assertIn('"last":', feedback["summary"])

        async def repaired(role, schema, data):
            if role == "GameCoder":
                contexts.append(data)
            return await scripted(role, schema, data)

        with patch.object(agents, "consult", side_effect=repaired):
            self.work()
        self.assertEqual(contexts[0]["starter"], feedback["sources"]["game_code"])
        self.assertEqual(
            contexts[0]["previous_submission"]["source"], contexts[0]["starter"]
        )
        self.assertIn("points", contexts[0]["sample_level"])
        self.assertEqual(self.get("games/" + self.game)["revision"]["stage"], "quality")

    def test_producer_selective_entity_rework_keeps_audio_and_existing_sprites(self):
        self.draft()
        before = self.get("games/" + self.game)["revision"]["docs"]["art"]
        self.decision(
            "revise", target="auto", note="增加一颗与灯塔配套的星星，原图与音乐保持一致"
        )
        called = []

        async def add_star(role, schema, data):
            called.append(role)
            value, provider = await scripted(role, schema, data)
            if role == "ArtDesigner":
                value["sprites"].append(
                    {
                        **value["sprites"][0],
                        "id": "star",
                        "title": "星",
                        "reference": "tower",
                    }
                )
                value["tempo"] = 155
                value["sprites"][0] = {**value["sprites"][0], "title": "错误替换"}
            return value, provider

        with patch.object(agents, "consult", side_effect=add_star):
            self.work()
        docs = self.get("games/" + self.game)["revision"]["docs"]
        self.assertEqual(docs["impact"]["entities"], ["star"])
        self.assertNotIn("LevelDesigner", called)
        self.assertEqual(docs["art"]["sprites"][:2], before["sprites"])
        self.assertEqual(docs["art"]["sprites"][-1]["reference"], "tower")
        self.assertEqual(docs["art"]["tempo"], before["tempo"])
        self.assertEqual(docs["art"]["melody"], before["melody"])

    def test_unplanned_art_never_reaches_the_image_gateway(self):
        new = self.post("games", IDEA, 201)
        self.game, self.rev = new["game"], new["rev"]
        self.work()
        self.decision("select_references", reference_ids=["beacon"])
        self.work()
        self.decision("choose", choice=0)
        attempts, submitted = [], []

        async def wrong_inventory(role, schema, data):
            val, provider = await scripted(role, schema, data)
            if role == "ArtDesigner":
                attempts.append(role)
                if len(attempts) == 1:
                    val["sprites"].append(
                        {**val["sprites"][0], "id": "decorative-glow"}
                    )
                if len(attempts) == 2:
                    val["sprites"] = val["sprites"][:1]
            return val, provider

        async def record(art):
            submitted.append([s["id"] for s in art["sprites"]])

        with (
            patch.object(agents, "consult", side_effect=wrong_inventory),
            patch("studio.image_service.materialize", side_effect=record),
        ):
            self.work()
        self.assertEqual(len(attempts), 3)
        self.assertEqual(submitted, [["tower", "boat"]])
        self.assertEqual(self.get("games/" + self.game)["revision"]["stage"], "plan")

    def test_blueprint_edits_rebuild_and_invalidate_old_playtest(self):
        self.draft()
        self.play(preview=self.rev)
        r = self.get("games/" + self.game)["revision"]
        endpoint = "revisions/" + self.rev + "/levels"
        edit = {
            "serial": r["serial"],
            "seed": r["seed"],
            "level": 1,
            "values": {"seconds": 73},
        }
        self.post(endpoint, edit)
        self.post(endpoint, edit, 409)
        self.work()
        self.assertEqual(self.get(endpoint)["levels"][0]["seconds"], 73)
        self.decision("accept", 409)
        self.play(preview=self.rev)
        self.decision("accept")
