"""Role membership and skill access for production and live operations."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Role:
    team: Literal["production", "operations"]
    skills: tuple[str, ...]


DESIGN = "design-gameplay"
BUILD = "build-playable-levels"
OPS = "review-game-experiments"
TASK_SKILLS = {"iteration": "iterate-live-game", "new_game": "evaluate-new-game"}
ROLES = {
    "Producer": Role("production", (DESIGN, BUILD)),
    "GameplayResearch": Role("production", (DESIGN,)),
    "Planner": Role("production", (DESIGN,)),
    "ArtDesigner": Role("production", (DESIGN,)),
    "LevelDesigner": Role("production", (DESIGN, BUILD)),
    "GameCoder": Role("production", (BUILD, DESIGN)),
    "LevelCoder": Role("production", (BUILD,)),
    "QualityReviewer": Role("production", (BUILD, DESIGN)),
    "Analyst": Role("operations", (OPS,)),
    "Engineer": Role("operations", (BUILD, OPS)),
    "GameDesigner": Role("operations", (DESIGN, OPS)),
    "Reviewer": Role("operations", (OPS,)),
    "Moderator": Role("operations", (OPS,)),
}


def skills_for_role(role, task=None):
    spec = ROLES[role]
    if spec.team == "operations" and task in TASK_SKILLS:
        return (*spec.skills, TASK_SKILLS[task])
    return spec.skills


def skill_catalog():
    base = (skill for spec in ROLES.values() for skill in spec.skills)
    return tuple(dict.fromkeys((*base, *TASK_SKILLS.values())))


def routes_for_run(task):
    team = None
    if task == "production":
        team = "production"
    elif task in TASK_SKILLS:
        team = "operations"
    tasks = (task,) if task in TASK_SKILLS else TASK_SKILLS
    return {
        role: {
            "default": spec.skills,
            **{
                key: skills_for_role(role, key)
                for key in tasks
                if spec.team == "operations"
            },
        }
        for role, spec in ROLES.items()
        if team is None or spec.team == team
    }


def manifest_skills(routes):
    selected = {
        skill
        for choices in routes.values()
        for names in choices.values()
        for skill in names
    }
    return tuple(skill for skill in skill_catalog() if skill in selected)
