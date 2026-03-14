"""
metrics_calculator.py — Aggregates sessions → daily_metrics.

Reads the sessions table, computes per-day per-tool metrics,
and upserts into daily_metrics.
Also computes commits_after_ai from raw_events commit records.
"""

import logging
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from database.connection import get_connection

logger = logging.getLogger(__name__)


def compute_session_metrics(db: sqlite3.Connection) -> None:
    """Aggregate sessions → daily_metrics (active_minutes, session_count, prompts, tokens)."""
    cur = db.execute(
        """
        SELECT
            DATE(start_time) AS date,
            tool,
            SUM(active_seconds) / 60.0  AS active_minutes,
            COUNT(*)                     AS session_count,
            SUM(prompt_count)            AS prompt_count,
            0                            AS estimated_tokens
        FROM sessions
        WHERE start_time IS NOT NULL
        GROUP BY DATE(start_time), tool
        """
    )
    rows = cur.fetchall()

    for row in rows:
        date, tool, active_minutes, session_count, prompt_count, est_tokens = row

        # Get token estimate from raw_events for claude_code
        if tool == "claude_code":
            tok_cur = db.execute(
                """
                SELECT SUM(estimated_tokens)
                FROM raw_events
                WHERE tool = 'claude_code'
                  AND event_type = 'prompt'
                  AND DATE(timestamp) = ?
                """,
                (date,),
            )
            tok_row = tok_cur.fetchone()
            est_tokens = tok_row[0] or 0 if tok_row else 0

        db.execute(
            """
            INSERT INTO daily_metrics
              (date, tool, active_minutes, session_count, prompt_count, estimated_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, tool) DO UPDATE SET
              active_minutes   = excluded.active_minutes,
              session_count    = excluded.session_count,
              prompt_count     = excluded.prompt_count,
              estimated_tokens = excluded.estimated_tokens
            """,
            (date, tool, active_minutes or 0, session_count or 0,
             prompt_count or 0, est_tokens or 0),
        )


def compute_commit_metrics(db: sqlite3.Connection) -> None:
    """Count commits correlated to AI sessions per day."""
    cur = db.execute(
        """
        SELECT DATE(r.timestamp) AS date,
               s.tool,
               COUNT(*) AS commit_count
        FROM raw_events r
        JOIN sessions s ON s.session_id = r.session_id
        WHERE r.event_type = 'commit'
          AND r.session_id IS NOT NULL
        GROUP BY DATE(r.timestamp), s.tool
        """
    )
    rows = cur.fetchall()
    for date, tool, count in rows:
        db.execute(
            """
            INSERT INTO daily_metrics (date, tool, commits_after_ai)
            VALUES (?, ?, ?)
            ON CONFLICT(date, tool) DO UPDATE SET
              commits_after_ai = excluded.commits_after_ai
            """,
            (date, tool, count),
        )


def run() -> None:
    db = get_connection()
    try:
        compute_session_metrics(db)
        compute_commit_metrics(db)
        db.commit()
        logger.info("Metrics calculator: daily_metrics updated.")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
