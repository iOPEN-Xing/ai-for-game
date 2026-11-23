"""Role-scoped AgentScope skills and immutable manifests for resumable jobs."""

import json

from agentscope.skill import LocalSkillLoader

from studio.domain.fingerprints import digest as digest
from studio.infra.repositories import skills as skills_db

from .infra.store import db, encode, now
from .settings import ROOT, chat_model

DESIGN = "design-gameplay"
BUILD = "build-playable-levels"
OPS = "review-game-experiments"
TASK = {"iteration": "iterate-live-game", "new_game": "evaluate-new-game"}
ROUTING = {
    "Producer": (DESIGN, BUILD),
    "GameplayResearch": (DESIGN,),
    "Planner": (DESIGN,),
    "ArtDesigner": (DESIGN,),
    "LevelDesigner": (DESIGN, BUILD),
    "GameCoder": (BUILD, DESIGN),
    "LevelCoder": (BUILD,),
    "QualityReviewer": (BUILD, DESIGN),
    "Analyst": (OPS,),
    "Engineer": (BUILD, OPS),
    "GameDesigner": (DESIGN, OPS),
    "Reviewer": (OPS,),
    "Moderator": (OPS,),
}
loader = LocalSkillLoader(str(ROOT / "studio/skills"), scan_subdir=True)


def routes(role, task=None):
    if not role:
        return (DESIGN, BUILD, OPS, *TASK.values())
    names = ROUTING[role]
    return (*names, TASK[task]) if task in TASK and OPS in names else names


async def read(role=None, task=None, manifest=None):
    names = routes(role, task)
    if manifest is not None:
        with db() as con:
            result = [
                skills_db.instruction(con, name, manifest[name]) for name in names
            ]
        if any(digest(s["body"]) != s["revision"] for s in result):
            raise RuntimeError("归档技能正文的摘要校验失败")
        return result
    return await local_skills(names)


async def local_skills(names):
    skills = {s.name: s for s in await loader.list_skills()}
    if any(name not in skills for name in names):
        raise RuntimeError("项目技能缺失，请检查部署包的 studio/skills")
    return [
        {
            "name": name,
            "description": skills[name].description,
            "body": skills[name].markdown,
            "revision": digest(skills[name].markdown),
        }
        for name in names
    ]


async def pin(run_id, task=None):
    with db() as con:
        existing = skills_db.binding(con, run_id)
    if not existing:
        if task == "production":
            names = (DESIGN, BUILD)
        elif task in TASK:
            names = (DESIGN, BUILD, OPS, TASK[task])
        else:
            names = routes(None)
        skills = await local_skills(names)
        with db(True) as con:
            existing = skills_db.pin(
                con,
                run_id,
                chat_model(),
                encode({s["name"]: s["revision"] for s in skills}),
                skills,
                now(),
            )
    return {
        "id": run_id,
        "model": existing["model"],
        "manifest": json.loads(existing["manifest"]),
    }


def bind_prompt(run_id, role, node, schema, prompt):
    signature = digest(schema.model_json_schema())
    with db(True) as con:
        saved = skills_db.bind_prompt(con, run_id, role, node, signature, prompt)
    if saved["schema_hash"] != signature and saved["schema_hash"] not in getattr(
        schema, "compatible_schema_hashes", ()
    ):
        raise RuntimeError("运行中的产物契约已变更，需要以新契约重新发起任务")
    return saved["prompt"]
