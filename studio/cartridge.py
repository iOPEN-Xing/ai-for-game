"""Compile validated designs into game bundles. The game host ABI is shared by old and new callers."""

import csv
import hashlib
import io
import os
import shutil
import tempfile
from pathlib import Path

from studio.artwork import sound, sprite
from studio.domain import limits
from studio.domain.levels import blueprint_path, check_curve
from studio.infra.bundles import (
    bundle_zip,
    folder,
    player_data,
    public_payload,
    read_player_assets,
)
from studio.infra.game_runtime import (
    BLUEPRINT_PLAY,
    CURVE_ABI,
    GAME_ABI,
    PROBE,
    approved_levels,
    evaluate,
    js_context,
    levels_for,
    remote_context,
    replay,
    source,
    verify_blueprint_play,
    verify_game,
)
from studio.infra.store import encode
from studio.settings import data_dir


def compile_bundle(rev, docs):
    design, art, gdd = docs["levels"], docs["art"], docs["gdd"]
    curve, game = docs["level_code"]["source"], docs["game_code"]["source"]
    levels, params = levels_for(design, rev["seed"], curve)
    proof = verify_game(game, levels)
    regressions = []
    for extra_seed in (rev["seed"] ^ 0x1729, rev["seed"] ^ 0x1138):
        additional, _ = levels_for(design, extra_seed, curve)
        cases = [
            additional[i]
            for i in sorted({0, len(additional) // 2, len(additional) - 1})
        ]
        regressions.append(
            {
                "seed": extra_seed,
                "levels": [c["index"] for c in cases],
                "proof": verify_game(game, cases),
            }
        )
    # The prefab remote consumes the saved blueprint. Its generator stays in the authoring bundle.
    factory = source("factory.js")
    shared = (
        factory[: factory.index("function maze")]
        if design["mode"] == "prefab"
        else factory
    )
    runtime_curve = curve if design["mode"] == "runtime" else ""
    get_level = (
        "i=>makeLevel(i,"
        + str(len(levels))
        + ","
        + str(rev["seed"])
        + ","
        + encode(design["game_type"])
        + ",parameters)"
        if design["mode"] == "runtime"
        else "i=>levels[i-1]"
    )
    remote = "\n".join(
        [
            "'use strict';",
            "globalThis.LoopCartridge=(()=>{",
            shared,
            source("base.js"),
            game,
            runtime_curve,
            "const levels="
            + encode(levels if design["mode"] == "prefab" else [])
            + ";",
            "const module={start,step,draw,level:" + get_level + "};",
            "return {init:()=>{},get:async key=>{if(key!=='./game')throw Error('Unknown module');return ()=>module;}};})();",
        ]
    )
    # Check the exact remote entry generated for release.
    published = remote_context(remote)
    for level in levels:
        if evaluate(published, f"loadedGame.level({level['index']})") != level:
            raise ValueError("发布关卡与验收蓝图不一致")
        if level["family"] == "trail":
            verify_blueprint_play(published, level, "loadedGame")
    pack = {
        "mode": design["mode"],
        "seed": rev["seed"],
        "family": design["game_type"],
        "levels": levels,
        "proof": proof,
        "regressions": regressions,
    }
    difficulty = io.StringIO()
    writer = csv.DictWriter(
        difficulty, fieldnames=["level", "quota", "seconds", "radius", "size", "pace"]
    )
    writer.writeheader()
    for i, p in enumerate(params, 1):
        writer.writerow({"level": i, **{k: p[k] for k in writer.fieldnames[1:]}})
    asset = {
        "style": art["style"],
        "anchors": {
            k: art.get(k) for k in ("base_anchor", "style_anchor", "entity_anchor")
        },
        "palette": {k: art[k] for k in ("background", "ink", "accent")},
        "sprite": "sprite.png",
        "sprites": {
            item["id"]: {
                "title": item["title"],
                "file": "sprite-" + item["id"] + ".png",
                "reference": item.get("reference"),
                "generation": art.get("rendered", {}).get(item["id"]),
            }
            for item in art.get("sprites", [])
        },
        "audio": {
            event: event + ".wav" for event in ("hit", "miss", "win", "ui", "bgm")
        },
    }
    gdd_text = "\n\n".join(
        ["# " + gdd["title"]]
        + [
            "## " + label + "\n\n" + str(gdd[key])
            for key, label in [
                ("core_loop", "核心循环"),
                ("controls", "操作"),
                ("win_condition", "胜利"),
                ("failure_condition", "失败"),
                ("difficulty", "难度"),
            ]
        ]
    )
    if inventory := gdd.get("illustrated_entities"):
        gdd_text += "\n\n## 生图清单\n\n" + "\n".join(
            f"- {entry['id']}　{entry['title']}" for entry in inventory
        )
    if hypothesis := gdd.get("product_hypothesis"):
        gdd_text += "\n\n## 产品验证\n\n" + "\n\n".join(
            f"**{label}**　{hypothesis[key]}"
            for key, label in (
                ("audience", "目标玩家"),
                ("player_value", "游玩价值"),
                ("activation", "首次有效体验"),
                ("metric", "北极星指标"),
                ("validation", "验证办法"),
            )
        )
    files = {
        "Core_GDD.md": gdd_text.encode(),
        "Difficulty_Config.csv": difficulty.getvalue().encode(),
        "Level_Pack.json": encode(pack).encode(),
        "asset.json": encode(asset).encode(),
        "game.js": game.encode(),
        "level-generator.js": curve.encode(),
        "level-factory.js": source("factory.js").encode(),
        "remoteEntry.js": remote.encode(),
        "sprite.png": sprite(art),
    }
    for asset_id, item in asset["sprites"].items():
        files[item["file"]] = sprite(art, asset_id)
    for event, name in asset["audio"].items():
        files[name] = sound(art, event)
    manifest = {
        "title": rev.get("project_title") or gdd["title"],
        "controls": gdd["controls"],
        "count": len(levels),
        "mode": design["mode"],
        "family": design["game_type"],
        "entry": "remoteEntry.js",
        "exposes": "./game",
        "assets": asset,
    }
    files["manifest.json"] = encode(manifest).encode()
    if sum(map(len, files.values())) > limits.BUNDLE_BYTES:
        raise ValueError("构建超过 5 MiB，请缩减图像、音轨或关卡数据")
    digest = hashlib.sha256()
    for name, payload in sorted(files.items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(payload).digest())
    key = digest.hexdigest()
    base = data_dir() / "builds"
    base.mkdir(parents=True, exist_ok=True)
    if not (base / key).is_dir():
        tmp = tempfile.mkdtemp(dir=base)
        try:
            for name, payload in files.items():
                (Path(tmp) / name).write_bytes(payload)
            try:
                os.rename(tmp, base / key)
            except OSError:
                if not (base / key).is_dir():
                    raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return key, {
        "levels": len(levels),
        "proof": proof,
        "regression_seeds": [v["seed"] for v in regressions],
        "seed": rev["seed"],
        "files": sorted(files),
    }


__all__ = [
    "BLUEPRINT_PLAY",
    "CURVE_ABI",
    "GAME_ABI",
    "PROBE",
    "approved_levels",
    "blueprint_path",
    "bundle_zip",
    "check_curve",
    "compile_bundle",
    "evaluate",
    "folder",
    "js_context",
    "levels_for",
    "player_data",
    "public_payload",
    "read_player_assets",
    "remote_context",
    "replay",
    "source",
    "verify_blueprint_play",
    "verify_game",
]
