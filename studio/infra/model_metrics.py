"""Low-cardinality aggregates across retries. Model content never enters metrics."""

import logging
import sqlite3

from .store import db


def record(role, provider, outcome, elapsed_ms, usage):
    try:
        with db(True) as con:
            con.execute(
                """INSERT INTO model_call_totals VALUES(?,?,?,1,?,?,?,?)
                ON CONFLICT(role,provider,outcome) DO UPDATE SET
                calls=calls+1, elapsed_ms=elapsed_ms+excluded.elapsed_ms,
                usage_reports=usage_reports+excluded.usage_reports,
                input_tokens=input_tokens+excluded.input_tokens,
                output_tokens=output_tokens+excluded.output_tokens""",
                (
                    role,
                    provider,
                    outcome,
                    elapsed_ms,
                    int(usage is not None),
                    usage["input_tokens"] if usage else 0,
                    usage["output_tokens"] if usage else 0,
                ),
            )
    except sqlite3.Error as exc:
        # A telemetry write failure must not retry an already billed generation.
        logging.getLogger(__name__).warning(
            "model_metrics_unavailable type=%s", type(exc).__name__
        )
