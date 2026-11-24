"""Public v1 agents API. Implementation lives in the application package."""

from studio.application.agents.gateway import consult
from studio.application.agents.streaming import research_reply
from studio.application.prompts.builder import output_schema
from studio.domain.agent_outputs import (
    AnalysisOutput,
    Art,
    ArtSpec,
    Bet,
    Brush,
    Design,
    Direction,
    EntityBrief,
    Impact,
    Levels,
    Opinion,
    Output,
    ProductHypothesis,
    Quality,
    Research,
    Route,
    SearchBrief,
    Soundtrack,
    Source,
    SpriteDesign,
    VisualAnalysis,
)
from studio.settings import provider_names

__all__ = [
    "AnalysisOutput",
    "Art",
    "ArtSpec",
    "Bet",
    "Brush",
    "Design",
    "Direction",
    "EntityBrief",
    "Impact",
    "Levels",
    "Opinion",
    "Output",
    "ProductHypothesis",
    "Quality",
    "Research",
    "Route",
    "SearchBrief",
    "Soundtrack",
    "Source",
    "SpriteDesign",
    "VisualAnalysis",
    "consult",
    "output_schema",
    "provider_names",
    "research_reply",
]
