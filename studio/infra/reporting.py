"""Read-only aggregate projections over a single SQLite snapshot."""

import datetime as dt

from studio.domain.metrics import attach_retention, rates
from studio.infra.store import need, now, one, rows
from studio.settings import ZONE

TOTALS = """COUNT(*) exposures, COUNT(DISTINCT player) visitors, COUNT(started) starts,
 COUNT(DISTINCT CASE WHEN started IS NOT NULL THEN player END) players,
 COUNT(CASE WHEN ended IS NOT NULL AND COALESCE(finish,'natural')='natural' THEN 1 END) ends,
 COUNT(DISTINCT CASE WHEN ended IS NOT NULL AND COALESCE(finish,'natural')='natural' THEN player END) finish_players,
 COUNT(DISTINCT CASE WHEN action_label IS NOT NULL THEN player END) action_visitors,
 COUNT(DISTINCT CASE WHEN action_label IS NOT NULL AND started IS NOT NULL THEN player END) action_starters,
 COUNT(DISTINCT CASE WHEN action_label IS NOT NULL AND ended IS NOT NULL AND COALESCE(finish,'natural')='natural' THEN player END) action_finishers,
 COUNT(DISTINCT CASE WHEN action_at IS NOT NULL THEN player END) action_players,
 COUNT(hint_at) hint_rounds,COUNT(rescues) rescue_observed,
 COUNT(CASE WHEN rescues>0 THEN 1 END) rescued_rounds,
 COUNT(CASE WHEN finish='quit' AND ended IS NOT NULL THEN 1 END) quits,
 COALESCE(SUM(won),0) wins, COALESCE(SUM(ended-started),0) seconds"""


def retention(
    con, start, end, game=None, revision=None, bundle=None, experiment=None, daily=False
):
    midnight = int(
        dt.datetime.combine(
            dt.datetime.fromtimestamp(end, ZONE).date(), dt.time(), ZONE
        ).timestamp()
    )
    mature = midnight - 86400
    since = (
        start - 86400 if daily and end == midnight and end - start == 86400 else start
    )
    filters = ["r.preview=0", "r.started>=?", "r.started<?"]
    args = [since, mature]
    for col, val in (
        ("game", game),
        ("rev", revision),
        ("bundle", bundle),
        ("experiment", experiment),
    ):
        if val is not None:
            filters.append("r." + col + "=?")
            args.append(val)
    # First formal start per browser and game; an entire following Shanghai calendar day must have elapsed.
    data = rows(
        con,
        """SELECT game,arm,COUNT(*) d1_eligible,SUM(EXISTS(
      SELECT 1 FROM rounds n WHERE n.game=c.game AND n.player=c.player AND n.preview=0
      AND n.started>=c.day_start+86400 AND n.started<c.day_start+172800)) d1_returned FROM (
      SELECT r.game,r.arm,r.player,((r.started+28800)/86400)*86400-28800 day_start
      FROM rounds r WHERE """
        + " AND ".join(filters)
        + """ AND NOT EXISTS(
        SELECT 1 FROM rounds old WHERE old.game=r.game AND old.player=r.player AND old.preview=0
        AND (old.started<r.started OR (old.started=r.started AND old.rowid<r.rowid)))) c GROUP BY game,arm""",
        *args,
    )
    return data, [since, max(since, mature)]


def observations(start, end, game=None, experiment=None, revision=None, bundle=None):
    # Both reports and experiment arms use the same issuance cohort and event cutoff.
    query = """FROM (SELECT r.game,r.rev,r.bundle,r.experiment,r.player,r.level,r.finish,r.arm,r.campaign,
        c.name AS channel,c.action_label,
        CASE WHEN r.started<? THEN r.started END started,CASE WHEN r.ended<? THEN r.ended END ended,
        CASE WHEN r.ended<? THEN r.won END won,CASE WHEN r.action_at<? THEN r.action_at END action_at
        ,CASE WHEN r.hint_at<? THEN r.hint_at END hint_at,CASE WHEN r.ended<? THEN r.rescues END rescues,
        CASE WHEN r.ended<? THEN r.mistakes END mistakes,CASE WHEN r.ended<? THEN r.slow_round END slow_round
        FROM rounds r LEFT JOIN campaigns c ON c.id=r.campaign
        WHERE r.preview=0 AND r.issued>=? AND r.issued<?"""
    args = [end] * 8 + [start, end]
    for column, value in (
        ("r.game", game),
        ("r.experiment", experiment),
        ("r.rev", revision),
        ("r.bundle", bundle),
    ):
        if value is not None:
            query += " AND " + column + "=?"
            args.append(value)
    return query + ")", args


def report(con, start=0, end=None, game=None, revision=None, bundle=None):
    end = now() + 1 if end is None else end
    query, args = observations(start, end, game=game, revision=revision, bundle=bundle)
    total = rates(one(con, "SELECT " + TOTALS + " " + query, *args))

    def groups(cols):
        return [
            rates(r)
            for r in rows(con, f"SELECT {cols},{TOTALS} {query} GROUP BY {cols}", *args)
        ]

    games = groups("game")
    cohorts, period = retention(con, start, end, game, revision, bundle, daily=True)
    attach_retention(total, cohorts, period)
    for row in games:
        attach_retention(
            row, [entry for entry in cohorts if entry["game"] == row["game"]], period
        )
    return {
        "start": start,
        "end": end,
        "total": total,
        "games": games,
        "versions": groups("game,rev,bundle,experiment,arm"),
        "levels": groups("game,rev,level"),
        "quadrants": rows(
            con,
            """SELECT game,rev,level,slow_round,(mistakes>=2) repeated_errors,
            COUNT(*) AS rounds,SUM(won) AS wins,COUNT(hint_at) AS hinted,COUNT(rescues) AS rescue_observed
            """
            + query
            + " WHERE ended IS NOT NULL AND slow_round IS NOT NULL AND mistakes IS NOT NULL GROUP BY game,rev,level,slow_round,(mistakes>=2)",
            *args,
        ),
        "channels": groups("game,campaign,channel,action_label"),
    }


def exp_stats(con, experiment, cutoff):
    query, args = observations(0, cutoff, experiment=experiment)
    arms = {
        r["arm"]: rates(r)
        for r in rows(con, f"SELECT arm,{TOTALS} {query} GROUP BY arm", *args)
    }
    e = need(con, "SELECT started FROM experiments WHERE id=?", experiment)
    cohorts, period = retention(con, e["started"], cutoff, experiment=experiment)
    for arm, stats in arms.items():
        attach_retention(stats, [row for row in cohorts if row["arm"] == arm], period)
    return arms


def game_baselines(con, start, end):
    query, args = observations(start, end)
    return rows(con, f"SELECT game,{TOTALS} {query} GROUP BY game", *args)
