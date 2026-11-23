import hashlib
import json
from unittest.mock import patch

from studio import agents, cartridge, operations
from studio.services import experiments
from studio.store import db, need
from tests.fixtures.model import scripted
from tests.support import StudioCase


class ExperimentsTests(StudioCase):
    def test_returning_players_share_pre_experiment_progress(self):
        self.draft()
        self.publish()
        eid = "b" * 24
        players = {}
        for i in range(100):
            player = f"returning-test-player-{i}"
            arm = hashlib.sha256((eid + player).encode()).digest()[0] % 2
            players.setdefault(arm, player)
            if len(players) == 2:
                break
        for player in players.values():
            self.play(player)
        pid = self.post("operations/analyze", {"game": self.game})["id"]
        self.work()
        self.rev = self.post("proposals/" + pid + "/review", {"accept": True})[
            "production"
        ]["rev"]
        self.work()
        self.decision("approve")
        self.work()
        self.play(preview=self.rev)
        self.decision("accept")
        with patch.object(experiments, "uid", return_value=eid):
            self.decision("publish")
        opened = [
            self.post("play/" + self.game + "/open", {"player": players[i]})
            for i in (0, 1)
        ]
        self.assertEqual([r["version"] for r in opened], [1, 2])
        self.assertEqual([r["level"] for r in opened], [2, 2])

    def test_release_checks_the_approved_parameter(self):
        exp = self.iteration()
        with db(True) as con:
            row = need(con, "SELECT doc FROM proposals WHERE id=?", exp["proposal"])
            doc = json.loads(row["doc"])
            doc["bet"]["checks"] = [
                {
                    "kind": "parameter",
                    "level": 1,
                    "field": "seconds",
                    "before": 60,
                    "after": 70,
                }
            ]
            con.execute(
                "UPDATE proposals SET doc=? WHERE id=?",
                (json.dumps(doc), exp["proposal"]),
            )
            with patch.object(experiments, "now", return_value=exp["due"] + 1):
                operations.settle(con, exp)
        self.assertEqual(
            self.get("operations")["experiments"][0]["result"]["attribution"], "执行错"
        )

    def test_click_experiment_interval_requires_evidence_at_the_player_level(self):
        e = self.iteration("action_rate")
        entry = self.get("operations")["campaigns"][0]["id"]
        counts = [0, 0]
        for i in range(100):
            player = f"experiment-player-{i:04}"
            arm = hashlib.sha256((e["id"] + player).encode()).digest()[0] % 2
            if counts[arm] >= 2:
                continue
            self.post(
                "play/" + self.game + "/open", {"player": player, "campaign": entry}
            )
            counts[arm] += 1
            if min(counts) == 2:
                break
        self.assertEqual(counts, [2, 2])
        with (
            db(True) as con,
            patch.object(experiments, "now", return_value=e["due"] + 1),
        ):
            operations.settle(con, e)
        result = self.get("operations")["experiments"][0]["result"]
        self.assertEqual(result["sample_basis"], "action_visitors")
        self.assertEqual(result["attribution"], "方法待验证")
        lo, hi = result["interval_95_pp"]
        self.assertLess(lo, 0)
        self.assertGreater(hi, 0)
        self.assertAlmostEqual(lo, -hi)
        high = operations.click_difference_interval(
            {"action_visitors": 100, "action_players": 0},
            {"action_visitors": 100, "action_players": 100},
        )
        self.assertGreater(high[0], 90)
        self.assertAlmostEqual(high[1], 100)

    def test_ab_assignment_due_settlement_and_knowledge(self):
        e = self.iteration()
        players = {0: [], 1: []}
        for i in range(30):
            player = f"sample-test-player-{i}"
            arm = hashlib.sha256((e["id"] + player).encode()).digest()[0] % 2
            if len(players[arm]) >= 2:
                continue
            players[arm].append(player)
            v = self.post("play/" + self.game + "/open", {"player": player})["version"]
            self.assertEqual(v, arm + 1)
            self.play(player)
        with db(True) as con:
            with self.assertRaisesRegex(Exception, "结算时间"):
                operations.settle(con, e)
            with patch.object(experiments, "now", return_value=e["due"] + 1):
                operations.settle(con, e)
        settled = self.get("operations")["experiments"][0]
        self.assertEqual(settled["result"]["delta"], 0)
        self.assertIn("game.js", settled["result"]["changed_files"])
        self.post("experiments/" + e["id"] + "/decision", {"accept": True})
        self.assertEqual(self.get("games/" + self.game)["game"]["live"], e["treatment"])
        k = self.get("memory")["entries"][0]
        self.assertEqual(k["status"], "pending")
        self.post("knowledge/" + k["id"] + "/review", {"accept": True})
        self.assertEqual(self.get("memory")["entries"][0]["status"], "active")

    def test_confounded_and_sparse_experiments_stay_unverified(self):
        e = self.iteration()
        self.post(
            "operations/changes", {"game": self.game, "text": "入口替换使采样发生改变"}
        )
        with (
            db(True) as con,
            patch.object(experiments, "now", return_value=e["due"] + 1),
        ):
            operations.settle(con, e)
        k = self.get("memory")["entries"][0]
        self.assertEqual(k["evidence"]["attribution"], "方法错")
        self.post("knowledge/" + k["id"] + "/review", {"accept": True})
        self.assertEqual(self.get("memory")["entries"][0]["status"], "unverified")
        self.post("experiments/" + e["id"] + "/decision", {"accept": False})
        self.assertEqual(self.get("games/" + self.game)["game"]["live"], e["control"])

    def test_underpowered_experiment_preserves_uncertainty(self):
        e = self.iteration()
        self.play("small-sample-player")
        with (
            db(True) as con,
            patch.object(experiments, "now", return_value=e["due"] + 1),
        ):
            operations.settle(con, e)
        result = self.get("operations")["experiments"][0]["result"]
        self.assertEqual(result["attribution"], "方法待验证")
        self.assertIsNone(result["delta"])
        self.assertEqual(self.get("memory")["entries"][0]["grade"], "未验证推断")

    def test_approved_parameter_reaches_both_real_bundles(self):
        self.draft()
        self.publish()
        self.play()

        async def parameter_change(role, schema, data):
            value, provider = await scripted(role, schema, data)
            if data.get("phase") == "decision":
                value.update(
                    change="只为首关增加十秒",
                    checks=[
                        {
                            "kind": "parameter",
                            "level": 1,
                            "field": "seconds",
                            "before": 60,
                            "after": 70,
                        }
                    ],
                )
            if role == "LevelCoder" and "approved_proposal" in data:
                value["source"] = value["source"].replace(
                    "seconds: 60", "seconds: index === 1 ? 70 : 60"
                )
            return value, provider

        with patch.object(agents, "consult", side_effect=parameter_change):
            pid = self.post("operations/analyze", {"game": self.game})["id"]
            self.work()
            self.rev = self.post("proposals/" + pid + "/review", {"accept": True})[
                "production"
            ]["rev"]
            self.work()
            self.decision("approve")
            self.work()
            self.play(preview=self.rev)
            self.decision("accept")
            self.decision("publish")
        e = self.get("operations")["experiments"][0]
        self.assertEqual(e["status"], "running")
        with db() as con:
            bundles = [
                need(con, "SELECT bundle FROM revisions WHERE id=?", e[k])["bundle"]
                for k in ("control", "treatment")
            ]
        packs = [
            json.loads((cartridge.folder(b) / "Level_Pack.json").read_bytes())
            for b in bundles
        ]
        self.assertEqual([p["levels"][0]["seconds"] for p in packs], [60, 70])
        self.assertEqual(packs[0]["levels"][1:], packs[1]["levels"][1:])
        self.assertEqual(
            *[(cartridge.folder(b) / "game.js").read_bytes() for b in bundles]
        )
