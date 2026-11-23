"""Replay versioned studio quality cases; --live additionally calls the configured model."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from studio.domain.deliberation import (
    validate_candidates,
    validate_refs,
    visible_sources,
)
from studio.domain.evaluation import adjudicate

CASES = Path(__file__).resolve().parents[1] / "evals" / "studio-v1.json"


def accepts(gate, *values):
    try:
        gate(*values)
    except ValueError:
        return False
    return True


def replay(cases):
    evidence = {
        "sources": [
            "metrics",
            "game",
            "game.js",
            "level:1",
            "level:9",
            "player-1",
            "unreleased_plan",
            "external_changes",
        ],
        "game": {"players": 40},
        "game_code": "function step(){}",
        "external_changes": [],
        "level_pack": {"levels": [{"index": 1}]},
        "feedback": [{"id": "player-1"}],
    }
    for case in cases["attribution"]:
        low, high = case.get("bounds", [1, 20])
        bet = {"low": low, "high": high, "min_players": 20}
        result = adjudicate(
            case["metric"],
            bet,
            case["arms"],
            delivery_ok=case.get("delivery_ok", True),
            confounded=case.get("confounded", False),
        )
        yield case, {key: result[key] for key in case["expected"]}
    for case in cases["references"]:
        yield (
            case,
            accepts(
                validate_refs,
                {"assessment": {"refs": case["refs"]}},
                set(visible_sources(case["role"], evidence)),
            ),
        )
    for case in cases["candidates"]:
        options = [
            dict(zip(("title", "loop", "evidence"), values, strict=True))
            for values in case["choices"]
        ]
        yield case, accepts(validate_candidates, options, {"metrics", "game"})


async def live(cases):
    from studio import agents, skillbook
    from studio.domain.deliberation import first_schema
    from studio.infra.store import init
    from studio.settings import load_environment

    load_environment()
    if not agents.provider_names():
        raise RuntimeError("在线验收需要配置 GLM 服务凭据")
    with tempfile.TemporaryDirectory(prefix="studio-evaluation-") as folder:
        # This CLI owns its process and never opens the production DB.
        os.environ["STUDIO_DATA_DIR"] = folder
        init()
        run = await skillbook.pin("evaluation:" + cases["version"], "production")
        records = []
        for case in cases["live_impact"]:
            output, _ = await agents.consult(
                "Producer",
                agents.Impact,
                {
                    "_run_binding": run,
                    "_node": case["id"],
                    "request": case["request"],
                    "available": ["gdd", "art", "levels", "game_code", "level_code"],
                    "entities": ["beacon"],
                },
            )
            observed = {
                k: sorted(output[k]) if isinstance(output[k], list) else output[k]
                for k in case["expected"]
            }
            records.append((case, observed))
        manifests = {"production": run["manifest"]}
        for case in cases["live_operations"]:
            task, role, evidence = case["task"], case["role"], case["evidence"]
            binding = await skillbook.pin("evaluation:" + task, task)
            manifests[task] = binding["manifest"]
            output, _ = await agents.consult(
                role,
                first_schema(task, role),
                {
                    "_run_binding": binding,
                    "_node": case["id"],
                    "task": task,
                    "phase": case["phase"],
                    "evidence": evidence,
                },
            )
            observed = {
                "within_sources": accepts(
                    validate_refs, output, set(evidence["sources"])
                )
            }
            if role == "Reviewer":
                observed["examined"] = sorted(output["examined"])
            else:
                assessment = " ".join(
                    output[k] for k in ("evidence", "recommendation", "objection")
                )
                observed["observed_denominator"] = bool(
                    re.search(r"(?<![0-9])40(?![0-9])|四十", assessment)
                )
                observed["identified_interference"] = "external_changes" in output[
                    "refs"
                ] and bool(re.search("入口|人群|渠道", assessment))
            records.append((case, observed))
        return records, {"model": run["model"], "skill_manifests": manifests}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="同时调用配置的 GLM 服务评测制作人"
    )
    args = parser.parse_args()
    raw = CASES.read_bytes()
    cases = json.loads(raw)
    records, model = list(replay(cases)), None
    if args.live:
        additional, model = asyncio.run(live(cases))
        records.extend(additional)
    results = [
        {
            "id": case["id"],
            "expected": case["expected"],
            "actual": value,
            "passed": case["expected"] == value,
        }
        for case, value in records
    ]
    passed = sum(r["passed"] for r in results)
    print(
        json.dumps(
            {
                "suite": cases["version"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "live": model,
                "passed": passed,
                "total": len(results),
                "cases": results,
            },
            ensure_ascii=False,
        )
    )
    return int(passed != len(results))


if __name__ == "__main__":
    raise SystemExit(main())
