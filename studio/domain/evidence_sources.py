"""Define citable evidence once, at freezing and at per-role delivery."""

SHARED_FIELDS = (
    "period",
    "definitions",
    "center",
    "game",
    "levels",
    "channels",
    "arms",
    "quadrants",
    "historical_versions",
    "priority",
    "history",
    "external_changes",
    "version",
    "knowledge",
    "gdd",
    "dead_ends",
    "portfolio",
    "portfolio_designs",
    "peers",
    "supplement",
)

CODE_SOURCES = {"game.js": "game_code", "level-generator.js": "level_code"}


def source_catalog(evidence):
    aliases = {"metrics": "game", "asset.json": "assets", **CODE_SOURCES}
    return [
        *(source for source, field in aliases.items() if field in evidence),
        *(
            key
            for key in (*SHARED_FIELDS, "feedback", "level_pack", "probes")
            if key in evidence
        ),
        *(
            f"level:{lv['index']}"
            for lv in evidence.get("level_pack", {}).get("levels", [])
        ),
        *("probe:" + str(key) for key in evidence.get("probes", {})),
        *(k["id"] for k in evidence.get("knowledge", [])),
    ]


def visible_sources(role, evidence):
    allowed = set(source_catalog(evidence))
    if role not in {"Engineer", "Reviewer"}:
        allowed.difference_update(CODE_SOURCES)
    allowed.difference_update(
        r["id"] for r in evidence.get("feedback", []) if "id" in r
    )
    return [source for source in evidence["sources"] if source in allowed]
