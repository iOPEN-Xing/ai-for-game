"""Capacity of a single studio on the lightweight server."""

GAMES_PER_STUDIO = 50
REVISIONS_PER_GAME = 200
CAMPAIGNS_PER_GAME = 20
NEW_ANALYSES_PER_DAY = 20
BUNDLE_BYTES = 5 * 1024 * 1024

# The longest supported game is 180 s. At 25 frames/s an uninterrupted drag uses
# up to 9,000 clock/pointer samples; cap both real bytes and simulation steps.
REPLAY_STEPS = 12_000
PLAYER_BODY_BYTES = 256 * 1024
REPLAY_RETENTION_DAYS = 180
OPEN_PER_IP_DAY = 1200
OPEN_PER_STUDIO_DAY = 10_000
# 180 days at this intake rate occupy at most ~4.22 GiB of compressed replay data.
REPLAY_BYTES_PER_DAY = 24 * 1024 * 1024
