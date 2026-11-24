"""Select the evidence and preferences each role can see before a model call."""

import json

from studio.domain.deliberation import feedback_summary
from studio.domain.evidence_sources import SHARED_FIELDS, visible_sources
from studio.domain.fingerprints import digest

FIELDS = ("audience", "visual_style", "controls", "audio", "avoid")

EVIDENCE_FIELDS = ("inference_mode", "quadrant_definition", *SHARED_FIELDS)

PREFERENCE_FIELDS = {
    "ArtDesigner": ("audience", "visual_style", "audio", "avoid"),
    "LevelCoder": ("audience", "controls", "avoid"),
    "LevelDesigner": ("audience", "controls", "avoid"),
    "Analyst": ("audience", "avoid"),
    "Engineer": ("controls", "audio", "avoid"),
}


def memory_for(role, saved):
    prefs = saved["preferences"]
    return {
        "project": saved["game"],
        "preference_version": prefs["version"],
        "preferences": {
            k: prefs["values"][k]
            for k in PREFERENCE_FIELDS.get(role, FIELDS)
            if k in prefs["values"]
        },
        "approved_knowledge": saved["knowledge"],
        "past_decisions": saved["decisions"],
    }


def evidence_for(role, frozen):
    view = {key: frozen[key] for key in EVIDENCE_FIELDS if key in frozen}
    sources = visible_sources(role, frozen)
    if role in ("Engineer", "Reviewer"):
        view.update(game_code=frozen["game_code"], level_code=frozen["level_code"])
    # Reconstruct safe feedback aggregates when resuming pre-migration evidence snapshots.
    view["feedback"] = feedback_summary(frozen.get("feedback", []))
    view["sources"] = sources
    pack = frozen["level_pack"]
    view["level_pack"] = {
        key: pack[key]
        for key in ("seed", "mode", "family", "chapters", "chapter_proof")
        if key in pack
    }
    if role == "Engineer":
        view["level_pack"]["levels"] = pack["levels"]
    else:
        view["level_pack"]["levels"] = [
            {k: v for k, v in lv.items() if isinstance(v, (str, int, float, bool))}
            for lv in pack["levels"]
        ]
    view["probes"] = {
        key: {
            "observed": p["observed"],
            "input_count": len(p["inputs"]),
            "input_sha256": digest(p["inputs"]),
        }
        for key, p in frozen["probes"].items()
    }
    view["assets"] = {
        k: v
        for k, v in frozen["assets"].items()
        if k in ("style", "palette", "sprites", "audio")
    }
    return view


def clean_handoff(value):
    if isinstance(value, dict):
        return {k: clean_handoff(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [clean_handoff(v) for v in value]
    return value


def bounded(visible, limit=160_000):
    """Keep complete current evidence and code. Trim older comparisons first."""

    def size():
        return len(
            json.dumps(
                visible, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
        )

    if size() <= limit:
        return visible
    visible = dict(visible)
    evidence = dict(visible.get("evidence", {}))
    if "evidence" in visible:
        visible["evidence"] = evidence
    omissions = {}
    for key in (
        "portfolio_designs",
        "historical_versions",
        "peers",
        "history",
    ):
        items = evidence.get(key, [])
        if len(items) > 3:
            omissions[key] = {"retained": 3, "available": len(items)}
            evidence[key] = items[:3]
        if size() + 800 <= limit:
            break
    if omissions:
        visible["context_sampling"] = omissions
    if size() > limit:
        raise ValueError("当前必要证据和源码超过单次输入预算，请拆小任务后重新发起")
    return visible
