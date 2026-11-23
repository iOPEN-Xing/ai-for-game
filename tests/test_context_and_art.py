"""Check the exact SDK handoff, archived inputs, image transport and retry semantics."""

import asyncio
import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import app
from studio import agents, context, research, skillbook
from studio import image_service as images
from studio.store import db, init


class ContextAndArtTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(
            os.environ,
            {
                "STUDIO_DATA_DIR": tmp.name,
                "STUDIO_ACCESS_KEY": "",
                "STUDIO_DEPLOYED": "0",
                "ZAI_1_TOKEN": "fixture",
                "ZAI_2_TOKEN": "",
                "ZAI_EXTRA_TOKEN": "",
                "ZAI_MODEL": "glm-5.4",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        init()

    def test_pinned_skill_revision_model_context_and_prompt_are_recoverable(self):
        async def check():
            run = await skillbook.pin("proposal:resume")
            with db() as con:
                memory = context.capture(con, "project-1")
            memory["preferences"] = {
                "version": 3,
                "values": {"audience": "通勤", "visual_style": "插画"},
            }
            sent = []

            class RecordedAgent:
                def __init__(self, **params):
                    sent.append(params["system_prompt"])

                async def reply(self, message):
                    sent.append(json.loads(message.get_text_content()))
                    return SimpleNamespace(
                        finished_reason=agents.ReplyFinishedReason.COMPLETED,
                        get_text_content=lambda: json.dumps(
                            {
                                "evidence": "首关正式样本",
                                "objection": "时间短",
                                "recommendation": "观察次日回访",
                            }
                        ),
                    )

            with (
                patch.object(
                    skillbook.loader,
                    "list_skills",
                    side_effect=AssertionError("不应读当前文件"),
                ),
                patch.dict(os.environ, {"ZAI_MODEL": "new-default"}),
                patch.object(agents, "Agent", RecordedAgent),
            ):
                resumed = await skillbook.pin("proposal:resume")
                result, _ = await agents.consult(
                    "Analyst",
                    agents.Opinion,
                    {
                        "task": "iteration",
                        "phase": "independent",
                        "_node": "Analyst",
                        "_run_binding": resumed,
                        "_memory": memory,
                        "evidence": {"inference_mode": "descriptive"},
                    },
                )
            audit = result["_run"]
            self.assertEqual(audit["model"], "glm-5.4")
            self.assertEqual(
                set(audit["skills"]), {"iterate-live-game", "review-game-experiments"}
            )
            self.assertIn("存量游戏改版", sent[0])
            self.assertNotIn("新游戏立项的独立约束审计", sent[0])
            self.assertEqual(
                sent[1]["project_memory"]["preferences"], {"audience": "通勤"}
            )
            self.assertEqual(audit["preference_version"], 3)
            with db() as con:
                archived = context.inspect_input(
                    con, run["id"], "Analyst", audit["context_sha256"]
                )
            self.assertEqual(archived["prompt"], sent[0])
            self.assertEqual(archived["input"], sent[1])
            self.assertEqual(
                skillbook.digest(archived["prompt"]), audit["prompt_revision"]
            )
            client = TestClient(
                app.app, base_url="http://localhost", client=("127.0.0.1", 50000)
            )
            try:
                url = f"/api/agent-runs/{run['id']}/nodes/Analyst/contexts/{audit['context_sha256']}"
                self.assertEqual(client.get(url).status_code, 200)
                with patch.dict(os.environ, {"STUDIO_ACCESS_KEY": "private"}):
                    self.assertEqual(client.get(url).status_code, 401)
            finally:
                client.close()

        asyncio.run(check())

    def test_selected_pixels_are_archived_and_retries_do_not_redownload(self):
        async def check():
            run = await skillbook.pin("revision:images", "production")
            ref = next(
                item for item in research.retrieve("海岛") if item["id"] == "beacon"
            )
            first = await research.frozen_image(run["id"], ref)
            with patch.object(
                research, "image_input", side_effect=AssertionError("不应重新下载")
            ):
                self.assertEqual(await research.frozen_image(run["id"], ref), first)
            raw = base64.b64decode(first["data"])
            digest = hashlib.sha256(raw).hexdigest()
            client = TestClient(
                app.app, base_url="http://localhost", client=("127.0.0.1", 50000)
            )
            try:
                self.assertEqual(
                    client.get(f"/api/agent-runs/{run['id']}/media/{digest}").content,
                    raw,
                )
                self.assertEqual(
                    client.get(
                        f"/api/agent-runs/revision:another/media/{digest}"
                    ).status_code,
                    404,
                )
            finally:
                client.close()

        asyncio.run(check())

    def test_responses_image_reference_cache_failure_and_retry(self):
        image = Image.new("RGBA", (96, 96))
        ImageDraw.Draw(image).rectangle([25, 13, 65, 74], fill="orange")
        out = io.BytesIO()
        image.save(out, format="PNG")
        encoded = base64.b64encode(out.getvalue()).decode()
        item = {"type": "image_generation_call", "result": encoded}
        requests = []

        def reply(request):
            payload = json.loads(request.content)
            requests.append(payload)
            self.assertEqual(request.url.path, "/v1/responses")
            self.assertEqual(request.headers["Authorization"], "Bearer fixture-art")
            if len(requests) == 2:
                return httpx.Response(403, json={"error": "disabled"})
            frame = json.dumps({"type": "response.output_item.done", "item": item})
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="data: " + frame + "\n\n",
            )

        real = httpx.Client

        def client(**kw):
            return real(transport=httpx.MockTransport(reply), **kw)

        with (
            patch.dict(
                os.environ,
                {
                    "STUDIO_ART_API_KEY": "fixture-art",
                    "STUDIO_ART_BASE_URL": "https://example.test/v1",
                    "STUDIO_ART_IMAGE_MODEL": "gpt-image-2",
                    "STUDIO_ART_RESPONSE_MODEL": "gpt-image-2",
                },
            ),
            patch.object(images.httpx, "Client", client),
        ):
            base = images.render({"entity": "beacon"}, None)
            self.assertEqual(base, images.render({"entity": "beacon"}, None))
            with self.assertRaisesRegex(RuntimeError, "403"):
                images.render({"entity": "beacon-lit"}, base)
            lit = images.render({"entity": "beacon-lit"}, base)
            self.assertEqual(lit["reference_sha256"], base["sha256"])
            self.assertEqual(len(requests), 3)
            media = requests[-1]["input"][0]["content"][-1]
            self.assertEqual(
                hashlib.sha256(
                    base64.b64decode(media["image_url"].split(",")[1])
                ).hexdigest(),
                base["sha256"],
            )
            self.assertEqual(requests[0]["tools"][0]["model"], "gpt-image-2")
            self.assertNotIn("fixture-art", json.dumps(lit))
