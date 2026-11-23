"""Definitions shared by daily reporting, analysis and A/B settlement."""

import math
from statistics import NormalDist


def rates(row):
    row = dict(row)
    starts, players = row["starts"], row["players"]
    row.update(
        entry_rate=round(100 * players / row["visitors"], 2)
        if row["visitors"]
        else None,
        completion_rate=round(100 * row["ends"] / starts, 2) if starts else None,
        win_rate=round(100 * row["wins"] / starts, 2) if starts else None,
        rounds_per_player=round(starts / players, 3) if players else None,
        seconds_per_player=round(row["seconds"] / players, 2) if players else None,
        action_rate=round(100 * row["action_players"] / row["action_visitors"], 2)
        if row["action_visitors"]
        else None,
    )
    return row


def attach_retention(row, cohorts, period):
    eligible = sum(r["d1_eligible"] for r in cohorts)
    returned = sum(r["d1_returned"] for r in cohorts)
    row.update(
        d1_eligible=eligible,
        d1_returned=returned,
        d1_rate=round(100 * returned / eligible, 2) if eligible else None,
        d1_period=period,
    )


def sample_unit(metric):
    return {"action_rate": "action_visitors", "d1_rate": "d1_eligible"}.get(
        metric, "players"
    )


def click_difference_interval(
    control, treatment, numerator="action_players", denominator="action_visitors"
):
    """Newcombe hybrid-score 95% interval in percentage points; one binary outcome per player."""
    z = NormalDist().inv_cdf(0.975)

    def wilson(arm):
        n = arm[denominator]
        p = arm[numerator] / n
        divisor = 1 + z * z / n
        middle = (p + z * z / (2 * n)) / divisor
        radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / divisor
        return p, max(0, middle - radius), min(1, middle + radius)

    a, lo_a, hi_a = wilson(control)
    b, lo_b, hi_b = wilson(treatment)
    diff = b - a
    return [
        100 * (diff - math.hypot(b - lo_b, hi_a - a)),
        100 * (diff + math.hypot(hi_b - b, a - lo_a)),
    ]


METRIC_HELP = "通关率按胜局除以开局计算。人均开局和人均游玩时长以开局玩家为分母。活动入口点击率按点击行动按钮的人数除以进入带按钮链接的人数计算。次留按游戏内首次正式开局、次一上海自然日完整可观察的玩家去重，统计次日再次开局人数。日报的成熟首玩队列比报表日早一天。人数按浏览器玩家标识去重，试玩单独记录。"
