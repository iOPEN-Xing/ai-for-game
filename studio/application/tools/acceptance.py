"""Verify approved changes against the built control and treatment cartridges."""

import json

from studio.application.tools import cartridge
from studio.domain.acceptance import compatible_progress, validate_baseline
from studio.infra.store import encode


def read_pack(bundle):
    return json.loads((cartridge.folder(bundle) / "Level_Pack.json").read_bytes())


def probes(bundle, levels):
    root = cartridge.folder(bundle)
    ctx = cartridge.js_context(
        cartridge.source("factory.js"),
        cartridge.source("base.js"),
        (root / "game.js").read_text(),
    )
    traces = {}
    for level in levels:
        events = cartridge.evaluate(
            ctx,
            """(L => {
            let s=start(L), initial=s.score, inputs=[];
            for(let i=0;i<100 && !s.done && s.score===initial;i++){
                let e=witness(JSON.parse(JSON.stringify(s)),L);
                inputs.push(e); s=step(s,e,L);
            }
            return inputs;
        })("""
            + encode(level)
            + ")",
        )
        index = level["index"]
        traces[str(index)] = {
            "inputs": events,
            "observed": cartridge.replay(bundle, index, events),
        }
    return traces


def verify(control, treatment, bet, evidence):
    from studio.domain.deliberation import Iteration

    if not bet.get("checks"):
        raise ValueError("旧提案缺少可执行验收项，需要重新论证")
    checks = [c.model_dump() for c in Iteration.model_validate(bet).checks]
    validate_baseline(checks, evidence)
    if evidence["version"]["bundle"] != control:
        raise ValueError("批准的基线构建已经改变")
    old, new = read_pack(control), read_pack(treatment)
    before, after = cartridge.folder(control), cartridge.folder(treatment)
    kinds = {c["kind"] for c in checks}
    if (
        "replay" not in kinds
        and "asset" not in kinds
        and (before / "game.js").read_bytes() != (after / "game.js").read_bytes()
    ):
        raise ValueError("参数实验包含未经批准的玩法代码变更")
    if "parameter" not in kinds and old["levels"] != new["levels"]:
        raise ValueError("构建包含未经批准的关卡变更")
    if "parameter" in kinds:
        if (old["seed"], old["mode"], old["family"]) != (
            new["seed"],
            new["mode"],
            new["family"],
        ):
            raise ValueError("参数实验改变了种子、生成模式或玩法")
        if len(old["levels"]) != len(new["levels"]):
            raise ValueError("参数实验改变了关卡总数")
        changes = {}
        for check in checks:
            if check["kind"] == "parameter":
                changes.setdefault(check["level"], {})[check["field"]] = check["after"]
        factory = before / "level-factory.js"
        expected = cartridge.approved_levels(
            old,
            (before / "level-generator.js").read_text(),
            changes,
            factory.read_text() if factory.is_file() else None,
        )
        for planned, delivered in zip(expected, new["levels"], strict=True):
            if planned != delivered:
                different = sorted(
                    k
                    for k in planned.keys() | delivered.keys()
                    if planned.get(k) != delivered.get(k)
                )
                raise ValueError(
                    f"第 {planned['index']} 关交付与批准蓝图不符："
                    + "、".join(different)
                )
    declared_assets = {c["entity"] for c in checks if c["kind"] == "asset"}
    for filename in {
        p.name for folder in (before, after) for p in folder.glob("sprite-*.png")
    }:
        if filename[7:-4] not in declared_assets and not same_file(
            before, after, filename
        ):
            raise ValueError("未批准的实体图形发生变化：" + filename)
    for name in ("bgm.wav", "hit.wav", "miss.wav", "win.wav", "ui.wav"):
        if not same_file(before, after, name):
            raise ValueError("实验混入了未批准的音轨变更")
    for c in checks:
        if c["kind"] == "asset":
            name = "sprite-" + c["entity"] + ".png"
            exists = (after / name).is_file()
            if exists != (c["action"] != "remove") or same_file(before, after, name):
                raise ValueError("图形实体与批准的资产操作不一致：" + c["entity"])
            continue
        i, field = c["level"], c["field"]
        if c["kind"] == "parameter":
            values = [pack["levels"][i - 1].get(field) for pack in (old, new)]
        else:
            inputs = evidence["probes"][str(i)]["inputs"]
            values = [
                cartridge.replay(key, i, inputs)[field] for key in (control, treatment)
            ]
        if values != [c["before"], c["after"]]:
            raise ValueError(
                f"第 {i} 关 {field} 实测 {values}，批准值为 {[c['before'], c['after']]}"
            )
    return checks


def same_file(before, after, name):
    a, b = before / name, after / name
    return a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes()


__all__ = ["compatible_progress", "probes", "read_pack", "same_file", "verify"]
