"""Public operations entry points for the studio and existing integrations."""

from studio.application.harness.operations.analysis import analyze
from studio.application.usecases.operations.batches import (
    audit_batches,
    daily_priorities,
    run_batch,
)
from studio.application.usecases.operations.decisions import (
    review_knowledge,
    review_proposal,
)
from studio.application.usecases.operations.evidence import freeze, frozen_evidence
from studio.application.usecases.operations.experiments import (
    decide_experiment,
    delivery_diff,
    distribution,
    progress_scope,
    release,
    settle,
)
from studio.domain import deliberation
from studio.domain.metrics import (
    METRIC_HELP,
    click_difference_interval,
    rates,
    sample_unit,
)
from studio.infra.reporting import exp_stats, report, retention

MANUAL = "先读冻结的三级报表、版本配置与原始历史，再独立分析、互评、形成一条可执行假设。没有样本或有效版本则停止。"

__all__ = [
    "METRIC_HELP",
    "analyze",
    "audit_batches",
    "click_difference_interval",
    "daily_priorities",
    "decide_experiment",
    "deliberation",
    "delivery_diff",
    "distribution",
    "exp_stats",
    "freeze",
    "frozen_evidence",
    "progress_scope",
    "rates",
    "release",
    "report",
    "retention",
    "review_knowledge",
    "review_proposal",
    "run_batch",
    "sample_unit",
    "settle",
]
