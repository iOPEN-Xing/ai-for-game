import asyncio
import datetime as dt
from unittest.mock import patch

from studio import operations
from studio.application.agents import gateway
from studio.application.harness import worker
from studio.application.usecases.operations import batches, experiments
from studio.settings import ZONE
from studio.store import db, init, need, one
from tests.fixtures.model import scripted
from tests.support import IDEA, StudioCase


class OperationsTests(StudioCase):
    def test_current_revision_needs_its_own_starts(self):
        exp = self.iteration()
        with (
            db(True) as con,
            patch.object(experiments, "now", return_value=exp["due"] + 1),
        ):
            operations.settle(con, exp)
        self.post("experiments/" + exp["id"] + "/decision", {"accept": True})
        self.post("operations/analyze", {"game": self.game, "kind": "new_game"}, 409)
        self.play("new-version-test-player")
        pid = self.post("operations/analyze", {"game": self.game, "kind": "new_game"})[
            "id"
        ]
        frozen = self.get("proposals/" + pid)["evidence"]
        self.assertEqual(frozen["game"]["starts"], 1)
        self.assertEqual({r["rev"] for r in frozen["levels"]}, {exp["treatment"]})
        self.assertEqual(frozen["level_pack"]["levels"][0]["seconds"], 60)

    def test_final_reviewer_can_hold_an_unanswered_challenge(self):
        self.draft()
        self.publish()
        self.play()
        calls = []

        async def disputed(role, schema, data):
            calls.append((role, data.get("phase")))
            value, provider = await scripted(role, schema, data)
            if data.get("phase") == "final_review":
                value["approved"] = False
                value["reason"] = "尚未核实受影响人群的分母。"
            return value, provider

        with patch.object(gateway, "consult", side_effect=disputed):
            pid = self.post(
                "operations/analyze", {"game": self.game, "kind": "new_game"}
            )["id"]
            self.work()
        proposal = self.get("proposals/" + pid)
        self.assertEqual(proposal["status"], "needs_evidence")
        self.assertLess(
            calls.index(("Reviewer", "constraints")),
            calls.index(("GameDesigner", "candidates")),
        )
        self.assertLess(
            calls.index(("Analyst", "challenge")),
            calls.index(("Moderator", "decision")),
        )
        self.post("proposals/" + pid + "/review", {"accept": True}, 409)

    def test_daily_queue_compares_each_games_own_metric_to_its_history(self):
        self.draft(metric="action_rate")
        self.publish()
        campaign_game = self.game
        cid = self.post(
            "games/" + self.game + "/campaigns",
            {
                "name": "会员活动",
                "action_label": "详情",
                "action_url": "https://example.org/members",
            },
        )["id"]
        self.draft()
        self.publish()
        with db(True) as con:
            for gid in (campaign_game, self.game):
                for day in (1, 8):
                    for n in range(10):
                        at = day * 86400 + n
                        click = gid == campaign_game and n < (8 if day == 1 else 4)
                        con.execute(
                            """INSERT INTO rounds(id,game,rev,player,level,preview,bundle,issued,started,ended,won,score,finish,campaign,action_at)
                                    VALUES(?,?, 'snapshot',?,1,0,'snapshot',?,?,?,?,0,'natural',?,?)""",
                            (
                                f"{gid}-{day}-{n}",
                                gid,
                                f"visitor-{n}",
                                at,
                                at + 1,
                                at + 2,
                                int(gid == campaign_game or n == 0),
                                cid if gid == campaign_game else None,
                                at + 3 if click else None,
                            ),
                        )
            snapshot = operations.report(con, 8 * 86400, 9 * 86400)
            rank = operations.daily_priorities(con, snapshot)
            self.assertEqual(rank[0]["game"], campaign_game)
            self.assertEqual(
                [
                    rank[0][k]
                    for k in ("metric", "value", "baseline", "relative_decline")
                ],
                ["action_rate", 40, 80, 0.5],
            )
            self.assertEqual(rank[1]["relative_decline"], 0)

    def test_idempotency_queue_repair_batch_gate_and_restart(self):
        body = {**IDEA, "request_id": "0123456789abcdef"}
        a = self.post("games", body, 201)
        self.assertEqual(a, self.post("games", body, 201))
        self.post("games", {**body, "title": "不同创意"}, 409)
        with db(True) as con:
            con.execute("UPDATE jobs SET state='done'")
            worker.audit_deliveries(con)
            self.assertEqual(need(con, "SELECT state FROM jobs")["state"], "queued")
        self.work()
        init()
        self.assertEqual(
            self.get("games/" + a["game"])["revision"]["stage"], "references"
        )
        day = dt.datetime.now(ZONE).date() - dt.timedelta(days=1)
        with (
            patch.object(batches, "report", side_effect=RuntimeError("报表出数失败")),
            self.assertRaises(RuntimeError),
        ):
            operations.run_batch(day)
        with db() as con:
            self.assertEqual(
                need(con, "SELECT status FROM batches")["status"], "failed"
            )
            self.assertEqual(one(con, "SELECT COUNT(*) n FROM proposals")["n"], 0)
        first = operations.run_batch(day)
        self.assertEqual(first, operations.run_batch(day))

    def test_daily_batch_new_game_reconciliation_and_checkpoint_resume(self):
        self.draft()
        self.publish()
        self.play()
        today = dt.datetime.now(ZONE).date()
        day = today - dt.timedelta(days=1)
        at = int(dt.datetime.combine(day, dt.time(12), ZONE).timestamp())
        with db(True) as con:
            con.execute(
                "UPDATE rounds SET issued=?,started=?,ended=? WHERE preview=0",
                (at, at + 1, at + 8),
            )
        batch = operations.run_batch(day)
        self.assertEqual(len(batch["proposals"]), 2)
        self.assertEqual(len(operations.run_batch(day)["proposals"]), 2)
        self.work()
        self.work()
        record = self.get("operations/batches/" + day.isoformat())
        self.assertEqual(record["status"], "complete")
        p = next(
            self.get("proposals/" + pid)
            for pid in batch["proposals"]
            if self.get("proposals/" + pid)["kind"] == "new_game"
        )
        new = self.post("proposals/" + p["id"] + "/review", {"accept": True})[
            "production"
        ]
        self.assertNotEqual(new["game"], self.game)
        self.game, self.rev = new["game"], new["rev"]
        self.work()
        self.decision("select_references", reference_ids=["beacon", "island"])
        self.work()
        self.decision("choose", choice=0)
        failed_once = False

        async def interrupted(role, schema, data):
            nonlocal failed_once
            if role == "ArtDesigner" and not failed_once:
                failed_once = True
                raise RuntimeError("interrupted")
            return await scripted(role, schema, data)

        with patch.object(gateway, "consult", side_effect=interrupted):
            asyncio.run(worker.run_job(worker.claim()))
        partial = self.get("games/" + self.game)["revision"]
        self.assertIn("gdd", partial["docs"])
        self.work()
        self.assertEqual(
            partial["docs"]["gdd"],
            self.get("games/" + self.game)["revision"]["docs"]["gdd"],
        )
        self.decision("approve")
        self.work()
        self.publish()
        self.play()
        day_after = today + dt.timedelta(days=1)
        with patch.object(
            batches,
            "now",
            return_value=int(
                dt.datetime.combine(day_after, dt.time(8), ZONE).timestamp()
            ),
        ):
            second = operations.run_batch(today)
        match = next(
            entry
            for entry in second["launch_reconciliation"]
            if entry["proposal"] == p["id"]
        )
        self.assertEqual(match["live"], self.rev)
        self.assertIsNotNone(match["first_exposure"])

    def test_role_isolation_and_first_round_blocker_survives_moderation(self):
        self.draft()
        self.publish()
        self.play()
        calls = {}

        async def with_blocker(role, schema, data):
            label = data["_node"]
            calls[label] = data
            value, provider = await scripted(role, schema, data)
            if label == "Reviewer":
                value["blocker"] = {
                    "owner": "Engineer",
                    "question": "旧版回放能代表此构建吗？",
                    "refs": ["metrics"],
                }
            if label == "reply_b-Reviewer":
                value["supported"] = False
            return value, provider

        with patch.object(gateway, "consult", side_effect=with_blocker):
            pid = self.post("operations/analyze", {"game": self.game})["id"]
            self.work()
        p = self.get("proposals/" + pid)
        self.assertEqual(p["status"], "needs_evidence")
        for role in ("Engineer", "Analyst", "Reviewer", "GameDesigner"):
            self.assertNotIn("independent_opinions", calls[role])
        self.assertNotIn("game_code", calls["Analyst"]["evidence"])
        self.assertIn("function step", calls["Engineer"]["evidence"]["game_code"])
        self.assertIn("resolve_b-Reviewer", p["doc"])
        self.assertIn("hold", p["doc"])
        self.assertNotIn("bet", p["doc"])
        self.post("proposals/" + pid + "/review", {"accept": True}, 409)
        self.post("proposals/" + pid + "/retry", {"note": "检查过同一版本的正式玩家"})
        self.work()
        new = self.get("proposals/" + pid)
        self.assertNotEqual(
            new["evidence"]["memory"]["id"], p["evidence"]["memory"]["id"]
        )
        self.assertEqual(new["status"], "review")
