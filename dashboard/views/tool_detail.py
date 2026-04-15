"""dashboard/views/tool_detail.py — Shared page layout for Cursor, ChatGPT, Gemini."""

from datetime import date as _date
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from data import (
    _fill_gaps,
    _get_period_range,
    load_sessions_range,
    load_tool_activity,
    load_tool_hourly,
    tool_color,
    tool_name,
)

_LA_TZ = ZoneInfo("America/Los_Angeles")
PERIODS = ["Today", "Week", "Month", "Year", "All Time"]
BLOCK_LABELS = ["12AM–6AM", "6AM–12PM", "12PM–6PM", "6PM–12AM"]


def _ctx_window(period, d_since, d_until, today_pst):
    """Return (load_since, load_until) — a padded window around the current period."""
    if period == "Today":
        return str(today_pst - timedelta(days=29)), str(today_pst)
    if period == "Week":
        return str(_date.fromisoformat(d_since) - timedelta(days=21)), str(today_pst)
    if period == "Month":
        return str(_date.fromisoformat(d_since) - timedelta(days=31)), str(today_pst)
    if period == "Year":
        yr = int(d_since[:4])
        return f"{yr-1}-01-01", f"{yr+1}-12-31"
    # All Time — no context needed
    return d_since, d_until


def _to_quarter(date_str: str) -> str:
    m = int(date_str[5:7])
    return f"Q{(m-1)//3 + 1} {date_str[:4]}"


def _quarter_sort_key(q: str) -> tuple:
    parts = q.split()
    return (int(parts[1]), int(parts[0][1]))


def _padded_range(d0: str, d1: str, granularity: str):
    """Add half-bar-width padding so edge bars aren't clipped."""
    pad = timedelta(days=15) if granularity == "month" else timedelta(days=1)
    return str(_date.fromisoformat(d0) - pad), str(_date.fromisoformat(d1) + pad)


def page_tool_detail(tool_id: str, config: dict) -> None:
    display = tool_name(tool_id, config)
    st.title(display)

    user_id = st.session_state["user"]["user_id"]

    st.info(
        "Prompt and token counts are only available for Claude Code. "
        f"{display} is tracked via window activity monitoring."
    )

    _today_pst = datetime.now(_LA_TZ).date()

    # ── State init ─────────────────────────────────────────────────────────────
    _pfx = f"{tool_id}_"
    if f"{_pfx}period" not in st.session_state:
        st.session_state[f"{_pfx}period"] = "Month"
    for _k in (f"{_pfx}offset_active", f"{_pfx}offset_sessions", f"{_pfx}offset_hourly"):
        if _k not in st.session_state:
            st.session_state[_k] = 0
    if f"{_pfx}date_from" not in st.session_state:
        s, u, *_ = _get_period_range("Month", 0)
        st.session_state[f"{_pfx}date_from"] = _date.fromisoformat(s)
        st.session_state[f"{_pfx}date_to"]   = _date.fromisoformat(u)

    if st.session_state.pop(f"{_pfx}nav_triggered", False):
        s, u, *_ = _get_period_range(st.session_state[f"{_pfx}period"], 0)
        st.session_state[f"{_pfx}date_from"] = _date.fromisoformat(s)
        st.session_state[f"{_pfx}date_to"]   = _date.fromisoformat(u)

    def _on_period_change():
        for k in (f"{_pfx}offset_active", f"{_pfx}offset_sessions", f"{_pfx}offset_hourly"):
            st.session_state[k] = 0
        st.session_state[f"{_pfx}nav_triggered"] = True

    # ── Period pills + date pickers ────────────────────────────────────────────
    period = st.pills(
        "Period", PERIODS, default="Month", key=f"{_pfx}period",
        on_change=_on_period_change, label_visibility="collapsed",
    ) or "Month"

    base_since_str, base_until_str, _, granularity, _ = _get_period_range(period, 0)
    base_since = _date.fromisoformat(base_since_str)
    base_until = _date.fromisoformat(base_until_str)

    for _k in (f"{_pfx}date_from", f"{_pfx}date_to"):
        if isinstance(st.session_state.get(_k), _date) and st.session_state[_k] > _today_pst:
            st.session_state[_k] = _today_pst

    _dc1, _dc2 = st.columns(2)
    with _dc1:
        picker_since = st.date_input("From", key=f"{_pfx}date_from", max_value=_today_pst)
    with _dc2:
        picker_until = st.date_input("To", key=f"{_pfx}date_to", max_value=_today_pst)

    _all_zero = all(
        st.session_state[k] == 0
        for k in (f"{_pfx}offset_active", f"{_pfx}offset_sessions", f"{_pfx}offset_hourly")
    )
    custom_mode = _all_zero and (picker_since != base_since or picker_until != base_until)
    custom_since, custom_until = str(picker_since), str(picker_until)

    _chart_cfg = {"scrollZoom": False, "displayModeBar": False}

    # ── x-axis formatting helper ───────────────────────────────────────────────
    def _fmt_x(df_, col_):
        if granularity == "6h":
            df_[col_] = df_[col_].astype(int).map(lambda i: BLOCK_LABELS[i])
        elif granularity == "hour":
            df_[col_] = df_[col_].astype(int)
        elif granularity == "month":
            # Keep as YYYY-MM-01 for Plotly date axis; tickformat handles display
            df_[col_] = df_[col_].astype(str)
            df_[col_] = pd.to_datetime(df_[col_] + "-01").dt.strftime("%Y-%m-01")
        else:  # day granularity
            df_[col_] = df_[col_].astype(str).str[:10]  # ensure "YYYY-MM-DD" only

    x_label = {"6h": "Time Block", "hour": "Hour", "month": "Month"}.get(granularity, "Date")

    # ── Tooltip x-axis format ─────────────────────────────────────────────────
    if period == "All Time":
        _hover_x = "%{x}"
    elif granularity == "month":
        _hover_x = "%{x|%B %Y}"
    elif granularity in ("6h", "hour"):
        _hover_x = "%{x}"
    else:
        _hover_x = "%{x|%b %d, %Y}"

    # ── Per-chart nav helper ───────────────────────────────────────────────────
    def chart_nav(chart_key, offset_key):
        if period == "All Time":
            all_since, all_until, *_ = _get_period_range("All Time", 0)
            return all_since, all_until
        offset = st.session_state[offset_key]
        c_since, c_until, c_label, _, c_at_latest = _get_period_range(period, offset)
        c1, c2, c3 = st.columns([1, 8, 1])
        with c1:
            if st.button("◀", key=f"{_pfx}prev_{chart_key}", use_container_width=True):
                st.session_state[offset_key] -= 1
                st.session_state[f"{_pfx}nav_triggered"] = True
                st.rerun()
        with c2:
            st.markdown(
                f"<p style='text-align:center;font-weight:600;font-size:0.95rem;"
                f"margin:0;padding-top:5px'>{c_label}</p>",
                unsafe_allow_html=True,
            )
        with c3:
            if st.button("▶", key=f"{_pfx}next_{chart_key}", use_container_width=True, disabled=c_at_latest):
                st.session_state[offset_key] += 1
                st.session_state[f"{_pfx}nav_triggered"] = True
                st.rerun()
        return c_since, c_until

    # ── KPI range ─────────────────────────────────────────────────────────────
    kpi_since = custom_since if custom_mode else base_since_str
    kpi_until = custom_until if custom_mode else base_until_str

    sessions = load_sessions_range(kpi_since, kpi_until, user_id)
    if not sessions.empty:
        sessions = sessions[sessions["tool"] == tool_id]

    k1, k2, k3, k4, k5 = st.columns(5, gap="medium")
    if not sessions.empty:
        k1.metric("Sessions",       f"{len(sessions):,}")
        k2.metric("Active Minutes", f"{sessions['active_minutes'].sum():.1f}")
        k3.metric("Active Days",    f"{sessions['date'].nunique()}")
        k4.metric("Avg Session",    f"{sessions['active_seconds'].mean()/60:.1f} min")
        last = sessions["start_time"].max()
        k5.metric("Last Used",      last.strftime("%Y-%m-%d") if pd.notna(last) else "—")
    else:
        for k in (k1, k2, k3, k4, k5):
            k.metric("—", "—")

    st.divider()

    # ── Active Minutes Over Time ───────────────────────────────────────────────
    st.subheader("Active Minutes Over Time")
    if custom_mode:
        chart_nav("active", f"{_pfx}offset_active")
        a_since, a_until = custom_since, custom_until
    else:
        a_since, a_until = chart_nav("active", f"{_pfx}offset_active")

    if custom_mode:
        a_load_since, a_load_until = a_since, a_until
    elif period == "All Time":
        a_load_since, a_load_until = a_since, a_until
    elif granularity == "6h":
        a_load_since, a_load_until = a_since, a_until
    else:
        a_load_since, a_load_until = _ctx_window(period, a_since, a_until, _today_pst)

    act_data = load_tool_activity(tool_id, a_load_since, a_load_until, granularity, user_id)
    act_col = act_data["col"]
    act_df = _fill_gaps(act_data["active"], act_col, granularity, a_load_since, a_load_until)
    if "active_minutes" not in act_df.columns:
        act_df["active_minutes"] = 0

    if period == "All Time" and granularity not in ("6h", "hour", "month"):
        act_df = act_df.copy()
        act_df[act_col] = act_df[act_col].apply(_to_quarter)
        act_df = act_df.groupby(act_col, as_index=False)["active_minutes"].sum()
        act_df = act_df.sort_values(act_col, key=lambda s: s.map(_quarter_sort_key))

    if period not in ("All Time",) and granularity not in ("6h", "hour"):
        _f_since = a_since[:7] if granularity == "month" else a_since
        _f_until = a_until[:7] if granularity == "month" else a_until
        act_df = act_df[(act_df[act_col] >= _f_since) & (act_df[act_col] <= _f_until)]

    _fmt_x(act_df, act_col)
    fig = px.bar(
        act_df, x=act_col, y="active_minutes",
        labels={act_col: x_label, "active_minutes": "Active Minutes"},
        color_discrete_sequence=[tool_color(tool_id, config)],
    )
    fig.update_traces(hovertemplate=f"{_hover_x}: %{{y:.1f}} min<extra></extra>")
    fig.update_layout(height=280, margin=dict(t=4, b=4), font=dict(size=14), dragmode="pan")
    if granularity == "month" and period != "All Time":
        _r0, _r1 = _padded_range(a_since, a_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %Y")
    elif period not in ("All Time",) and granularity not in ("6h", "hour"):
        _r0, _r1 = _padded_range(a_since, a_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %d")
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=_chart_cfg, width='stretch')

    # ── Sessions Over Time ────────────────────────────────────────────────────
    st.subheader("Sessions Over Time")
    if custom_mode:
        chart_nav("sessions", f"{_pfx}offset_sessions")
        ss_since, ss_until = custom_since, custom_until
    else:
        ss_since, ss_until = chart_nav("sessions", f"{_pfx}offset_sessions")

    if custom_mode:
        ss_load_since, ss_load_until = ss_since, ss_until
    elif period == "All Time":
        ss_load_since, ss_load_until = ss_since, ss_until
    elif granularity == "6h":
        ss_load_since, ss_load_until = ss_since, ss_until
    else:
        ss_load_since, ss_load_until = _ctx_window(period, ss_since, ss_until, _today_pst)

    sess_data = load_tool_activity(tool_id, ss_load_since, ss_load_until, granularity, user_id)
    sess_col = sess_data["col"]
    sess_df = _fill_gaps(sess_data["sessions"], sess_col, granularity, ss_load_since, ss_load_until)
    if "session_count" not in sess_df.columns:
        sess_df["session_count"] = 0

    if period == "All Time" and granularity not in ("6h", "hour", "month"):
        sess_df = sess_df.copy()
        sess_df[sess_col] = sess_df[sess_col].apply(_to_quarter)
        sess_df = sess_df.groupby(sess_col, as_index=False)["session_count"].sum()
        sess_df = sess_df.sort_values(sess_col, key=lambda s: s.map(_quarter_sort_key))

    if period not in ("All Time",) and granularity not in ("6h", "hour"):
        _f_since = ss_since[:7] if granularity == "month" else ss_since
        _f_until = ss_until[:7] if granularity == "month" else ss_until
        sess_df = sess_df[(sess_df[sess_col] >= _f_since) & (sess_df[sess_col] <= _f_until)]

    _fmt_x(sess_df, sess_col)
    fig = px.bar(
        sess_df, x=sess_col, y="session_count",
        labels={sess_col: x_label, "session_count": "Sessions"},
        color_discrete_sequence=[tool_color(tool_id, config)],
    )
    fig.update_traces(hovertemplate=f"{_hover_x}: %{{y:.0f}} sessions<extra></extra>")
    fig.update_layout(height=240, margin=dict(t=4, b=4), font=dict(size=14), dragmode="pan")
    if granularity == "month" and period != "All Time":
        _r0, _r1 = _padded_range(ss_since, ss_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %Y")
    elif period not in ("All Time",) and granularity not in ("6h", "hour"):
        _r0, _r1 = _padded_range(ss_since, ss_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %d")
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=_chart_cfg, width='stretch')

    # ── Usage by Hour of Day ──────────────────────────────────────────────────
    st.subheader("Usage by Hour of Day")
    hourly = load_tool_hourly(tool_id, kpi_since, kpi_until, user_id)
    if not hourly.empty:
        full_hours = pd.DataFrame({"hour": list(range(24))})
        hourly = full_hours.merge(hourly, on="hour", how="left").fillna(0)
        fig = px.bar(
            hourly, x="hour", y="active_minutes",
            labels={"hour": "Hour of Day (PST)", "active_minutes": "Active Minutes"},
            color_discrete_sequence=[tool_color(tool_id, config)],
        )
        fig.update_traces(hovertemplate="Hour %{x}: %{y:.1f} min<extra></extra>")
        fig.update_layout(height=240, margin=dict(t=4, b=4), font=dict(size=14))
        fig.update_yaxes(fixedrange=True)
        st.plotly_chart(fig, config=_chart_cfg, width='stretch')
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
        fig.update_traces(hovertemplate="Duration: %{x:.1f} min<br>Sessions: %{y}<extra></extra>")
        fig.update_layout(height=240, margin=dict(t=4, b=4), font=dict(size=14))
        fig.update_yaxes(fixedrange=True)
        st.plotly_chart(fig, config=_chart_cfg, width='stretch')

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
            width='stretch',
            hide_index=True,
        )
    else:
        st.info("No sessions in this date range.")
