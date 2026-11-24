"""Validated commands accepted by the studio and player APIs."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)

from studio.domain import limits
from studio.domain.levels import MAX_LEVELS

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
Player = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{16,100}$")]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Command):
    key: str = Field(max_length=512)


class Idea(Command):
    request_id: Player | None = None
    level_count: int | None = Field(default=None, ge=3, le=MAX_LEVELS)
    title: Title
    brief: Text
    metric: Literal[
        "win_rate", "rounds_per_player", "seconds_per_player", "action_rate", "d1_rate"
    ] = "win_rate"
    bounds: Text


class PreferenceValues(Command):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}
    audience: str = Field(default="", max_length=200)
    visual_style: str = Field(default="", max_length=240)
    controls: str = Field(default="", max_length=200)
    audio: str = Field(default="", max_length=160)
    avoid: str = Field(default="", max_length=300)


class PreferenceUpdate(Command):
    version: int = Field(ge=0)
    values: PreferenceValues


class Decision(Command):
    action: Literal[
        "select_references", "choose", "approve", "accept", "publish", "revise", "retry"
    ]
    serial: int = Field(ge=0)
    choice: int | None = None
    note: str = Field(default="", max_length=1400)
    target: str | None = None
    reference_ids: list[str] | None = Field(default=None, max_length=4)


class Note(Command):
    note: Text


class BlueprintEdit(Command):
    serial: int = Field(ge=0)
    seed: int = Field(ge=0, le=2147483647)
    level: int = Field(ge=1, le=MAX_LEVELS)
    values: dict[str, int | float | list[int]] = Field(max_length=8)


class RoundRequest(Command):
    player: Player
    preview: str | None = None
    level: int | None = Field(default=None, ge=1, le=MAX_LEVELS)
    delivery: Literal["inline", "cached"] = "inline"
    campaign: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{24}$")] | None = None


class Campaign(Command):
    name: Title
    action_label: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
        ]
        | None
    ) = None
    action_url: HttpUrl | None = None

    @model_validator(mode="after")
    def action(self):
        if bool(self.action_label) != bool(self.action_url):
            raise ValueError("行动按钮需要同时填写文字和目标网址")
        if self.action_url and (
            self.action_url.scheme != "https"
            or self.action_url.username
            or self.action_url.password
        ):
            raise ValueError("请填写不含登录凭据的 HTTPS 活动网址")
        return self


Key = Literal[
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Space",
    "Enter",
    "KeyW",
    "KeyA",
    "KeyS",
    "KeyD",
]


class GameInput(Command):
    type: Literal["tap", "press", "move", "release", "key", "keyup", "tick"]
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    dt: float | None = Field(default=None, gt=0, le=0.101)
    key: Key | None = None

    @model_validator(mode="after")
    def required_fields(self):
        if self.type == "tick" and self.dt is None:
            raise ValueError("时钟输入缺少 dt")
        if self.type in ("tap", "press", "move", "release") and (
            self.x is None or self.y is None
        ):
            raise ValueError("指针输入缺少坐标")
        if self.type in ("key", "keyup") and self.key is None:
            raise ValueError("按键输入缺少键名")
        return self


# The iframe gives the same quantized coordinates to the game and to the journal.
# Older, object-shaped inputs retain their original floating point precision.
Coordinate = Annotated[int, Field(strict=True, ge=0, le=10000)]
Milliseconds = Annotated[int, Field(strict=True, ge=1, le=101)]
RecordedInput = (
    GameInput
    | Milliseconds
    | tuple[Literal["tap", "press", "move", "release"], Coordinate, Coordinate]
    | tuple[Literal["key", "keyup"], Key]
)


class RoundEvent(Command):
    event: Literal["start", "end"]
    won: bool = False
    finish: Literal["natural", "quit"] = "natural"
    inputs: list[RecordedInput] = Field(
        default_factory=list, max_length=limits.REPLAY_STEPS
    )
    score: int = Field(default=0, ge=-1000000, le=1000000)


class Feedback(Command):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)


class ExternalChange(Command):
    game: str
    text: Text
    affects_measurement: bool = True


class Analysis(Command):
    game: str
    kind: Literal["iteration", "new_game"] = "iteration"


class Verdict(Command):
    accept: bool
    note: str = Field(default="", max_length=1000)


class KnowledgeVerdict(Verdict):
    supersede: list[str] = Field(default_factory=list, max_length=10)


class Supplement(Command):
    note: str = Field(default="", max_length=1000)
