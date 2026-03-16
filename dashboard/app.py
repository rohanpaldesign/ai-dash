"""
dashboard/app.py — AI Usage Dashboard entrypoint.

Navigation:
  Overview
  ── Tools ──
    Claude Code
    Cursor
    ChatGPT
    Gemini
  Sessions
  Insights
  Settings
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from streamlit_cookies_controller import CookieController

from processors.metrics_calculator import run as _run_metrics

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
    load_tool_activity,
    load_tool_hourly,
)
from views.claude_code import page_claude_code
from views.insights import page_insights
from views.login import handle_oauth_callback, page_login
from views.overview import page_overview
from views.sessions import page_sessions
from views.settings import page_settings
from views.tool_detail import page_tool_detail

_LA_TZ = ZoneInfo("America/Los_Angeles")

def _nav_button(label: str, page_key: str) -> None:
    """Render a nav button; clicking sets current_page and reruns."""
    if st.button(label, key=f"nav_{page_key}", use_container_width=True):
        st.session_state["current_page"] = page_key
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="SignalBoard",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _cookies = CookieController()

    # Password reset link intercept — must run before auth gate
    if "reset_token" in st.query_params:
        from views.reset_password import page_reset_password
        page_reset_password()
        st.stop()

    # Handle Google OAuth callback before any other rendering
    handle_oauth_callback(_cookies)

    # Auto-login from persistent session cookie
    if not st.session_state.get("user"):
        _token = _cookies.get("sb_session")
        if _token:
            from auth import validate_session_token
            _user_from_cookie = validate_session_token(_token)
            if _user_from_cookie:
                st.session_state["user"] = _user_from_cookie
            else:
                _cookies.remove("sb_session")

    # Auth gate — show login page if not signed in
    if not st.session_state.get("user"):
        page_login(_cookies)
        st.stop()

    config = load_config()

    # ── Claim un-owned data + compute metrics once per session on startup ────────
    if "metrics_computed" not in st.session_state:
        _user_id = st.session_state["user"]["user_id"]
        try:
            from auth import claim_existing_data as _claim
            _claim(_user_id)
        except Exception:
            pass
        try:
            _run_metrics()
        except Exception as _metrics_err:
            import traceback as _tb
            st.warning(f"Metrics computation failed: {_metrics_err}\n\n```\n{_tb.format_exc()}\n```")
        st.session_state["metrics_computed"] = True

    # ── Page state init ────────────────────────────────────────────────────────
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "Overview"

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("SignalBoard")
        st.caption("Cloud • Zero cost • Always on")

        _user = st.session_state["user"]
        st.markdown("""
<style>
div:has(#profile-nav-anchor) + div button {
    background: none !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    color: inherit !important;
    font-size: 1em !important;
    font-weight: bold !important;
    cursor: pointer !important;
    text-align: left !important;
    width: fit-content !important;
    min-height: unset !important;
    line-height: 1.5 !important;
}
div:has(#profile-nav-anchor) + div button:hover {
    opacity: 0.7 !important;
    background: none !important;
}
</style>
<div id="profile-nav-anchor"></div>""", unsafe_allow_html=True)
        if st.button(f"👤 {_user['username']}", key="nav_profile"):
            st.session_state["current_page"] = "Settings"
            st.rerun()

        st.divider()

        _nav_button("Overview", "Overview")

        st.markdown("**Tools**")
        _nav_button("Claude Code", "Claude Code")
        _nav_button("Cursor",      "Cursor")
        _nav_button("ChatGPT",     "ChatGPT")
        _nav_button("Gemini",      "Gemini")

        st.divider()
        _nav_button("Sessions", "Sessions")
        _nav_button("Insights", "Insights")
        _nav_button("Settings", "Settings")
        if _user.get("role", "basic") in ("admin", "owner"):
            _nav_button("Users", "Users")

        st.divider()

        if st.button("Refresh Data"):
            _run_metrics()
            load_today_live.clear()
            load_daily_metrics.clear()
            load_daily_metrics_range.clear()
            load_sessions.clear()
            load_sessions_range.clear()
            load_raw_events.clear()
            load_raw_events_range.clear()
            load_claude_metrics.clear()
            load_tool_activity.clear()
            load_tool_hourly.clear()
            load_db_stats.clear()
            st.rerun()

        st.caption(f"Last refresh: {datetime.now(_LA_TZ).strftime('%H:%M:%S')} PST")

        st.divider()
        if st.button("Log out", use_container_width=True):
            from auth import invalidate_session_token
            _tok = _cookies.get("sb_session")
            if _tok:
                invalidate_session_token(_tok)
                _cookies.remove("sb_session")
            del st.session_state["user"]
            st.rerun()

    # ── Routing ────────────────────────────────────────────────────────────────
    page = st.session_state["current_page"]

    if page == "Overview":
        page_overview(config)
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
    elif page == "Users":
        from views.users import page_users
        page_users(config)


if __name__ == "__main__":
    main()
