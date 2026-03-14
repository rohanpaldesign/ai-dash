"""
sessionizer.py — Groups raw_events into sessions.

Logic:
- For window_active events: use session_id from tracker (already gap-separated)
- For claude_code hook events: use session_id from Claude Code itself
- Session = contiguous activity within gap_seconds (default 5 min)

Writes/updates the sessions table.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
CONFIG_PATH = BASE_DIR / "config" / "subscriptions.yaml"

from database.connection import get_connection

logger = logging.getLogger(__name__)


def upsert_session(db: sqlite3.Connection, session: dict) -> None:
    db.execute(
        """
        INSERT INTO sessions
          (session_id, tool, start_time, end_time, active_seconds, repo,
           prompt_count, tool_call_count, failure_count)
        VALUES (:session_id, :tool, :start_time, :end_time, :active_seconds, :repo,
                :prompt_count, :tool_call_count, :failure_count)
        ON CONFLICT(session_id) DO UPDATE SET
          end_time        = excluded.end_time,
          active_seconds  = excluded.active_seconds,
          repo            = COALESCE(excluded.repo, sessions.repo),
          prompt_count    = excluded.prompt_count,
          tool_call_count = excluded.tool_call_count,
          failure_count   = excluded.failure_count
        """,
        session,
    )


def process_window_sessions(db: sqlite3.Connection) -> int:
    """Group window_active events by session_id and compute per-session stats."""
    cur = db.execute(
        """
        SELECT session_id, tool,
               MIN(timestamp) AS start_time,
               MAX(timestamp) AS end_time,
               SUM(duration_seconds) AS active_seconds,
               MAX(repo) AS repo
        FROM raw_events
        WHERE event_type = 'window_active'
          AND session_id IS NOT NULL
        GROUP BY session_id, tool
        """
    )
    rows = cur.fetchall()
    count = 0
    for row in rows:
        session_id, tool, start_time, end_time, active_seconds, repo = row
        upsert_session(db, {
            "session_id": session_id,
            "tool": tool,
            "start_time": start_time,
            "end_time": end_time,
            "active_seconds": active_seconds or 0,
            "repo": repo,
            "prompt_count": 0,
            "tool_call_count": 0,
            "failure_count": 0,
        })
        count += 1
    return count


def process_claude_sessions(db: sqlite3.Connection) -> int:
    """
    Group Claude Code hook events by session_id.
    Compute: active_seconds from Stop events, prompt/tool/failure counts.
    """
    cur = db.execute(
        """
        SELECT session_id,
               MIN(timestamp) AS start_time,
               MAX(timestamp) AS end_time,
               MAX(cwd) AS cwd,
               MAX(repo) AS repo,
               SUM(CASE WHEN event_type = 'prompt' THEN 1 ELSE 0 END) AS prompt_count,
               SUM(CASE WHEN event_type = 'tool_call' AND success = 1 THEN 1 ELSE 0 END) AS tool_call_count,
               SUM(CASE WHEN event_type IN ('tool_failure') OR (event_type='tool_call' AND success=0) THEN 1 ELSE 0 END) AS failure_count
        FROM raw_events
        WHERE tool = 'claude_code'
          AND session_id IS NOT NULL
        GROUP BY session_id
        HAVING COUNT(*) > 0
        """
    )
    rows = cur.fetchall()
    count = 0
    for row in rows:
        (session_id, start_time, end_time, cwd, repo,
         prompt_count, tool_call_count, failure_count) = row

        # Estimate active_seconds from start→end (since we don't have explicit duration from hooks)
        try:
            t0 = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            active_seconds = (t1 - t0).total_seconds()
        except Exception:
            active_seconds = 0

        upsert_session(db, {
            "session_id": session_id,
            "tool": "claude_code",
            "start_time": start_time,
            "end_time": end_time,
            "active_seconds": max(0, active_seconds),
            "repo": repo,
            "prompt_count": prompt_count or 0,
            "tool_call_count": tool_call_count or 0,
            "failure_count": failure_count or 0,
        })
        count += 1
    return count


def run() -> None:
    db = get_connection()
    try:
        w = process_window_sessions(db)
        c = process_claude_sessions(db)
        db.commit()
        logger.info("Sessionizer: %d window sessions, %d Claude sessions processed", w, c)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
