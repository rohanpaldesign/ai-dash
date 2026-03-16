"""dashboard/data.py — All data loading functions and helpers for the AI Usage Dashboard."""

import calendar as _calendar
import sys
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st
import yaml

from database.connection import query_df

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "subscriptions.yaml"

_LA_TZ = ZoneInfo("America/Los_Angeles")
TOOL_ORDER = ["claude_code", "cursor", "chatgpt", "gemini"]
WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tz_offset_sql() -> str:
    """Return SQLite datetime offset string for current PST/PDT, e.g. '-8 hours'."""
    offset_hours = int(datetime.now(_LA_TZ).utcoffset().total_seconds() // 3600)
    return f"{offset_hours:+d} hours"


def tool_color(tool: str, config: dict) -> str:
    return config.get("tools", {}).get(tool, {}).get("color", "#888888")


def tool_name(tool: str, config: dict) -> str:
    return config.get("tools", {}).get(tool, {}).get("name", tool.replace("_", " ").title())


def _process_sessions(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty:
        df["start_time"] = pd.to_datetime(df["start_time"], utc=True, errors="coerce")
        df["end_time"]   = pd.to_datetime(df["end_time"],   utc=True, errors="coerce")
        _pst = df["start_time"].dt.tz_convert(_LA_TZ)
        df["date"]           = _pst.dt.date
        df["hour"]           = _pst.dt.hour
        df["weekday"]        = _pst.dt.day_name()
        df["active_minutes"] = df["active_seconds"] / 60
        df["is_deep_work"]   = df["active_seconds"] >= 1500
    return df


# ── Config ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_config() -> dict:
    try:
        return yaml.safe_load(CONFIG_PATH.read_text())
    except FileNotFoundError:
        return {}


# ── Sessions ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_sessions(days: int = 30, user_id: str = "") -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    df = query_df(
        "SELECT * FROM sessions WHERE start_time >= ? AND user_id = ? ORDER BY start_time",
        (since, user_id),
    )
    return _process_sessions(df)


@st.cache_data(ttl=60)
def load_sessions_range(since: str, until: str, user_id: str = "") -> pd.DataFrame:
    tz = _tz_offset_sql()
    df = query_df(
        f"SELECT * FROM sessions WHERE DATE(datetime(start_time, '{tz}')) BETWEEN ? AND ? AND user_id = ? ORDER BY start_time",
        (since, until, user_id),
    )
    return _process_sessions(df)


# ── Daily metrics ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_daily_metrics(days: int = 30, user_id: str = "") -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return query_df(
        "SELECT * FROM daily_metrics WHERE date >= ? AND user_id = ? ORDER BY date, tool",
        (since, user_id),
    )


@st.cache_data(ttl=60)
def load_daily_metrics_range(since: str, until: str, user_id: str = "") -> pd.DataFrame:
    return query_df(
        "SELECT * FROM daily_metrics WHERE date BETWEEN ? AND ? AND user_id = ? ORDER BY date, tool",
        (since, until, user_id),
    )


# ── Raw events ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_raw_events(days: int = 30, user_id: str = "") -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    df = query_df(
        "SELECT * FROM raw_events WHERE timestamp >= ? AND user_id = ? ORDER BY timestamp",
        (since, user_id),
    )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


@st.cache_data(ttl=60)
def load_raw_events_range(since: str, until: str, user_id: str = "") -> pd.DataFrame:
    df = query_df(
        "SELECT * FROM raw_events WHERE DATE(timestamp) BETWEEN ? AND ? AND user_id = ? ORDER BY timestamp",
        (since, until, user_id),
    )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


# ── Today live (for Refresh cache clearing) ───────────────────────────────────

@st.cache_data(ttl=60)
def load_today_live(user_id: str = "") -> pd.DataFrame:
    """Query today's KPIs directly from raw_events and sessions (no aggregation delay)."""
    today_str = datetime.now().strftime("%Y-%m-%d")

    window_min = query_df(
        "SELECT tool, SUM(duration_seconds)/60.0 AS active_minutes "
        "FROM raw_events WHERE event_type='window_active' AND DATE(timestamp)=? "
        "AND tool != 'claude_code' AND user_id = ? GROUP BY tool",
        (today_str, user_id),
    )
    cc_min = query_df(
        "SELECT 'claude_code' AS tool, "
        "COALESCE(SUM((julianday(end_time)-julianday(start_time))*86400)/60.0, 0) AS active_minutes "
        "FROM sessions WHERE tool='claude_code' AND DATE(start_time)=? AND user_id = ?",
        (today_str, user_id),
    )
    sess_counts = query_df(
        "SELECT tool, COUNT(*) AS session_count FROM sessions WHERE DATE(start_time)=? AND user_id = ? GROUP BY tool",
        (today_str, user_id),
    )
    prompt_stats = query_df(
        "SELECT tool, COUNT(*) AS prompt_count, COALESCE(SUM(estimated_tokens), 0) AS estimated_tokens "
        "FROM raw_events WHERE event_type='prompt' AND DATE(timestamp)=? AND user_id = ? GROUP BY tool",
        (today_str, user_id),
    )

    active_min = pd.concat([window_min, cc_min], ignore_index=True)
    active_min = active_min[active_min["active_minutes"].notna() & (active_min["active_minutes"] > 0)]

    if active_min.empty:
        return pd.DataFrame(columns=["tool", "active_minutes", "session_count", "prompt_count", "estimated_tokens"])

    result = active_min.copy()
    result = result.merge(sess_counts, on="tool", how="left") if not sess_counts.empty else result.assign(session_count=0)
    result = result.merge(prompt_stats, on="tool", how="left") if not prompt_stats.empty else result.assign(prompt_count=0, estimated_tokens=0)
    return result.fillna(0)


# ── Claude Code metrics ───────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_claude_metrics(since: str, until: str, granularity: str, user_id: str = "") -> dict:
    """Load prompts, tokens, and edits grouped by block / hour / day / month (PST)."""
    tz = _tz_offset_sql()
    dt_expr = f"datetime(timestamp, '{tz}')"
    date_filter = f"DATE({dt_expr}) BETWEEN ? AND ?"

    if granularity == "6h":
        grp = f"CAST(strftime('%H', {dt_expr}) AS INTEGER) / 6"
        col = "block"
    elif granularity == "hour":
        grp = f"CAST(strftime('%H', {dt_expr}) AS INTEGER)"
        col = "hour"
    elif granularity == "month":
        grp = f"strftime('%Y-%m', {dt_expr})"
        col = "month"
    else:
        grp = f"DATE({dt_expr})"
        col = "date"

    prompts = query_df(
        f"SELECT {grp} AS {col}, COUNT(*) AS prompts "
        "FROM raw_events WHERE event_type='prompt' AND tool='claude_code' "
        f"AND {date_filter} AND user_id = ? GROUP BY {grp} ORDER BY {grp}",
        (since, until, user_id),
    )
    tokens = query_df(
        f"SELECT {grp} AS {col}, "
        "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
        "SUM(cache_read_tokens) AS cache_read_tokens, SUM(cache_creation_tokens) AS cache_creation_tokens "
        "FROM raw_events WHERE event_type='stop' AND tool='claude_code' "
        f"AND input_tokens IS NOT NULL AND {date_filter} AND user_id = ? GROUP BY {grp} ORDER BY {grp}",
        (since, until, user_id),
    )
    edits = query_df(
        f"SELECT {grp} AS {col}, COUNT(*) AS edits_accepted "
        "FROM raw_events WHERE event_type='tool_call' AND tool='claude_code' "
        f"AND tool_name IN ('Edit','Write','NotebookEdit') AND success=1 "
        f"AND {date_filter} AND user_id = ? GROUP BY {grp} ORDER BY {grp}",
        (since, until, user_id),
    )
    return {"prompts": prompts, "tokens": tokens, "edits": edits, "col": col}


# ── Period range helpers (used by Claude Code page) ───────────────────────────

def _get_period_range(period: str, offset: int):
    """Return (since, until, label, granularity, at_latest) for a period + offset."""
    today = datetime.now(_LA_TZ).date()

    if period == "Today":
        d = today + timedelta(days=offset)
        label = "Today" if offset == 0 else d.strftime("%B %d, %Y")
        return str(d), str(d), label, "6h", offset == 0

    if period == "Week":
        start_of_week = today - timedelta(days=today.weekday())
        start = start_of_week + timedelta(weeks=offset)
        end = start + timedelta(days=6)
        label = "This Week" if offset == 0 else f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
        return str(start), str(end), label, "day", offset == 0

    if period == "Month":
        year, month = today.year, today.month + offset
        while month <= 0:
            month += 12; year -= 1
        while month > 12:
            month -= 12; year += 1
        start = _date(year, month, 1)
        end = _date(year, month, _calendar.monthrange(year, month)[1])
        label = "This Month" if offset == 0 else start.strftime("%B %Y")
        return str(start), str(end), label, "day", offset == 0

    if period == "Year":
        year = today.year + offset
        start = _date(year, 1, 1)
        end = _date(year, 12, 31)
        label = "This Year" if offset == 0 else str(year)
        return str(start), str(end), label, "month", offset == 0

    if period == "All Time":
        start = _date(2020, 1, 1)
        return str(start), str(today), "All Time", "month", True

    return str(today), str(today), "", "day", True


def _fill_gaps(df: pd.DataFrame, col: str, granularity: str, since: str, until: str) -> pd.DataFrame:
    """Ensure every time slot in the range has a row, filling missing ones with 0."""
    if granularity == "6h":
        full = pd.DataFrame({col: [0, 1, 2, 3]})
    elif granularity == "hour":
        full = pd.DataFrame({col: list(range(24))})
    elif granularity == "month":
        periods = pd.period_range(
            pd.Timestamp(since).to_period("M"),
            pd.Timestamp(until).to_period("M"),
            freq="M",
        )
        full = pd.DataFrame({col: [str(p) for p in periods]})
    else:
        full = pd.DataFrame({col: [str(d.date()) for d in pd.date_range(since, until, freq="D")]})

    if df.empty:
        return full

    if granularity in ("hour", "6h"):
        df = df.copy(); df[col] = df[col].astype(int)
    else:
        df = df.copy(); df[col] = df[col].astype(str)

    merged = full.merge(df, on=col, how="left")
    num_cols = merged.select_dtypes(include="number").columns.difference([col])
    merged[num_cols] = merged[num_cols].fillna(0)
    return merged


# ── Tool activity (for tool detail pages) ────────────────────────────────────

@st.cache_data(ttl=60)
def load_tool_activity(tool: str, since: str, until: str, granularity: str, user_id: str = "") -> dict:
    """Load window-active minutes and session counts grouped by time bucket (PST)."""
    tz = _tz_offset_sql()
    dt_expr = f"datetime(timestamp, '{tz}')"
    date_filter = f"DATE({dt_expr}) BETWEEN ? AND ?"

    if granularity == "6h":
        grp = f"CAST(strftime('%H', {dt_expr}) AS INTEGER) / 6"
        col = "block"
    elif granularity == "hour":
        grp = f"CAST(strftime('%H', {dt_expr}) AS INTEGER)"
        col = "hour"
    elif granularity == "month":
        grp = f"strftime('%Y-%m', {dt_expr})"
        col = "month"
    else:  # day
        grp = f"DATE({dt_expr})"
        col = "date"

    active = query_df(
        f"SELECT {grp} AS {col}, SUM(duration_seconds)/60.0 AS active_minutes "
        "FROM raw_events WHERE tool=? AND event_type='window_active' "
        f"AND {date_filter} AND user_id = ? GROUP BY {grp} ORDER BY {grp}",
        (tool, since, until, user_id),
    )
    sessions_q = query_df(
        f"SELECT {grp} AS {col}, COUNT(DISTINCT session_id) AS session_count "
        "FROM raw_events WHERE tool=? AND event_type='window_active' "
        f"AND {date_filter} AND user_id = ? GROUP BY {grp} ORDER BY {grp}",
        (tool, since, until, user_id),
    )
    return {"active": active, "sessions": sessions_q, "col": col}


# ── Tool hourly breakdown (for tool detail pages) ────────────────────────────

@st.cache_data(ttl=60)
def load_tool_hourly(tool: str, since: str, until: str, user_id: str = "") -> pd.DataFrame:
    tz = _tz_offset_sql()
    dt_expr = f"datetime(timestamp, '{tz}')"
    return query_df(
        f"SELECT CAST(strftime('%H', {dt_expr}) AS INTEGER) AS hour, "
        "SUM(duration_seconds)/60.0 AS active_minutes "
        "FROM raw_events WHERE tool=? AND event_type='window_active' "
        f"AND DATE({dt_expr}) BETWEEN ? AND ? AND user_id = ? "
        "GROUP BY hour ORDER BY hour",
        (tool, since, until, user_id),
    )


# ── DB stats (for Settings page) ─────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_db_stats() -> dict:
    counts = {}
    for table in ["sessions", "raw_events", "daily_metrics"]:
        r = query_df(f"SELECT COUNT(*) AS cnt FROM {table}")
        counts[table] = int(r["cnt"].iloc[0]) if not r.empty else 0
    last_events = query_df(
        "SELECT tool, MAX(timestamp) AS last_event FROM raw_events GROUP BY tool"
    )
    return {"counts": counts, "last_events": last_events}
