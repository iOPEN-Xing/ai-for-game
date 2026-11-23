import asyncio
import os
from unittest.mock import patch

import quickjs
from fastapi.testclient import TestClient

import app as server
from studio import cartridge, skillbook
from tests.support import IDEA, StudioCase


class AccessTests(StudioCase):
    def test_editor_isolation_precedence_and_frozen_project_context(self):
        obj = self.get("preferences")
        self.assertEqual(obj, {"version": 0, "values": {}})
        endpoint = "/api/preferences"
        payload = {
            "version": 0,
            "values": {
                "audience": "通勤玩家",
                "visual_style": "剪纸海港",
                "controls": "单手",
            },
        }
        self.assertEqual(self.client.put(endpoint, json=payload).status_code, 200)
        self.assertEqual(self.client.put(endpoint, json=payload).status_code, 409)
        other = TestClient(
            server.app, base_url="http://localhost", client=("127.0.0.1", 50000)
        )
        self.addCleanup(other.close)
        self.assertEqual(other.get(endpoint).json()["values"], {})
        g = self.post("games", IDEA, 201)
        project_url = "/api/games/" + g["game"] + "/preferences"
        self.assertEqual(
            self.client.get(project_url).json()["values"]["audience"], "通勤玩家"
        )
        self.client.put(
            endpoint, json={"version": 1, "values": {"audience": "新默认"}}
        ).raise_for_status()
        self.client.put(
            project_url, json={"version": 1, "values": {"audience": "团建玩家"}}
        ).raise_for_status()
        trace = self.get("games/" + g["game"])["revision"]["docs"]["context_snapshot"]
        self.assertEqual(trace["preferences"]["values"]["audience"], "通勤玩家")
        from studio import context as scoped

        self.assertNotIn(
            "visual_style", scoped.memory_for("Analyst", trace)["preferences"]
        )
        self.assertEqual(
            scoped.memory_for("ArtDesigner", trace)["preferences"]["visual_style"],
            "剪纸海港",
        )
        self.assertEqual(
            self.client.get(project_url).json()["values"], {"audience": "团建玩家"}
        )
        other_game = self.post("games", IDEA, 201)
        self.assertEqual(
            self.get("games/" + other_game["game"] + "/preferences")["values"],
            {"audience": "新默认"},
        )
        with patch.dict(os.environ, {"STUDIO_ACCESS_KEY": "private"}):
            self.assertEqual(self.client.get(endpoint).status_code, 401)

    def test_isolation_authentication_and_sample(self):
        with patch.dict(
            os.environ, {"STUDIO_ACCESS_KEY": "test-secret", "STUDIO_DEPLOYED": "1"}
        ):
            self.assertEqual(self.client.get("/api/studio").status_code, 401)
            self.assertEqual(self.client.get("/sample").status_code, 200)
            self.assertEqual(self.client.get("/.env").status_code, 404)
            session = self.post("login", {"key": "test-secret"})["session"]
            self.assertEqual(
                self.client.get(
                    "/api/studio", headers={"X-Atelier-Session": session}
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.post(
                    "/api/games", json=IDEA, headers={"Origin": "https://other.example"}
                ).status_code,
                403,
            )
        for family in ("pulse", "trail", "drift", "custom"):
            levels, _ = cartridge.levels_for(
                {"count": 3, "game_type": family},
                48,
                cartridge.source("curve-template.js"),
            )
            self.assertEqual(
                len(
                    cartridge.verify_game(cartridge.source("game-template.js"), levels)
                ),
                3,
            )
        cheating = cartridge.source("game-template.js").replace(
            "return baseWitness(s, L);",
            "s.done=s.won=true;return {type:'tap',x:0,y:0};",
        )
        with self.assertRaises((ValueError, quickjs.JSException)):
            cartridge.verify_game(cheating, levels)
        self.assertEqual(
            cartridge.js_context().eval("typeof process+' / '+typeof fetch"),
            "undefined / undefined",
        )
        loaded = asyncio.run(skillbook.read("GameCoder"))
        self.assertEqual(
            {s["name"] for s in loaded}, {"build-playable-levels", "design-gameplay"}
        )
