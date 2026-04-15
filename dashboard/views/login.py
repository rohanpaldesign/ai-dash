"""
dashboard/views/login.py — Login / signup page for Alpha 0.2.
"""

from pathlib import Path

import streamlit as st

_logo_path = Path(__file__).parent.parent / "assets" / "siscil-circle-logo.png"

from auth import (
    build_google_auth_url,
    claim_existing_data,
    create_session_token,
    create_user,
    exchange_google_code,
    get_user_by_email,
    get_user_by_username,
    is_first_user,
    update_last_login,
    verify_password,
    SESSION_DAYS,
)


def _set_session_cookie(cookies, user: dict) -> None:
    token = create_session_token(user["user_id"])
    cookies.set("sb_session", token, max_age=SESSION_DAYS * 86400)


def handle_oauth_callback(cookies) -> None:
    """Check for Google OAuth callback params and handle them before rendering."""
    params = st.query_params
    if "code" not in params:
        if "error" in params:
            st.session_state["oauth_error"] = params.get("error", "Unknown OAuth error")
            st.query_params.clear()
        return

    code = params.get("code", "")
    state = params.get("state", "")
    st.query_params.clear()

    userinfo = exchange_google_code(code, state)
    if userinfo is None:
        st.session_state["oauth_error"] = "Google sign-in failed. Please try again."
        return

    sub = userinfo["sub"]
    email = userinfo["email"]
    name = userinfo["name"]

    # Find existing user by Google sub or email
    user = get_user_by_email(email)
    if user is None:
        # Auto-register new Google user
        # Derive username from email prefix, ensure uniqueness
        base = email.split("@")[0].replace(".", "_").lower()
        candidate = base
        suffix = 1
        while get_user_by_username(candidate) is not None:
            candidate = f"{base}{suffix}"
            suffix += 1
        first = is_first_user()
        user = create_user(username=candidate, email=email, display_name=name, google_sub=sub)
        if first:
            claim_existing_data(user["user_id"])

    claim_existing_data(user["user_id"])
    update_last_login(user["user_id"])
    _set_session_cookie(cookies, user)
    st.session_state["user"] = user
    st.rerun()


def page_login(cookies) -> None:
    handle_oauth_callback(cookies)

    # Show OAuth error if any
    if "oauth_error" in st.session_state:
        st.error(st.session_state.pop("oauth_error"))

    # Sub-view state
    if "auth_view" not in st.session_state:
        st.session_state["auth_view"] = "login"

    st.image(str(_logo_path), width=64)
    st.title("Siscil")

    # Centre the form with columns
    _, col, _ = st.columns([1, 2, 1])

    with col:
        if st.session_state["auth_view"] == "login":
            _render_login(cookies)
        else:
            _render_signup(cookies)


def _google_button() -> None:
    try:
        url = build_google_auth_url()
        st.link_button("Sign in with Google", url, use_container_width=True)
    except Exception:
        st.caption("Google sign-in is not configured.")


def _render_login(cookies) -> None:
    st.subheader("Sign In")

    identifier = st.text_input("Username or Email", key="login_identifier")
    password = st.text_input("Password", type="password", key="login_password")

    if st.button("Sign In", use_container_width=True, type="primary"):
        if not identifier or not password:
            st.error("Please enter your username/email and password.")
        else:
            user = (
                get_user_by_username(identifier)
                or get_user_by_email(identifier)
            )
            if user is None or not user.get("password_hash"):
                st.error("Invalid credentials.")
            elif not verify_password(password, user["password_hash"]):
                st.error("Invalid credentials.")
            else:
                claim_existing_data(user["user_id"])
                update_last_login(user["user_id"])
                _set_session_cookie(cookies, user)
                st.session_state["user"] = user
                st.rerun()

    st.divider()
    _google_button()
    st.divider()

    if st.button("Create account", use_container_width=True):
        st.session_state["auth_view"] = "signup"
        st.rerun()


def _render_signup(cookies) -> None:
    st.subheader("Create Account")

    username = st.text_input("Username", key="signup_username")
    display_name = st.text_input("Display Name (optional)", key="signup_display_name")
    email = st.text_input("Email", key="signup_email")
    password = st.text_input("Password", type="password", key="signup_password")
    confirm = st.text_input("Confirm Password", type="password", key="signup_confirm")

    # Real-time uniqueness check
    if username:
        existing = get_user_by_username(username)
        if existing:
            st.warning("Username already taken.")

    if st.button("Create Account", use_container_width=True, type="primary"):
        error = None
        if not username or not email or not password:
            error = "Username, email, and password are required."
        elif get_user_by_username(username):
            error = "Username already taken."
        elif get_user_by_email(email):
            error = "An account with this email already exists."
        elif password != confirm:
            error = "Passwords do not match."

        if error:
            st.error(error)
        else:
            first = is_first_user()
            user = create_user(
                username=username,
                email=email,
                display_name=display_name or None,
                password=password,
            )
            if first:
                claim_existing_data(user["user_id"])
            update_last_login(user["user_id"])
            _set_session_cookie(cookies, user)
            st.session_state["user"] = user
            st.rerun()

    st.divider()
    _google_button()
    st.divider()

    if st.button("Back to sign in", use_container_width=True):
        st.session_state["auth_view"] = "login"
        st.rerun()
