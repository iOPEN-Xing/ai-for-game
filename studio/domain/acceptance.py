"""Validation of the approved baseline and player-progress compatibility."""

from studio.domain.levels import check_curve


def validate_baseline(checks, evidence):
    levels = {lv["index"]: lv for lv in evidence["level_pack"]["levels"]}
    assets = evidence["assets"].get("sprites", {})
    for c in checks:
        if c["kind"] == "asset":
            if (c["entity"] in assets) == (c["action"] == "add"):
                raise ValueError("美术验收与基线实体清单不符")
            continue
        level, field = c["level"], c["field"]
        if level not in levels:
            raise ValueError("验收目标关卡不存在")
        if c["kind"] == "parameter":
            source = levels[level]
            if field in ("quota", "seconds", "radius", "pace", "size"):
                candidate = {**source, field: c["after"]}
                if (
                    field in ("quota", "seconds", "size")
                    and float(c["after"]).is_integer()
                ):
                    candidate[field] = int(c["after"])
                check_curve(candidate)
            elif (
                "grid" not in source
                or not float(c["after"]).is_integer()
                or not 0 <= c["after"] < len(source["grid"])
            ):
                raise ValueError("路径端点超出可用蓝图")
        else:
            source = evidence["probes"][str(level)]["observed"]
        if (
            field not in source
            or source[field] != c["before"]
            or c["before"] == c["after"]
        ):
            raise ValueError(
                f"第 {level} 关 {field} 原值与冻结基线不符，或目标值未改变"
            )


def compatible_progress(a, b):
    def stages(pack):
        return [
            (
                x["index"],
                x["family"],
                x.get("size") if x.get("grid") else None,
                x.get("grid"),
                x.get("from"),
                x.get("to"),
            )
            for x in pack["levels"]
        ]

    return a["family"] == b["family"] and stages(a) == stages(b)
