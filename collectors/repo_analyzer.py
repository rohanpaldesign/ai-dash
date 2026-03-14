"""
repo_analyzer.py — Git commit/AI session correlator.

Runs periodically (every 10 min) in background thread.
Finds git repos under configured root paths, reads recent commits,
matches them to AI sessions within a 30-minute window, and writes
commit events to raw_events.
"""

import json
import logging
import sys
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
CONFIG_PATH = BASE_DIR / "config" / "subscriptions.yaml"

from database.connection import get_connection

SCAN_INTERVAL = 600       # seconds between scans
COMMIT_WINDOW = 1800      # 30 min: AI session → commit correlation window
GIT_LOOKBACK = "2 hours"  # how far back to scan git log

logger = logging.getLogger(__name__)



def find_git_repos(roots: list[str], max_depth: int = 4) -> list[Path]:
    """Find all git repositories under the given root paths."""
    repos: list[Path] = []
    for root_str in roots:
        root = Path(root_str)
        if not root.exists():
            continue
        try:
            _scan_for_repos(root, repos, depth=0, max_depth=max_depth)
        except PermissionError:
            pass
    return repos


def _scan_for_repos(path: Path, repos: list[Path], depth: int, max_depth: int) -> None:
    if depth > max_depth:
        return
    if (path / ".git").exists():
        repos.append(path)
        return  # Don't recurse into sub-repos
    try:
        for child in path.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                try:
                    _scan_for_repos(child, repos, depth + 1, max_depth)
                except PermissionError:
                    pass
    except PermissionError:
        pass


def get_recent_commits(repo_path: Path) -> list[dict]:
    """Return commits from the last GIT_LOOKBACK period."""
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--since={GIT_LOOKBACK}",
                "--format=%H|%aI|%s|%an",
                "--no-merges",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) < 3:
                continue
            commits.append({
                "hash": parts[0],
                "timestamp": parts[1],
                "message": parts[2],
                "author": parts[3] if len(parts) > 3 else "",
                "repo": repo_path.name,
            })
        return commits
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as exc:
        logger.debug("git log failed for %s: %s", repo_path, exc)
        return []


def already_recorded(db: sqlite3.Connection, commit_hash: str) -> bool:
    cur = db.execute(
        "SELECT 1 FROM raw_events WHERE event_type='commit' AND metadata_json LIKE ?",
        (f'%"{commit_hash}"%',),
    )
    return cur.fetchone() is not None


def find_preceding_ai_session(
    db: sqlite3.Connection, commit_time: datetime, repo: str
) -> str | None:
    """Find the most recent AI session that ended within COMMIT_WINDOW before commit."""
    window_start = (commit_time - timedelta(seconds=COMMIT_WINDOW)).isoformat()
    commit_iso = commit_time.isoformat()

    cur = db.execute(
        """
        SELECT session_id FROM sessions
        WHERE end_time >= ? AND end_time <= ?
          AND (repo = ? OR repo IS NULL)
        ORDER BY end_time DESC
        LIMIT 1
        """,
        (window_start, commit_iso, repo),
    )
    row = cur.fetchone()
    return row[0] if row else None


def record_commit(db: sqlite3.Connection, commit: dict, session_id: str | None) -> None:
    db.execute(
        """
        INSERT INTO raw_events
          (timestamp, tool, event_type, session_id, repo, metadata_json)
        VALUES (?, 'git', 'commit', ?, ?, ?)
        """,
        (
            commit["timestamp"],
            session_id,
            commit["repo"],
            json.dumps({
                "hash": commit["hash"],
                "message": commit["message"],
                "author": commit["author"],
                "ai_correlated": session_id is not None,
            }),
        ),
    )
    db.commit()


def run_once(config: dict) -> None:
    roots = config.get("repo_roots", [])
    if not roots:
        logger.warning("No repo_roots configured in subscriptions.yaml")
        return

    repos = find_git_repos(roots)
    logger.info("Scanning %d git repos for recent commits", len(repos))

    db = get_connection()
    total_new = 0

    for repo_path in repos:
        commits = get_recent_commits(repo_path)
        for commit in commits:
            if already_recorded(db, commit["hash"]):
                continue
            try:
                commit_time = datetime.fromisoformat(commit["timestamp"])
                if commit_time.tzinfo is None:
                    commit_time = commit_time.replace(tzinfo=timezone.utc)
            except ValueError:
                commit_time = datetime.now(timezone.utc)

            session_id = find_preceding_ai_session(db, commit_time, commit["repo"])
            record_commit(db, commit, session_id)
            total_new += 1
            logger.debug(
                "Recorded commit %s in %s (ai_session=%s)",
                commit["hash"][:8],
                commit["repo"],
                session_id is not None,
            )

    db.close()
    if total_new:
        logger.info("Recorded %d new commits", total_new)


def run(stop_event=None) -> None:
    """Periodic loop. Pass threading.Event() for clean shutdown."""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    logger.info("Repo analyzer started (interval: %ds)", SCAN_INTERVAL)

    while stop_event is None or not stop_event.is_set():
        try:
            run_once(config)
        except Exception as exc:
            logger.error("Repo analyzer error: %s", exc)
        # Sleep in small increments to respect stop_event
        for _ in range(SCAN_INTERVAL // 5):
            if stop_event and stop_event.is_set():
                break
            time.sleep(5)

    logger.info("Repo analyzer stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
    config = yaml.safe_load(CONFIG_PATH.read_text())
    run_once(config)
