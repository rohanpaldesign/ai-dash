"""dashboard/views/overview.py — Overview page."""

from datetime import date as _date
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data import (
    TOOL_ORDER,
    WEEKDAY_ORDER,
    _fill_gaps,
    _get_period_range,
    load_daily_metrics_range,
    load_sessions_range,
    tool_color,
    tool_name,
)

_LA_TZ = ZoneInfo("America/Los_Angeles")
PERIODS = ["Today", "Week", "Month", "Year"]


def page_overview(config: dict) -> None:
    st.title("Overview")

    _today_pst = datetime.now(_LA_TZ).date()

    # ── State init ─────────────────────────────────────────────────────────────
    if "ov_period" not in st.session_state:
        st.session_state["ov_period"] = "Week"
    for _k in ("ov_offset_daily", "ov_offset_share", "ov_offset_heatmap", "ov_offset_trend"):
        if _k not in st.session_state:
            st.session_state[_k] = 0
    if "ov_date_from" not in st.session_state:
        s, u, *_ = _get_period_range("Week", 0)
        st.session_state["ov_date_from"] = _date.fromisoformat(s)
        st.session_state["ov_date_to"]   = _date.fromisoformat(u)

    if st.session_state.pop("ov_nav_triggered", False):
        s, u, *_ = _get_period_range(st.session_state["ov_period"], 0)
        st.session_state["ov_date_from"] = _date.fromisoformat(s)
        st.session_state["ov_date_to"]   = _date.fromisoformat(u)

    def _on_ov_period_change():
        for k in ("ov_offset_daily", "ov_offset_share", "ov_offset_heatmap", "ov_offset_trend"):
            st.session_state[k] = 0
        st.session_state["ov_nav_triggered"] = True

    # ── Period pills + date pickers ────────────────────────────────────────────
    period = st.pills(
        "", PERIODS, default="Week", key="ov_period",
        on_change=_on_ov_period_change, label_visibility="collapsed",
    ) or "Week"

    base_since_str, base_until_str, _, granularity, _ = _get_period_range(period, 0)
    base_since = _date.fromisoformat(base_since_str)
    base_until = _date.fromisoformat(base_until_str)

    _dc1, _dc2 = st.columns(2)
    with _dc1:
        picker_since = st.date_input("From", key="ov_date_from", max_value=_today_pst)
    with _dc2:
        picker_until = st.date_input("To", key="ov_date_to", max_value=_today_pst)

    _all_zero = all(st.session_state[k] == 0 for k in ("ov_offset_daily", "ov_offset_share", "ov_offset_heatmap", "ov_offset_trend"))
    custom_mode = _all_zero and (picker_since != base_since or picker_until != base_until)
    custom_since, custom_until = str(picker_since), str(picker_until)

    # ── Per-chart nav helper ───────────────────────────────────────────────────
    def chart_nav(chart_key, offset_key):
        offset = st.session_state[offset_key]
        c_since, c_until, c_label, _, c_at_latest = _get_period_range(period, offset)
        c1, c2, c3 = st.columns([1, 8, 1])
        with c1:
            if st.button("◀", key=f"ov_prev_{chart_key}", use_container_width=True):
                st.session_state[offset_key] -= 1
                st.session_state["ov_nav_triggered"] = True
                st.rerun()
        with c2:
            st.markdown(
                f"<p style='text-align:center;font-weight:600;font-size:0.95rem;"
                f"margin:0;padding-top:5px'>{c_label}</p>",
                unsafe_allow_html=True,
            )
        with c3:
            if st.button("▶", key=f"ov_next_{chart_key}", use_container_width=True, disabled=c_at_latest):
                st.session_state[offset_key] += 1
                st.session_state["ov_nav_triggered"] = True
                st.rerun()
        return c_since, c_until

    # ── KPI range (base period, no offset) ────────────────────────────────────
    kpi_since = custom_since if custom_mode else base_since_str
    kpi_until = custom_until if custom_mode else base_until_str

    sessions = load_sessions_range(kpi_since, kpi_until)

    total_sessions = len(sessions)
    total_prompts  = int(sessions["prompt_count"].sum()) if not sessions.empty else 0
    active_days    = int(sessions["date"].nunique()) if not sessions.empty else 0
    avg_duration   = (sessions["active_seconds"].mean() / 60) if not sessions.empty else 0
    if not sessions.empty:
        tool_mins = sessions.groupby("tool")["active_minutes"].sum()
        most_used = tool_name(tool_mins.idxmax(), config) if not tool_mins.empty else "—"
    else:
        most_used = "—"

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Sessions",      f"{total_sessions:,}")
    k2.metric("Prompts",             f"{total_prompts:,}")
    k3.metric("Active Days",         f"{active_days}")
    k4.metric("Avg Session Duration", f"{avg_duration:.1f} min")
    k5.metric("Most Used Tool",      most_used)

    st.divider()

    # ── Daily Activity charts (side by side) ──────────────────────────────────
    st.subheader("Daily Activity")

    if custom_mode:
        chart_nav("daily", "ov_offset_daily")
        d_since, d_until = custom_since, custom_until
    else:
        d_since, d_until = chart_nav("daily", "ov_offset_daily")

    daily = load_daily_metrics_range(d_since, d_until)
    full_dates = pd.date_range(d_since, d_until, freq="D").strftime("%Y-%m-%d").tolist()

    if not daily.empty:
        pivot_min = daily.pivot_table(
            index="date", columns="tool", values="active_minutes", aggfunc="sum"
        ).fillna(0)
        pivot_min = pivot_min.reindex(full_dates, fill_value=0).reset_index()
        pivot_min = pivot_min.rename(columns={"index": "date"})
        pivot_min.columns.name = None

        pivot_sess = daily.pivot_table(
            index="date", columns="tool", values="session_count", aggfunc="sum"
        ).fillna(0)
        pivot_sess = pivot_sess.reindex(full_dates, fill_value=0).reset_index()
        pivot_sess = pivot_sess.rename(columns={"index": "date"})
        pivot_sess.columns.name = None
    else:
        pivot_min = pd.DataFrame({"date": full_dates})
        pivot_sess = pd.DataFrame({"date": full_dates})
        for t in TOOL_ORDER:
            pivot_min[t] = 0.0
            pivot_sess[t] = 0.0

    col_min, col_sess = st.columns([1, 1])

    with col_min:
        st.markdown("**Active Minutes**")
        fig = go.Figure()
        for tool in TOOL_ORDER:
            if tool in pivot_min.columns:
                vals = pivot_min[tool]
                fig.add_trace(go.Bar(
                    name=tool_name(tool, config),
                    x=pivot_min["date"],
                    y=vals,
                    marker_color=tool_color(tool, config),
                    text=vals.apply(lambda v: f"{v:.1f}" if v > 0 else ""),
                    textposition="inside",
                    insidetextanchor="middle",
                    textfont=dict(size=10),
                    hovertemplate="%{y:.1f} min<extra></extra>",
                ))
        fig.update_layout(
            barmode="stack", xaxis_title="Date", yaxis_title="Active Minutes",
            legend_title="Tool", height=320, margin=dict(t=4, b=4), showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_sess:
        st.markdown("**Sessions**")
        fig = go.Figure()
        for tool in TOOL_ORDER:
            if tool in pivot_sess.columns:
                vals = pivot_sess[tool]
                fig.add_trace(go.Bar(
                    name=tool_name(tool, config),
                    x=pivot_sess["date"],
                    y=vals,
                    marker_color=tool_color(tool, config),
                    text=vals.apply(lambda v: f"{int(v)}" if v > 0 else ""),
                    textposition="inside",
                    insidetextanchor="middle",
                    textfont=dict(size=10),
                    hovertemplate="%{y}<extra></extra>",
                ))
        fig.update_layout(
            barmode="stack", xaxis_title="Date", yaxis_title="Sessions",
            legend_title="Tool", height=320, margin=dict(t=4, b=4), showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Tool Comparison table ──────────────────────────────────────────────────
    st.divider()
    st.subheader("Tool Comparison")
    if not sessions.empty:
        agg = sessions.groupby("tool").agg(
            sessions=("session_id", "count"),
            active_min=("active_minutes", "sum"),
            active_days=("date", "nunique"),
            avg_session=("active_seconds", "mean"),
        ).reset_index()

        cc_prompts = (
            sessions[sessions["tool"] == "claude_code"]["prompt_count"].sum()
            if not sessions.empty else 0
        )

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

    # ── Trend Over Time ────────────────────────────────────────────────────────
    st.subheader("Trend Over Time")
    metric_pill = st.pills(
        "", ["Active Minutes", "Sessions"], default="Active Minutes",
        key="ov_trend_metric", label_visibility="collapsed",
    ) or "Active Minutes"

    if custom_mode:
        chart_nav("trend", "ov_offset_trend")
        t_since, t_until = custom_since, custom_until
    else:
        t_since, t_until = chart_nav("trend", "ov_offset_trend")

    trend_daily = load_daily_metrics_range(t_since, t_until)
    val_col = "active_minutes" if metric_pill == "Active Minutes" else "session_count"
    fig = go.Figure()
    for tool in TOOL_ORDER:
        tool_data = trend_daily[trend_daily["tool"] == tool]
        if not tool_data.empty:
            fig.add_trace(go.Scatter(
                x=tool_data["date"], y=tool_data[val_col],
                name=tool_name(tool, config),
                mode="lines+markers",
                line=dict(color=tool_color(tool, config), width=2),
            ))
    fig.update_layout(xaxis_title="Date", yaxis_title=metric_pill,
                      legend_title="Tool", height=320, margin=dict(t=4, b=4))
    st.plotly_chart(fig, use_container_width=True)

    # ── Tool Usage Share ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("Tool Usage Share")
    _sc1, _sc2 = st.columns([2, 3])

    if custom_mode:
        chart_nav("share", "ov_offset_share")
        s_since, s_until = custom_since, custom_until
    else:
        s_since, s_until = chart_nav("share", "ov_offset_share")

    share_daily = load_daily_metrics_range(s_since, s_until)
    with _sc1:
        if not share_daily.empty:
            share = share_daily.groupby("tool")["active_minutes"].sum().reset_index()
            share = share[share["active_minutes"] > 0]
            share["tool_name"] = share["tool"].apply(lambda t: tool_name(t, config))
            if not share.empty:
                fig = px.pie(
                    share,
                    values="active_minutes",
                    names="tool_name",
                    color="tool",
                    color_discrete_map={t: tool_color(t, config) for t in TOOL_ORDER},
                    hole=0.4,
                )
                fig.update_traces(
                    textinfo="label+percent",
                    texttemplate="%{label}<br>%{percent:.0%}",
                    textposition="inside",
                    hovertemplate="%{label}: %{value:.1f} min (%{percent})<extra></extra>",
                )
                fig.update_layout(height=300, showlegend=True, legend_title="Tool",
                                  margin=dict(t=4, b=4))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data.")
        else:
            st.info("No data.")

    # ── Usage Heatmap ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Usage Heatmap")
    tool_options = ["All"] + [tool_name(t, config) for t in TOOL_ORDER]
    tool_name_to_id = {tool_name(t, config): t for t in TOOL_ORDER}
    selected = st.pills("", tool_options, default="All",
                        key="overview_heat_tool", label_visibility="collapsed") or "All"

    if custom_mode:
        chart_nav("heatmap", "ov_offset_heatmap")
        h_since, h_until = custom_since, custom_until
    else:
        h_since, h_until = chart_nav("heatmap", "ov_offset_heatmap")

    heat_sessions = load_sessions_range(h_since, h_until)
    if not heat_sessions.empty:
        df = heat_sessions.copy()
        if selected != "All":
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
                text_auto=".1f",
            )
            fig.update_traces(hovertemplate="Day: %{y}<br>Hour: %{x}<br>%{z:.1f} min<extra></extra>")
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
    tool_filter_opts = ["All"] + [tool_name(t, config) for t in TOOL_ORDER]
    rs_filter = st.pills("", tool_filter_opts, default="All",
                         key="ov_rs_tool_filter", label_visibility="collapsed") or "All"

    if not sessions.empty:
        recent = sessions.copy()
        if rs_filter != "All":
            tool_id = {tool_name(t, config): t for t in TOOL_ORDER}[rs_filter]
            recent = recent[recent["tool"] == tool_id]
        recent = recent.sort_values("start_time", ascending=False).head(10).copy()
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
