"""
sessionizer.py — Groups raw_events into sessions.

Logic:
- For window_active events: use session_id from tracker (already gap-separated)
- For claude_code hook events: use session_id from Claude Code itself
- Session = contiguous activity within gap_seconds (default 5 min)

Writes/updates the sessions table.
"""

import logging
import sqlite3
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          end_time        = excluded.end_time,
          active_seconds  = excluded.active_seconds,
          repo            = COALESCE(excluded.repo, sessions.repo),
          prompt_count    = excluded.prompt_count,
          tool_call_count = excluded.tool_call_count,
          failure_count   = excluded.failure_count
        """,
        (
            session["session_id"], session["tool"], session["start_time"],
            session["end_time"], session["active_seconds"], session["repo"],
            session["prompt_count"], session["tool_call_count"], session["failure_count"],
        ),
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


def process_claude_sessions(db: sqlite3.Connection, gap_seconds: float = 600) -> int:
    """
    Group Claude Code hook events by session_id.
    Compute: active_seconds as sum of inter-event gaps <= gap_seconds, prompt/tool/failure counts.
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

    # Fetch all timestamps per session for gap-sum calculation
    ts_cur = db.execute(
        "SELECT session_id, timestamp FROM raw_events "
        "WHERE tool = 'claude_code' AND session_id IS NOT NULL "
        "ORDER BY session_id, timestamp"
    )
    from collections import defaultdict
    session_timestamps = defaultdict(list)
    for sid, ts in ts_cur.fetchall():
        session_timestamps[sid].append(ts)

    def compute_active_seconds(timestamps):
        if len(timestamps) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(timestamps)):
            try:
                t0 = datetime.fromisoformat(timestamps[i-1].replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(timestamps[i].replace("Z", "+00:00"))
                gap = (t1 - t0).total_seconds()
                if gap <= gap_seconds:
                    total += gap
            except Exception:
                pass
        return total

    count = 0
    for row in rows:
        (session_id, start_time, end_time, cwd, repo,
         prompt_count, tool_call_count, failure_count) = row

        active_seconds = compute_active_seconds(session_timestamps.get(session_id, []))

        upsert_session(db, {
            "session_id": session_id,
            "tool": "claude_code",
            "start_time": start_time,
            "end_time": end_time,
            "active_seconds": active_seconds,
            "repo": repo,
            "prompt_count": prompt_count or 0,
            "tool_call_count": tool_call_count or 0,
            "failure_count": failure_count or 0,
        })
        count += 1
    return count


def run() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    gap_seconds = config.get("session_gap_seconds", 600)
    db = get_connection()
    try:
        w = process_window_sessions(db)
        c = process_claude_sessions(db, gap_seconds=gap_seconds)
        db.commit()
        logger.info("Sessionizer: %d window sessions, %d Claude sessions processed", w, c)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
