"""Check routing with transport failures without contacting a paid provider."""

import itertools
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from studio.application.agents import gateway, skillbook
from studio.domain import agent_outputs as outputs


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyst_rewrites_uncomputed_interval_in_a_descriptive_report(self):
        observed = "一位访客完成一局并点击，当前没有对照。"
        first = observed + "任何差值的置信区间都覆盖全范围 0–100 个百分点。"
        replies = iter((first, observed))
        attempts = []

        class TestAgent:
            def __init__(self, **_kwargs):
                pass

            async def reply(self, message):
                attempts.append(message.get_text_content())
                report = {
                    "evidence": next(replies),
                    "recommendation": "先补充访客与对照。",
                    "objection": "暂时无法估计改版差值。",
                }
                return SimpleNamespace(
                    finished_reason=gateway.ReplyFinishedReason.COMPLETED,
                    get_text_content=lambda: json.dumps(report),
                )

        with (
            patch.object(gateway, "Agent", TestAgent),
            patch.dict(
                os.environ,
                {"ZAI_1_TOKEN": "test-key", "ZAI_2_TOKEN": "", "ZAI_EXTRA_TOKEN": ""},
            ),
        ):
            result, _ = await gateway.consult(
                "Analyst",
                outputs.Opinion,
                {"evidence": {"inference_mode": "descriptive", "players": 1}},
            )
        self.assertEqual(result["evidence"], observed)
        self.assertEqual(len(attempts), 2)
        self.assertIn("未经结算计算", attempts[1])

    async def test_real_model_configuration_and_fallback_retain_role_skills(self):
        calls = []
        inputs = []

        class TestAgent:
            def __init__(self, name, system_prompt, model):
                calls.append((name, system_prompt, model))

            async def reply(self, message):
                inputs.append(message.get_text_content())
                if len(inputs) == 1:
                    return SimpleNamespace(
                        finished_reason=gateway.ReplyFinishedReason.COMPLETED,
                        get_text_content=lambda: "{}",
                    )
                if len(calls) == 1:
                    raise ConnectionError("upstream unavailable")
                return SimpleNamespace(
                    finished_reason=gateway.ReplyFinishedReason.COMPLETED,
                    get_text_content=lambda: json.dumps(
                        {
                            "summary": "dispatch",
                            "focus": ["input"],
                            "next_role": "Planner",
                        }
                    ),
                )

        opts = {
            "ZAI_MODEL": "glm-5.4",
            "ZAI_BASE_URL": "https://api.z.ai/api/v1",
            "ZAI_WIRE_API": "responses",
            "ZAI_1_TOKEN": "test-first",
            "ZAI_2_TOKEN": "test-second",
            "ZAI_EXTRA_TOKEN": "",
        }
        with (
            patch.dict(os.environ, opts),
            patch.object(gateway, "Agent", TestAgent),
            patch.object(gateway, "_counter", itertools.count()),
            patch.object(gateway, "_cooldowns", {}),
        ):
            result, provider = await gateway.consult(
                "Producer", outputs.Route, {"request_stage": "design"}
            )
        self.assertEqual(provider, "zai_2")
        self.assertIn("请纠正", inputs[1])
        self.assertEqual(json.loads(inputs[2]), {"request_stage": "design"})
        self.assertEqual(result["_run"]["model"], "glm-5.4")
        self.assertEqual(
            [call[2].credential.api_key.get_secret_value() for call in calls],
            ["test-first", "test-second"],
        )
        self.assertTrue(all(call[2].type == "openai_response" for call in calls))
        for s in await skillbook.read("Producer"):
            self.assertIn(s["body"], calls[1][1])
            self.assertEqual(result["_run"]["skills"][s["name"]], s["revision"])
        self.assertNotIn("test-second", json.dumps(result))

    async def test_absent_credentials_cannot_create_a_model_artifact(self):
        with (
            patch.dict(
                os.environ,
                {"ZAI_1_TOKEN": "", "ZAI_2_TOKEN": "", "ZAI_EXTRA_TOKEN": ""},
            ),
            self.assertRaisesRegex(RuntimeError, "ZAI_1_TOKEN"),
        ):
            await gateway.consult("Planner", outputs.Design, {})
