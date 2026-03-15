"""dashboard/views/claude_code.py — Claude Code deep-dive page."""

from datetime import date as _date

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data import (
    _fill_gaps,
    _get_period_range,
    load_claude_metrics,
    load_raw_events,
    load_sessions,
    tool_color,
)


def page_claude_code(config: dict) -> None:
    st.title("Claude Code")

    PERIODS      = ["Today", "Week", "Month", "Year"]
    BLOCK_LABELS = ["12AM–6AM", "6AM–12PM", "12PM–6PM", "6PM–12AM"]
    cc_color     = tool_color("claude_code", config)

    # ── State init ─────────────────────────────────────────────────────────────
    if "m_period" not in st.session_state:
        st.session_state["m_period"] = "Week"
    for _k in ("m_offset_prompts", "m_offset_tokens", "m_offset_edits"):
        if _k not in st.session_state:
            st.session_state[_k] = 0
    if "m_date_from" not in st.session_state:
        s, u, *_ = _get_period_range("Week", 0)
        st.session_state["m_date_from"] = _date.fromisoformat(s)
        st.session_state["m_date_to"]   = _date.fromisoformat(u)

    if st.session_state.pop("m_nav_triggered", False):
        s, u, *_ = _get_period_range(st.session_state["m_period"], 0)
        st.session_state["m_date_from"] = _date.fromisoformat(s)
        st.session_state["m_date_to"]   = _date.fromisoformat(u)

    # ── Period pills ───────────────────────────────────────────────────────────
    def _on_period_change():
        st.session_state["m_offset_prompts"] = 0
        st.session_state["m_offset_tokens"]  = 0
        st.session_state["m_offset_edits"]   = 0
        st.session_state["m_nav_triggered"]  = True

    period = st.pills(
        "", PERIODS, default="Week", key="m_period",
        on_change=_on_period_change, label_visibility="collapsed",
    ) or "Week"

    base_since_str, base_until_str, _, granularity, _ = _get_period_range(period, 0)
    base_since = _date.fromisoformat(base_since_str)
    base_until = _date.fromisoformat(base_until_str)

    from zoneinfo import ZoneInfo
    from datetime import datetime
    _LA_TZ = ZoneInfo("America/Los_Angeles")
    _today_pst = datetime.now(_LA_TZ).date()

    _dc1, _dc2 = st.columns(2)
    with _dc1:
        picker_since = st.date_input("From", key="m_date_from", max_value=_today_pst)
    with _dc2:
        picker_until = st.date_input("To",   key="m_date_to",   max_value=_today_pst)
    if picker_since > picker_until:
        picker_until = picker_since

    _all_zero = all(
        st.session_state[_k] == 0
        for _k in ("m_offset_prompts", "m_offset_tokens", "m_offset_edits")
    )
    custom_mode  = _all_zero and (picker_since != base_since or picker_until != base_until)
    custom_since = str(picker_since)
    custom_until = str(picker_until)

    # ── x-axis formatting helper ───────────────────────────────────────────────
    def _fmt_x(df_, col_):
        if granularity == "6h":
            df_[col_] = df_[col_].astype(int).map(lambda i: BLOCK_LABELS[i])
        elif granularity == "hour":
            df_[col_] = df_[col_].astype(int)
        elif granularity == "month":
            df_[col_] = df_[col_].astype(str)
            import pandas as pd
            df_[col_] = pd.to_datetime(df_[col_] + "-01").dt.strftime("%b %Y")

    x_label = {"6h": "Time Block", "hour": "Hour", "month": "Month"}.get(granularity, "Date")

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

    # ── KPIs ──────────────────────────────────────────────────────────────────
    kpi_since = custom_since if custom_mode else base_since_str
    kpi_until = custom_until if custom_mode else base_until_str
    kpi_data  = load_claude_metrics(kpi_since, kpi_until, granularity)
    kpi_col   = kpi_data["col"]
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

    # ── Prompts chart ─────────────────────────────────────────────────────────
    st.subheader("Prompts")
    if custom_mode:
        chart_nav("prompts", "m_offset_prompts")
        p_since, p_until = custom_since, custom_until
    else:
        p_since, p_until, _, _ = chart_nav("prompts", "m_offset_prompts")
    p_data    = load_claude_metrics(p_since, p_until, granularity)
    p_col     = p_data["col"]
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

    # ── Tokens chart ───────────────────────────────────────────────────────────
    st.subheader("Tokens")
    if custom_mode:
        chart_nav("tokens", "m_offset_tokens")
        t_since, t_until = custom_since, custom_until
    else:
        t_since, t_until, _, _ = chart_nav("tokens", "m_offset_tokens")
    t_data   = load_claude_metrics(t_since, t_until, granularity)
    t_col    = t_data["col"]
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

    # ── Edits Accepted chart ───────────────────────────────────────────────────
    st.subheader("Edits Accepted")
    if custom_mode:
        chart_nav("edits", "m_offset_edits")
        e_since, e_until = custom_since, custom_until
    else:
        e_since, e_until, _, _ = chart_nav("edits", "m_offset_edits")
    e_data   = load_claude_metrics(e_since, e_until, granularity)
    e_col    = e_data["col"]
    edits_df  = _fill_gaps(e_data["edits"], e_col, granularity, e_since, e_until)
    if "edits_accepted" not in edits_df.columns:
        edits_df["edits_accepted"] = 0
    _fmt_x(edits_df, e_col)
    fig = px.bar(edits_df, x=e_col, y="edits_accepted",
                 labels={e_col: x_label, "edits_accepted": "Edits"},
                 color_discrete_sequence=[cc_color])
    fig.update_layout(height=240, margin=dict(t=4, b=4))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Tool Call Breakdown ────────────────────────────────────────────────────
    st.subheader("Tool Call Breakdown")
    raw = load_raw_events(30)
    if not raw.empty:
        cc_tools = raw[
            (raw["tool"] == "claude_code") &
            (raw["event_type"] == "tool_call") &
            raw["tool_name"].notna()
        ]
        if not cc_tools.empty:
            tc_counts = cc_tools["tool_name"].value_counts().reset_index()
            tc_counts.columns = ["Tool Name", "Count"]
            fig = px.bar(
                tc_counts, x="Tool Name", y="Count",
                color_discrete_sequence=[cc_color],
            )
            fig.update_layout(height=300, margin=dict(t=4, b=4))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No tool call data yet.")
    else:
        st.info("No raw event data yet.")

    st.divider()

    # ── Top Repos ──────────────────────────────────────────────────────────────
    st.subheader("Top Repos by AI Time")
    sessions = load_sessions(30)
    cc_sessions = sessions[sessions["tool"] == "claude_code"] if not sessions.empty else sessions
    repo_time = (
        cc_sessions[cc_sessions["repo"].notna()]
        .groupby("repo")["active_minutes"]
        .sum()
        .sort_values(ascending=False)
        .head(15)
        .reset_index()
    ) if not cc_sessions.empty else None

    if repo_time is not None and not repo_time.empty:
        fig = px.bar(
            repo_time,
            x="active_minutes", y="repo", orientation="h",
            labels={"active_minutes": "Minutes", "repo": "Repository"},
            color_discrete_sequence=[cc_color],
        )
        fig.update_layout(
            height=max(200, len(repo_time) * 30),
            yaxis={"categoryorder": "total ascending"},
            margin=dict(t=4, b=4),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No repo data yet. Repo context comes from Claude Code hook events.")

    st.divider()

    # ── Commit-after-AI ────────────────────────────────────────────────────────
    st.subheader("Commit-after-AI")
    if not raw.empty and not sessions.empty:
        commits       = raw[raw["event_type"] == "commit"]
        ai_correlated = commits[commits["session_id"].notna()]

        c1, c2, c3 = st.columns(3)
        c1.metric("AI Sessions (30d)",         len(sessions))
        c2.metric("Commits within 30min of AI", len(ai_correlated))
        rate = len(ai_correlated) / len(sessions) * 100 if len(sessions) > 0 else 0
        c3.metric("Commit-after-AI Rate",       f"{rate:.1f}%")

        if not commits.empty:
            import pandas as pd
            commit_daily  = commits.groupby(commits["timestamp"].dt.date).size().reset_index(name="commits")
            session_daily = sessions.groupby("date").size().reset_index(name="sessions")
            commit_daily["date"]  = pd.to_datetime(commit_daily["timestamp"])
            session_daily["date"] = pd.to_datetime(session_daily["date"])

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=session_daily["date"], y=session_daily["sessions"],
                name="AI Sessions", marker_color="#4A9EFF", opacity=0.7,
            ))
            fig.add_trace(go.Scatter(
                x=commit_daily["date"], y=commit_daily["commits"],
                name="Commits", mode="lines+markers",
                line=dict(color="#F4B400", width=2), yaxis="y2",
            ))
            fig.update_layout(
                yaxis=dict(title="AI Sessions"),
                yaxis2=dict(title="Commits", overlaying="y", side="right"),
                legend_title="Metric",
                height=320,
                margin=dict(t=4, b=4),
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data for commit-after-AI analysis.")
