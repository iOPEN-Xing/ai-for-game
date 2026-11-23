"""Exercise disputed evidence and parameter changes through the ordinary human gates."""

import asyncio
import json
from unittest.mock import patch

from studio import agents, cartridge, context, worker
from studio.infra.store import db, need
from tests.fixtures.model import scripted
from tests.support import StudioCase


class ReleaseIntegrityTests(StudioCase):
    def test_candidate_must_cite_its_own_evidence_at_submission_and_approval(self):
        self.draft()
        self.publish()
        token = self.play()
        self.post(
            f"rounds/{token}/feedback", {"rating": 2, "comment": "PRIVATE-PLAYER-TEXT"}
        )
        attempts = []

        async def miscite(role, schema, data):
            candidate, provider = await scripted(role, schema, data)
            if data.get("phase") == "candidates":
                attempts.append(
                    (data.get("correction"), list(data["evidence"]["sources"]))
                )
                if len(attempts) == 1:
                    candidate["candidates"][0]["evidence"] = "game.js"
            return candidate, provider

        with patch.object(agents, "consult", side_effect=miscite):
            pid = self.post(
                "operations/analyze", {"kind": "new_game", "game": self.game}
            )["id"]
            self.work()
        self.assertEqual(len(attempts), 2)
        self.assertTrue(attempts[1][0])
        self.assertNotIn("game.js", attempts[1][1])
        proposal = self.get("proposals/" + pid)
        self.assertEqual(proposal["status"], "review")
        self.assertNotIn("PRIVATE-PLAYER-TEXT", json.dumps(proposal["evidence"]))
        self.assertEqual(
            proposal["evidence"]["feedback"],
            [{"level": 1, "rating": 2, "responses": 1}],
        )
        old = dict(
            proposal["evidence"],
            feedback=[
                {
                    "id": "old-rating",
                    "comment": "PRIVATE-PLAYER-TEXT",
                    "level": 1,
                    "rating": 2,
                }
            ],
        )
        old["sources"] = [*old["sources"], "old-rating"]
        view = context.evidence_for("GameDesigner", old)
        self.assertNotIn("PRIVATE-PLAYER-TEXT", json.dumps(view))
        self.assertNotIn("old-rating", view["sources"])
        doc = proposal["doc"]
        doc["GameDesigner"]["candidates"][0]["evidence"] = "game.js"
        with db(True) as con:
            con.execute("UPDATE proposals SET doc=? WHERE id=?", (json.dumps(doc), pid))
        self.post(f"proposals/{pid}/review", {"accept": True}, 409)
        with db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)

    def test_seconds_only_approval_rejects_playable_but_different_maze(self):
        self.draft(choice=1)
        self.publish()
        self.play()
        control = self.rev

        async def wider_maze(role, schema, data):
            value, provider = await scripted(role, schema, data)
            if data.get("phase") == "decision":
                value["checks"] = [
                    {
                        "kind": "parameter",
                        "level": 1,
                        "field": "seconds",
                        "before": 60,
                        "after": 70,
                    }
                ]
            if role == "LevelCoder" and "approved_proposal" in data:
                base = value["source"].replace(
                    "function parameters(", "function controlParameters("
                )
                value["source"] = (
                    base
                    + """
function parameters(index, total, seed) {
  const p = controlParameters(index, total, seed);
  if (index !== 1) return p;
  const grid = Array.from({length: p.size*p.size}, (_, i) => {
    const x = i % p.size, y = Math.floor(i / p.size);
    return Number(x > 0 && x < p.size-1 && y > 0 && y < p.size-1);
  });
  return {...p, seconds: 70, grid, from: p.size+1, to: p.size*(p.size-1)-2};
}
"""
                )
            return value, provider

        with patch.object(agents, "consult", side_effect=wider_maze):
            pid = self.post("operations/analyze", {"game": self.game})["id"]
            self.work()
            self.rev = self.post(f"proposals/{pid}/review", {"accept": True})[
                "production"
            ]["rev"]
            self.work()
            self.decision("approve")
            for _ in range(2):
                job = worker.claim()
                self.assertIsNotNone(job)
                asyncio.run(worker.run_job(job))
        self.decision("publish", 409)
        with db() as con:
            job = need(con, "SELECT state,error FROM jobs WHERE id=?", job["id"])
            self.assertEqual(job["state"], "failed")
            self.assertIn("grid", job["error"])
            self.assertEqual(
                need(con, "SELECT live FROM games WHERE id=?", self.game)["live"],
                control,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM experiments").fetchone()[0], 0
            )

    def test_approved_quota_can_change_its_deterministically_derived_points(self):
        design = {"count": 3, "game_type": "pulse"}
        curve = cartridge.source("curve-template.js")
        levels, _ = cartridge.levels_for(design, 701, curve)
        pack = {"family": "pulse", "levels": levels, "seed": 701}
        changed, _ = cartridge.levels_for(
            design, 701, curve.replace("3 + index", "(index === 1 ? 4 : 3) + index")
        )
        expected = cartridge.approved_levels(
            pack, curve, {1: {"quota": levels[0]["quota"] + 1}}
        )
        self.assertEqual(expected, changed)
        self.assertEqual(len(expected[0]["points"]), len(levels[0]["points"]) + 1)
        self.assertEqual(expected[1:], levels[1:])
