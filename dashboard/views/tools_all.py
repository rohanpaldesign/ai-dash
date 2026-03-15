"""dashboard/views/tools_all.py — All Tools comparison page."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data import (
    TOOL_ORDER,
    load_daily_metrics_range,
    load_sessions_range,
    tool_color,
    tool_name,
)


def page_tools_all(config: dict) -> None:
    st.title("All Tools")

    st.info(
        "Prompt and token counts are only available for Claude Code. "
        "Cursor, ChatGPT, and Gemini are tracked via window activity monitoring."
    )

    since = str(st.session_state.get("global_date_from"))
    until = str(st.session_state.get("global_date_to"))

    sessions = load_sessions_range(since, until)
    daily    = load_daily_metrics_range(since, until)

    # ── Comparison table ──────────────────────────────────────────────────────
    st.subheader("Tool Comparison")
    if not sessions.empty:
        agg = sessions.groupby("tool").agg(
            sessions=("session_id", "count"),
            active_min=("active_minutes", "sum"),
            active_days=("date", "nunique"),
            avg_session=("active_seconds", "mean"),
        ).reset_index()

        # Prompts from sessions (claude_code only)
        cc_prompts = (
            sessions[sessions["tool"] == "claude_code"]["prompt_count"].sum()
            if not sessions.empty else 0
        )

        # Last used per tool
        last_used = sessions.groupby("tool")["start_time"].max().dt.strftime("%Y-%m-%d")

        rows = []
        for tool in TOOL_ORDER:
            row = agg[agg["tool"] == tool]
            if row.empty:
                rows.append({
                    "Tool": tool_name(tool, config),
                    "Sessions": 0,
                    "Active Min": 0.0,
                    "Prompts": "—",
                    "Avg Session": "—",
                    "Active Days": 0,
                    "Last Used": "—",
                })
            else:
                r = row.iloc[0]
                rows.append({
                    "Tool": tool_name(tool, config),
                    "Sessions": int(r["sessions"]),
                    "Active Min": round(r["active_min"], 1),
                    "Prompts": str(int(cc_prompts)) if tool == "claude_code" else "—",
                    "Avg Session": f"{r['avg_session']/60:.1f} min",
                    "Active Days": int(r["active_days"]),
                    "Last Used": last_used.get(tool, "—"),
                })

        st.dataframe(
            pd.DataFrame(rows).set_index("Tool"),
            use_container_width=True,
        )
    else:
        st.info("No session data for this date range.")

    # ── Multi-tool trend ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("Trend Over Time")
    metric_pill = st.pills(
        "", ["Active Minutes", "Sessions"], default="Active Minutes",
        key="tools_all_metric_pill", label_visibility="collapsed",
    ) or "Active Minutes"

    if not daily.empty:
        val_col = "active_minutes" if metric_pill == "Active Minutes" else "session_count"
        fig = go.Figure()
        for tool in TOOL_ORDER:
            tool_data = daily[daily["tool"] == tool].copy()
            if not tool_data.empty:
                fig.add_trace(go.Scatter(
                    x=tool_data["date"],
                    y=tool_data[val_col],
                    name=tool_name(tool, config),
                    mode="lines+markers",
                    line=dict(color=tool_color(tool, config), width=2),
                ))
        fig.update_layout(
            xaxis_title="Date",
            yaxis_title=metric_pill,
            legend_title="Tool",
            height=320,
            margin=dict(t=4, b=4),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No daily metrics for this date range.")

    # ── Session Duration Distribution ─────────────────────────────────────────
    st.divider()
    st.subheader("Session Duration Distribution")
    if not sessions.empty:
        fig = px.histogram(
            sessions[sessions["active_minutes"] > 0],
            x="active_minutes",
            color="tool",
            color_discrete_map={t: tool_color(t, config) for t in TOOL_ORDER},
            nbins=40,
            labels={"active_minutes": "Duration (minutes)", "count": "Sessions"},
            barmode="overlay",
            opacity=0.75,
        )
        fig.update_layout(height=320, legend_title="Tool", margin=dict(t=4, b=4))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No session data for this date range.")
