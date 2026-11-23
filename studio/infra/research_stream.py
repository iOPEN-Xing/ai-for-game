"""Project a bounded, top-level JSON summary from an AgentScope text stream."""

import time
from contextlib import aclosing

from agentscope.event import TextBlockDeltaEvent
from agentscope.message import Msg
from pydantic_core import from_json


def partial_summary(text):
    raw = text.lstrip()
    if raw.startswith("```"):
        raw = raw.partition("\n")[2]
    try:
        obj = from_json(raw, allow_partial="trailing-strings")
    except ValueError:
        return ""
    summary = obj.get("summary") if isinstance(obj, dict) else None
    return summary[:2400] if isinstance(summary, str) else ""


async def research_reply(agent, msg, on_summary):
    raw, previous, final = "", "", None
    size, last = 0, 0.0
    async with aclosing(agent.reply_stream(msg, yield_final_msg=True)) as events:
        async for event in events:
            if isinstance(event, Msg):
                final = event
            elif isinstance(event, TextBlockDeltaEvent):
                size += len(event.delta.encode())
                if size > 64 * 1024:
                    raise ValueError("调研报告流超过文本预算")
                raw += event.delta
                if time.monotonic() - last >= 0.7:
                    summary = partial_summary(raw)
                    if summary and summary != previous:
                        await on_summary(summary)
                        previous = summary
                    last = time.monotonic()
    if final is None:
        raise RuntimeError("调研报告流未正常完成")
    summary = partial_summary(final.get_text_content())
    if summary and summary != previous:
        await on_summary(summary)
    return final
