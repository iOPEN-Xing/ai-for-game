"""Isolated studio, trusted local client and real game build/replay helpers."""

import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as server
from studio import agents, cartridge, worker
from studio.store import db, init, need
from tests.fixtures.model import scripted

IDEA = {
    "title": "回声航标",
    "brief": "点亮信标引导小船。",
    "bounds": "触屏操作，静音可玩。",
    "metric": "win_rate",
}


class StudioCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(
            os.environ,
            {
                "STUDIO_DATA_DIR": self.tmp.name,
                "STUDIO_ACCESS_KEY": "",
                "STUDIO_DEPLOYED": "0",
                "STUDIO_ART_API_KEY": "",
                "STUDIO_RESEARCH_ONLINE": "0",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        model = patch.object(agents, "consult", side_effect=scripted)
        model.start()
        self.addCleanup(model.stop)
        self.client = TestClient(
            server.app, base_url="http://localhost", client=("127.0.0.1", 50000)
        )
        self.addCleanup(self.client.close)
        init()

    def post(self, path, body, expected=200):
        res = self.client.post("/api/" + path, json=body)
        self.assertEqual(res.status_code, expected, res.text[:600])
        return res.json()

    def get(self, path):
        result = self.client.get("/api/" + path)
        self.assertEqual(result.status_code, 200, result.text[:300])
        return result.json()

    def work(self):
        job = worker.claim()
        self.assertIsNotNone(job)
        asyncio.run(worker.run_job(job))
        with db() as c:
            state = need(c, "SELECT state,error FROM jobs WHERE id=?", job["id"])
            self.assertEqual(state["state"], "done", state["error"])

    def decision(self, action, expected=200, **extra):
        version = self.get("games/" + self.game)["revision"]
        return self.post(
            "revisions/" + version["id"] + "/decision",
            {"serial": version["serial"], "action": action, **extra},
            expected,
        )

    def draft(self, choice=0, metric="win_rate"):
        result = self.post("games", {**IDEA, "metric": metric}, 201)
        self.game, self.rev = result["game"], result["rev"]
        self.decision("publish", 409)
        self.work()
        self.decision("select_references", reference_ids=["beacon", "island"])
        self.work()
        self.decision("choose", choice=choice)
        self.work()
        self.decision("approve")
        self.work()
        return self.rev

    def play(
        self, player="test-player-100000", preview=None, quit=False, campaign=None
    ):
        opened = self.post(
            "play/" + self.game + "/open",
            {"player": player, "preview": preview, "campaign": campaign},
        )
        token = opened["round"]
        path = "rounds/" + token + "/event"
        self.post(path, {"event": "end"}, 409)
        self.post(path, {"event": "start"})
        self.post(path, {"event": "start"})
        if quit:
            body = {"event": "end", "won": False, "finish": "quit"}
        else:
            self.post(path, {"event": "end", "won": True, "score": 999}, 422)
            with db() as con:
                r = need(con, "SELECT bundle FROM rounds WHERE id=?", token)
            root = cartridge.folder(r["bundle"])
            L = json.loads((root / "Level_Pack.json").read_bytes())["levels"][
                opened["level"] - 1
            ]
            ctx = cartridge.js_context(
                cartridge.source("factory.js"),
                cartridge.source("base.js"),
                (root / "game.js").read_text(),
            )
            ctx.set("L", ctx.parse_json(json.dumps(L)))
            trace = cartridge.evaluate(
                ctx,
                "(()=>{let s=start(L),e=[];while(!s.done&&e.length<2200){const input=witness(s,L);e.push(input);s=step(s,input,L)}return {inputs:e,score:s.score,won:s.won}})()",
            )
            body = {"event": "end", **trace}
        self.post(path, body)
        self.post(path, body)
        return token

    def publish(self):
        self.play(preview=self.rev)
        self.decision("accept")
        self.decision("publish")

    def iteration(self, metric="win_rate"):
        self.draft(metric=metric)
        self.publish()
        entry = None
        if metric == "action_rate":
            entry = self.post(
                "games/" + self.game + "/campaigns",
                {
                    "name": "社群",
                    "action_label": "活动详情",
                    "action_url": "https://example.org/activity",
                },
            )["id"]
        token = self.play(campaign=entry)
        self.post(
            "rounds/" + token + "/feedback", {"rating": 3, "comment": "提示可以更清楚"}
        )
        p = self.post("operations/analyze", {"game": self.game})["id"]
        self.post("operations/analyze", {"game": self.game}, 409)
        self.work()
        frozen = self.get("proposals/" + p)
        if entry:
            self.assertEqual(frozen["evidence"]["channels"][0]["campaign"], entry)
            self.assertNotIn("action_url", frozen["evidence"]["channels"][0])
        self.assertEqual(len(frozen["evidence"]["feedback"]), 1)
        self.assertIn("function step", frozen["evidence"]["game_code"])
        self.assertTrue(
            all(
                k in frozen["doc"]
                for k in [
                    "Analyst",
                    "Engineer",
                    "GameDesigner",
                    "Reviewer",
                    "challenge",
                    "bet",
                ]
            )
        )
        child = self.post("proposals/" + p + "/review", {"accept": True})["production"]
        self.rev = child["rev"]
        self.work()
        self.decision("approve")
        self.work()
        self.publish()
        return self.get("operations")["experiments"][0]
