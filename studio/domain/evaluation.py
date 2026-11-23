"""Judge a pre-registered hypothesis using verified delivery and frozen player counts."""

from studio.domain.metrics import click_difference_interval, sample_unit


def adjudicate(metric, bet, arms, *, delivery_ok, confounded):
    denominator = sample_unit(metric)
    enough = all(
        arms.get(a, {}).get(denominator, 0) >= bet["min_players"]
        for a in ("control", "treatment")
    )
    change = None
    interval = None
    threshold = (
        bet.get("falsify_below") if bet.get("falsify_below") is not None else bet["low"]
    )
    if not delivery_ok:
        attribution, conclusion, grade = (
            "执行错",
            "交付与冻结记录不符，本轮验证作废。",
            "未验证推断",
        )
    elif confounded:
        attribution, conclusion, grade = (
            "方法错",
            "实验期存在已标记的外部干扰，本轮结论退回未验证。",
            "未验证推断",
        )
    elif not enough:
        attribution, conclusion, grade = (
            "方法待验证",
            "每组样本未达到预注册门槛，保留原假设。",
            "未验证推断",
        )
    else:
        if metric in ("action_rate", "d1_rate"):
            control, treatment = arms["control"], arms["treatment"]
            numerator = "action_players" if metric == "action_rate" else "d1_returned"
            change = 100 * (
                treatment[numerator] / treatment[denominator]
                - control[numerator] / control[denominator]
            )
            interval = click_difference_interval(
                control, treatment, numerator, denominator
            )
        else:
            change = arms["treatment"][metric] - arms["control"][metric]
        if (
            interval
            and interval[1] >= threshold
            and (interval[0] <= 0 <= interval[1] or interval[0] < threshold)
        ):
            attribution, conclusion, grade = (
                "方法待验证",
                "玩家比例差值的 95% 区间仍包含零或跨过证伪阈值，应继续验证。",
                "未验证推断",
            )
        elif (interval[1] if interval else change) < threshold:
            attribution, conclusion, grade = (
                "假设错",
                "收益低于预注册下界，本次证据反对该假设。",
                "现象",
            )
        elif not bet["low"] <= change <= bet["high"]:
            attribution, conclusion, grade = (
                "方法待验证",
                "收益落在预期区间之外，预测幅度需要复核。",
                "现象",
            )
        else:
            attribution, conclusion, grade = (
                "命中预期",
                "观察差值落在预注册区间。",
                "现象",
            )
    return {
        "metric": metric,
        "sample_basis": denominator,
        "interval_95_pp": [round(v, 3) for v in interval] if interval else None,
        "delta": round(change, 3) if change is not None else None,
        "expected": [bet["low"], bet["high"]],
        "falsify_below": threshold,
        "attribution": attribution,
        "conclusion": conclusion,
        "grade": grade,
        "inference_method": "newcombe_95_pp"
        if interval
        else "descriptive"
        if change is not None
        else "unmeasured",
    }
