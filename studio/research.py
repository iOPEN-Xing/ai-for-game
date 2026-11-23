"""Searchable visual references from the project dossier and original studio concepts."""

import asyncio
import base64
import hashlib
import io
import os
from urllib.parse import urlsplit

import httpx
from PIL import Image

from studio.infra.repositories import evidence as evidence_db
from studio.infra.store import db

from .settings import ROOT, WEB

COMMONS = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "LoopAtelier/1.0 (game reference research; Wikimedia API)"}

# The archive is reference material. Cartridge generation uses the original studio asset pipeline.
LIBRARY = (
    (
        "beacon",
        "信标采样",
        "pulse",
        "海岛 灯塔 点按 信号 搜寻 即时反馈 采集",
        "/static/reference-pulse.png",
        "工作室原创玩法图",
    ),
    (
        "tide",
        "潮汐邮路",
        "trail",
        "海图 网格 地图 解谜 路径 迷宫 规划",
        "/static/reference-trail.png",
        "工作室原创玩法图",
    ),
    (
        "rail",
        "轨道接力",
        "drift",
        "轨道 节拍 速度 躲避 时机 切换 赛车 节奏",
        "/static/reference-drift.png",
        "工作室原创玩法图",
    ),
    (
        "island",
        "灯塔与铁道场景",
        "custom",
        "海岛 灯塔 船 铁道 暖色 立体 手工 美术",
        "/static/relay-island.webp",
        "工作室原创场景",
    ),
    (
        "archive-19",
        "连续操作的目标与反馈",
        "pulse",
        "反应 移动 操作 飞行 空间 目标",
        "/assets/img-19.png",
        "原文玩法调研 · 图 19",
    ),
    (
        "archive-20",
        "运动轨迹与过关判定",
        "drift",
        "跳跃 运动 轨迹 平台 地图 跑酷",
        "/assets/img-20.png",
        "原文玩法调研 · 图 20",
    ),
    (
        "archive-21",
        "离散棋盘的状态设计",
        "trail",
        "匹配 消除 棋盘 格子 离散 解谜",
        "/assets/img-21.png",
        "原文玩法调研 · 图 21",
    ),
)


def retrieve(brief):
    def score(ref):
        return sum(word in brief for word in ref[3].split())

    return [
        {
            "id": key,
            "title": title,
            "family": family,
            "keywords": tags,
            "image": image,
            "credit": credit,
        }
        for key, title, family, tags, image, credit in sorted(
            LIBRARY, key=score, reverse=True
        )
    ]


def attach(directions, references):
    for d in directions:
        ids = d.get("reference_ids", [])
        registry = {r["id"]: r for r in references}
        if not ids or len(ids) != len(set(ids)) or set(ids) - registry.keys():
            raise ValueError("每个方向必须引用本次选中的真实参考图 ID")
        d["references"] = [registry[i] for i in ids]


def online():
    return os.getenv("STUDIO_RESEARCH_ONLINE", "1") != "0"


async def pages(client, url, query, **params):
    result = await client.get(
        url,
        params={
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": 6,
            "format": "json",
            "formatversion": 2,
            **params,
        },
    )
    result.raise_for_status()
    body = result.json()
    if "error" in body:
        raise ValueError("公共检索服务返回错误")
    return sorted(
        body.get("query", {}).get("pages", []), key=lambda v: v.get("index", 0)
    )


async def discover(queries, brief):
    local = retrieve(brief)
    if not online():
        return {"references": local, "search_status": "本地资料库"}
    async with httpx.AsyncClient(headers=HEADERS, timeout=10) as client:
        results = await asyncio.gather(
            *(
                pages(
                    client,
                    COMMONS,
                    q,
                    gsrnamespace=6,
                    prop="imageinfo",
                    iiprop="url|mime",
                    iiurlwidth=480,
                )
                for q in queries
            ),
            return_exceptions=True,
        )
    collected = {}
    for batch in results:
        if isinstance(batch, BaseException):
            continue
        for p in batch:
            info = (p.get("imageinfo") or [{}])[0]
            url = info.get("thumburl", "")
            if urlsplit(url).hostname != "upload.wikimedia.org" or not info.get(
                "mime", ""
            ).startswith("image/"):
                continue
            key = "commons-" + str(p["pageid"])
            collected[key] = {
                "id": key,
                "title": p["title"].removeprefix("File:"),
                "image": url,
                "source": info.get("descriptionurl"),
                "credit": "Wikimedia Commons",
            }
    refs = list(collected.values())[:16] + local
    available = sum(not isinstance(r, BaseException) for r in results)
    return {
        "references": refs[:20],
        "search_status": f"公共检索 {available}/{len(queries)} 路返回，找到 {len(collected)} 条图像记录",
    }


async def rule_sources(queries):
    if not online():
        return []
    async with httpx.AsyncClient(headers=HEADERS, timeout=10) as client:
        batches = await asyncio.gather(
            *(
                pages(
                    client,
                    "https://en.wikipedia.org/w/api.php",
                    q,
                    prop="extracts|info",
                    exintro=1,
                    explaintext=1,
                    exsentences=3,
                    inprop="url",
                )
                for q in queries
            ),
            return_exceptions=True,
        )
    articles = {}
    for batch in batches:
        if isinstance(batch, BaseException):
            continue
        for page in batch:
            if page.get("extract") and page.get("fullurl"):
                articles[page["pageid"]] = {
                    "title": page["title"],
                    "source": page["fullurl"],
                    "extract": page["extract"][:900],
                }
    return list(articles.values())[:5]


async def image_input(ref):
    url = ref["image"]
    if url in {r[4] for r in LIBRARY}:
        prefix, _, filename = url.lstrip("/").partition("/")
        raw = (
            (WEB if prefix == "static" else ROOT / "docs/original/assets") / filename
        ).read_bytes()
    else:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "upload.wikimedia.org":
            raise ValueError("所选参考图没有可验证的图像来源")
        async with (
            httpx.AsyncClient(
                headers=HEADERS, timeout=15, follow_redirects=False
            ) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 8_000_000:
                    raise ValueError("所选参考图超过大小限制")
    with Image.open(io.BytesIO(raw)) as img:
        img.thumbnail((700, 700))
        output = io.BytesIO()
        img.convert("RGB").save(output, format="JPEG", quality=82)
    return {"name": ref["id"], "data": base64.b64encode(output.getvalue()).decode()}


async def frozen_image(run, reference):
    ref = reference["id"]
    with db() as con:
        item = evidence_db.reference_for_run(con, run, ref)
    if item is None:
        downloaded = await image_input(reference)
        content = base64.b64decode(downloaded["data"], validate=True)
        digest = hashlib.sha256(content).hexdigest()
        with db(True) as con:
            item = evidence_db.select_reference(con, run, ref, digest, content)
    if hashlib.sha256(item["content"]).hexdigest() != item["digest"]:
        raise ValueError("已选参考图与冻结内容摘要不符")
    return {"name": ref, "data": base64.b64encode(item["content"]).decode("ascii")}
