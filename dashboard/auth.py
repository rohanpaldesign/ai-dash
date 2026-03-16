"""
dashboard/auth.py — Authentication utilities for Alpha 0.2.
"""

import json
import random
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import bcrypt
import streamlit as st

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import execute_write, query_df


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


# ── User queries ──────────────────────────────────────────────────────────────

def is_first_user() -> bool:
    df = query_df("SELECT COUNT(*) AS cnt FROM users")
    return int(df["cnt"].iloc[0]) == 0 if not df.empty else True


def get_user_by_username(username: str) -> dict | None:
    df = query_df(
        "SELECT * FROM users WHERE username = ?",
        (username,),
    )
    return df.iloc[0].to_dict() if not df.empty else None


def get_user_by_email(email: str) -> dict | None:
    df = query_df(
        "SELECT * FROM users WHERE email = ?",
        (email,),
    )
    return df.iloc[0].to_dict() if not df.empty else None


def get_user_by_google_sub(google_sub: str) -> dict | None:
    df = query_df(
        "SELECT * FROM users WHERE google_sub = ?",
        (google_sub,),
    )
    return df.iloc[0].to_dict() if not df.empty else None


# ── User creation / mutation ──────────────────────────────────────────────────

def create_user(
    username: str,
    email: str,
    display_name: str | None = None,
    password: str | None = None,
    google_sub: str | None = None,
) -> dict:
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    password_hash = hash_password(password) if password else None
    execute_write(
        """
        INSERT INTO users (user_id, username, email, display_name, password_hash, google_sub, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, username, email, display_name, password_hash, google_sub, now),
    )
    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "display_name": display_name,
        "password_hash": password_hash,
        "google_sub": google_sub,
        "created_at": now,
        "last_login": None,
    }


def update_last_login(user_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    execute_write(
        "UPDATE users SET last_login = ? WHERE user_id = ?",
        (now, user_id),
    )


def claim_existing_data(user_id: str) -> None:
    """Assign all un-owned rows to this user (called once for the first registrant)."""
    for table in ("raw_events", "sessions", "daily_metrics"):
        execute_write(
            f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL",
            (user_id,),
        )


def update_password(user_id: str, new_password: str) -> None:
    execute_write(
        "UPDATE users SET password_hash = ? WHERE user_id = ?",
        (hash_password(new_password), user_id),
    )


def update_display_name(user_id: str, display_name: str) -> None:
    execute_write("UPDATE users SET display_name = ? WHERE user_id = ?", (display_name, user_id))


def update_username(user_id: str, new_username: str) -> None:
    execute_write(
        "UPDATE users SET username = ?, username_changes = username_changes + 1 WHERE user_id = ?",
        (new_username, user_id),
    )


def get_all_users() -> list[dict]:
    """Return all users ordered by role priority then username."""
    df = query_df(
        "SELECT user_id, username, display_name, role, created_at, last_login "
        "FROM users ORDER BY "
        "CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, username"
    )
    return df.to_dict("records") if not df.empty else []


def update_user_role(user_id: str, role: str) -> None:
    execute_write("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))


def delete_user(user_id: str) -> None:
    """Delete a user and all their associated data."""
    for table in ("raw_events", "sessions", "daily_metrics"):
        execute_write(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    execute_write("DELETE FROM auth_otp WHERE user_id = ?", (user_id,))
    execute_write("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    execute_write("DELETE FROM users WHERE user_id = ?", (user_id,))


# ── Persistent session tokens ─────────────────────────────────────────────────

SESSION_DAYS = 30


def create_session_token(user_id: str) -> str:
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    execute_write(
        "INSERT INTO user_sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (token, user_id, (now + timedelta(days=SESSION_DAYS)).isoformat(), now.isoformat()),
    )
    return token


def validate_session_token(token: str) -> dict | None:
    """Return the user dict if token is valid and unexpired, else None."""
    now = datetime.now(timezone.utc).isoformat()
    df = query_df(
        "SELECT user_id FROM user_sessions WHERE token = ? AND expires_at > ?",
        (token, now),
    )
    if df.empty:
        return None
    return get_user_by_id(str(df["user_id"].iloc[0]))


def invalidate_session_token(token: str) -> None:
    execute_write("DELETE FROM user_sessions WHERE token = ?", (token,))


# ── OTP ───────────────────────────────────────────────────────────────────────

def generate_otp(user_id: str) -> str:
    code = f"{random.randint(0, 999999):06d}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    execute_write(
        "INSERT INTO auth_otp (user_id, code, expires_at, purpose) VALUES (?, ?, ?, 'otp')",
        (user_id, code, expires_at),
    )
    return code


def verify_otp(user_id: str, code: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    df = query_df(
        """
        SELECT id FROM auth_otp
        WHERE user_id = ? AND code = ? AND used = 0 AND expires_at > ? AND purpose = 'otp'
        ORDER BY id DESC LIMIT 1
        """,
        (user_id, code, now),
    )
    if df.empty:
        return False
    otp_id = int(df["id"].iloc[0])
    execute_write("UPDATE auth_otp SET used = 1 WHERE id = ?", (otp_id,))
    return True


def _send_email(to_email: str, subject: str, body_plain: str, body_html: str | None = None) -> None:
    """Send email via Brevo SMTP (TLS on port 587)."""
    from email.mime.multipart import MIMEMultipart

    smtp_host = st.secrets["SMTP_HOST"]
    smtp_port = int(st.secrets["SMTP_PORT"])
    smtp_user = st.secrets["SMTP_USER"]
    smtp_password = st.secrets["SMTP_PASSWORD"]
    smtp_from = st.secrets.get("SMTP_FROM", smtp_user)

    if body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_plain, "plain"))
        msg.attach(MIMEText(body_html, "html"))
    else:
        msg = MIMEText(body_plain)

    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, to_email, msg.as_string())


def send_otp_email(email: str, display_name: str | None, code: str) -> None:
    name = display_name or email
    plain = (
        f"Hi {name},\n\n"
        f"Your verification code is: {code}\n\n"
        f"This code expires in 15 minutes.\n\n"
        f"— AI Usage Dashboard"
    )
    _send_email(email, f"Your verification code: {code}", plain)


# ── Password reset tokens ──────────────────────────────────────────────────────

def get_user_by_id(user_id: str) -> dict | None:
    df = query_df("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return df.iloc[0].to_dict() if not df.empty else None


def generate_reset_token(user_id: str) -> str:
    token = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    execute_write(
        "INSERT INTO auth_otp (user_id, code, expires_at, purpose) VALUES (?, ?, ?, 'reset')",
        (user_id, token, expires_at),
    )
    return token


def verify_reset_token(token: str) -> str | None:
    """Return user_id if token is valid and unexpired, else None. Does not mark used."""
    now = datetime.now(timezone.utc).isoformat()
    df = query_df(
        """
        SELECT user_id FROM auth_otp
        WHERE code = ? AND used = 0 AND expires_at > ? AND purpose = 'reset'
        ORDER BY id DESC LIMIT 1
        """,
        (token, now),
    )
    return str(df["user_id"].iloc[0]) if not df.empty else None


def invalidate_reset_token(token: str) -> None:
    execute_write(
        "UPDATE auth_otp SET used = 1 WHERE code = ? AND purpose = 'reset'",
        (token,),
    )


def send_reset_email(email: str, display_name: str | None, reset_url: str) -> None:
    name = display_name or email
    plain = (
        f"Hi {name},\n\n"
        f"Click the link below to reset your AI Usage Dashboard password.\n"
        f"This link expires in 1 hour.\n\n"
        f"{reset_url}\n\n"
        f"If you didn't request this, ignore this email.\n\n"
        f"— AI Usage Dashboard"
    )
    html = (
        f"<p>Hi {name},</p>"
        f"<p>Click the button below to reset your password. This link expires in <strong>1 hour</strong>.</p>"
        f'<p><a href="{reset_url}" style="background:#4F8EF7;color:#fff;padding:10px 20px;'
        f'border-radius:5px;text-decoration:none;font-weight:bold;">Reset Password</a></p>'
        f"<p>Or copy this URL into your browser:<br><code>{reset_url}</code></p>"
        f"<p>If you didn't request this, you can safely ignore this email.</p>"
        f"<p>— AI Usage Dashboard</p>"
    )
    _send_email(email, "Reset your AI Usage Dashboard password", plain, html)


# ── Google OAuth ──────────────────────────────────────────────────────────────

def _google_client_config() -> dict:
    return {
        "web": {
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def build_google_auth_url() -> str:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        _google_client_config(),
        scopes=["openid", "email", "profile"],
        redirect_uri=st.secrets["GOOGLE_REDIRECT_URI"],
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account",
    )
    st.session_state["oauth_state"] = state
    return auth_url


def exchange_google_code(code: str, state: str) -> dict | None:
    import urllib.request as _urllib_req

    expected_state = st.session_state.get("oauth_state")
    if not expected_state or state != expected_state:
        return None

    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_config(
            _google_client_config(),
            scopes=["openid", "email", "profile"],
            redirect_uri=st.secrets["GOOGLE_REDIRECT_URI"],
            state=state,
        )
        import os
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # localhost dev only
        flow.fetch_token(code=code)
        token = flow.credentials.token

        req = _urllib_req.Request(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        with _urllib_req.urlopen(req) as resp:
            userinfo = json.loads(resp.read())

        return {
            "sub": userinfo["sub"],
            "email": userinfo.get("email", ""),
            "name": userinfo.get("name", ""),
        }
    except Exception:
        return None
