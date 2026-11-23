CREATE INDEX rounds_replay_retention ON rounds(ended) WHERE replay IS NOT NULL;
CREATE TABLE team_sessions (
    digest TEXT PRIMARY KEY,
    expires INTEGER NOT NULL
);
CREATE INDEX team_sessions_expiry ON team_sessions(expires);
CREATE TABLE player_intake (
    day INTEGER PRIMARY KEY,
    opens INTEGER NOT NULL DEFAULT 0,
    replay_bytes INTEGER NOT NULL DEFAULT 0,
    omitted_replays INTEGER NOT NULL DEFAULT 0
);
-- Carry forward today's consumption when an existing studio upgrades mid-day.
WITH today(day) AS (
    SELECT (CAST(strftime('%s','now') AS INTEGER) + 28800) / 86400 * 86400 - 28800
)
INSERT INTO player_intake(day, opens, replay_bytes)
SELECT day,
    (SELECT COUNT(*) FROM rounds WHERE preview=0 AND issued>=day),
    (SELECT COALESCE(SUM(length(replay)),0) FROM rounds WHERE replay IS NOT NULL AND ended>=day)
FROM today;
