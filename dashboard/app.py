"""
dashboard/app.py — AI Usage Dashboard (Streamlit).

5 pages:
  1. Overview          — today's totals, 30-day trend
  2. Tool Breakdown    — per-tool metrics table + charts
  3. Session Analytics — duration distribution, deep work
  4. Time Heatmap      — hour × weekday activity heatmap
  5. Repos & Productivity — top repos, commit-after-AI rate
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml

from database.connection import query_df

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "subscriptions.yaml"

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


# ── Page 1: Overview ──────────────────────────────────────────────────────────

def page_overview(config: dict) -> None:
    st.title("AI Usage Overview")

    daily = load_daily_metrics(30)
    today_str = datetime.now().strftime("%Y-%m-%d")
    today = daily[daily["date"] == today_str] if not daily.empty else pd.DataFrame()

    # KPI row
    col1, col2, col3, col4 = st.columns(4)

    if not today.empty:
        total_min = today["active_minutes"].sum()
        total_sessions = today["session_count"].sum()
        total_prompts = today["prompt_count"].sum()
        total_tokens = today["estimated_tokens"].sum()
    else:
        total_min = total_sessions = total_prompts = total_tokens = 0

    col1.metric("Today's AI Time", f"{total_min:.0f} min")
    col2.metric("Sessions", f"{total_sessions:.0f}")
    col3.metric("Prompts (Claude)", f"{total_prompts:.0f}")
    col4.metric("Est. Tokens (Claude)", f"{total_tokens:,.0f}")

    st.divider()

    # Today's tool breakdown bar
    if not today.empty:
        st.subheader("Today's Time by Tool")
        today_chart = today.copy()
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


# ── Page 2: Tool Breakdown ────────────────────────────────────────────────────

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
                "Tool Breakdown",
                "Session Analytics",
                "Time Heatmap",
                "Repos & Productivity",
            ],
        )
        st.divider()
        if st.button("Refresh Data"):
            load_daily_metrics.clear()
            load_sessions.clear()
            load_raw_events.clear()
            st.rerun()
        st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

        # Debug: show backend + raw data
        try:
            from database.connection import _get_turso_creds
            url, _ = _get_turso_creds()
            backend = "Turso" if url else "SQLite (fallback!)"
            debug_df = query_df("SELECT date, tool, active_minutes FROM daily_metrics ORDER BY date DESC LIMIT 5")
            st.caption(f"Backend: {backend}")
            st.dataframe(debug_df, hide_index=True)
            last_event = query_df("SELECT MAX(timestamp) AS ts FROM raw_events").iloc[0]["ts"]
            st.caption(f"Last event: {last_event}")
        except Exception as e:
            st.caption(f"Debug error: {e}")

    if page == "Overview":
        page_overview(config)
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
