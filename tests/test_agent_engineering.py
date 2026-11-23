"""Regression checks for node inputs, provisional streams and model/tool failures."""

import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from agentscope.event import TextBlockDeltaEvent
from agentscope.message import AssistantMsg

from studio import agents, context, research, settings, skillbook
from studio.domain.context_policy import bounded
from studio.infra import image_response, monitoring, research_stream
from studio.infra.store import db, init
from studio.services import progress
from tests.support import IDEA, StudioCase


class StreamAndToolTests(unittest.TestCase):
    def test_only_top_level_streams_and_flushes_short_final(self):
        chunks = [
            '{"nested":{"summary":"内部草稿"},',
            '"summary":"含有\\"引号\\"和',
            '数字7"}',
        ]
        complete = "".join(chunks)

        class Stream:
            async def reply_stream(self, message, *, yield_final_msg):
                for chunk in chunks:
                    yield TextBlockDeltaEvent(reply_id="r", block_id="b", delta=chunk)
                yield AssistantMsg(name="Research", content=complete)

        publish = AsyncMock()
        result = asyncio.run(research_stream.research_reply(Stream(), None, publish))
        self.assertEqual(result.get_text_content(), complete)
        self.assertEqual(
            [x.args[0] for x in publish.await_args_list], ['含有"引号"和数字7']
        )
        self.assertEqual(
            research_stream.partial_summary(
                '{"notes":"summary","nested":{"summary":"N"}}'
            ),
            "",
        )

    def test_stream_is_bounded_and_generator_is_closed(self):
        closed = []

        class Oversize:
            async def reply_stream(self, message, *, yield_final_msg):
                try:
                    yield TextBlockDeltaEvent(
                        reply_id="r", block_id="b", delta="流" * 23000
                    )
                finally:
                    closed.append(True)

        with self.assertRaisesRegex(ValueError, "预算"):
            asyncio.run(research_stream.research_reply(Oversize(), None, AsyncMock()))
        self.assertEqual(closed, [True])

    def test_provisional_image_requires_a_successful_terminal_event(self):
        item = {"type": "image_generation_call", "result": "synthetic-encoded-pixels"}
        events = [{"type": "response.output_item.done", "item": item}]

        def stream(frames):
            text = "".join(
                "data: "
                + (frame if isinstance(frame, str) else json.dumps(frame))
                + "\r\n\r\n"
                for frame in frames
            )
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=text.encode(),
            )

        for end in (
            [],
            [{"type": "response.failed"}],
            [{"type": "response.incomplete"}],
            [{"type": "response.completed", "response": {"status": "incomplete"}}],
        ):
            with self.subTest(end=end), self.assertRaises(RuntimeError):
                image_response.completed_image(stream(events + end))
        for end in (
            "[DONE]",
            {"type": "response.completed", "response": {"status": "completed"}},
        ):
            self.assertEqual(
                image_response.completed_image(stream(events + [end])), item
            )
        with (
            patch.object(image_response, "MAX_RESPONSE_BYTES", 24),
            self.assertRaises(ValueError),
        ):
            image_response.completed_image(stream(events + ["[DONE]"]))
        with self.assertRaises(ValueError):
            image_response.completed_image(httpx.Response(200, json=[]))

    def test_configuration_fails_before_jobs_and_redacts_secrets(self):
        for key, value in (
            ("ZAI_BASE_URL", "http://example.com"),
            ("STUDIO_PUBLIC_URL", "https://local:invalid"),
            ("STUDIO_RESEARCH_ONLINE", "sometimes"),
            ("STUDIO_ART_MODE", "fallback"),
            ("STUDIO_DATA_DIR", " "),
        ):
            with (
                self.subTest(key=key),
                patch.dict(os.environ, {key: value}, clear=True),
                self.assertRaises(RuntimeError),
            ):
                settings.validate_runtime()
        with patch.dict(
            os.environ,
            {
                "ZAI_1_TOKEN": "fake-chat",
                "STUDIO_ART_API_KEY": "fake-image",
                "ZAI_BASE_URL": "http://127.0.0.1:9765/v1",
            },
            clear=True,
        ):
            settings.validate_runtime()
            self.assertNotIn("fake-chat", repr(settings.chat_settings()))
            self.assertNotIn("fake-image", repr(settings.art_settings()))

    def test_tool_outcomes_and_context_budget_preserve_confounds(self):
        self.assertEqual(
            [
                research.search_outcome(*x)["status"]
                for x in [(0, 0, 0), (2, 0, 0), (2, 1, 0), (2, 2, 0), (2, 2, 1)]
            ],
            ["offline", "unavailable", "partial", "empty", "complete"],
        )
        evidence = {"external_changes": ["入口换量"], "peers": ["a" * 80] * 30}
        trimmed = bounded({"evidence": evidence}, limit=1200)
        self.assertEqual(len(trimmed["evidence"]["peers"]), 3)
        self.assertEqual(len(evidence["peers"]), 30)
        self.assertEqual(trimmed["evidence"]["external_changes"], ["入口换量"])
        with self.assertRaisesRegex(ValueError, "必要证据"):
            bounded({"evidence": {"external_changes": ["x" * 2000]}}, limit=1200)


class StreamingEndpointTests(StudioCase):
    def test_serial_guard_and_reconnect_at_gate(self):
        item = self.post("games", IDEA, 201)
        rid = item["rev"]
        self.game = item["game"]
        self.work()
        gate = self.get("games/" + self.game)
        url = "/api/revisions/" + rid + "/events"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"].split(";")[0], "text/event-stream"
        )
        cursor = next(
            line[4:] for line in response.text.splitlines() if line.startswith("id: ")
        )
        self.assertTrue(json.loads(response.text.split("data: ")[1])["terminal"])
        self.assertIn(
            "event: progress",
            self.client.get(url, headers={"Last-Event-ID": cursor}).text,
        )
        self.decision("select_references", reference_ids=["beacon"])
        from studio.infra.repositories import revisions

        current = self.get("games/" + self.game)["revision"]
        with db(True) as con:
            revisions.stream_research(con, "新草稿", rid, current["serial"])
            revisions.stream_research(con, "过期写入", rid, gate["revision"]["serial"])
            self.assertNotIn(
                "research_draft", json.loads(revisions.get(con, rid)["docs"])
            )
        self.assertEqual(progress.snapshot(rid, None)[1]["summary"], "新草稿")
        self.assertEqual(
            self.get("games/" + self.game)["revision"]["docs"]["research_draft"],
            "新草稿",
        )
        self.work()
        with db() as con:
            self.assertIsNone(
                con.execute(
                    "SELECT rev FROM revision_drafts WHERE rev=?", (rid,)
                ).fetchone()
            )
        with patch.dict(os.environ, {"STUDIO_ACCESS_KEY": "disposable"}):
            self.assertEqual(self.client.get(url).status_code, 401)
            token = self.post("login", {"key": "disposable"})["session"]
            from studio.api.auth import session_digest

            digest = session_digest(token, "disposable")
            self.assertTrue(progress.snapshot(rid, digest)[1]["terminal"])
            self.assertEqual(
                self.client.post(
                    "/api/logout", json={}, headers={"Origin": "http://localhost"}
                ).status_code,
                200,
            )
            from studio.infra.store import Problem

            with self.assertRaises(Problem):
                progress.snapshot(rid, digest)

    def test_reconnect_advances_draft_and_revocation_closes_an_open_stream(self):
        from types import SimpleNamespace

        from studio.api import catalog
        from studio.infra.repositories import revisions, sessions
        from studio.infra.store import now
        from studio.services import revisions as revision_service

        item = self.post("games", IDEA, 201)
        self.game = item["game"]
        rid = item["rev"]
        self.work()
        self.decision("select_references", reference_ids=["beacon"])
        with db(True) as con:
            serial = revisions.get(con, rid)["serial"]
            sessions.issue(con, "local-session", now() + 30)
        cursor, _ = progress.snapshot(rid, "local-session")

        async def consume():
            request = SimpleNamespace(
                headers={"last-event-id": cursor},
                is_disconnected=AsyncMock(return_value=False),
            )
            response = await catalog.revision_events(rid, request, "local-session")
            body = response.body_iterator
            self.assertIn("retry:", await anext(body))
            with db(True) as con:
                revisions.stream_research(con, "可恢复的最新草稿", rid, serial)
            self.assertIn("可恢复的最新草稿", await asyncio.wait_for(anext(body), 3))
            with db(True) as con:
                sessions.revoke(con, "local-session")
            self.assertIn("session_closed", await asyncio.wait_for(anext(body), 3))
            with self.assertRaises(StopAsyncIteration):
                await anext(body)

        asyncio.run(consume())
        from studio.infra.store import Problem

        with self.assertRaises(Problem):
            revision_service.checkpoint(
                rid,
                "interpret",
                "research",
                {"summary": "stale"},
                "Research",
                serial=serial - 1,
            )
        self.assertNotIn("research", self.get("games/" + self.game)["revision"]["docs"])

    def test_v1_pinned_impact_schema_resumes_with_the_same_prompt(self):
        binding = asyncio.run(skillbook.pin("old-impact", "production"))
        (old_schema,) = agents.Impact.compatible_schema_hashes
        with db(True) as con:
            con.execute(
                "INSERT INTO agent_prompts VALUES(?,?,?,?,?)",
                (binding["id"], "Producer", "Impact", old_schema, "旧版约束"),
            )
        self.assertEqual(
            skillbook.bind_prompt(
                binding["id"], "Producer", "Impact", agents.Impact, "新约束"
            ),
            "旧版约束",
        )
        self.assertIsNone(
            agents.Impact.model_validate(
                {
                    "reason": "修改声音",
                    "affected": ["art"],
                    "audio": True,
                    "entities": [],
                }
            ).audio_tracks
        )

    def test_readiness_requires_a_recent_elected_worker_and_reconciliation(self):
        from studio.infra.repositories import jobs
        from studio.infra.store import now

        self.assertEqual(monitoring.readiness(True)["status"], "unavailable")
        with db(True) as con:
            jobs.leader_pulse(con, now())
            jobs.reconciliation_result(con, now(), True)
        self.assertEqual(monitoring.readiness(True)["status"], "ready")
        with db(True) as con:
            jobs.leader_pulse(con, now() - 46)
        self.assertFalse(monitoring.readiness(True)["checks"]["worker"]["ok"])
        with db(True) as con:
            jobs.leader_pulse(con, now())
            for _ in range(3):
                jobs.reconciliation_result(con, now(), False)
        self.assertFalse(monitoring.readiness(True)["checks"]["worker"]["ok"])


class ModelObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_bound_attempts_have_usage_and_replayable_prompt(self):
        replies = iter(
            [
                "{}",
                '{"summary":"分配调研","focus":["玩法"],"next_role":"GameplayResearch"}',
            ]
        )

        class Agent:
            def __init__(self, **kwargs):
                pass

            async def reply(self, message):
                return AssistantMsg(
                    name="Producer",
                    content=next(replies),
                    finished_reason=agents.ReplyFinishedReason.COMPLETED,
                    usage={"input_tokens": 18, "output_tokens": 7},
                )

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(
                os.environ,
                {"STUDIO_DATA_DIR": folder, "ZAI_1_TOKEN": "fixture"},
                clear=True,
            ),
            patch.object(agents, "Agent", Agent),
        ):
            init()
            binding = await skillbook.pin("test-run", "production")
            value, _ = await agents.consult(
                "Producer",
                agents.Route,
                {
                    "_run_binding": binding,
                    "_node": "route",
                    "request_stage": "research",
                },
            )
            meta = value["_run"]
            self.assertEqual(meta["attempt"], 2)
            self.assertEqual(meta["usage"]["output_tokens"], 7)
            report = monitoring.metrics()
            for outcome in ("invalid_output", "success"):
                labels = '{role="Producer",provider="zai_1",outcome="' + outcome + '"}'
                self.assertIn("studio_model_calls_total" + labels + " 1\n", report)
                self.assertIn(
                    "studio_model_input_tokens_total" + labels + " 18\n", report
                )
            with db() as con:
                saved = context.inspect_input(
                    con, binding["id"], "route", meta["context_sha256"]
                )
                self.assertEqual(saved["prompt_sha256"], meta["prompt_revision"])
                self.assertEqual(saved["input"], {"request_stage": "research"})
            with db(True) as con:
                con.execute(
                    "UPDATE agent_prompts SET prompt='changed' WHERE run=?",
                    (binding["id"],),
                )
            from studio.infra.store import Problem

            with db() as con, self.assertRaisesRegex(Problem, "提示"):
                context.inspect_input(
                    con, binding["id"], "route", meta["context_sha256"]
                )


class KnowledgeReviewTests(StudioCase):
    def test_cutoff_and_atomic_supersession(self):
        from studio.infra.repositories import evidence
        from studio.services import review

        game = self.post("games", IDEA, 201)["game"]
        other = self.post("games", {**IDEA, "title": "另一个项目"}, 201)["game"]
        with db(True) as con:
            for key, gid, citations in (
                ("old", game, []),
                ("other", other, []),
                ("new", game, ["old", "other"]),
            ):
                evidence.propose_knowledge(
                    con,
                    key,
                    gid,
                    "exp",
                    key,
                    json.dumps({"attribution": "假设错", "citations": citations}),
                    "现象",
                    0.65,
                    None,
                    20,
                )
        with patch.object(review, "now", return_value=100):
            self.post("knowledge/old/review", {"accept": True, "note": "适用首关"})
            self.post("knowledge/other/review", {"accept": True})
        with patch.object(review, "now", return_value=200):
            self.post(
                "knowledge/new/review",
                {"accept": True, "supersede": ["old", "other"]},
                409,
            )
            entries = {e["id"]: e for e in self.get("memory")["entries"]}
            self.assertEqual(
                (entries["old"]["status"], entries["new"]["status"]),
                ("active", "pending"),
            )
            self.post(
                "knowledge/new/review",
                {"accept": True, "supersede": ["old"], "note": "新玩家的分母已复核"},
            )
        entries = {e["id"]: e for e in self.get("memory")["entries"]}
        self.assertEqual(
            (entries["old"]["replacement"], entries["new"]["review_note"]),
            ("new", "新玩家的分母已复核"),
        )
        with db() as con:
            expected = [
                (100, []),
                (150, ["old"]),
                (200, ["old"]),
                (201, ["new"]),
                (None, ["new"]),
            ]
            for cutoff, ids in expected:
                captured = context.capture(con, game, cutoff)
                self.assertEqual(
                    [
                        k["id"]
                        for k in context.memory_for("Analyst", captured)[
                            "approved_knowledge"
                        ]
                    ],
                    ids,
                )
            self.assertEqual(
                con.execute("SELECT count(*) FROM knowledge_reviews").fetchone()[0], 4
            )

    def test_old_review_timestamp_is_conservatively_migrated_once(self):
        from studio.infra.repositories import evidence

        now = 45
        with db(True) as con:
            con.execute("DELETE FROM schema_migrations WHERE name LIKE 'migrate_003_%'")
            for kind, name in (
                ("VIEW", "knowledge_admissions"),
                ("TABLE", "knowledge_reviews"),
                ("TABLE", "revision_drafts"),
                ("TABLE", "dead_end_records"),
                ("INDEX", "history_game_kind_time"),
                ("TABLE", "worker_health"),
                ("TABLE", "model_call_totals"),
            ):
                con.execute(f"DROP {kind} {name}")
            evidence.propose_knowledge(
                con,
                "legacy",
                "old-game",
                "exp",
                "曾经采纳",
                "{}",
                "现象",
                0.65,
                None,
                now,
            )
            con.execute("UPDATE knowledge SET status='active' WHERE id='legacy'")
        init()
        init()
        with db() as con:
            self.assertEqual(context.capture(con, "old-game", now + 1)["knowledge"], [])
            (item,) = context.capture(con, "old-game")["knowledge"]
            self.assertGreater(item["admitted"], now)
            self.assertIn("原审核时间未记录", item["review_note"])
