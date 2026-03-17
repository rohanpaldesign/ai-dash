"""dashboard/views/sessions.py — Session browser page."""

import pandas as pd
import plotly.express as px
import streamlit as st

from data import (
    TOOL_ORDER,
    load_sessions,
    tool_color,
    tool_name,
)


def page_sessions(config: dict) -> None:
    st.title("Sessions")

    user_id = st.session_state["user"]["user_id"]

    # Load a 90-day window; user filters will narrow it down
    sessions = load_sessions(90, user_id)

    if sessions.empty:
        st.info("No sessions recorded yet.")
        return

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("Filters", expanded=True):
        fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 1])
        with fc1:
            tool_options = [tool_name(t, config) for t in TOOL_ORDER if t in sessions["tool"].unique()]
            selected_tools = st.multiselect("Tool", tool_options, default=tool_options)
        with fc2:
            date_min = sessions["date"].min()
            date_max = sessions["date"].max()
            date_from = st.date_input("From", value=date_min, min_value=date_min, max_value=date_max,
                                      key="sess_date_from")
        with fc3:
            date_to = st.date_input("To", value=date_max, min_value=date_min, max_value=date_max,
                                    key="sess_date_to")
        with fc4:
            min_dur = st.slider("Min Duration (min)", 0, 60, 0, key="sess_min_dur")

    # Apply filters
    tool_id_map = {tool_name(t, config): t for t in TOOL_ORDER}
    selected_tool_ids = [tool_id_map[n] for n in selected_tools if n in tool_id_map]

    df = sessions.copy()
    if selected_tool_ids:
        df = df[df["tool"].isin(selected_tool_ids)]
    df = df[(df["date"] >= date_from) & (df["date"] <= date_to)]
    df = df[df["active_minutes"] >= min_dur]

    # ── Sessions Table ────────────────────────────────────────────────────────
    st.subheader(f"Sessions ({len(df):,})")
    if not df.empty:
        display = df.sort_values("start_time", ascending=False).copy()
        display["Date"]     = display["start_time"].dt.strftime("%Y-%m-%d")
        display["Start"]    = display["start_time"].dt.strftime("%H:%M UTC")
        display["Tool"]     = display["tool"].apply(lambda t: tool_name(t, config))
        display["Duration"] = display["active_seconds"].apply(lambda s: f"{s/60:.1f} min")
        display["Prompts"]  = display.apply(
            lambda r: str(int(r["prompt_count"])) if r["tool"] == "claude_code" else "—", axis=1
        )
        display["Repo"]     = display["repo"].fillna("—")
        st.dataframe(
            display[["Date", "Start", "Tool", "Duration", "Prompts", "Repo"]].reset_index(drop=True),
            width='stretch',
            hide_index=True,
            height=400,
        )
    else:
        st.info("No sessions match the current filters.")

    st.divider()

    # ── Duration Distribution ─────────────────────────────────────────────────
    st.subheader("Session Duration Distribution")
    if not df.empty:
        fig = px.histogram(
            df[df["active_minutes"] > 0],
            x="active_minutes",
            color="tool",
            color_discrete_map={t: tool_color(t, config) for t in TOOL_ORDER},
            nbins=40,
            labels={"active_minutes": "Duration (minutes)", "count": "Sessions"},
            barmode="overlay",
            opacity=0.75,
        )
        fig.update_layout(height=300, legend_title="Tool", margin=dict(t=4, b=4))
        st.plotly_chart(fig, width='stretch')

    # ── Prompts per Session (Claude Code only) ────────────────────────────────
    cc_df = df[df["tool"] == "claude_code"]
    if not cc_df.empty:
        st.subheader("Prompts per Session (Claude Code)")
        st.caption("Prompt counts are only tracked for Claude Code.")
        fig = px.bar(
            cc_df.sort_values("start_time"),
            x="start_time",
            y="prompt_count",
            labels={"start_time": "Session Start", "prompt_count": "Prompts"},
            color_discrete_sequence=["#4A9EFF"],
        )
        fig.update_layout(height=260, margin=dict(t=4, b=4))
        st.plotly_chart(fig, width='stretch')

    # ── Deep Work ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Deep Work Sessions (≥25 min)")
    deep = df[df["is_deep_work"]].copy()
    if not deep.empty:
        deep["Date"]     = deep["start_time"].dt.strftime("%Y-%m-%d")
        deep["Start"]    = deep["start_time"].dt.strftime("%H:%M UTC")
        deep["Tool"]     = deep["tool"].apply(lambda t: tool_name(t, config))
        deep["Duration"] = deep["active_seconds"].apply(lambda s: f"{s/60:.1f} min")
        deep["Prompts"]  = deep.apply(
            lambda r: str(int(r["prompt_count"])) if r["tool"] == "claude_code" else "—", axis=1
        )
        deep["Repo"]     = deep["repo"].fillna("—")
        st.dataframe(
            deep[["Date", "Start", "Tool", "Duration", "Prompts", "Repo"]].reset_index(drop=True),
            width='stretch',
            hide_index=True,
        )
    else:
        st.info("No deep work sessions in the filtered range.")
