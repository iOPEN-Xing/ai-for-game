"""System instructions assembled for each role, task and phase."""

from pathlib import Path

BASE_RULES = Path(__file__).with_name("base.md").read_text(encoding="utf-8").strip()
