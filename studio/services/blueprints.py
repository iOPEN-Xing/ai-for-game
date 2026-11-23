"""Application operations for blueprints."""

import json

from studio import cartridge
from studio.domain.commands import BlueprintEdit
from studio.infra.repositories import revisions as revisions_db
from studio.infra.store import Problem, db, encode, enqueue, log


def blueprints(rid):
    with db() as con:
        r = revisions_db.built_revision(con, rid)
        parent = revisions_db.find_bundle(con, r["parent"])
    p = json.loads((cartridge.folder(r["bundle"]) / "Level_Pack.json").read_bytes())
    old = (
        json.loads(
            (cartridge.folder(parent["bundle"]) / "Level_Pack.json").read_bytes()
        )["levels"]
        if parent
        else []
    )
    for i, L in enumerate(p["levels"]):
        L["changes"] = [
            k
            for k in (
                "quota",
                "seconds",
                "radius",
                "size",
                "pace",
                "grid",
                "points",
                "from",
                "to",
                "seed",
            )
            if i < len(old) and L.get(k) != old[i].get(k)
        ]
        if parent and i >= len(old):
            L["changes"] = ["新增关卡"]
    p["removed_levels"] = [lv["index"] for lv in old[len(p["levels"]) :]]
    return p


def edit_blueprint(rid, body: BlueprintEdit):
    with db(True) as con:
        rev = revisions_db.get(con, rid)
        if rev["serial"] != body.serial or rev["stage"] not in ("quality", "ready"):
            raise Problem("只能编辑当前、已构建并待验收的草稿")
        docs = json.loads(rev["docs"])
        design, code = docs["levels"], docs["level_code"]
        if body.level > design["count"] or set(body.values) - {
            "quota",
            "seconds",
            "radius",
            "size",
            "pace",
            "grid",
            "from",
            "to",
        }:
            raise Problem("关卡或参数名无效", 422)
        if any(
            isinstance(v, list) and (k != "grid" or len(v) > 225)
            for k, v in body.values.items()
        ):
            raise Problem("地图最多为 15 × 15 格", 422)
        base = code.get("authored_source", code["source"])
        overrides = {**code.get("overrides", {}), str(body.level): body.values}
        wrapped = (
            "const blueprintParameters=(()=>{" + base + "\nreturn parameters;})();\n"
            "function parameters(index,total,seed){const edits="
            + encode(overrides)
            + ";return {...blueprintParameters(index,total,seed),...edits[index]};}"
        )
        try:
            cartridge.levels_for(design, body.seed, wrapped)
        except (ValueError, RuntimeError, TypeError) as exc:
            raise Problem("参数未通过生成验证：" + str(exc)[:240], 422) from None
        docs["level_code"] = {
            **code,
            "authored_source": base,
            "source": wrapped,
            "overrides": overrides,
        }
        for key in ("route_build", "validation", "quality_report", "build_feedback"):
            docs.pop(key, None)
        revisions_db.rebuild_blueprint(con, body.seed, encode(docs), rid)
        log(
            con,
            rev["game"],
            rid,
            "关卡编辑",
            f"重新生成第 {body.level} 关，种子 {body.seed}",
            "review",
        )
        enqueue(con, "production", rid, "build")
        return {"stage": "build"}
