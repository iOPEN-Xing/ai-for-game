"""Evidence types and deterministic review gates for both proposal kinds."""

import unicodedata
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, model_validator

from studio.domain.agent_outputs import Bet, Detail, Opinion, Output, Short

PROTOCOL = 3


class CitedOpinion(Opinion):
    refs: list[Short] = Field(min_length=1, max_length=6)
    blocker: "Issue | None" = None


class Constraints(CitedOpinion):
    audience: Detail
    requirements: list[Short] = Field(min_length=1, max_length=5)
    benchmark: Detail


class DeadEndAudit(CitedOpinion):
    examined: list[Short] = Field(max_length=12)
    definition_check: Detail


class Candidate(Output):
    title: Short
    audience: Short
    loop: Detail
    difference: Detail
    evidence: Short


class Candidates(CitedOpinion):
    candidates: list[Candidate] = Field(min_length=2, max_length=3)


class Issue(Output):
    owner: Literal["Analyst", "Engineer", "GameDesigner"]
    question: Detail
    refs: list[Short] = Field(min_length=1, max_length=4)


class Challenge(Output):
    issues: list[Issue] = Field(min_length=1, max_length=4)


class Answer(Output):
    supported: bool
    response: Detail
    refs: list[Short] = Field(min_length=1, max_length=6)


class ResolutionBody(Output):
    disposition: Literal["accepted", "revised", "rebutted", "open"]
    reason: Detail
    refs: list[Short] = Field(min_length=1, max_length=6)


class Resolution(ResolutionBody):
    issue: Short


class DecisionDraft(Bet):
    refs: list[Short] = Field(min_length=1, max_length=8)


class ParameterChange(Output):
    kind: Literal["parameter"]
    level: int = Field(ge=1, le=12)
    field: Literal["seconds", "quota", "radius", "pace", "size", "from", "to"]
    before: FiniteFloat
    after: FiniteFloat


class ReplayChange(Output):
    kind: Literal["replay"]
    level: int = Field(ge=1, le=12)
    field: Literal["score", "won", "done"]
    before: int | bool
    after: int | bool


class AssetChange(Output):
    kind: Literal["asset"]
    entity: str = Field(pattern=r"^[a-z][a-z0-9-]{0,30}$")
    action: Literal["add", "replace", "remove"]
    brief: Detail


Check = Annotated[
    ParameterChange | ReplayChange | AssetChange, Field(discriminator="kind")
]


class IterationDraft(DecisionDraft):
    checks: list[Check] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def different(self):
        seen = set()
        for check in self.checks:
            if isinstance(check, AssetChange):
                key = ("asset", check.entity)
            else:
                key = (check.kind, check.level, check.field)
                if check.before == check.after:
                    raise ValueError("验收项原值和目标值必须不同")
            if key in seen:
                raise ValueError("同一验收目标只能出现一次")
            seen.add(key)
        return self


class RejectedCandidate(Output):
    title: Short
    reason: Detail


class LaunchDraft(DecisionDraft):
    selected: Short
    discarded: list[RejectedCandidate] = Field(min_length=1, max_length=2)


class Iteration(IterationDraft):
    resolutions: list[Resolution] = Field(min_length=1, max_length=8)


class Launch(LaunchDraft):
    resolutions: list[Resolution] = Field(min_length=1, max_length=8)


class RulingBody(Output):
    closed: bool
    basis: Detail
    refs: list[Short] = Field(min_length=1, max_length=6)


class Ruling(Output):
    issue: Short
    closed: bool
    basis: Detail


class EvidenceRequest(Output):
    reason: Detail
    required: list[Short] = Field(min_length=1, max_length=5)
    refs: list[Short] = Field(min_length=1, max_length=6)


class FinalSummary(Output):
    approved: bool
    reason: Detail
    refs: list[Short] = Field(min_length=1, max_length=6)


class PortfolioCheck(Output):
    closest_title: Short | None
    verdict: Literal["distinct", "overlap", "insufficient"]
    difference: Detail


class LaunchReview(FinalSummary):
    portfolio_check: PortfolioCheck


class FinalReview(FinalSummary):
    rulings: list[Ruling] = Field(min_length=1, max_length=8)


def title_key(title):
    return "".join(
        c for c in unicodedata.normalize("NFKC", title).casefold() if c.isalnum()
    )


def feedback_summary(records):
    counts = {}
    for item in records:
        key = (item.get("level"), item.get("rating"))
        counts[key] = counts.get(key, 0) + item.get("responses", 1)
    return [
        {"level": level, "rating": rating, "responses": n}
        for (level, rating), n in counts.items()
    ]


def visible_sources(role: str, evidence) -> list[str]:
    restricted = (
        set() if role in ("Engineer", "Reviewer") else {"game.js", "level-generator.js"}
    )
    restricted.update(
        item["id"] for item in evidence.get("feedback", []) if "id" in item
    )
    return [source for source in evidence["sources"] if source not in restricted]


def validate_candidates(options, sources) -> None:
    if len({title_key(c["title"]) for c in options}) != len(options) or len(
        {title_key(c["loop"]) for c in options}
    ) != len(options):
        raise ValueError("候选必须有不同的名称和核心循环")
    if any(c["evidence"] not in sources for c in options):
        raise ValueError("候选依据必须来自设计师实际收到的证据目录")


def validate_refs(value, sources):
    if isinstance(value, list):
        for record in value:
            validate_refs(record, sources)
    elif isinstance(value, dict):
        unknown = set(value.get("refs", [])) - sources
        if unknown:
            raise ValueError(
                "证据 ID 不在本角色的来源目录中："
                + "、".join(sorted(unknown))[:220]
                + "。请按目录原样填写。"
            )
        for key, item in value.items():
            if key != "_run":
                validate_refs(item, sources)


def validate_decision(kind, doc, evidence):
    bet = doc["bet"]
    (Launch if kind == "new_game" else Iteration).model_validate(bet)
    if set(bet["citations"]) - {k["id"] for k in evidence["knowledge"]}:
        raise ValueError("提案引用了冻结证据之外的知识")
    ids = list(issue_ids(doc))
    if sorted(r["issue"] for r in bet["resolutions"]) != sorted(ids):
        raise ValueError("主持人必须逐项处置全部质询")
    if kind == "new_game":
        options = [c["title"] for c in doc["GameDesigner"]["candidates"]]
        if bet["title"] != bet["selected"] or sorted(options) != sorted(
            [bet["selected"], *(c["title"] for c in bet["discarded"])]
        ):
            raise ValueError("立项名称必须是所选候选，且须说明其余每个候选的淘汰理由")
        if title_key(bet["selected"]) in {title_key(t) for t in evidence["portfolio"]}:
            raise ValueError("推荐游戏与已有游戏重名")
    else:
        from . import acceptance

        acceptance.validate_baseline(bet["checks"], evidence)


def issue_ids(doc):
    issues = {f"q{i}": issue for i, issue in enumerate(doc["challenge"]["issues"], 1)}
    for role in ("Analyst", "Reviewer", "Engineer", "GameDesigner"):
        if blocker := doc[role].get("blocker"):
            issues["b-" + role] = blocker
    return issues


def reviewable(kind, doc, evidence):
    if doc.get("protocol") != PROTOCOL:
        return False
    try:
        for role in ("Analyst", "Engineer", "Reviewer", "GameDesigner"):
            (first_schema(kind, role)).model_validate(doc[role])
            allowed = set(visible_sources(role, evidence))
            validate_refs(doc[role], allowed)
            if role == "Engineer" and not {
                "game.js",
                "level-generator.js",
            }.intersection(doc[role]["refs"]):
                return False
            if kind == "new_game" and role == "GameDesigner":
                validate_candidates(doc[role]["candidates"], allowed)
        if kind == "new_game" and set(doc["Reviewer"]["examined"]) != {
            i["id"] for i in evidence["dead_ends"]
        }:
            return False
        challenge = Challenge.model_validate(doc["challenge"])
        challenger = "Analyst" if kind == "new_game" else "Reviewer"
        validate_refs(doc["challenge"], set(visible_sources(challenger, evidence)))
        if kind == "new_game" and not any(
            issue.owner == "GameDesigner" for issue in challenge.issues
        ):
            return False
        validate_refs(doc["bet"], set(visible_sources("Moderator", evidence)))
        validate_decision(kind, doc, evidence)
        final = FinalReview.model_validate(doc["final_review"])
        ids = issue_ids(doc)
        answers = [Answer.model_validate(doc["reply_" + q]) for q in ids]
        if sorted(r.issue for r in final.rulings) != sorted(ids):
            return False
        if kind == "new_game":
            duplicate = LaunchReview.model_validate(doc["final_review"]).portfolio_check
            if duplicate.verdict != "distinct" or (
                evidence["portfolio"]
                and duplicate.closest_title not in evidence["portfolio"]
            ):
                return False
            selected_loop = next(
                c["loop"]
                for c in doc["GameDesigner"]["candidates"]
                if c["title"] == doc["bet"]["selected"]
            )
            if any(
                title_key(x.get("core_loop") or "") == title_key(selected_loop)
                for x in evidence.get("portfolio_designs", [])
            ):
                return False
        for key in ids:
            validate_refs(
                doc["reply_" + key],
                set(visible_sources(ids[key]["owner"], evidence)),
            )
            ruling = next(
                r for r in doc["final_review"]["rulings"] if r["issue"] == key
            )
            resolution = next(r for r in doc["bet"]["resolutions"] if r["issue"] == key)
            if RulingBody.model_validate(ruling) != RulingBody.model_validate(
                doc["verify_" + key]
            ) or ResolutionBody.model_validate(
                resolution
            ) != ResolutionBody.model_validate(doc["resolve_" + key]):
                return False
        validate_refs(doc, set(evidence["sources"]))
        return (
            final.approved
            and all(r.closed for r in final.rulings)
            and all(a.supported for a in answers)
            and all(r["disposition"] != "open" for r in doc["bet"]["resolutions"])
        )
    except (KeyError, TypeError, ValueError, StopIteration):
        return False


def first_schema(kind, role):
    if kind == "new_game":
        return {
            "Analyst": Constraints,
            "Reviewer": DeadEndAudit,
            "GameDesigner": Candidates,
        }.get(role, CitedOpinion)
    return CitedOpinion
