"""Run independent opinions, directed challenges, adjudication and final review."""

import asyncio

from studio.domain.deliberation import (
    Answer,
    Candidates,
    Challenge,
    EvidenceRequest,
    FinalSummary,
    IterationDraft,
    LaunchDraft,
    LaunchReview,
    ResolutionBody,
    RulingBody,
    first_schema,
    issue_ids,
    reviewable,
)


async def conduct(kind, doc, evidence, call):
    async def independent(role, phase="independent"):
        await call(role, role, first_schema(kind, role), phase)

    if kind == "new_game":
        async with asyncio.TaskGroup() as group:
            for role in ("Analyst", "Reviewer", "Engineer"):
                group.create_task(independent(role, "constraints"))
        await call(
            "GameDesigner",
            "GameDesigner",
            Candidates,
            "candidates",
            constraints=doc["Analyst"],
            dead_end_audit=doc["Reviewer"],
            feasibility=doc["Engineer"],
        )
    else:
        async with asyncio.TaskGroup() as group:
            for role in ("Analyst", "Reviewer", "Engineer", "GameDesigner"):
                group.create_task(independent(role))
    opinions = {r: doc[r] for r in ("Analyst", "Reviewer", "Engineer", "GameDesigner")}
    await call(
        "challenge",
        "Analyst" if kind == "new_game" else "Reviewer",
        Challenge,
        "challenge",
        independent_opinions=opinions,
    )
    issues = issue_ids(doc)
    async with asyncio.TaskGroup() as group:
        for key, issue in issues.items():
            owner = issue["owner"]
            group.create_task(
                call(
                    "reply_" + key,
                    owner,
                    Answer,
                    "reply",
                    issue_id=key,
                    question=issue,
                    original=opinions[owner],
                    opinions=opinions,
                )
            )
    replies = {key: doc["reply_" + key] for key in issues}
    debate = {"independent_opinions": opinions, "questions": issues, "replies": replies}
    async with asyncio.TaskGroup() as group:
        for key, issue in issues.items():
            group.create_task(
                call(
                    "resolve_" + key,
                    "Moderator",
                    ResolutionBody,
                    "adjudicate",
                    issue_id=key,
                    question=issue,
                    answer=replies[key],
                )
            )
    resolutions = {key: doc["resolve_" + key] for key in issues}
    unresolved = {
        key: resolutions[key]
        for key in issues
        if not replies[key]["supported"] or resolutions[key]["disposition"] == "open"
    }
    if unresolved:
        await call(
            "hold",
            "Moderator",
            EvidenceRequest,
            "hold",
            **debate,
            unresolved=unresolved,
        )
        return False
    await call(
        "bet",
        "Moderator",
        LaunchDraft if kind == "new_game" else IterationDraft,
        "decision",
        **debate,
        decisions=resolutions,
    )
    async with asyncio.TaskGroup() as group:
        for key, issue in issues.items():
            group.create_task(
                call(
                    "verify_" + key,
                    "Reviewer",
                    RulingBody,
                    "verify_issue",
                    issue_id=key,
                    question=issue,
                    answer=replies[key],
                    adjudication=resolutions[key],
                    proposed=doc["bet"],
                )
            )
    await call(
        "final_review",
        "Reviewer",
        LaunchReview if kind == "new_game" else FinalSummary,
        "final_review",
        proposed=doc["bet"],
        verified={key: doc["verify_" + key] for key in issues},
        **debate,
    )
    return reviewable(kind, doc, evidence)
