"""
dashboard/app.py — AI Usage Dashboard (Streamlit).

5 pages:
  1. Overview          — today's totals, 30-day trend
  2. Tool Breakdown    — per-tool metrics table + charts
  3. Session Analytics — duration distribution, deep work
  4. Time Heatmap      — hour × weekday activity heatmap
  5. Repos & Productivity — top repos, commit-after-AI rate
"""

import calendar as _calendar
import sys
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml

from database.connection import query_df

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "subscriptions.yaml"

_LA_TZ = ZoneInfo("America/Los_Angeles")


def _tz_offset_sql() -> str:
    """Return SQLite datetime offset string for current PST/PDT, e.g. '-8 hours'."""
    offset_hours = int(datetime.now(_LA_TZ).utcoffset().total_seconds() // 3600)
    return f"{offset_hours:+d} hours"


# ── Config ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_config() -> dict:
    try:
        return yaml.safe_load(CONFIG_PATH.read_text())
    except FileNotFoundError:
        return {}


def tool_color(tool: str, config: dict) -> str:
    return config.get("tools", {}).get(tool, {}).get("color", "#888888")


def tool_name(tool: str, config: dict) -> str:
    return config.get("tools", {}).get(tool, {}).get("name", tool.replace("_", " ").title())


TOOL_ORDER = ["claude_code", "cursor", "chatgpt", "gemini"]

# ── DB helpers ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_daily_metrics(days: int = 30) -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return query_df(
        "SELECT * FROM daily_metrics WHERE date >= ? ORDER BY date, tool",
        (since,),
    )


@st.cache_data(ttl=60)
def load_sessions(days: int = 30) -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    df = query_df(
        "SELECT * FROM sessions WHERE start_time >= ? ORDER BY start_time",
        (since,),
    )
    if not df.empty:
        df["start_time"] = pd.to_datetime(df["start_time"], utc=True, errors="coerce")
        df["end_time"] = pd.to_datetime(df["end_time"], utc=True, errors="coerce")
        df["date"] = df["start_time"].dt.date
        df["hour"] = df["start_time"].dt.hour
        df["weekday"] = df["start_time"].dt.day_name()
        df["active_minutes"] = df["active_seconds"] / 60
        df["is_deep_work"] = (df["active_seconds"] >= 1500)
    return df


@st.cache_data(ttl=60)
def load_raw_events(days: int = 30) -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    df = query_df(
        "SELECT * FROM raw_events WHERE timestamp >= ? ORDER BY timestamp",
        (since,),
    )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


@st.cache_data(ttl=60)
def load_today_live() -> pd.DataFrame:
    """Query today's KPIs directly from raw_events and sessions (no aggregation delay)."""
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Active minutes from window events (cursor, chatgpt, gemini)
    window_min = query_df(
        "SELECT tool, SUM(duration_seconds)/60.0 AS active_minutes "
        "FROM raw_events WHERE event_type='window_active' AND DATE(timestamp)=? "
        "AND tool != 'claude_code' GROUP BY tool",
        (today_str,),
    )

    # Claude Code active minutes from session spans (hooks don't emit window_active)
    cc_min = query_df(
        "SELECT 'claude_code' AS tool, "
        "COALESCE(SUM((julianday(end_time)-julianday(start_time))*86400)/60.0, 0) AS active_minutes "
        "FROM sessions WHERE tool='claude_code' AND DATE(start_time)=?",
        (today_str,),
    )

    # Session counts per tool
    sess_counts = query_df(
        "SELECT tool, COUNT(*) AS session_count FROM sessions WHERE DATE(start_time)=? GROUP BY tool",
        (today_str,),
    )

    # Prompt counts and estimated tokens (claude_code hook events)
    prompt_stats = query_df(
        "SELECT tool, COUNT(*) AS prompt_count, COALESCE(SUM(estimated_tokens), 0) AS estimated_tokens "
        "FROM raw_events WHERE event_type='prompt' AND DATE(timestamp)=? GROUP BY tool",
        (today_str,),
    )

    active_min = pd.concat([window_min, cc_min], ignore_index=True)
    active_min = active_min[active_min["active_minutes"].notna() & (active_min["active_minutes"] > 0)]

    if active_min.empty:
        return pd.DataFrame(columns=["tool", "active_minutes", "session_count", "prompt_count", "estimated_tokens"])

    result = active_min.copy()
    result = result.merge(sess_counts, on="tool", how="left") if not sess_counts.empty else result.assign(session_count=0)
    result = result.merge(prompt_stats, on="tool", how="left") if not prompt_stats.empty else result.assign(prompt_count=0, estimated_tokens=0)
    return result.fillna(0)


# ── Page 1: Overview ──────────────────────────────────────────────────────────

def page_overview(config: dict) -> None:
    st.title("AI Usage Overview")

    today_live = load_today_live()  # live from raw_events + sessions (~60s freshness)
    daily = load_daily_metrics(30)  # used for 30-day trend chart only

    # KPI row
    col1, col2, col3, col4 = st.columns(4)

    if not today_live.empty:
        total_min = today_live["active_minutes"].sum()
        total_sessions = today_live["session_count"].sum()
        total_prompts = today_live["prompt_count"].sum()
        total_tokens = today_live["estimated_tokens"].sum()
    else:
        total_min = total_sessions = total_prompts = total_tokens = 0

    col1.metric("Today's AI Time", f"{total_min:.0f} min")
    col2.metric("Sessions", f"{total_sessions:.0f}")
    col3.metric("Prompts (Claude)", f"{total_prompts:.0f}")
    col4.metric("Est. Tokens (Claude)", f"{total_tokens:,.0f}")

    st.divider()

    # Today's tool breakdown bar
    if not today_live.empty and total_min > 0:
        st.subheader("Today's Time by Tool")
        today_chart = today_live.copy()
        today_chart["tool_name"] = today_chart["tool"].apply(lambda t: tool_name(t, config))
        fig = px.bar(
            today_chart.sort_values("active_minutes", ascending=True),
            x="active_minutes", y="tool_name", orientation="h",
            color="tool",
            color_discrete_map={t: tool_color(t, config) for t in TOOL_ORDER},
            labels={"active_minutes": "Minutes", "tool_name": "Tool"},
        )
        fig.update_layout(showlegend=False, height=250)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No activity recorded today yet.")

    st.divider()

    # 30-day stacked area chart
    st.subheader("Daily AI Time — Last 30 Days")
    if not daily.empty:
        pivot = daily.pivot_table(
            index="date", columns="tool", values="active_minutes", aggfunc="sum"
        ).fillna(0).reset_index()

        fig = go.Figure()
        for tool in TOOL_ORDER:
            if tool in pivot.columns:
                fig.add_trace(go.Bar(
                    name=tool_name(tool, config),
                    x=pivot["date"],
                    y=pivot[tool],
                    marker_color=tool_color(tool, config),
                ))
        fig.update_layout(
            barmode="stack",
            xaxis_title="Date",
            yaxis_title="Minutes",
            legend_title="Tool",
            height=350,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data in the last 30 days.")


# ── Page 2: Claude Metrics ────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_claude_metrics(since: str, until: str, granularity: str) -> dict:
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
        f"AND {date_filter} GROUP BY {grp} ORDER BY {grp}",
        (since, until),
    )
    tokens = query_df(
        f"SELECT {grp} AS {col}, "
        "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
        "SUM(cache_read_tokens) AS cache_read_tokens, SUM(cache_creation_tokens) AS cache_creation_tokens "
        "FROM raw_events WHERE event_type='stop' AND tool='claude_code' "
        f"AND input_tokens IS NOT NULL AND {date_filter} GROUP BY {grp} ORDER BY {grp}",
        (since, until),
    )
    edits = query_df(
        f"SELECT {grp} AS {col}, COUNT(*) AS edits_accepted "
        "FROM raw_events WHERE event_type='tool_call' AND tool='claude_code' "
        f"AND tool_name IN ('Edit','Write','NotebookEdit') AND success=1 "
        f"AND {date_filter} GROUP BY {grp} ORDER BY {grp}",
        (since, until),
    )
    return {"prompts": prompts, "tokens": tokens, "edits": edits, "col": col}


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
        end = min(start + timedelta(days=6), today)
        label = "This Week" if offset == 0 else f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
        return str(start), str(end), label, "day", offset == 0

    if period == "Month":
        year, month = today.year, today.month + offset
        while month <= 0:
            month += 12; year -= 1
        while month > 12:
            month -= 12; year += 1
        start = _date(year, month, 1)
        end = min(_date(year, month, _calendar.monthrange(year, month)[1]), today)
        label = "This Month" if offset == 0 else start.strftime("%B %Y")
        return str(start), str(end), label, "day", offset == 0

    if period == "Year":
        year = today.year + offset
        start = _date(year, 1, 1)
        end = min(_date(year, 12, 31), today)
        label = "This Year" if offset == 0 else str(year)
        return str(start), str(end), label, "month", offset == 0

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

    # Coerce types so merge key matches
    if granularity in ("hour", "6h"):
        df = df.copy(); df[col] = df[col].astype(int)
    else:
        df = df.copy(); df[col] = df[col].astype(str)

    merged = full.merge(df, on=col, how="left")
    num_cols = merged.select_dtypes(include="number").columns.difference([col])
    merged[num_cols] = merged[num_cols].fillna(0)
    return merged


def page_claude_metrics(config: dict) -> None:
    st.title("Claude Code Metrics")

    PERIODS = ["Today", "Week", "Month", "Year"]
    BLOCK_LABELS = ["12AM–6AM", "6AM–12PM", "12PM–6PM", "6PM–12AM"]

    # ── State init ─────────────────────────────────────────────────────────────
    if "m_period" not in st.session_state:
        st.session_state["m_period"] = "Week"
    for _k in ("m_offset_prompts", "m_offset_tokens", "m_offset_edits"):
        if _k not in st.session_state:
            st.session_state[_k] = 0
    if "m_date_range" not in st.session_state:
        s, u, *_ = _get_period_range("Week", 0)
        st.session_state["m_date_range"] = (_date.fromisoformat(s), _date.fromisoformat(u))

    # If a pill or arrow just fired, sync the date range picker to the BASE period
    if st.session_state.pop("m_nav_triggered", False):
        s, u, *_ = _get_period_range(st.session_state["m_period"], 0)
        st.session_state["m_date_range"] = (_date.fromisoformat(s), _date.fromisoformat(u))

    # ── Segmented control (Apple-style pills) ──────────────────────────────────
    def _on_period_change():
        st.session_state["m_offset_prompts"] = 0
        st.session_state["m_offset_tokens"]  = 0
        st.session_state["m_offset_edits"]   = 0
        st.session_state["m_nav_triggered"]  = True

    period = st.pills(
        "",
        PERIODS,
        default="Week",
        key="m_period",
        on_change=_on_period_change,
        label_visibility="collapsed",
    ) or "Week"

    # ── Base period (offset=0) for KPIs and date-picker sync ──────────────────
    base_since_str, base_until_str, _, granularity, _ = _get_period_range(period, 0)
    base_since = _date.fromisoformat(base_since_str)
    base_until = _date.fromisoformat(base_until_str)

    # ── Date range picker (always visible, synced with period/arrows) ──────────
    date_val = st.date_input(
        "Date range",
        key="m_date_range",
        max_value=datetime.now(_LA_TZ).date(),
    )
    if isinstance(date_val, (list, tuple)) and len(date_val) == 2:
        picker_since = _date.fromisoformat(str(date_val[0]))
        picker_until = _date.fromisoformat(str(date_val[1]))
    else:
        _d = date_val[0] if isinstance(date_val, (list, tuple)) else date_val
        picker_since = picker_until = _date.fromisoformat(str(_d))

    # Custom mode: user manually changed the picker (differs from base period)
    _all_zero = all(
        st.session_state[_k] == 0
        for _k in ("m_offset_prompts", "m_offset_tokens", "m_offset_edits")
    )
    custom_mode = _all_zero and (picker_since != base_since or picker_until != base_until)
    custom_since = str(picker_since)
    custom_until = str(picker_until)

    cc_color = tool_color("claude_code", config)

    # ── Per-chart navigation helper ────────────────────────────────────────────
    def chart_nav(chart_key: str, offset_key: str):
        offset = st.session_state[offset_key]
        c_since, c_until, c_label, _, c_at_latest = _get_period_range(period, offset)
        c1, c2, c3 = st.columns([1, 8, 1])
        with c1:
            if st.button("◀", key=f"prev_{chart_key}", use_container_width=True):
                st.session_state[offset_key] -= 1
                st.session_state["m_nav_triggered"] = True
                st.rerun()
        with c2:
            st.markdown(
                f"<p style='text-align:center;font-weight:600;font-size:0.95rem;"
                f"margin:0;padding-top:5px'>{c_label}</p>",
                unsafe_allow_html=True,
            )
        with c3:
            if st.button("▶", key=f"next_{chart_key}", use_container_width=True, disabled=c_at_latest):
                st.session_state[offset_key] += 1
                st.session_state["m_nav_triggered"] = True
                st.rerun()
        return c_since, c_until, c_label, c_at_latest

    # ── x-axis formatting helper ───────────────────────────────────────────────
    def _fmt_x(df_: pd.DataFrame, col_: str) -> None:
        if granularity == "6h":
            df_[col_] = df_[col_].astype(int).map(lambda i: BLOCK_LABELS[i])
        elif granularity == "hour":
            df_[col_] = df_[col_].astype(int)
        elif granularity == "month":
            df_[col_] = pd.to_datetime(df_[col_] + "-01").dt.strftime("%b %Y")

    if granularity == "6h":
        x_label = "Time Block"
    elif granularity == "hour":
        x_label = "Hour"
    elif granularity == "month":
        x_label = "Month"
    else:
        x_label = "Date"

    # ── KPIs (always base / custom period) ────────────────────────────────────
    kpi_since = custom_since if custom_mode else base_since_str
    kpi_until = custom_until if custom_mode else base_until_str
    kpi_data = load_claude_metrics(kpi_since, kpi_until, granularity)
    kpi_col = kpi_data["col"]
    kpi_prompts_df = _fill_gaps(kpi_data["prompts"], kpi_col, granularity, kpi_since, kpi_until)
    kpi_tokens_df  = _fill_gaps(kpi_data["tokens"],  kpi_col, granularity, kpi_since, kpi_until)
    kpi_edits_df   = _fill_gaps(kpi_data["edits"],   kpi_col, granularity, kpi_since, kpi_until)
    for _df, _req in [
        (kpi_prompts_df, ["prompts"]),
        (kpi_edits_df,   ["edits_accepted"]),
        (kpi_tokens_df,  ["input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"]),
    ]:
        for _c in _req:
            if _c not in _df.columns:
                _df[_c] = 0

    total_prompts    = int(kpi_prompts_df["prompts"].sum())
    total_input      = int(kpi_tokens_df["input_tokens"].sum())
    total_output     = int(kpi_tokens_df["output_tokens"].sum())
    total_cache_read = int(kpi_tokens_df["cache_read_tokens"].sum())
    total_edits      = int(kpi_edits_df["edits_accepted"].sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Prompts",        f"{total_prompts:,}")
    k2.metric("Input Tokens",   f"{total_input:,}")
    k3.metric("Output Tokens",  f"{total_output:,}")
    k4.metric("Cache Read",     f"{total_cache_read:,}")
    k5.metric("Edits Accepted", f"{total_edits:,}")

    st.divider()

    # ── Prompts ────────────────────────────────────────────────────────────────
    st.subheader("Prompts")
    if custom_mode:
        chart_nav("prompts", "m_offset_prompts")
        p_since, p_until = custom_since, custom_until
    else:
        p_since, p_until, _, _ = chart_nav("prompts", "m_offset_prompts")
    p_data = load_claude_metrics(p_since, p_until, granularity)
    p_col = p_data["col"]
    prompts_df = _fill_gaps(p_data["prompts"], p_col, granularity, p_since, p_until)
    if "prompts" not in prompts_df.columns:
        prompts_df["prompts"] = 0
    _fmt_x(prompts_df, p_col)
    fig = px.bar(prompts_df, x=p_col, y="prompts",
                 labels={p_col: x_label, "prompts": "Prompts"},
                 color_discrete_sequence=[cc_color])
    fig.update_layout(height=240, margin=dict(t=4, b=4))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Tokens ─────────────────────────────────────────────────────────────────
    st.subheader("Tokens")
    if custom_mode:
        chart_nav("tokens", "m_offset_tokens")
        t_since, t_until = custom_since, custom_until
    else:
        t_since, t_until, _, _ = chart_nav("tokens", "m_offset_tokens")
    t_data = load_claude_metrics(t_since, t_until, granularity)
    t_col = t_data["col"]
    tokens_df = _fill_gaps(t_data["tokens"], t_col, granularity, t_since, t_until)
    for _c in ["input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"]:
        if _c not in tokens_df.columns:
            tokens_df[_c] = 0
    _fmt_x(tokens_df, t_col)
    fig = go.Figure()
    for series, color, name in [
        ("input_tokens",          "#4A9EFF", "Input"),
        ("output_tokens",         "#F4B400", "Output"),
        ("cache_read_tokens",     "#34A853", "Cache Read"),
        ("cache_creation_tokens", "#EA4335", "Cache Creation"),
    ]:
        fig.add_trace(go.Bar(name=name, x=tokens_df[t_col], y=tokens_df[series], marker_color=color))
    fig.update_layout(barmode="stack", height=260, legend_title="Type",
                      xaxis_title=x_label, yaxis_title="Tokens", margin=dict(t=4, b=4))
    st.plotly_chart(fig, use_container_width=True)
    if int(tokens_df["input_tokens"].sum()) == 0:
        st.caption("Token counts appear after a session ends (Stop hook reads the transcript).")

    st.divider()

    # ── Edits Accepted ─────────────────────────────────────────────────────────
    st.subheader("Edits Accepted")
    if custom_mode:
        chart_nav("edits", "m_offset_edits")
        e_since, e_until = custom_since, custom_until
    else:
        e_since, e_until, _, _ = chart_nav("edits", "m_offset_edits")
    e_data = load_claude_metrics(e_since, e_until, granularity)
    e_col = e_data["col"]
    edits_df = _fill_gaps(e_data["edits"], e_col, granularity, e_since, e_until)
    if "edits_accepted" not in edits_df.columns:
        edits_df["edits_accepted"] = 0
    _fmt_x(edits_df, e_col)
    fig = px.bar(edits_df, x=e_col, y="edits_accepted",
                 labels={e_col: x_label, "edits_accepted": "Edits"},
                 color_discrete_sequence=[cc_color])
    fig.update_layout(height=240, margin=dict(t=4, b=4))
    st.plotly_chart(fig, use_container_width=True)


# ── Page 3: Tool Breakdown ────────────────────────────────────────────────────

def page_tool_breakdown(config: dict) -> None:
    st.title("Tool Breakdown")

    daily = load_daily_metrics(30)
    raw = load_raw_events(30)

    if daily.empty:
        st.info("No data yet.")
        return

    # Aggregate per-tool (30-day totals)
    agg = daily.groupby("tool").agg(
        active_minutes=("active_minutes", "sum"),
        session_count=("session_count", "sum"),
        prompt_count=("prompt_count", "sum"),
        estimated_tokens=("estimated_tokens", "sum"),
        commits_after_ai=("commits_after_ai", "sum"),
    ).reset_index()
    agg["tool_name"] = agg["tool"].apply(lambda t: tool_name(t, config))

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("30-Day Totals")
        display = agg[["tool_name", "active_minutes", "session_count",
                        "prompt_count", "estimated_tokens", "commits_after_ai"]].copy()
        display.columns = ["Tool", "Active Min", "Sessions", "Prompts", "Est. Tokens", "AI Commits"]
        display["Active Min"] = display["Active Min"].round(1)
        st.dataframe(display.set_index("Tool"), use_container_width=True)

    with col2:
        st.subheader("Time Share")
        fig = px.pie(
            agg,
            values="active_minutes",
            names="tool_name",
            color="tool",
            color_discrete_map={t: tool_color(t, config) for t in TOOL_ORDER},
            hole=0.4,
        )
        fig.update_layout(height=300, showlegend=True, legend_title="Tool")
        st.plotly_chart(fig, use_container_width=True)

    # Claude Code tool call breakdown
    st.divider()
    st.subheader("Claude Code — Tool Call Breakdown")
    if not raw.empty:
        cc_tools = raw[
            (raw["tool"] == "claude_code") & (raw["event_type"] == "tool_call") & raw["tool_name"].notna()
        ]
        if not cc_tools.empty:
            tc_counts = cc_tools["tool_name"].value_counts().reset_index()
            tc_counts.columns = ["Tool Name", "Count"]
            fig = px.bar(
                tc_counts,
                x="Tool Name", y="Count",
                color_discrete_sequence=[tool_color("claude_code", config)],
            )
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No tool call data yet for Claude Code.")
    else:
        st.info("No raw event data yet.")


# ── Page 3: Session Analytics ─────────────────────────────────────────────────

def page_session_analytics(config: dict) -> None:
    st.title("Session Analytics")

    sessions = load_sessions(30)

    if sessions.empty:
        st.info("No sessions recorded yet.")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Sessions (30d)", len(sessions))
    col2.metric("Deep Work Sessions", int(sessions["is_deep_work"].sum()))
    avg_dur = sessions["active_seconds"].mean() / 60
    col3.metric("Avg Session Duration", f"{avg_dur:.1f} min")

    st.divider()

    # Duration histogram
    st.subheader("Session Duration Distribution")
    sessions_plot = sessions.copy()
    sessions_plot["tool_name"] = sessions_plot["tool"].apply(lambda t: tool_name(t, config))
    fig = px.histogram(
        sessions_plot[sessions_plot["active_minutes"] > 0],
        x="active_minutes",
        color="tool",
        color_discrete_map={t: tool_color(t, config) for t in TOOL_ORDER},
        nbins=40,
        labels={"active_minutes": "Duration (minutes)", "count": "Sessions"},
        barmode="overlay",
        opacity=0.75,
    )
    fig.update_layout(height=350, legend_title="Tool")
    st.plotly_chart(fig, use_container_width=True)

    # Sessions per day stacked bar
    st.subheader("Sessions per Day")
    if not sessions.empty:
        daily_counts = sessions.groupby(["date", "tool"]).size().reset_index(name="count")
        daily_counts["tool_name"] = daily_counts["tool"].apply(lambda t: tool_name(t, config))
        fig = px.bar(
            daily_counts,
            x="date", y="count", color="tool",
            color_discrete_map={t: tool_color(t, config) for t in TOOL_ORDER},
            barmode="stack",
            labels={"count": "Sessions", "date": "Date"},
        )
        fig.update_layout(height=300, legend_title="Tool")
        st.plotly_chart(fig, use_container_width=True)

    # Deep work sessions list
    st.divider()
    st.subheader("Deep Work Sessions (≥25 min)")
    deep = sessions[sessions["is_deep_work"]].copy()
    if not deep.empty:
        deep["Duration"] = deep["active_seconds"].apply(lambda s: f"{s/60:.1f} min")
        deep["Tool"] = deep["tool"].apply(lambda t: tool_name(t, config))
        deep["Start"] = deep["start_time"].dt.strftime("%Y-%m-%d %H:%M")
        display_cols = ["Start", "Tool", "Duration", "repo", "prompt_count"]
        st.dataframe(
            deep[display_cols].rename(columns={"repo": "Repo", "prompt_count": "Prompts"})
                               .reset_index(drop=True),
            use_container_width=True,
        )
    else:
        st.info("No deep work sessions yet (sessions ≥ 25 min).")


# ── Page 4: Time Heatmap ──────────────────────────────────────────────────────

WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def page_heatmap(config: dict) -> None:
    st.title("Time Heatmap")

    sessions = load_sessions(30)

    tool_options = ["All Tools"] + [tool_name(t, config) for t in TOOL_ORDER]
    tool_name_to_id = {tool_name(t, config): t for t in TOOL_ORDER}

    selected = st.selectbox("Filter by tool", tool_options)

    if sessions.empty:
        st.info("No session data yet.")
        return

    df = sessions.copy()
    if selected != "All Tools":
        df = df[df["tool"] == tool_name_to_id[selected]]

    if df.empty:
        st.info(f"No data for {selected}.")
        return

    # Build hour × weekday pivot (sum of active_minutes)
    df["weekday"] = pd.Categorical(df["weekday"], categories=WEEKDAY_ORDER, ordered=True)
    pivot = df.groupby(["weekday", "hour"])["active_minutes"].sum().reset_index()
    pivot = pivot.pivot(index="weekday", columns="hour", values="active_minutes").fillna(0)

    # Reindex to ensure all hours 0-23 and all weekdays present
    pivot = pivot.reindex(WEEKDAY_ORDER)
    for h in range(24):
        if h not in pivot.columns:
            pivot[h] = 0
    pivot = pivot[sorted(pivot.columns)]

    fig = px.imshow(
        pivot,
        labels={"x": "Hour of Day", "y": "Day of Week", "color": "Active Minutes"},
        color_continuous_scale="Blues",
        aspect="auto",
        title=f"Activity Heatmap — {selected}",
    )
    fig.update_xaxes(tickvals=list(range(0, 24, 2)), ticktext=[f"{h:02d}:00" for h in range(0, 24, 2)])
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Color intensity = total active minutes in that hour slot over the last 30 days. "
        "Hours are local time."
    )


# ── Page 5: Repos & Productivity ──────────────────────────────────────────────

def page_repos(config: dict) -> None:
    st.title("Repos & Productivity")

    sessions = load_sessions(30)
    raw = load_raw_events(30)

    if sessions.empty:
        st.info("No session data yet.")
        return

    # Top repos by AI time
    st.subheader("Top Repos by AI Time")
    repo_time = (
        sessions[sessions["repo"].notna()]
        .groupby("repo")["active_minutes"]
        .sum()
        .sort_values(ascending=False)
        .head(15)
        .reset_index()
    )
    if not repo_time.empty:
        fig = px.bar(
            repo_time,
            x="active_minutes", y="repo", orientation="h",
            labels={"active_minutes": "Minutes", "repo": "Repository"},
            color_discrete_sequence=["#4A9EFF"],
        )
        fig.update_layout(height=max(200, len(repo_time) * 30), yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No repo data yet. Repo context comes from Claude Code hook events.")

    # Commit-after-AI rate
    st.divider()
    st.subheader("Commit-after-AI Rate")

    if not raw.empty:
        commits = raw[raw["event_type"] == "commit"]
        ai_correlated = commits[commits["session_id"].notna()]

        col1, col2, col3 = st.columns(3)
        col1.metric("Total AI Sessions (30d)", len(sessions))
        col2.metric("Commits within 30min of AI", len(ai_correlated))
        rate = len(ai_correlated) / len(sessions) * 100 if len(sessions) > 0 else 0
        col3.metric("Commit-after-AI Rate", f"{rate:.1f}%")

        # Timeline: commits vs sessions per day
        if not commits.empty:
            st.subheader("Git Commits vs AI Sessions Over Time")
            commit_daily = commits.groupby(commits["timestamp"].dt.date).size().reset_index(name="commits")
            session_daily = sessions.groupby("date").size().reset_index(name="sessions")

            commit_daily["date"] = pd.to_datetime(commit_daily["timestamp"])
            session_daily["date"] = pd.to_datetime(session_daily["date"])

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=session_daily["date"], y=session_daily["sessions"],
                name="AI Sessions", marker_color="#4A9EFF", opacity=0.7,
            ))
            fig.add_trace(go.Scatter(
                x=commit_daily["date"], y=commit_daily["commits"],
                name="Commits", mode="lines+markers", line=dict(color="#F4B400", width=2),
                yaxis="y2",
            ))
            fig.update_layout(
                yaxis=dict(title="AI Sessions"),
                yaxis2=dict(title="Commits", overlaying="y", side="right"),
                legend_title="Metric",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No raw event data yet.")

    # Cost overview
    st.divider()
    st.subheader("Cost Estimate (This Month)")
    config_data = load_config()
    tools_cfg = config_data.get("tools", {})

    cost_rows = []
    today = datetime.now()
    days_this_month = today.day
    daily_metrics = load_daily_metrics(days_this_month)

    for tool_id, tcfg in tools_cfg.items():
        monthly = tcfg.get("monthly_cost", 0)
        daily_cost = monthly / 30
        used_days = 0
        if not daily_metrics.empty:
            used_days = daily_metrics[
                (daily_metrics["tool"] == tool_id) & (daily_metrics["active_minutes"] > 0)
            ]["date"].nunique()
        cost_rows.append({
            "Tool": tcfg.get("name", tool_id),
            "Monthly Cost": f"${monthly:.2f}",
            "Days Used": used_days,
            "Est. Cost (days used)": f"${daily_cost * used_days:.2f}",
        })

    st.dataframe(pd.DataFrame(cost_rows).set_index("Tool"), use_container_width=True)


# ── App entrypoint ────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="AI Usage Dashboard",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    config = load_config()

    with st.sidebar:
        st.title("AI Usage Dashboard")
        st.caption("Cloud • Zero cost • Always on")
        st.divider()
        page = st.radio(
            "Navigate",
            [
                "Overview",
                "Claude Metrics",
                "Tool Breakdown",
                "Session Analytics",
                "Time Heatmap",
                "Repos & Productivity",
            ],
        )
        st.divider()
        if st.button("Refresh Data"):
            load_today_live.clear()
            load_daily_metrics.clear()
            load_sessions.clear()
            load_raw_events.clear()
            load_claude_metrics.clear()
            st.rerun()
        st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")


    if page == "Overview":
        page_overview(config)
    elif page == "Claude Metrics":
        page_claude_metrics(config)
    elif page == "Tool Breakdown":
        page_tool_breakdown(config)
    elif page == "Session Analytics":
        page_session_analytics(config)
    elif page == "Time Heatmap":
        page_heatmap(config)
    elif page == "Repos & Productivity":
        page_repos(config)


if __name__ == "__main__":
    main()
