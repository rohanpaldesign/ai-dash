"""dashboard/views/overview.py — Overview page."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data import (
    TOOL_ORDER,
    WEEKDAY_ORDER,
    load_daily_metrics_range,
    load_sessions_range,
    tool_color,
    tool_name,
)


def page_overview(config: dict) -> None:
    st.title("Overview")

    date_from = st.session_state.get("global_date_from")
    date_to   = st.session_state.get("global_date_to")
    since = str(date_from)
    until = str(date_to)

    sessions = load_sessions_range(since, until)
    daily    = load_daily_metrics_range(since, until)

    # ── KPI row ────────────────────────────────────────────────────────────────
    total_sessions = len(sessions)
    total_prompts  = (
        int(sessions[sessions["tool"] == "claude_code"]["prompt_count"].sum())
        if not sessions.empty else 0
    )
    active_days    = int(sessions["date"].nunique()) if not sessions.empty else 0
    avg_duration   = (sessions["active_seconds"].mean() / 60) if not sessions.empty else 0
    if not sessions.empty:
        tool_mins  = sessions.groupby("tool")["active_minutes"].sum()
        most_used  = tool_name(tool_mins.idxmax(), config) if not tool_mins.empty else "—"
    else:
        most_used = "—"

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Sessions",       f"{total_sessions:,}")
    k2.metric("Prompts (Claude)",      f"{total_prompts:,}")
    k3.metric("Active Days",           f"{active_days}")
    k4.metric("Avg Session Duration",  f"{avg_duration:.1f} min")
    k5.metric("Most Used Tool",        most_used)

    st.divider()

    # ── Daily Activity chart ───────────────────────────────────────────────────
    st.subheader("Daily Activity")
    metric_pill = st.pills(
        "", ["Active Minutes", "Sessions"], default="Active Minutes",
        key="overview_metric_pill", label_visibility="collapsed",
    ) or "Active Minutes"

    if not daily.empty:
        val_col = "active_minutes" if metric_pill == "Active Minutes" else "session_count"
        pivot = daily.pivot_table(
            index="date", columns="tool", values=val_col, aggfunc="sum"
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
            yaxis_title=metric_pill,
            legend_title="Tool",
            height=320,
            margin=dict(t=4, b=4),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No activity data for this date range.")

    # ── Tool Usage Share + Heatmap (side by side) ──────────────────────────────
    col_donut, col_heat = st.columns([1, 2])

    with col_donut:
        st.subheader("Tool Usage Share")
        if not daily.empty:
            share = daily.groupby("tool")["active_minutes"].sum().reset_index()
            share["tool_name"] = share["tool"].apply(lambda t: tool_name(t, config))
            fig = px.pie(
                share,
                values="active_minutes",
                names="tool_name",
                color="tool",
                color_discrete_map={t: tool_color(t, config) for t in TOOL_ORDER},
                hole=0.4,
            )
            fig.update_layout(height=300, showlegend=True, legend_title="Tool",
                              margin=dict(t=4, b=4))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data.")

    with col_heat:
        st.subheader("Usage Heatmap")
        tool_options = ["All Tools"] + [tool_name(t, config) for t in TOOL_ORDER]
        tool_name_to_id = {tool_name(t, config): t for t in TOOL_ORDER}
        selected = st.selectbox("Filter by tool", tool_options, key="overview_heat_tool")

        if not sessions.empty:
            df = sessions.copy()
            if selected != "All Tools":
                df = df[df["tool"] == tool_name_to_id[selected]]

            if not df.empty:
                df["weekday"] = pd.Categorical(df["weekday"], categories=WEEKDAY_ORDER, ordered=True)
                pivot_h = df.groupby(["weekday", "hour"])["active_minutes"].sum().reset_index()
                pivot_h = pivot_h.pivot(index="weekday", columns="hour", values="active_minutes").fillna(0)
                pivot_h = pivot_h.reindex(WEEKDAY_ORDER)
                for h in range(24):
                    if h not in pivot_h.columns:
                        pivot_h[h] = 0
                pivot_h = pivot_h[sorted(pivot_h.columns)]

                fig = px.imshow(
                    pivot_h,
                    labels={"x": "Hour", "y": "Day", "color": "Active Min"},
                    color_continuous_scale="Blues",
                    aspect="auto",
                )
                fig.update_xaxes(
                    tickvals=list(range(0, 24, 3)),
                    ticktext=[f"{h:02d}:00" for h in range(0, 24, 3)],
                )
                fig.update_layout(height=280, margin=dict(t=4, b=4))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info(f"No data for {selected}.")
        else:
            st.info("No session data for this date range.")

    # ── Recent Sessions ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Recent Sessions")
    if not sessions.empty:
        recent = sessions.sort_values("start_time", ascending=False).head(10).copy()
        recent["Date"]     = recent["start_time"].dt.strftime("%Y-%m-%d")
        recent["Start"]    = recent["start_time"].dt.strftime("%H:%M UTC")
        recent["Tool"]     = recent["tool"].apply(lambda t: tool_name(t, config))
        recent["Duration"] = recent["active_seconds"].apply(lambda s: f"{s/60:.1f} min")
        recent["Prompts"]  = recent.apply(
            lambda r: str(int(r["prompt_count"])) if r["tool"] == "claude_code" else "—", axis=1
        )
        recent["Repo"] = recent["repo"].fillna("—")
        st.dataframe(
            recent[["Date", "Start", "Tool", "Duration", "Prompts", "Repo"]].reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No sessions in this date range.")
