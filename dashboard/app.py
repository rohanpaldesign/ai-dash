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

import base64
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image as _PILImage

_logo_path = Path(__file__).parent / "assets" / "siscil-circle-logo.png"
_text_logo_path = Path(__file__).parent / "assets" / "siscil-text-logo.png"

_DARK_CSS = """
<style>
/* Siscil dark mode overrides */
.stApp { background-color: #0E1117 !important; color: #FAFAFA !important; }
header[data-testid="stHeader"] { background-color: #0E1117 !important; }
section[data-testid="stSidebar"] > div:first-child { background-color: #1A1D27 !important; }
.main .block-container { background-color: #0E1117 !important; }
/* Text */
p, span, label, li, td, th, h1, h2, h3, h4, h5, h6,
[data-testid="stMetricValue"], [data-testid="stMetricLabel"],
[data-testid="stMetricDelta"], .stMarkdown { color: #FAFAFA !important; }
/* Metric cards */
[data-testid="metric-container"] { background-color: #1E2028 !important; border-color: #3A3D4A !important; }
/* Inputs / textareas */
input, textarea, [data-baseweb="input"] > div, [data-baseweb="textarea"] > div,
[data-baseweb="select"] > div { background-color: #1E2028 !important; color: #FAFAFA !important; border-color: #3A3D4A !important; }
/* Buttons — primary keeps brand color, secondary darkened */
button[data-testid="stBaseButton-primary"] { background-color: #474CD2 !important; color: #FFFFFF !important; border-color: #474CD2 !important; }
button[data-testid="stBaseButton-secondary"] { background-color: #1E2028 !important; color: #FAFAFA !important; border-color: #3A3D4A !important; }
/* Dividers */
hr { border-color: #3A3D4A !important; }
/* Alerts */
[data-testid="stAlert"] { background-color: #1E2028 !important; }
/* Dataframe rows */
[data-testid="stDataFrame"] th { background-color: #1E2028 !important; color: #FAFAFA !important; }
[data-testid="stDataFrame"] td { background-color: #0E1117 !important; color: #FAFAFA !important; }
/* Pills */
[data-testid="stPillsContainer"] { background-color: #1E2028 !important; }
/* Caption */
.stCaption { color: #AAAAAA !important; }
/* Code */
pre, code { background-color: #1E2028 !important; color: #E0E0E0 !important; }
</style>
"""


_PRIMARY_CSS = """
<style>
/* Ensure brand primary color is always applied (in case config.toml isn't loaded) */
button[data-testid="stBaseButton-primary"] { background-color: #474CD2 !important; color: #FFFFFF !important; border-color: #474CD2 !important; }
[data-testid="stPillsContainer"] button[aria-selected="true"] { background-color: #474CD2 !important; color: #FFFFFF !important; }
</style>
"""


def _apply_theme(cookies) -> None:
    if "theme_pref" not in st.session_state:
        saved = cookies.get("sb_theme") or "system"
        st.session_state["theme_pref"] = saved
    pref = st.session_state["theme_pref"]
    st.markdown(_PRIMARY_CSS, unsafe_allow_html=True)
    if pref == "dark":
        st.markdown(_DARK_CSS, unsafe_allow_html=True)
    elif pref == "system":
        wrapped = _DARK_CSS.replace("<style>", "<style>@media (prefers-color-scheme: dark) {").replace("</style>", "}</style>")
        st.markdown(wrapped, unsafe_allow_html=True)

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


def _icon_b64(name: str) -> str:
    path = Path(__file__).parent / "assets" / f"{name}.svg"
    try:
        return base64.b64encode(path.read_bytes()).decode()
    except FileNotFoundError:
        return ""


_icons = {
    "claude":  _icon_b64("claude"),
    "openai":  _icon_b64("openai"),
    "cursor":  _icon_b64("cursor"),
    "gemini":  _icon_b64("gemini"),
}


def _nav_button(label: str, page_key: str) -> None:
    """Render a nav button; clicking sets current_page and reruns."""
    is_active = st.session_state.get("current_page") == page_key
    btn_type = "primary" if is_active else "secondary"
    if st.button(label, key=f"nav_{page_key}", use_container_width=True, type=btn_type):
        st.session_state["current_page"] = page_key
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Siscil",
        page_icon=_PILImage.open(_logo_path),
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

    _apply_theme(_cookies)

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
            import urllib.error as _ue
            if isinstance(_metrics_err, _ue.HTTPError):
                try:
                    _turso_body = _metrics_err.read().decode(errors="replace")
                except Exception:
                    _turso_body = "(body unreadable)"
                st.warning(f"Metrics HTTP {_metrics_err.code}: {_turso_body}")
            else:
                import traceback as _tb
                st.warning(f"Metrics error [{type(_metrics_err).__name__}]: {_metrics_err}\n\n```\n{_tb.format_exc()}\n```")
        st.session_state["metrics_computed"] = True

    # ── Page state init ────────────────────────────────────────────────────────
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "Overview"

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.image(str(_text_logo_path), width=150)
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

        # Icon CSS for tool nav buttons (mask-image on p::before: groups icon+text, inherits text color)
        _icon_css = "".join(
            f"""div:has(#nav-icon-{nav_id}) + div button p {{
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
    margin: 0 !important;
    justify-content: center !important;
}}
div:has(#nav-icon-{nav_id}) + div button p::before {{
    content: "" !important;
    display: block !important;
    width: 16px !important;
    height: 16px !important;
    flex-shrink: 0 !important;
    background-color: currentColor !important;
    -webkit-mask-image: url("data:image/svg+xml;base64,{_icons[icon_key]}") !important;
    mask-image: url("data:image/svg+xml;base64,{_icons[icon_key]}") !important;
    -webkit-mask-size: contain !important;
    mask-size: contain !important;
    -webkit-mask-repeat: no-repeat !important;
    mask-repeat: no-repeat !important;
    -webkit-mask-position: center !important;
    mask-position: center !important;
}}"""
            for nav_id, icon_key in (
                ("claude", "claude"), ("cursor", "cursor"),
                ("openai", "openai"), ("gemini", "gemini"),
            )
            if _icons[icon_key]
        )
        if _icon_css:
            st.markdown(f"<style>{_icon_css}</style>", unsafe_allow_html=True)

        _nav_button("Overview", "Overview")

        st.markdown("**Tools**")
        st.markdown('<div id="nav-icon-claude"></div>', unsafe_allow_html=True)
        _nav_button("Claude Code", "Claude Code")
        st.markdown('<div id="nav-icon-cursor"></div>', unsafe_allow_html=True)
        _nav_button("Cursor",      "Cursor")
        st.markdown('<div id="nav-icon-openai"></div>', unsafe_allow_html=True)
        _nav_button("ChatGPT",     "ChatGPT")
        st.markdown('<div id="nav-icon-gemini"></div>', unsafe_allow_html=True)
        _nav_button("Gemini",      "Gemini")

        st.divider()
        _nav_button("Sessions", "Sessions")
        _nav_button("Insights", "Insights")

        st.divider()
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
        page_settings(config, _cookies)
    elif page == "Users":
        from views.users import page_users
        page_users(config)


if __name__ == "__main__":
    main()
