"""
window_monitor.py — Windows foreground window tracker.

Polls the active window every 5 seconds using pywin32.
Detects AFK via ctypes GetLastInputInfo().
Identifies Cursor, ChatGPT, and Gemini by window title patterns.
Writes window_active events to SQLite.
"""

import ctypes
import json
import logging
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import win32gui
import yaml

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
CONFIG_PATH = BASE_DIR / "config" / "subscriptions.yaml"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"

from database.connection import get_connection

POLL_INTERVAL = 5  # seconds between window checks

logger = logging.getLogger(__name__)


# ── AFK detection ────────────────────────────────────────────────────────────

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def seconds_since_last_input() -> float:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    millis_now = ctypes.windll.kernel32.GetTickCount()
    elapsed_ms = millis_now - lii.dwTime
    return elapsed_ms / 1000.0


# ── DB helpers ────────────────────────────────────────────────────────────────

def ensure_db(db: sqlite3.Connection) -> None:
    cur = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_events'"
    )
    if cur.fetchone() is None:
        db.executescript(SCHEMA_PATH.read_text())
        db.commit()


def write_event(
    db: sqlite3.Connection,
    tool: str,
    duration_seconds: float,
    window_title: str,
    session_id: str,
) -> None:
    db.execute(
        """
        INSERT INTO raw_events
          (timestamp, tool, event_type, session_id, window_title, duration_seconds)
        VALUES (?, ?, 'window_active', ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            tool,
            session_id,
            window_title[:500],
            round(duration_seconds, 2),
        ),
    )
    db.commit()


# ── Tool detection ────────────────────────────────────────────────────────────

def load_patterns(config: dict) -> dict[str, list[str]]:
    """Return {tool: [pattern, ...]} from config, lowercased."""
    raw = config.get("window_patterns", {})
    return {tool: [p.lower() for p in patterns] for tool, patterns in raw.items()}


def detect_tool(title: str, patterns: dict[str, list[str]]) -> str | None:
    title_lower = title.lower()
    for tool, pats in patterns.items():
        for pat in pats:
            if pat in title_lower:
                return tool
    return None


# ── Session tracking ─────────────────────────────────────────────────────────

class SessionTracker:
    """Tracks per-tool session IDs with gap-based boundaries."""

    def __init__(self, gap_seconds: float = 300):
        self.gap_seconds = gap_seconds
        self._sessions: dict[str, str] = {}        # tool → session_id
        self._last_seen: dict[str, float] = {}     # tool → last active time

    def get_session_id(self, tool: str) -> str:
        now = time.monotonic()
        last = self._last_seen.get(tool)
        if last is None or (now - last) > self.gap_seconds:
            self._sessions[tool] = str(uuid.uuid4())
        self._last_seen[tool] = now
        return self._sessions[tool]


# ── Main monitor loop ─────────────────────────────────────────────────────────

def run(stop_event=None) -> None:
    """
    Main monitoring loop. Pass a threading.Event() as stop_event
    to allow clean shutdown from run_background.py.
    """
    config = yaml.safe_load(CONFIG_PATH.read_text())
    patterns = load_patterns(config)
    afk_threshold = config.get("afk_threshold_seconds", 300)
    gap_seconds = config.get("session_gap_seconds", 300)

    tracker = SessionTracker(gap_seconds=gap_seconds)

    # State: accumulate contiguous active duration per tool
    current_tool: str | None = None
    current_title: str = ""
    window_start: float = time.monotonic()
    current_session_id: str | None = None

    db = get_connection()
    if isinstance(db, sqlite3.Connection):
        ensure_db(db)

    logger.info("Window monitor started (poll interval: %ds)", POLL_INTERVAL)

    def flush_current(reason: str = "") -> None:
        nonlocal current_tool, current_title, window_start, current_session_id
        if current_tool is None:
            return
        duration = time.monotonic() - window_start
        if duration >= POLL_INTERVAL:  # only write if ≥1 poll interval
            logger.debug(
                "Flush %s: %.1fs (%s) [%s]", current_tool, duration, reason, current_title[:60]
            )
            write_event(db, current_tool, duration, current_title, current_session_id)
        current_tool = None
        current_title = ""
        current_session_id = None

    while stop_event is None or not stop_event.is_set():
        try:
            # AFK check
            idle = seconds_since_last_input()
            if idle >= afk_threshold:
                if current_tool is not None:
                    flush_current("afk")
                time.sleep(POLL_INTERVAL)
                continue

            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd) if hwnd else ""
            tool = detect_tool(title, patterns) if title else None

            if tool != current_tool:
                flush_current("tool_switch")
                if tool is not None:
                    current_tool = tool
                    current_title = title
                    current_session_id = tracker.get_session_id(tool)
                    window_start = time.monotonic()
            elif tool is not None and title != current_title:
                # Same tool, title changed (e.g. new browser tab)
                current_title = title

        except Exception as exc:
            logger.warning("Window monitor error: %s", exc)

        time.sleep(POLL_INTERVAL)

    flush_current("shutdown")
    db.close()
    logger.info("Window monitor stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
    run()
