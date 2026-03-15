"""
dashboard/app.py — AI Usage Dashboard entrypoint.

Navigation:
  Overview
  ── Tools ──
    All Tools
    Claude Code
    Cursor
    ChatGPT
    Gemini
  Sessions
  Insights
  Settings
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from data import (
    load_claude_metrics,
    load_config,
    load_daily_metrics,
    load_daily_metrics_range,
    load_db_stats,
    load_raw_events,
    load_raw_events_range,
    load_sessions,
    load_sessions_range,
    load_today_live,
    load_tool_hourly,
)
from views.claude_code import page_claude_code
from views.insights import page_insights
from views.overview import page_overview
from views.sessions import page_sessions
from views.settings import page_settings
from views.tool_detail import page_tool_detail
from views.tools_all import page_tools_all

_LA_TZ = ZoneInfo("America/Los_Angeles")

_NAV_ITEMS = [
    "Overview",
    "── Tools ──",
    "All Tools",
    "Claude Code",
    "Cursor",
    "ChatGPT",
    "Gemini",
    "──────────",
    "Sessions",
    "Insights",
    "Settings",
]

# Pages that are section dividers (not navigable)
_DIVIDERS = {"── Tools ──", "──────────"}


def main() -> None:
    st.set_page_config(
        page_title="AI Usage Dashboard",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    config = load_config()

    # ── Global date range init ─────────────────────────────────────────────────
    today = datetime.now(_LA_TZ).date()
    if "global_date_from" not in st.session_state:
        st.session_state["global_date_from"] = today - timedelta(days=29)
    if "global_date_to" not in st.session_state:
        st.session_state["global_date_to"] = today

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("AI Usage Dashboard")
        st.caption("Cloud • Zero cost • Always on")
        st.divider()

        # Global date range pickers
        gf = st.date_input("From", value=st.session_state["global_date_from"],
                           max_value=today, key="global_date_from")
        gt = st.date_input("To",   value=st.session_state["global_date_to"],
                           max_value=today, key="global_date_to")
        if gf > gt:
            st.session_state["global_date_to"] = gf

        st.divider()

        page = st.radio(
            "Navigate",
            _NAV_ITEMS,
            label_visibility="collapsed",
        )

        st.divider()

        if st.button("Refresh Data"):
            load_today_live.clear()
            load_daily_metrics.clear()
            load_daily_metrics_range.clear()
            load_sessions.clear()
            load_sessions_range.clear()
            load_raw_events.clear()
            load_raw_events_range.clear()
            load_claude_metrics.clear()
            load_tool_hourly.clear()
            load_db_stats.clear()
            st.rerun()

        st.caption(f"Last refresh: {datetime.now(_LA_TZ).strftime('%H:%M:%S')} PST")

    # ── Routing ────────────────────────────────────────────────────────────────
    if page in _DIVIDERS:
        st.info("Select a page from the sidebar.")
    elif page == "Overview":
        page_overview(config)
    elif page == "All Tools":
        page_tools_all(config)
    elif page == "Claude Code":
        page_claude_code(config)
    elif page == "Cursor":
        page_tool_detail("cursor", config)
    elif page == "ChatGPT":
        page_tool_detail("chatgpt", config)
    elif page == "Gemini":
        page_tool_detail("gemini", config)
    elif page == "Sessions":
        page_sessions(config)
    elif page == "Insights":
        page_insights(config)
    elif page == "Settings":
        page_settings(config)


if __name__ == "__main__":
    main()
