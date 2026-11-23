"""Cross-layer regressions for single-studio publishing, input limits and immutable evidence."""

import asyncio
import base64
import datetime as dt
import hashlib
import json
import os
from unittest.mock import patch

from studio import cartridge, research, skillbook
from studio.domain import limits
from studio.domain.commands import RoundEvent
from studio.infra import bundles, rate_limits, retention
from studio.infra.reporting import report
from studio.infra.store import db, need, now
from studio.services import batches, evidence, production_nodes
from studio.settings import ZONE
from tests.support import StudioCase


class LifecycleTests(StudioCase):
    def test_logins_are_independent_and_cookie_writes_require_origin(self):
        with patch.dict(os.environ, {"STUDIO_ACCESS_KEY": "fixture"}):
            old = self.post("login", {"key": "fixture"})["session"]
            current = self.post("login", {"key": "fixture"})["session"]
            self.assertNotEqual(old, current)
            self.get("preferences")
            self.assertIn("loop_editor", self.client.cookies)
            self.assertEqual(self.client.post("/api/logout").status_code, 403)
            self.assertEqual(
                self.client.post(
                    "/api/logout",
                    headers={"Origin": "null", "Referer": "http://localhost/"},
                ).status_code,
                403,
            )
            self.client.post(
                "/api/logout", headers={"Referer": "http://localhost/"}
            ).raise_for_status()
            self.assertNotIn("loop_session", self.client.cookies)
            self.assertNotIn("loop_editor", self.client.cookies)

            def with_token(token):
                return self.client.get(
                    "/api/studio", headers={"X-Atelier-Session": token}
                ).status_code

            self.assertEqual(with_token(current), 401)
            self.assertEqual(with_token(old), 200)
            with patch.dict(os.environ, {"STUDIO_ACCESS_KEY": "rotated-for-test"}):
                self.assertEqual(with_token(old), 401)
            self.assertEqual(
                self.client.get("/healthz").headers["cache-control"], "no-store"
            )

    def test_oversize_fixed_and_streamed_player_requests_stop_before_replay(self):
        url = "/api/rounds/missing/event"
        chunk = b" " * (limits.PLAYER_BODY_BYTES // 2 + 1)
        with patch.object(cartridge, "replay") as replay:
            for body in (chunk * 2, iter((chunk, chunk))):
                res = self.client.post(
                    url, content=body, headers={"Content-Type": "application/json"}
                )
                self.assertEqual(res.status_code, 413, res.text[:150])
                self.assertEqual(res.json()["code"], "PAYLOAD_TOO_LARGE")
            for inputs in ([1] * 12001, [102], [["move", 10001, 2]], [{"type": "key"}]):
                self.assertEqual(
                    self.client.post(
                        url, json={"event": "end", "inputs": inputs}
                    ).status_code,
                    422,
                )
            replay.assert_not_called()

    def test_full_180_second_drag_has_an_exact_compact_replay(self):
        # 25 Hz with a pointer move on every frame, independently of when a fixture normally wins.
        src = """globalThis.LoopCartridge={get:async()=>()=>({level:()=>({seconds:180}),
        start:()=>({n:0,score:0,elapsed:0}),step:(s,e)=>{
          s.n++;if(e.type==='tick') s.elapsed+=e.dt;
          else if(e.type==='move') s.score+=Math.round(10000*(e.x+e.y));
          s.done=s.won=s.n===9000;return s;}})}"""
        key = hashlib.sha256(src.encode()).hexdigest()
        root = cartridge.folder(key)
        root.mkdir(parents=True)
        (root / "remoteEntry.js").write_text(src)
        compact, legacy = [], []
        for i in range(4500):
            compact.extend((["move", i, 10000 - i], 40))
            legacy.extend(
                (
                    {"type": "move", "x": i / 10000, "y": (10000 - i) / 10000},
                    {"type": "tick", "dt": 0.04},
                )
            )
        raw = json.dumps({"event": "end", "inputs": compact}, separators=(",", ":"))
        self.assertLess(len(raw), limits.PLAYER_BODY_BYTES)
        RoundEvent.model_validate_json(raw)
        state = cartridge.replay(key, 1, compact)
        self.assertTrue(state["won"])
        self.assertEqual(state["score"], 45000000)
        self.assertEqual(state, cartridge.replay(key, 1, legacy))

    def test_distribution_is_rechecked_after_file_io_and_debits_one_open(self):
        self.draft()
        self.publish()
        original = bundles.manifest
        switched = []

        def publish_during_read(key):
            if not switched:
                with db(True) as con:
                    con.execute(
                        """INSERT INTO revisions(id,game,num,stage,seed,docs,bundle,created)
                        SELECT 'new-live',game,num+1,'released',seed,docs,bundle,created FROM revisions WHERE id=?""",
                        (self.rev,),
                    )
                    con.execute(
                        "UPDATE games SET live='new-live' WHERE id=?", (self.game,)
                    )
                switched.append(True)
            return original(key)

        path = "play/" + self.game + "/open"
        player = {"player": "publication-race-01", "delivery": "cached"}
        with (
            patch.object(bundles, "manifest", side_effect=publish_during_read),
            patch.object(limits, "OPEN_PER_STUDIO_DAY", 1),
        ):
            response = self.post(path, player)
            self.assertEqual(response["version"], 2)
            self.assertEqual(self.post(path, player, 429)["code"], "QUOTA_EXCEEDED")
        with db() as con:
            self.assertEqual(
                need(con, "SELECT rev FROM rounds WHERE id=?", response["round"])[
                    "rev"
                ],
                "new-live",
            )
            self.assertEqual(
                need(con, "SELECT SUM(opens) n FROM player_intake")["n"], 1
            )

    def test_replay_budget_and_expiry_preserve_verified_results_and_counts(self):
        self.draft()
        self.publish()
        with patch.object(limits, "REPLAY_BYTES_PER_DAY", 1):
            reduced = self.play()
        retained = self.play()
        at = now()
        with db(True) as con:
            before = report(con, at - 3600, at + 10)["total"]
            self.assertEqual(
                need(con, "SELECT replay,won FROM rounds WHERE id=?", reduced),
                {"replay": None, "won": 1},
            )
            self.assertTrue(
                need(con, "SELECT replay FROM rounds WHERE id=?", retained)["replay"]
            )
            self.assertEqual(
                need(con, "SELECT SUM(omitted_replays) n FROM player_intake")["n"], 1
            )
        retention.sweep(at + (limits.REPLAY_RETENTION_DAYS + 1) * 86400, batch_size=1)
        with db() as con:
            self.assertEqual(need(con, "SELECT COUNT(replay) n FROM rounds")["n"], 0)
            self.assertEqual(report(con, at - 3600, at + 10)["total"], before)

    def test_expiry_window_resets_in_place_and_idle_limits_are_swept(self):
        counter = [("test", "one", 1, 30)]
        with patch.object(rate_limits, "now", return_value=100):
            self.assertEqual(rate_limits.consume(counter), 0)
            self.assertEqual(rate_limits.consume(counter), 30)
            rate_limits.consume([("test", "two", 1, 30)])
        with patch.object(rate_limits, "now", return_value=140):
            self.assertEqual(rate_limits.consume(counter), 0)
        with db() as con:
            self.assertEqual(need(con, "SELECT COUNT(*) n FROM request_limits")["n"], 2)
        retention.sweep(140)
        with db() as con:
            self.assertEqual(
                need(con, "SELECT used,expires FROM request_limits"),
                {"used": 1, "expires": 170},
            )

    def test_deferred_daily_proposals_resume_once_from_the_ranked_window(self):
        self.draft()
        self.publish()
        self.play()
        day = dt.datetime.now(ZONE).date() - dt.timedelta(days=1)
        midday = int(dt.datetime.combine(day, dt.time(12), ZONE).timestamp())
        with db(True) as con:
            con.execute(
                "UPDATE rounds SET issued=?,started=?,ended=? WHERE preview=0",
                (midday, midday + 1, midday + 6),
            )
        with patch.object(limits, "NEW_ANALYSES_PER_DAY", 1):
            first = batches.run_batch(day)
            self.assertEqual(len(first["proposals"]), 1)
            self.assertEqual(
                first["pending"],
                [{"game": self.game, "revision": self.rev, "kind": "new_game"}],
            )
            self.assertEqual(batches.run_batch(day), first)
            retry = first["retry_at"] + 1
            with (
                patch.object(batches, "now", return_value=retry),
                patch.object(evidence, "now", return_value=retry),
                patch.object(
                    batches, "report", side_effect=AssertionError("changed snapshot")
                ),
            ):
                resumed = batches.run_batch(day)
                self.assertEqual(resumed["report"], first["report"])
                self.assertEqual(resumed["pending"], [])
                self.assertEqual(len(set(resumed["proposals"])), 2)
                self.assertEqual(batches.run_batch(day), resumed)

    def test_host_blueprint_and_remote_use_the_same_level_file_in_both_modes(self):
        for choice, mode in ((0, "runtime"), (1, "prefab")):
            with self.subTest(mode=mode):
                self.draft(choice=choice)
                rev = self.get("games/" + self.game)["revision"]
                root = cartridge.folder(rev["bundle"])
                config = json.loads((root / "level.json").read_bytes())
                self.assertEqual(config["mode"], mode)
                pack = self.get("revisions/" + self.rev + "/levels")
                self.assertEqual(pack["configuration"], config)
                opened = self.post(
                    "play/" + self.game + "/open",
                    {"player": "config-player-00001", "preview": self.rev, "level": 2},
                )
                entry = opened["game"]["level_entry"]
                self.assertEqual(entry, config["entries"][1])
                ctx = cartridge.remote_context((root / "remoteEntry.js").read_text())
                actual = cartridge.evaluate(
                    ctx, "loadedGame.level(2," + json.dumps(entry) + ")"
                )
                self.assertEqual(
                    actual,
                    {k: v for k, v in pack["levels"][1].items() if k != "changes"},
                )
                self.assertEqual(cartridge.evaluate(ctx, "loadedGame.level(2)"), actual)
                changed = {**entry, "seconds": entry["seconds"] + 1}
                self.assertEqual(
                    cartridge.evaluate(
                        ctx, "loadedGame.level(2," + json.dumps(changed) + ").seconds"
                    ),
                    changed["seconds"],
                )

    def test_direction_images_follow_design_into_child_runs_without_redownload(self):
        self.draft()
        version = self.get("games/" + self.game)["revision"]
        docs = version["docs"]
        selected = docs["research"]["directions"][version["choice"]]["references"]
        self.assertEqual(
            docs["art"]["research_references"]["ids"], [r["id"] for r in selected]
        )

        async def inspect():
            binding = await skillbook.pin("revision:child-art", "production")
            with patch.object(
                research, "image_input", side_effect=AssertionError("mutable download")
            ):
                _, _, data = await production_nodes.prepare_request(
                    "art",
                    version,
                    {k: v for k, v in docs.items() if k != "art_spec"},
                    {},
                    {"_run_binding": binding},
                )
            for picture in data["_image_inputs"]:
                raw = base64.b64decode(picture["data"])
                digest = hashlib.sha256(raw).hexdigest()
                result = self.client.get(
                    f"/api/agent-runs/{binding['id']}/media/{digest}"
                )
                self.assertEqual(result.content, raw)

        asyncio.run(inspect())
