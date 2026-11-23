"""Generate persistent, content-addressed game sprites using an OpenAI Responses gateway."""

import asyncio
import base64
import binascii
import fcntl
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

import httpx
from PIL import Image

from .infra.image_response import completed_image
from .settings import art_settings, data_dir
from .store import encode


def enabled():
    return art_settings().mode == "responses"


def folder():
    return data_dir() / "generated-art"


def png_bytes(record):
    digest = record["sha256"]
    if not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("无效的图像摘要")
    image = (folder() / (digest + ".png")).read_bytes()
    if hashlib.sha256(image).hexdigest() != digest:
        raise ValueError("图像内容与生成记录不符")
    return image


def atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        name = Path(tmp.name)
        try:
            tmp.write(data)
            tmp.flush()
            os.replace(name, path)
        finally:
            name.unlink(missing_ok=True)


def generate(body, base, key):
    with (
        httpx.Client(
            timeout=httpx.Timeout(300, connect=15), follow_redirects=False
        ) as client,
        client.stream(
            "POST",
            base + "/responses",
            json=body,
            headers={"Authorization": "Bearer " + key},
        ) as response,
    ):
        if response.status_code in (401, 403):
            raise RuntimeError(
                f"图像网关 HTTP {response.status_code}，请核对密钥分组的 image_generation 权限，再重试美术任务"
            )
        if not response.is_success:
            raise RuntimeError(
                f"图像网关 HTTP {response.status_code}，请检查 Responses 路由与所选模型"
            )
        return completed_image(response)


def render(spec, reference):
    config = art_settings()
    key, base, model = config.api_key, config.base_url, config.response_model
    if config.mode != "responses" or not key:
        raise RuntimeError("当前配置未启用 Responses 生图")
    tool = {
        "type": "image_generation",
        "size": "1024x1024",
        "quality": "medium",
        "background": "transparent",
    }
    tool["model"] = config.image_model
    prompt = (
        "绘制一张用于移动端小游戏的独立精灵 PNG。主体完整、居中，有明确轮廓和透明留白，"
        "缩到 64 像素仍可辨认。不要文字、边框、拼贴或底板。参考图仅用于保持本游戏内实体风格。\n"
        + encode(spec)
    )
    parent_hash = reference["sha256"] if reference else None
    fingerprint = hashlib.sha256(
        encode([base, model, tool, prompt, parent_hash]).encode()
    ).hexdigest()
    root = folder()
    root.mkdir(parents=True, exist_ok=True)
    cache = root / (fingerprint + ".json")
    with (root / (fingerprint + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cache.is_file():
            try:
                saved = json.loads(cache.read_bytes())
                if (
                    saved["request_hash"] == fingerprint
                    and saved.get("reference_sha256") == parent_hash
                    and saved["model"] == model
                    and saved.get("tool") == tool["model"]
                ):
                    png_bytes(saved)
                    return saved
            except (FileNotFoundError, ValueError, TypeError, KeyError):
                pass
        content = [{"type": "input_text", "text": prompt}]
        if reference:
            uri = (
                "data:image/png;base64,"
                + base64.b64encode(png_bytes(reference)).decode()
            )
            content.append({"type": "input_image", "image_url": uri})
        item = generate(
            {
                "model": model,
                "input": [{"role": "user", "content": content}],
                "tools": [tool],
                "tool_choice": {"type": "image_generation"},
                "stream": True,
            },
            base,
            key,
        )
        try:
            if len(item["result"]) > 40_000_000:
                raise ValueError("图像文件过大")
            raw = base64.b64decode(item["result"], validate=True)
            with Image.open(io.BytesIO(raw)) as image:
                if min(image.size) < 64 or max(image.size) > 4096:
                    raise ValueError("图像尺寸超出范围")
                image = image.convert("RGBA")
                if not image.getbbox() or image.getchannel("A").getextrema()[0] == 255:
                    raise ValueError("实体图缺少透明背景或主体")
                image.thumbnail((336, 336), Image.Resampling.LANCZOS)
                out = io.BytesIO()
                image.save(out, format="PNG", optimize=True)
        except (OSError, ValueError, binascii.Error) as exc:
            raise RuntimeError(
                "生成图像未通过尺寸、透明度或格式验收：" + str(exc)[:90]
            ) from None
        data = out.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        record = {
            "sha256": digest,
            "provider": "OpenAI Responses",
            "model": model,
            "tool": tool.get("model", "image_generation"),
            "reference_sha256": parent_hash,
            "request_hash": fingerprint,
        }
        atomic(root / (digest + ".png"), data)
        atomic(cache, encode(record).encode())
        return record


def merge_assets(previous, new, touched, change_audio, tracks=None):
    from .agents import Art
    from .artwork import sprite

    originals = {s["id"]: s for s in previous["sprites"]}
    proposed = {s["id"]: s for s in new["sprites"]}
    merged = dict(previous)
    merged["_run"] = new.get("_run", {})
    merged["sprites"] = [
        proposed.get(s["id"], s) if s["id"] in touched else s
        for s in previous["sprites"]
        if s["id"] not in touched or s["id"] in proposed
    ]
    merged["sprites"].extend(
        s for s in new["sprites"] if s["id"] in touched and s["id"] not in originals
    )
    if change_audio and tracks is not None and set(tracks) != set(previous["melody"]):
        # Tempo and base pitch affect every rendered track; keep both for a local edit.
        merged["melody"] = {
            **previous["melody"],
            **{name: new["melody"][name] for name in tracks},
        }
    elif change_audio:
        for key in ("tempo", "root_hz", "melody"):
            merged[key] = new[key]
    Art.model_validate(merged)
    merged["rendered"] = {
        k: v for k, v in previous.get("rendered", {}).items() if k not in touched
    }
    if enabled():
        folder().mkdir(parents=True, exist_ok=True)
        for key in originals.keys() - touched - merged["rendered"].keys():
            raw = sprite(previous, key)
            digest = hashlib.sha256(raw).hexdigest()
            atomic(folder() / (digest + ".png"), raw)
            merged["rendered"][key] = {"sha256": digest, "provider": "已批准的父版本"}
    return merged


async def materialize(art):
    if not enabled():
        return
    rendered = art.setdefault("rendered", {})
    pending = {s["id"]: s for s in art["sprites"] if s["id"] not in rendered}
    while pending:
        ready = [
            s
            for s in pending.values()
            if not s.get("reference") or s["reference"] in rendered
        ]
        if not ready:
            raise ValueError("美术参考形成循环或指向缺失的实体")
        for entity in ready:
            style = {
                k: art.get(k)
                for k in (
                    "style",
                    "base_anchor",
                    "style_anchor",
                    "background",
                    "ink",
                    "accent",
                )
            }
            spec = {**style, "entity": entity}
            rendered[entity["id"]] = await asyncio.to_thread(
                render, spec, rendered.get(entity.get("reference"))
            )
            pending.pop(entity["id"])
