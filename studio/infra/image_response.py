"""Read a bounded Responses result. Only a terminal message can seal a paid tool call."""

import json

import httpx

MAX_RESPONSE_BYTES = 64 * 1024 * 1024


def _chunks(response):
    received = 0
    for chunk in response.iter_bytes(chunk_size=64 * 1024):
        received += len(chunk)
        if received > MAX_RESPONSE_BYTES:
            raise ValueError("图像响应超过容量")
        yield chunk


def _lines(chunks):
    pending = bytearray()
    for chunk in chunks:
        parts = chunk.split(b"\n")
        for part in parts[:-1]:
            pending.extend(part)
            yield bytes(pending).rstrip(b"\r")
            pending.clear()
        pending.extend(parts[-1])
    if pending:
        yield bytes(pending).rstrip(b"\r")


def _events(chunks):
    data = []
    for line in _lines(chunks):
        if line.startswith(b"data:"):
            data.append(line[5:].removeprefix(b" "))
        elif not line and data:
            yield b"\n".join(data)
            data.clear()
    if data:
        yield b"\n".join(data)


def _result(items):
    if not isinstance(items, list):
        raise ValueError("图像网关返回无效的产物列表")
    return next(
        (
            item
            for item in items
            if isinstance(item, dict)
            and item.get("type") == "image_generation_call"
            and item.get("status", "completed") == "completed"
            and isinstance(item.get("result"), str)
            and item["result"]
        ),
        None,
    )


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("图像网关返回无效的响应对象")
    return value


def completed_image(response: httpx.Response):
    chunks = _chunks(response)
    candidate = None
    if "text/event-stream" not in response.headers.get("content-type", ""):
        reply = _object(json.loads(b"".join(chunks)))
        if reply.get("status", "completed") == "completed":
            candidate = _result(reply.get("output", []))
    else:
        terminal = False
        for payload in _events(chunks):
            if payload.strip() == b"[DONE]":
                terminal = True
                break
            event = _object(json.loads(payload))
            kind = event.get("type")
            if kind in (
                "error",
                "response.failed",
                "response.incomplete",
                "response.cancelled",
            ):
                raise RuntimeError("图像网关未完成生成")
            if kind == "response.output_item.done":
                candidate = _result([event.get("item")]) or candidate
            if kind == "response.completed":
                reply = _object(event.get("response", {}))
                if reply.get("status", "completed") != "completed":
                    raise RuntimeError("图像网关返回未完成状态")
                candidate = _result(reply.get("output", [])) or candidate
                terminal = True
                break
        if not terminal:
            raise RuntimeError("图像响应流在确认完成前中断")
    if candidate is None:
        raise RuntimeError("图像响应缺少已完成的生图结果")
    return candidate
