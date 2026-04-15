"""dashboard/views/overview.py — Overview page."""

from datetime import date as _date
from datetime import datetime, timedelta
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
PERIODS = ["Today", "Week", "Month", "Year", "All Time"]


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


def _expand_sessions_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Expand each session into per-hour rows, distributing active_minutes proportionally."""
    if df.empty:
        return pd.DataFrame(columns=["date", "weekday", "hour", "active_minutes"])
    rows = []
    for _, sess in df.iterrows():
        start = sess["start_time"]
        active_secs = float(sess["active_seconds"] or 0)
        if pd.isna(start) or active_secs <= 0:
            continue
        end = start + pd.Timedelta(seconds=active_secs)
        db_end = sess.get("end_time")
        if pd.notna(db_end) and db_end > start:
            end = db_end
        start_pst = start.astimezone(_LA_TZ)
        end_pst = end.astimezone(_LA_TZ)
        slot = start_pst.replace(minute=0, second=0, microsecond=0)
        while slot < end_pst:
            slot_end = slot + pd.Timedelta(hours=1)
            overlap_min = (min(end_pst, slot_end) - max(start_pst, slot)).total_seconds() / 60
            if overlap_min > 0:
                rows.append({
                    "date":           slot.date(),
                    "weekday":        slot.strftime("%A"),
                    "hour":           slot.hour,
                    "active_minutes": overlap_min,
                })
            slot = slot_end
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["date", "weekday", "hour", "active_minutes"]
    )


def page_overview(config: dict) -> None:
    st.title("Overview")

    user_id = st.session_state["user"]["user_id"]
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
        "Period", PERIODS, default="Week", key="ov_period",
        on_change=_on_ov_period_change, label_visibility="collapsed",
    ) or "Week"

    base_since_str, base_until_str, _, granularity, _ = _get_period_range(period, 0)
    base_since = _date.fromisoformat(base_since_str)
    base_until = _date.fromisoformat(base_until_str)

    _dc1, _dc2 = st.columns(2)
    with _dc1:
        picker_since = st.date_input("From", key="ov_date_from")
    with _dc2:
        picker_until = st.date_input("To", key="ov_date_to")

    _all_zero = all(st.session_state[k] == 0 for k in ("ov_offset_daily", "ov_offset_share", "ov_offset_heatmap", "ov_offset_trend"))
    custom_mode = _all_zero and (picker_since != base_since or picker_until != base_until)
    custom_since, custom_until = str(picker_since), str(picker_until)

    _chart_cfg = {"scrollZoom": False, "displayModeBar": False}

    # ── Per-chart nav helper ───────────────────────────────────────────────────
    def chart_nav(chart_key, offset_key):
        if period == "All Time":
            all_since, all_until, *_ = _get_period_range("All Time", 0)
            return all_since, all_until
        offset = st.session_state[offset_key]
        c_since, c_until, c_label, _, c_at_latest = _get_period_range(period, offset)
        c1, c2, c3 = st.columns([1, 8, 1])
        with c1:
            if st.button("◀", key=f"ov_prev_{chart_key}", use_container_width=True):
                st.session_state[offset_key] -= 1
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
                st.rerun()
        return c_since, c_until

    # ── KPI range (base period, no offset, capped at today) ───────────────────
    kpi_since = custom_since if custom_mode else base_since_str
    kpi_until = custom_until if custom_mode else str(min(base_until, _today_pst))

    sessions = load_sessions_range(kpi_since, kpi_until, user_id)

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

    if custom_mode:
        d_load_since, d_load_until = d_since, str(min(_date.fromisoformat(d_until), _today_pst))
    elif period == "All Time":
        d_load_since, d_load_until = d_since, d_until
    else:
        d_load_since, d_load_until = _ctx_window(period, d_since, d_until, _today_pst)
    daily = load_daily_metrics_range(d_load_since, d_load_until, user_id)

    # Tooltip x-axis format
    if period == "All Time":
        _hover_x_daily = "%{x}"
    elif granularity == "month":
        _hover_x_daily = "%{x|%B %Y}"
    else:
        _hover_x_daily = "%{x|%b %d, %Y}"

    # For Year use monthly buckets; for All Time use quarterly buckets
    if period == "All Time":
        if not daily.empty:
            daily = daily.copy()
            daily["date"] = daily["date"].apply(_to_quarter)
            daily = daily.groupby(["date", "tool"], as_index=False)[
                ["session_count", "estimated_tokens", "prompt_count", "active_minutes"]
            ].sum()
        all_quarters = sorted(daily["date"].unique().tolist(), key=_quarter_sort_key) if not daily.empty else []
        full_dates = all_quarters
    elif granularity == "month":
        daily_dates_raw = [f"{str(p)}-01" for p in pd.period_range(d_since, d_until, freq="M")]
        full_dates = daily_dates_raw
        if not daily.empty:
            daily = daily.copy()
            daily["date"] = daily["date"].str[:7] + "-01"  # "YYYY-MM-DD" → "YYYY-MM-01"
            daily = daily.groupby(["date", "tool"], as_index=False)[
                ["session_count", "estimated_tokens", "prompt_count", "active_minutes"]
            ].sum()
    else:
        full_dates = pd.date_range(d_since, d_until, freq="D").strftime("%Y-%m-%d").tolist()

    if not daily.empty:
        pivot_sess = daily.pivot_table(
            index="date", columns="tool", values="session_count", aggfunc="sum"
        ).fillna(0)
        pivot_sess = pivot_sess.reindex(full_dates, fill_value=0).reset_index()
        pivot_sess = pivot_sess.rename(columns={"index": "date"})
        pivot_sess.columns.name = None

        pivot_tok = daily.pivot_table(
            index="date", columns="tool", values="estimated_tokens", aggfunc="sum"
        ).fillna(0).reindex(full_dates, fill_value=0).reset_index().rename(columns={"index": "date"})
        pivot_tok.columns.name = None

        pivot_prom = daily.pivot_table(
            index="date", columns="tool", values="prompt_count", aggfunc="sum"
        ).fillna(0).reindex(full_dates, fill_value=0).reset_index().rename(columns={"index": "date"})
        pivot_prom.columns.name = None
    else:
        pivot_sess = pd.DataFrame({"date": full_dates})
        pivot_tok = pd.DataFrame({"date": full_dates})
        pivot_prom = pd.DataFrame({"date": full_dates})
        for t in TOOL_ORDER:
            pivot_sess[t] = 0.0
            pivot_tok[t] = 0.0
            pivot_prom[t] = 0.0

    st.markdown("**Total Tokens**")
    fig = go.Figure()
    for tool in TOOL_ORDER:
        if tool in pivot_tok.columns:
            vals = pivot_tok[tool]
            fig.add_trace(go.Bar(
                name=tool_name(tool, config),
                x=pivot_tok["date"],
                y=vals,
                marker_color=tool_color(tool, config),
                text=vals.apply(lambda v: f"{v:,.0f}" if v > 0 else ""),
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(size=12),
                hovertemplate=f"{_hover_x_daily}: %{{y:,.0f}} tokens<extra></extra>",
            ))
    fig.update_layout(
        barmode="stack", xaxis_title="Date", yaxis_title="Estimated Tokens",
        legend_title="Tool", height=320, margin=dict(t=4, b=4), showlegend=True,
        font=dict(size=14), dragmode="pan",
    )
    if granularity == "month" and period != "All Time":
        _r0, _r1 = _padded_range(d_since, d_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %Y")
    elif period not in ("All Time",):
        _r0, _r1 = _padded_range(d_since, d_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %d")
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=_chart_cfg, width='stretch')

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
                textfont=dict(size=12),
                hovertemplate=f"{_hover_x_daily}: %{{y:,.0f}} sessions<extra></extra>",
            ))
    fig.update_layout(
        barmode="stack", xaxis_title="Date", yaxis_title="Sessions",
        legend_title="Tool", height=320, margin=dict(t=4, b=4), showlegend=True,
        font=dict(size=14), dragmode="pan",
    )
    if granularity == "month" and period != "All Time":
        _r0, _r1 = _padded_range(d_since, d_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %Y")
    elif period not in ("All Time",):
        _r0, _r1 = _padded_range(d_since, d_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %d")
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=_chart_cfg, width='stretch')

    st.markdown("**Prompts (Claude Code)**")
    fig = go.Figure()
    if "claude_code" in pivot_prom.columns:
        vals = pivot_prom["claude_code"]
        fig.add_trace(go.Bar(
            name=tool_name("claude_code", config),
            x=pivot_prom["date"],
            y=vals,
            marker_color=tool_color("claude_code", config),
            text=vals.apply(lambda v: f"{int(v)}" if v > 0 else ""),
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(size=12),
            hovertemplate=f"{_hover_x_daily}: %{{y:,.0f}} prompts<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack", xaxis_title="Date", yaxis_title="Prompts",
        legend_title="Tool", height=320, margin=dict(t=4, b=4), showlegend=True,
        font=dict(size=14), dragmode="pan",
    )
    if granularity == "month" and period != "All Time":
        _r0, _r1 = _padded_range(d_since, d_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %Y")
    elif period not in ("All Time",):
        _r0, _r1 = _padded_range(d_since, d_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %d")
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=_chart_cfg, width='stretch')

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
            width='stretch',
        )
    else:
        st.info("No session data for this date range.")

    # ── Trend Over Time ────────────────────────────────────────────────────────
    st.subheader("Trend Over Time")
    metric_pill = st.pills(
        "Metric", ["Active Minutes", "Sessions"], default="Active Minutes",
        key="ov_trend_metric", label_visibility="collapsed",
    ) or "Active Minutes"

    if custom_mode:
        chart_nav("trend", "ov_offset_trend")
        t_since, t_until = custom_since, custom_until
    else:
        t_since, t_until = chart_nav("trend", "ov_offset_trend")

    if custom_mode:
        t_load_since, t_load_until = t_since, str(min(_date.fromisoformat(t_until), _today_pst))
    elif period == "All Time":
        t_load_since, t_load_until = t_since, t_until
    else:
        t_load_since, t_load_until = _ctx_window(period, t_since, t_until, _today_pst)
    trend_daily = load_daily_metrics_range(t_load_since, t_load_until, user_id)

    # Tooltip x-axis format for trend
    if period == "All Time":
        _hover_x_trend = "%{x}"
    elif granularity == "month":
        _hover_x_trend = "%{x|%B %Y}"
    else:
        _hover_x_trend = "%{x|%b %d, %Y}"

    if period == "All Time":
        if not trend_daily.empty:
            trend_daily = trend_daily.copy()
            trend_daily["date"] = trend_daily["date"].apply(_to_quarter)
            trend_daily = trend_daily.groupby(["date", "tool"], as_index=False)[
                ["active_minutes", "session_count"]
            ].sum()
    elif granularity == "month" and not trend_daily.empty:
        trend_daily = trend_daily.copy()
        trend_daily["date"] = trend_daily["date"].str[:7] + "-01"
        trend_daily = trend_daily.groupby(["date", "tool"], as_index=False)[
            ["active_minutes", "session_count"]
        ].sum()

    if period not in ("All Time",) and not trend_daily.empty:
        _tf_since = t_since[:7] + "-01" if granularity == "month" else t_since
        _tf_until = t_until[:7] + "-01" if granularity == "month" else t_until
        trend_daily = trend_daily[(trend_daily["date"] >= _tf_since) & (trend_daily["date"] <= _tf_until)]

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
                hovertemplate=f"{_hover_x_trend}: %{{y:,.0f}}<extra></extra>",
            ))
    fig.update_layout(xaxis_title="Date", yaxis_title=metric_pill,
                      legend_title="Tool", height=320, margin=dict(t=4, b=4),
                      font=dict(size=14), dragmode="pan")
    if granularity == "month" and period != "All Time":
        _r0, _r1 = _padded_range(t_since, t_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %Y")
    elif period not in ("All Time",):
        _r0, _r1 = _padded_range(t_since, t_until, granularity)
        fig.update_xaxes(range=[_r0, _r1], tickformat="%b %d")
    fig.update_yaxes(fixedrange=True)
    st.plotly_chart(fig, config=_chart_cfg, width='stretch')

    # ── Tool Usage Share ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("Tool Usage Share")
    if custom_mode:
        chart_nav("share", "ov_offset_share")
        s_since, s_until = custom_since, custom_until
    else:
        s_since, s_until = chart_nav("share", "ov_offset_share")

    if custom_mode:
        s_load_since, s_load_until = s_since, str(min(_date.fromisoformat(s_until), _today_pst))
    elif period == "All Time":
        s_load_since, s_load_until = s_since, s_until
    else:
        s_load_since, s_load_until = _ctx_window(period, s_since, s_until, _today_pst)
    share_daily = load_daily_metrics_range(s_load_since, s_load_until, user_id)
    if not share_daily.empty:
        if custom_mode or period not in ("All Time",):
            share_filtered = share_daily[
                (share_daily["date"] >= s_since) & (share_daily["date"] <= s_until)
            ]
        else:
            share_filtered = share_daily
        share = share_filtered.groupby("tool")["active_minutes"].sum().reset_index()
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
                              margin=dict(t=4, b=4), font=dict(size=14))
            fig.update_yaxes(fixedrange=True)
            st.plotly_chart(fig, config=_chart_cfg, width='stretch')
        else:
            st.info("No data.")
    else:
        st.info("No data.")

    # ── Usage Heatmap ──────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Usage Heatmap")
    tool_options = ["All"] + [tool_name(t, config) for t in TOOL_ORDER]
    tool_name_to_id = {tool_name(t, config): t for t in TOOL_ORDER}
    selected = st.pills("Tool filter", tool_options, default="All",
                        key="overview_heat_tool", label_visibility="collapsed") or "All"

    if custom_mode:
        chart_nav("heatmap", "ov_offset_heatmap")
        h_since, h_until = custom_since, custom_until
    else:
        h_since, h_until = chart_nav("heatmap", "ov_offset_heatmap")

    if custom_mode:
        h_load_since, h_load_until = h_since, str(min(_date.fromisoformat(h_until), _today_pst))
    elif period == "All Time":
        h_load_since, h_load_until = h_since, h_until
    else:
        h_load_since, h_load_until = _ctx_window(period, h_since, h_until, _today_pst)
    heat_sessions = load_sessions_range(h_load_since, h_load_until, user_id)
    if not heat_sessions.empty:
        df = heat_sessions.copy()
        if not custom_mode and period not in ("All Time",):
            df = df[(df["date"] >= _date.fromisoformat(h_since)) & (df["date"] <= _date.fromisoformat(h_until))]
        if selected != "All":
            df = df[df["tool"] == tool_name_to_id[selected]]

        if not df.empty:
            hourly = _expand_sessions_hourly(df)
            if hourly.empty:
                st.info(f"No data for {selected}.")
            else:
                hourly["weekday"] = pd.Categorical(hourly["weekday"], categories=WEEKDAY_ORDER, ordered=True)
                per_day = hourly.groupby(["date", "weekday", "hour"], observed=True)["active_minutes"].sum().reset_index()
                per_day["active_minutes"] = per_day["active_minutes"].clip(upper=60)
                pivot_h = per_day.groupby(["weekday", "hour"], observed=True)["active_minutes"].sum().reset_index()
                pivot_h = pivot_h.pivot_table(index="weekday", columns="hour", values="active_minutes", aggfunc="sum", fill_value=0)
                pivot_h = pivot_h.reindex(WEEKDAY_ORDER).fillna(0)
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
                fig.update_layout(height=280, margin=dict(t=4, b=4), font=dict(size=14))
                fig.update_yaxes(fixedrange=True)
                st.plotly_chart(fig, config=_chart_cfg, width='stretch')
        else:
            st.info(f"No data for {selected}.")
    else:
        st.info("No session data for this date range.")

    # ── Recent Sessions ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Recent Sessions")
    tool_filter_opts = ["All"] + [tool_name(t, config) for t in TOOL_ORDER]
    rs_filter = st.pills("Tool filter", tool_filter_opts, default="All",
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
            width='stretch',
            hide_index=True,
        )
    else:
        st.info("No sessions in this date range.")
