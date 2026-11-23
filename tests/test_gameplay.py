import datetime as dt
import json

from studio import operations
from studio.settings import ZONE
from studio.store import db, need
from tests.support import StudioCase


class GameplayTests(StudioCase):
    def test_campaign_links_measure_unique_eligible_players_at_cutoff(self):
        self.draft(metric="action_rate")
        endpoint = "games/" + self.game + "/campaigns"
        config = {
            "name": "社群",
            "action_label": "查看活动",
            "action_url": "https://example.org/winter",
        }
        self.post(endpoint, config, 409)
        self.publish()
        entry = self.post(endpoint, config)
        self.assertEqual(entry, self.post(endpoint, config))
        self.post(endpoint, {**config, "action_label": "另一目标"}, 409)
        self.post(endpoint, {**config, "action_url": None}, 422)
        self.post(endpoint, {**config, "action_url": "http://example.org/"}, 422)
        cid = entry["id"]
        trail = self.post(endpoint, {"name": "试玩群"})["id"]
        route = "play/" + self.game + "/open"
        visitor = {"player": "unique-player-00001", "campaign": cid}
        self.post(route, {**visitor, "preview": self.rev}, 422)
        self.post(route, {**visitor, "campaign": "f" * 24}, 404)
        opened = self.post(route, visitor)
        self.assertEqual(opened["action_label"], config["action_label"])
        self.assertEqual(self.client.post("/go/" + opened["round"]).status_code, 409)
        self.assertEqual(self.client.get("/go/" + opened["round"]).status_code, 405)
        token = self.play(visitor["player"], campaign=cid)
        self.play(visitor["player"], campaign=cid)
        self.play(visitor["player"], campaign=trail)
        quit = self.play("quit-player-000000", quit=True, campaign=cid)
        self.assertEqual(self.client.post("/go/" + quit).status_code, 409)
        self.post(route, {**visitor, "player": "visit-only-0000001"})
        self.play("direct-player-000000")
        for _ in range(2):
            go = self.client.post("/go/" + token, follow_redirects=False)
            self.assertEqual(go.status_code, 303)
            self.assertEqual(go.headers["location"], config["action_url"])
        snapshot = self.get("operations?days=7")["report"]
        channel = next(row for row in snapshot["channels"] if row["campaign"] == cid)
        self.assertEqual(
            [
                channel[k]
                for k in (
                    "visitors",
                    "players",
                    "finish_players",
                    "action_players",
                    "action_rate",
                )
            ],
            [3, 2, 1, 1, 33.33],
        )
        self.assertEqual(
            [
                snapshot["total"][k]
                for k in (
                    "visitors",
                    "action_visitors",
                    "action_starters",
                    "action_finishers",
                    "action_players",
                )
            ],
            [4, 3, 2, 1, 1],
        )
        self.assertIsNone(
            next(x for x in snapshot["channels"] if x["campaign"] == trail)[
                "action_rate"
            ]
        )
        with db(True) as con:
            cutoff = snapshot["end"]
            con.execute("UPDATE rounds SET action_at=? WHERE id=?", (cutoff, token))
            frozen = operations.report(con, end=cutoff)
            self.assertEqual(frozen["total"]["action_players"], 0)

    def test_published_game_assets_cache_but_rounds_and_drafts_stay_separate(self):
        self.draft()
        rev = self.get("games/" + self.game)["revision"]
        path = "/cartridges/v1/" + rev["bundle"] + ".json"
        player = {"player": "cached-player-0001", "delivery": "cached"}
        preview = self.post(
            "play/" + self.game + "/open", {**player, "preview": self.rev}
        )
        self.assertIn("game", preview)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.publish()
        first = self.post("play/" + self.game + "/open", player)
        again = self.post("play/" + self.game + "/open", player)
        self.assertEqual(first["game_url"], path)
        self.assertNotEqual(first["round"], again["round"])
        asset = self.client.get(path)
        self.assertIn("immutable", asset.headers["cache-control"])
        self.assertEqual(
            self.client.get(
                path, headers={"If-None-Match": asset.headers["etag"]}
            ).status_code,
            304,
        )
        inline = self.post("play/" + self.game + "/open", {"player": player["player"]})
        self.assertEqual({**asset.json(), **first["game_info"]}, inline["game"])
        self.assertLess(len(json.dumps(again)), len(asset.content) // 10)

    def test_mature_d1_cohort_uses_first_formal_game_start(self):
        self.draft()
        self.publish()
        day = int(dt.datetime(2026, 2, 1, tzinfo=ZONE).timestamp())
        with db(True) as con:
            meta = need(con, "SELECT bundle FROM revisions WHERE id=?", self.rev)
            for i, (player, offset, preview) in enumerate(
                [
                    ("a", 50, 0),
                    ("a", 100, 0),
                    ("a", 86410, 0),
                    ("b", 60, 0),
                    ("b", 86500, 1),
                    ("c", 86420, 0),
                    ("d", -86410, 0),
                    ("d", 70, 0),
                ]
            ):
                con.execute(
                    """INSERT INTO rounds(id,game,rev,player,level,preview,bundle,issued,started) VALUES(?,?,?,?,1,?,?,?,?)""",
                    (
                        "ret-" + str(i),
                        self.game,
                        self.rev,
                        player,
                        preview,
                        meta["bundle"],
                        day + offset,
                        day + offset,
                    ),
                )
            early = operations.report(con, day, day + 172799, game=self.game)["total"]
            full = operations.report(con, day, day + 172800, game=self.game)["total"]
            daily = operations.report(con, day + 86400, day + 172800, game=self.game)[
                "total"
            ]
        self.assertIsNone(early["d1_rate"])
        self.assertEqual(
            (full["d1_eligible"], full["d1_returned"], full["d1_rate"]), (2, 1, 50)
        )
        self.assertEqual(daily["d1_period"], [day, day + 86400])
        self.assertEqual(daily["d1_rate"], 50)
