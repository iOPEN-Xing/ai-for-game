"""Role-scoped AgentScope skills and immutable manifests for resumable jobs."""

import json
from pathlib import Path

from agentscope.skill import LocalSkillLoader

from studio.application.agents.registry import (
    manifest_skills,
    routes_for_run,
    skill_catalog,
    skills_for_role,
)
from studio.domain.fingerprints import digest
from studio.infra.repositories import skills as skills_db
from studio.infra.store import db, encode, now
from studio.settings import chat_model

loader = LocalSkillLoader(str(Path(__file__).with_name("skills")), scan_subdir=True)


def v1_routes():
    # Pre-routing bindings contain only skill hashes. They used the released v1 policy.
    return json.loads(
        Path(__file__).with_name("v1-skill-routes.json").read_text("utf-8")
    )


async def read(role=None, task=None, binding=None):
    if not binding:
        return await local_skills(
            skills_for_role(role, task) if role else skill_catalog()
        )
    manifest = binding["manifest"]
    names = tuple(manifest)
    if role:
        routes = binding.get("routes")
        choices = (routes if routes is not None else v1_routes())[role]
        names = choices.get(task, choices["default"])
    with db() as con:
        result = [skills_db.instruction(con, name, manifest[name]) for name in names]
    if any(digest(s["body"]) != s["revision"] for s in result):
        raise RuntimeError("归档技能正文的摘要校验失败")
    return result


async def local_skills(names):
    skills = {s.name: s for s in await loader.list_skills()}
    if any(name not in skills for name in names):
        raise RuntimeError(
            "项目技能缺失，请检查部署包的 studio/application/agents/skills"
        )
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
        routes = routes_for_run(task)
        skills = await local_skills(manifest_skills(routes))
        with db(True) as con:
            existing = skills_db.pin(
                con,
                run_id,
                chat_model(),
                encode({s["name"]: s["revision"] for s in skills}),
                encode(routes),
                skills,
                now(),
            )
    return {
        "id": run_id,
        "model": existing["model"],
        "manifest": json.loads(existing["manifest"]),
        "routes": json.loads(existing["routes"])
        if existing["routes"] is not None
        else v1_routes(),
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
