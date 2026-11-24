"""AgentScope Responses gateway. Each role receives an isolated agent and pinned instructions."""

import asyncio
import base64
import hashlib
import itertools
import json
import logging
import time

from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import Base64Source, DataBlock, TextBlock, UserMsg
from agentscope.model import OpenAIResponseModel
from agentscope.types import ReplyFinishedReason
from openai import AuthenticationError, RateLimitError
from pydantic import ValidationError

from studio.application.agents import skillbook
from studio.application.agents.streaming import research_reply
from studio.application.memory import projection, snapshots
from studio.application.prompts.builder import system_prompt
from studio.domain.agent_outputs import (
    Art,
    Source,
)
from studio.domain.fingerprints import digest
from studio.infra import model_metrics
from studio.settings import chat_settings

_counter = itertools.count()
_cooldowns: dict[str, float] = {}
for logger in ("openai", "httpx", "agentscope"):
    logging.getLogger(logger).setLevel(logging.WARNING)


async def _validated_reply(
    agent, request, on_summary, schema, evidence, role, provider, measure
):
    started = time.monotonic()
    outcome, usage = "provider_error", None
    try:
        msg = await asyncio.wait_for(
            research_reply(agent, request, on_summary)
            if on_summary
            else agent.reply(request),
            timeout=300,
        )
        report = getattr(msg, "usage", None)
        if report and all(
            isinstance(getattr(report, k, None), int)
            for k in ("input_tokens", "output_tokens")
        ):
            usage = {
                "input_tokens": report.input_tokens,
                "output_tokens": report.output_tokens,
            }
        if msg.finished_reason != ReplyFinishedReason.COMPLETED:
            outcome = "incomplete"
            raise RuntimeError("模型未完成回复")
        text = msg.get_text_content().strip()
        if text.startswith("```"):
            text = text.partition("\n")[2].rsplit("```", 1)[0].strip()
        outcome = "invalid_output"
        product = schema.model_validate_json(
            text, context=evidence if isinstance(evidence, dict) else None
        )
        outcome = "success"
        return product.model_dump(), usage
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        if measure:
            await asyncio.to_thread(
                model_metrics.record,
                role,
                provider,
                outcome,
                round((time.monotonic() - started) * 1000),
                usage,
            )
        if on_summary and outcome != "success":
            await on_summary("")


async def consult(role, schema, context):
    config = chat_settings()
    pool = config.providers
    if not pool:
        raise RuntimeError("请配置 ZAI_1_TOKEN、ZAI_2_TOKEN 或 ZAI_EXTRA_TOKEN")
    available = [
        provider
        for provider in pool
        if _cooldowns.get(provider[0], 0) <= time.monotonic()
    ]
    if available:
        pool = available
    start = next(_counter) % len(pool)
    run = context.get("_run_binding", {})
    started = time.monotonic()
    skills = await skillbook.read(role, context.get("task"), run)
    handbook = "\n\n".join(item["body"] for item in skills)
    prompt = system_prompt(role, schema, context, handbook)
    node = context.get("_node") or context.get("phase") or schema.__name__
    if run:
        prompt = skillbook.bind_prompt(run["id"], role, node, schema, prompt)
    media = context.get("_image_inputs", [])
    on_summary = context.get("_on_summary")
    visible = projection.clean_handoff(context)
    memory = context.get("_memory")
    if memory:
        visible["project_memory"] = projection.memory_for(role, memory)
    visible = projection.bounded(visible)
    instruction = json.dumps(
        visible, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    image_hashes = {}
    image_bytes = 0
    if len(media) > 4 or len(prompt.encode()) > 64 * 1024:
        raise ValueError("系统提示或参考图数量超过本次模型输入预算")
    for item in media:
        if len(item["data"]) > 1_400_000 or item["name"] in image_hashes:
            raise ValueError("参考图过大或 ID 重复")
        raw = base64.b64decode(item["data"], validate=True)
        image_bytes += len(raw)
        image_hashes[item["name"]] = hashlib.sha256(raw).hexdigest()
    if image_bytes > 3 * 1024 * 1024:
        raise ValueError("参考图总容量超过本次模型输入预算")
    fingerprint = snapshots.archive_input(
        run.get("id"), node, visible, image_hashes, role=role, prompt=prompt
    )
    evidence = context.get("evidence")
    failures = []
    calls = 0
    for offset in range(len(pool)):
        name, key = pool[(start + offset) % len(pool)]
        model = OpenAIResponseModel(
            credential=OpenAICredential(
                api_key=key,
                base_url=config.base_url,
            ),
            model=run.get("model") or config.model,
            stream=True,
            max_retries=0,
            parameters=OpenAIResponseModel.Parameters(
                max_tokens=6500
                if (schema is Source or issubclass(schema, Art)) or role == "Moderator"
                else 3800,
                reasoning_effort="low",
            ),
            client_kwargs={"timeout": 180.0, "max_retries": 0},
        )
        try:
            agent = Agent(name=role, system_prompt=prompt, model=model)
            message = instruction
            for attempt in range(2):
                calls += 1
                request = UserMsg(
                    name="studio",
                    content=(
                        [
                            TextBlock(text=message),
                            *[
                                DataBlock(
                                    name=m["name"],
                                    source=Base64Source(
                                        media_type="image/jpeg", data=m["data"]
                                    ),
                                )
                                for m in media
                            ],
                        ]
                        if media and attempt == 0
                        else message
                    ),
                )
                try:
                    product, usage = await _validated_reply(
                        agent,
                        request,
                        on_summary,
                        schema,
                        evidence,
                        role,
                        name,
                        bool(run),
                    )
                    product["_run"] = {
                        "role": role,
                        "provider": name,
                        "model": model.model,
                        "prompt_revision": digest(prompt),
                        "run_id": run.get("id"),
                        "node": node,
                        "phase": context.get("phase") or context.get("request_stage"),
                        "context_sha256": fingerprint,
                        "context_bytes": len(instruction.encode()),
                        "system_bytes": len(prompt.encode()),
                        "image_bytes": image_bytes,
                        "evidence_sha256": context.get("_evidence_hash"),
                        "preference_version": memory["preferences"]["version"]
                        if memory
                        else None,
                        "image_hashes": image_hashes,
                        "attempt": calls,
                        "usage": usage,
                        "prior_failures": list(failures),
                        "elapsed_ms": round((time.monotonic() - started) * 1000),
                        "skills": {s["name"]: s["revision"] for s in skills},
                    }
                    return product, name
                except ValidationError as exc:
                    if attempt:
                        raise
                    issues = exc.errors(
                        include_url=False, include_input=False, include_context=False
                    )
                    message = (
                        "请纠正上一个 JSON 产物并重新完整输出。字段问题："
                        + json.dumps(issues, ensure_ascii=False)[:1500]
                    )
        except Exception as exc:  # noqa: BLE001 - SDK and transport failures share the credential failover boundary.
            if isinstance(exc, (RateLimitError, AuthenticationError)):
                _cooldowns[name] = time.monotonic() + 300
            detail = type(exc).__name__
            if isinstance(exc, ValidationError):
                detail += " " + ", ".join(
                    ".".join(map(str, err["loc"])) + "/" + err["type"]
                    for err in exc.errors(include_input=False)[:4]
                )
            failures.append(f"{name} ({detail})")
        finally:
            await model.client.close()
    raise RuntimeError("模型调用或产物校验失败：" + "、".join(failures))
