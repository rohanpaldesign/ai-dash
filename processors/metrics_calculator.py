"""
metrics_calculator.py — Aggregates sessions → daily_metrics.

Reads the sessions table, computes per-day per-tool metrics,
and upserts into daily_metrics.
Also computes commits_after_ai from raw_events commit records.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from database.connection import execute_many, execute_write, query_df

logger = logging.getLogger(__name__)

_LA_TZ = ZoneInfo("America/Los_Angeles")


def _tz_offset_sql() -> str:
    offset_hours = int(datetime.now(_LA_TZ).utcoffset().total_seconds() // 3600)
    return f"{offset_hours:+d} hours"


def _nan_to_none(val):
    """Normalise pandas NaN / None → Python None."""
    try:
        return None if pd.isna(val) else val
    except (TypeError, ValueError):
        return val


def compute_session_metrics() -> None:
    """Aggregate sessions → daily_metrics (active_minutes, session_count, prompts, tokens)."""
    tz = _tz_offset_sql()

    session_df = query_df(f"""
        SELECT
            DATE(datetime(start_time, '{tz}')) AS date,
            tool,
            user_id,
            SUM(active_seconds) / 60.0 AS active_minutes,
            COUNT(*)                    AS session_count,
            SUM(prompt_count)           AS prompt_count
        FROM sessions
        WHERE start_time IS NOT NULL
        GROUP BY DATE(datetime(start_time, '{tz}')), tool, user_id
    """)

    if session_df.empty:
        return

    # Pre-fetch all claude_code token totals in one query (avoids N round-trips)
    tokens_df = query_df(f"""
        SELECT DATE(datetime(timestamp, '{tz}')) AS date,
               user_id,
               SUM(estimated_tokens) AS estimated_tokens
        FROM raw_events
        WHERE tool = 'claude_code' AND event_type = 'prompt'
        GROUP BY DATE(datetime(timestamp, '{tz}')), user_id
    """)

    tokens_map: dict = {}
    for _, r in tokens_df.iterrows():
        key = (str(r["date"]), _nan_to_none(r["user_id"]))
        tokens_map[key] = int(r["estimated_tokens"] or 0)

    rows = []
    for _, row in session_df.iterrows():
        date = str(row["date"])
        tool = row["tool"]
        user_id = _nan_to_none(row["user_id"])
        est_tokens = tokens_map.get((date, user_id), 0) if tool == "claude_code" else 0
        rows.append((
            date, tool, user_id,
            float(row["active_minutes"] or 0),
            int(row["session_count"] or 0),
            int(row["prompt_count"] or 0),
            int(est_tokens),
        ))

    execute_many(
        """
        INSERT INTO daily_metrics
          (date, tool, user_id, active_minutes, session_count, prompt_count, estimated_tokens)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, tool) DO UPDATE SET
          user_id          = excluded.user_id,
          active_minutes   = excluded.active_minutes,
          session_count    = excluded.session_count,
          prompt_count     = excluded.prompt_count,
          estimated_tokens = excluded.estimated_tokens
        """,
        rows,
    )


def compute_commit_metrics() -> None:
    """Count commits correlated to AI sessions per day."""
    tz = _tz_offset_sql()

    commit_df = query_df(f"""
        SELECT DATE(datetime(r.timestamp, '{tz}')) AS date,
               s.tool,
               s.user_id,
               COUNT(*) AS commit_count
        FROM raw_events r
        JOIN sessions s ON s.session_id = r.session_id
        WHERE r.event_type = 'commit'
          AND r.session_id IS NOT NULL
        GROUP BY DATE(datetime(r.timestamp, '{tz}')), s.tool, s.user_id
    """)

    if commit_df.empty:
        return

    rows = []
    for _, row in commit_df.iterrows():
        rows.append((
            str(row["date"]),
            row["tool"],
            _nan_to_none(row["user_id"]),
            int(row["commit_count"] or 0),
        ))

    execute_many(
        """
        INSERT INTO daily_metrics (date, tool, user_id, commits_after_ai)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date, tool) DO UPDATE SET
          user_id          = excluded.user_id,
          commits_after_ai = excluded.commits_after_ai
        """,
        rows,
    )


def run() -> None:
    execute_write("DELETE FROM daily_metrics")
    compute_session_metrics()
    compute_commit_metrics()
    logger.info("Metrics calculator: daily_metrics updated.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
