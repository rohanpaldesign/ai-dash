"""dashboard/views/tool_detail.py — Shared page layout for Cursor, ChatGPT, Gemini."""

import pandas as pd
import plotly.express as px
import streamlit as st

from data import (
    load_sessions_range,
    load_tool_hourly,
    tool_color,
    tool_name,
)


def page_tool_detail(tool_id: str, config: dict) -> None:
    display = tool_name(tool_id, config)
    st.title(display)

    st.info(
        "Prompt and token counts are only available for Claude Code. "
        f"{display} is tracked via window activity monitoring."
    )

    since = str(st.session_state.get("global_date_from"))
    until = str(st.session_state.get("global_date_to"))

    sessions = load_sessions_range(since, until)
    if not sessions.empty:
        sessions = sessions[sessions["tool"] == tool_id]

    # ── KPI row ───────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    if not sessions.empty:
        k1.metric("Sessions",            f"{len(sessions):,}")
        k2.metric("Active Minutes",      f"{sessions['active_minutes'].sum():.1f}")
        k3.metric("Active Days",         f"{sessions['date'].nunique()}")
        k4.metric("Avg Session",         f"{sessions['active_seconds'].mean()/60:.1f} min")
        last = sessions["start_time"].max()
        k5.metric("Last Used",           last.strftime("%Y-%m-%d") if pd.notna(last) else "—")
    else:
        for k in (k1, k2, k3, k4, k5):
            k.metric("—", "—")

    st.divider()

    # ── Active minutes over time ───────────────────────────────────────────────
    st.subheader("Active Minutes Over Time")
    if not sessions.empty:
        daily = sessions.groupby("date")["active_minutes"].sum().reset_index()
        fig = px.bar(
            daily,
            x="date", y="active_minutes",
            labels={"date": "Date", "active_minutes": "Active Minutes"},
            color_discrete_sequence=[tool_color(tool_id, config)],
        )
        fig.update_layout(height=280, margin=dict(t=4, b=4))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data for this date range.")

    # ── Sessions over time ────────────────────────────────────────────────────
    st.subheader("Sessions Over Time")
    if not sessions.empty:
        daily_sess = sessions.groupby("date").size().reset_index(name="sessions")
        fig = px.bar(
            daily_sess,
            x="date", y="sessions",
            labels={"date": "Date", "sessions": "Sessions"},
            color_discrete_sequence=[tool_color(tool_id, config)],
        )
        fig.update_layout(height=240, margin=dict(t=4, b=4))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No session data.")

    # ── Usage by Hour of Day ──────────────────────────────────────────────────
    st.subheader("Usage by Hour of Day")
    hourly = load_tool_hourly(tool_id, since, until)
    if not hourly.empty:
        # Fill missing hours
        full_hours = pd.DataFrame({"hour": list(range(24))})
        hourly = full_hours.merge(hourly, on="hour", how="left").fillna(0)
        fig = px.bar(
            hourly, x="hour", y="active_minutes",
            labels={"hour": "Hour of Day (PST)", "active_minutes": "Active Minutes"},
            color_discrete_sequence=[tool_color(tool_id, config)],
        )
        fig.update_layout(height=240, margin=dict(t=4, b=4))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No hourly data.")

    # ── Session Duration Distribution ─────────────────────────────────────────
    st.subheader("Session Duration Distribution")
    if not sessions.empty:
        fig = px.histogram(
            sessions[sessions["active_minutes"] > 0],
            x="active_minutes",
            nbins=30,
            labels={"active_minutes": "Duration (minutes)", "count": "Sessions"},
            color_discrete_sequence=[tool_color(tool_id, config)],
        )
        fig.update_layout(height=240, margin=dict(t=4, b=4))
        st.plotly_chart(fig, use_container_width=True)

    # ── Recent Sessions table ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Recent Sessions")
    if not sessions.empty:
        recent = sessions.sort_values("start_time", ascending=False).head(20).copy()
        recent["Date"]     = recent["start_time"].dt.strftime("%Y-%m-%d")
        recent["Start"]    = recent["start_time"].dt.strftime("%H:%M UTC")
        recent["Duration"] = recent["active_seconds"].apply(lambda s: f"{s/60:.1f} min")
        st.dataframe(
            recent[["Date", "Start", "Duration"]].reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No sessions in this date range.")
