"""dashboard/views/insights.py — Computed behavioral summaries."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from data import (
    load_daily_metrics,
    load_sessions,
    tool_name,
)


def _arrow(delta: float) -> str:
    if delta > 0:
        return f"↑ {delta:+.0f}"
    if delta < 0:
        return f"↓ {delta:.0f}"
    return "→ 0"


def page_insights(config: dict) -> None:
    st.title("Insights")

    user_id = st.session_state["user"]["user_id"]

    sessions = load_sessions(90, user_id)
    daily    = load_daily_metrics(90, user_id)

    if sessions.empty:
        st.info("Not enough data for insights yet.")
        return

    today     = date.today()
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(weeks=1)
    last_week_end   = this_week_start - timedelta(days=1)

    def _week_sessions(start: date, end: date) -> pd.DataFrame:
        return sessions[(sessions["date"] >= start) & (sessions["date"] <= end)]

    this_week_sess = _week_sessions(this_week_start, today)
    last_week_sess = _week_sessions(last_week_start, last_week_end)

    # ── Week-over-week comparison ──────────────────────────────────────────────
    st.subheader("Week-over-Week")

    def _wow_card(col, label: str, this_val: float, last_val: float, fmt: str = "{:.0f}") -> None:
        delta = this_val - last_val
        arrow = _arrow(delta)
        color = "#34A853" if delta >= 0 else "#EA4335"
        col.metric(
            label,
            fmt.format(this_val),
            delta=arrow,
            delta_color="normal" if delta >= 0 else "inverse",
        )

    w1, w2, w3, w4 = st.columns(4)

    this_sessions  = len(this_week_sess)
    last_sessions  = len(last_week_sess)
    w1.metric("Sessions (this week)", this_sessions,
              delta=f"{this_sessions - last_sessions:+d} vs last week")

    this_prompts = int(this_week_sess[this_week_sess["tool"] == "claude_code"]["prompt_count"].sum())
    last_prompts = int(last_week_sess[last_week_sess["tool"] == "claude_code"]["prompt_count"].sum())
    w2.metric("Prompts — Claude (this week)", this_prompts,
              delta=f"{this_prompts - last_prompts:+d} vs last week")

    this_min = this_week_sess["active_minutes"].sum()
    last_min = last_week_sess["active_minutes"].sum()
    w3.metric("Active Minutes (this week)", f"{this_min:.0f}",
              delta=f"{this_min - last_min:+.0f} vs last week")

    this_days = this_week_sess["date"].nunique()
    last_days = last_week_sess["date"].nunique()
    w4.metric("Active Days (this week)", this_days,
              delta=f"{this_days - last_days:+d} vs last week")

    st.divider()

    # ── Usage Patterns ────────────────────────────────────────────────────────
    st.subheader("Usage Patterns")

    p1, p2 = st.columns(2)

    with p1:
        # Peak hour
        if not sessions.empty:
            hour_totals = sessions.groupby("hour")["active_minutes"].sum()
            peak_hour   = int(hour_totals.idxmax())
            st.metric("Peak Hour", f"{peak_hour:02d}:00 – {peak_hour+1:02d}:00 PT")
        else:
            st.metric("Peak Hour", "—")

        # Most active weekday
        WEEKDAY_ORDER = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        if not sessions.empty:
            wd_totals  = sessions.groupby("weekday")["active_minutes"].sum()
            most_wd    = wd_totals.idxmax() if not wd_totals.empty else "—"
            st.metric("Most Active Weekday", most_wd)
        else:
            st.metric("Most Active Weekday", "—")

    with p2:
        # Current streak
        streak = 0
        check = today
        dates_set = set(sessions["date"].unique())
        while check in dates_set:
            streak += 1
            check   = check - timedelta(days=1)
        st.metric("Current Streak", f"{streak} day{'s' if streak != 1 else ''}")

        # Avg daily AI time (over active days)
        active_day_count = sessions["date"].nunique()
        total_mins       = sessions["active_minutes"].sum()
        avg_daily        = (total_mins / active_day_count) if active_day_count > 0 else 0
        st.metric("Avg Daily AI Time (active days)", f"{avg_daily:.1f} min")

    st.divider()

    # ── Tool Behavior ─────────────────────────────────────────────────────────
    st.subheader("Tool Behavior")

    b1, b2, b3 = st.columns(3)

    with b1:
        # Longest session
        if not sessions.empty:
            idx_max    = sessions["active_seconds"].idxmax()
            longest    = sessions.loc[idx_max]
            b1.metric(
                "Longest Session",
                f"{longest['active_seconds']/60:.1f} min",
                delta=f"{tool_name(longest['tool'], config)} — {longest['date']}",
                delta_color="off",
            )

    with b2:
        # Most prompts in one session (Claude Code)
        cc = sessions[sessions["tool"] == "claude_code"]
        if not cc.empty:
            idx_max_p  = cc["prompt_count"].idxmax()
            most_p_row = cc.loc[idx_max_p]
            b2.metric(
                "Most Prompts (single session)",
                f"{int(most_p_row['prompt_count'])}",
                delta=str(most_p_row["date"]),
                delta_color="off",
            )
        else:
            b2.metric("Most Prompts (single session)", "—")

    with b3:
        # Tool with longest avg session
        avg_by_tool = sessions.groupby("tool")["active_seconds"].mean()
        if not avg_by_tool.empty:
            best_tool = avg_by_tool.idxmax()
            b3.metric(
                "Longest Avg Session",
                f"{avg_by_tool[best_tool]/60:.1f} min",
                delta=tool_name(best_tool, config),
                delta_color="off",
            )
        else:
            b3.metric("Longest Avg Session", "—")
