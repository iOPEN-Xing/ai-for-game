"""Validated game-production and operations deliverables."""

import re
from typing import Annotated, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from studio.domain.levels import MAX_LEVELS

Short = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
]
Detail = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2400)
]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Family = Literal["pulse", "trail", "drift", "custom"]


class Output(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Route(Output):
    summary: Detail
    focus: list[Short] = Field(min_length=1, max_length=6)
    next_role: Literal[
        "GameplayResearch",
        "Planner",
        "ArtDesigner",
        "LevelDesigner",
        "GameCoder",
        "LevelCoder",
    ]


class Impact(Output):
    reason: Detail
    affected: list[Literal["gdd", "art", "levels", "game_code", "level_code"]] = Field(
        min_length=1, max_length=5
    )
    entities: list[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,30}$")]
    ] = Field(max_length=6)
    audio: bool
    audio_tracks: list[Literal["bgm", "hit", "miss", "win", "ui"]] | None = Field(
        default=None, max_length=5
    )
    # v1.0 persisted this schema without audio_tracks. Its pinned prompts remain valid.
    compatible_schema_hashes: ClassVar = frozenset(
        {"ec8544a607eed56cdd86d0d8dbc399dbb3932a16fe313a36b1ef1c771a17e389"}
    )

    @model_validator(mode="after")
    def changed_tracks(self):
        if self.audio_tracks is not None and (
            bool(self.audio_tracks) != self.audio
            or len(set(self.audio_tracks)) != len(self.audio_tracks)
        ):
            raise ValueError(
                "audio_tracks 须逐项列出有修改的音轨，无音频修改时填空列表"
            )
        return self


class Direction(Output):
    title: Short
    mechanic: Family
    pitch: Detail
    interaction: Short
    visual: Short
    color: Color
    reference_ids: list[Short] = Field(default_factory=list, max_length=3)


class Research(Output):
    summary: Detail
    directions: list[Direction] = Field(min_length=2, max_length=3)


class SearchBrief(Output):
    game_name: Short
    queries: list[Short] = Field(min_length=2, max_length=4)


class VisualAnalysis(Output):
    observations: dict[str, Detail] = Field(min_length=1, max_length=4)
    mechanics: Detail
    queries: list[Short] = Field(min_length=1, max_length=3)


class ProductHypothesis(Output):
    audience: Short
    player_value: Detail
    activation: Detail
    metric: Literal[
        "win_rate", "rounds_per_player", "seconds_per_player", "action_rate", "d1_rate"
    ]
    validation: Detail


class EntityBrief(Output):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,30}$")]
    title: Short


class Design(Output):
    title: Short
    core_loop: Detail
    product_hypothesis: ProductHypothesis
    illustrated_entities: list[EntityBrief] = Field(min_length=1, max_length=6)
    controls: Detail
    win_condition: Detail
    failure_condition: Detail
    assets: list[Short] = Field(min_length=1, max_length=10)
    difficulty: Detail


class Experience(Output):
    viewport: Literal["square", "portrait", "landscape"]
    composition: Short
    decision: Detail
    feedback: Short


class GameDesign(Design):
    experience: Experience


Coordinate = Annotated[float, Field(ge=0, le=1)]
Semitones = Annotated[
    list[Annotated[int, Field(ge=-12, le=24)]], Field(min_length=1, max_length=12)
]


class Brush(Output):
    shape: Literal["rect", "ellipse", "polygon", "line"]
    points: list[tuple[Coordinate, Coordinate]] = Field(min_length=2, max_length=12)
    color: Color

    @model_validator(mode="after")
    def geometry(self):
        if self.shape == "polygon" and len(self.points) < 3:
            raise ValueError("polygons need at least three points")
        return self


class SpriteDesign(Output):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,30}$")]
    title: Short
    reference: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,30}$")
    brief: str = Field(default="", max_length=800)
    layers: list[Brush] = Field(min_length=1, max_length=12)


class Soundtrack(Output):
    bgm: Semitones
    hit: Semitones
    miss: Semitones
    win: Semitones
    ui: Semitones


class Art(Output):
    style: Detail
    base_anchor: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=180)
    ] = ""
    style_anchor: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=180)
    ] = ""
    entity_anchor: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=180)
    ] = ""
    background: Color
    ink: Color
    accent: Color
    motif: Literal["beacon", "crystal", "leaf", "planet"]
    tempo: int = Field(ge=65, le=180)
    root_hz: int = Field(ge=150, le=650)
    sprites: list[SpriteDesign] = Field(min_length=1, max_length=6)
    melody: Soundtrack

    @model_validator(mode="after")
    def distinct_entities(self):
        parents = {s.id: s.reference for s in self.sprites}
        if len(parents) != len(self.sprites):
            raise ValueError("实体 ID 重复")
        for entity, parent in parents.items():
            path = {entity}
            while parent is not None:
                if parent not in parents or parent in path:
                    raise ValueError("美术参考需要指向已有实体，依赖图不能有环")
                path.add(parent)
                parent = parents[parent]
        return self


class ArtSpec(Art):
    base_anchor: Short
    style_anchor: Short
    entity_anchor: Short


class Levels(Output):
    game_type: Family
    data_structure: Detail
    production: Detail
    verification: Detail
    curve: Detail
    count: int = Field(ge=3, le=12)
    mode: Literal["runtime", "prefab"]


class Chapter(Output):
    start: int = Field(ge=1, le=MAX_LEVELS)
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=24)
    ]
    goal: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=4, max_length=80)
    ]
    rule: Short


class ChapterLevels(Levels):
    count: int = Field(ge=3, le=MAX_LEVELS)
    chapters: list[Chapter] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def chapters_cover_progression(self):
        starts = [chapter.start for chapter in self.chapters]
        if starts[0] != 1 or starts != sorted(set(starts)) or starts[-1] > self.count:
            raise ValueError("章节从首关开始，起始关号须递增且在总关数内")
        for field in ("title", "rule"):
            if len({getattr(chapter, field) for chapter in self.chapters}) != len(
                starts
            ):
                raise ValueError("每章需要独立标题和具体的新规则或决策")
        return self


class Source(Output):
    summary: Detail
    source: str = Field(min_length=40, max_length=22000)


class Quality(Output):
    quick_start: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=110)
    ]
    evidence: Detail
    blockers: list[Short] = Field(max_length=4)
    playtest_focus: list[Short] = Field(min_length=1, max_length=4)


class AnalysisOutput(Output):
    @field_validator(
        "evidence",
        "basis",
        "objection",
        "objections",
        "recommendation",
        check_fields=False,
    )
    @classmethod
    def observed_statistics(cls, value: str, info: ValidationInfo):
        if (info.context or {}).get("inference_mode") == "descriptive":
            for sentence in re.split(r"[。；;\n]", value):
                interval = re.search(
                    r"置信区间|置信范围|可信区间|效应区间|confidence interval|\bCI\b",
                    sentence,
                    re.IGNORECASE,
                )
                if interval and re.search(
                    r"\d+(?:\.\d+)?\s*[%％]?\s*(?:[–—~～至到-]|[,，]\s*(?=[+-]?\d))\s*[+-]?\d|±\s*\d",
                    sentence[interval.end() :],
                    re.IGNORECASE,
                ):
                    raise ValueError(
                        "冻结报表只有描述性数据。请保留实测人数和分母，删除未经结算计算的具体置信区间。"
                    )
        return value


class Opinion(AnalysisOutput):
    evidence: Detail
    recommendation: Detail
    objection: Detail


class Bet(AnalysisOutput):
    title: Short
    change: Detail
    basis: Detail
    low: float = Field(ge=-1000, le=1000)
    high: float = Field(ge=-1000, le=1000)
    falsifier: Detail
    falsify_below: float | None = Field(default=None, ge=-1000, le=1000)
    objections: Detail
    days: int = Field(ge=1, le=28)
    min_players: int = Field(ge=2, le=10000)
    citations: list[str] = Field(max_length=10)

    @model_validator(mode="after")
    def interval(self):
        if self.low > self.high:
            raise ValueError("low must be <= high")
        if self.falsify_below is None:
            self.falsify_below = self.low
        if self.falsify_below > self.low:
            raise ValueError("falsify_below must be <= low")
        return self
