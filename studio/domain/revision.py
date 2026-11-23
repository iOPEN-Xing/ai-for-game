"""Ordered deliverables and the human approval gate following each production stage."""

STEPS = {
    "research": ["route_research", "discovery"],
    "interpret": ["visual_analysis", "research"],
    "design": ["route_design", "gdd", "art", "levels"],
    "build": ["route_build", "game_code", "level_code", "validation", "quality_report"],
}
NEXT = {
    "research": "references",
    "interpret": "direction",
    "design": "plan",
    "build": "quality",
}


HUMAN_GATES = {
    "select_references": ("references", "interpret"),
    "choose": ("direction", "design"),
    "approve": ("plan", "build"),
    "accept": ("quality", "ready"),
    "publish": ("ready", "released"),
}
