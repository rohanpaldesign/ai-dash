"""dashboard/views/settings.py — Config display and data export."""

import pandas as pd
import streamlit as st

from auth import generate_reset_token, send_reset_email, update_display_name, update_username
from auth import generate_otp, send_otp_email, verify_otp, get_user_by_username
from data import (
    BASE_DIR,
    load_db_stats,
    load_sessions,
    load_raw_events,
)


def page_settings(config: dict) -> None:
    st.title("Settings")

    user = st.session_state["user"]
    user_id = user["user_id"]

    # ── Profile ───────────────────────────────────────────────────────────────
    st.subheader("Profile")

    username_changes = user.get("username_changes", 0) or 0

    p1, p2, p3 = st.columns(3)
    p1.markdown(f"**Username**\n\n{user.get('username', '—')}")
    p2.markdown(f"**Display Name**\n\n{user.get('display_name') or '—'}")
    p3.markdown(f"**Email**\n\n{user.get('email', '—')}")

    # Trigger buttons sit inside their columns
    if username_changes >= 1:
        p1.caption("Cannot be changed again.")
    elif not st.session_state.get("uname_change_mode"):
        if p1.button("Change", key="uname_change"):
            st.session_state["uname_change_mode"] = True
            st.rerun()

    if not st.session_state.get("dname_edit_mode"):
        if p2.button("Edit", key="dname_edit"):
            st.session_state["dname_edit_mode"] = True
            st.rerun()

    # ── Display Name edit form (full-width, below columns) ───────────────────
    if st.session_state.get("dname_edit_mode"):
        new_dname = st.text_input("Display Name", value=user.get("display_name") or "")
        col_save, col_cancel, _ = st.columns([1, 1, 4])
        if col_save.button("Save", key="dname_save"):
            update_display_name(user_id, new_dname)
            st.session_state["user"]["display_name"] = new_dname
            del st.session_state["dname_edit_mode"]
            st.rerun()
        if col_cancel.button("Cancel", key="dname_cancel"):
            del st.session_state["dname_edit_mode"]
            st.rerun()

    # ── Username change flow (full-width, below columns) ─────────────────────
    if st.session_state.get("uname_change_mode"):
        email_addr = user.get("email", "")
        parts = email_addr.split("@")
        masked_email = parts[0][:2] + "***@" + parts[1] if len(parts) == 2 else email_addr

        if st.session_state.get("uname_otp_sent"):
            # Step 2 — OTP entry
            st.info(f"Verification code sent to {masked_email}.")
            otp_code = st.text_input("Verification Code", key="uname_otp_input")
            col_confirm, col_cancel2, _ = st.columns([1, 1, 4])
            if col_confirm.button("Confirm Username Change", key="uname_confirm"):
                if verify_otp(user_id, otp_code):
                    new_uname = st.session_state["uname_pending"]
                    update_username(user_id, new_uname)
                    st.session_state["user"]["username"] = new_uname
                    st.session_state["user"]["username_changes"] = username_changes + 1
                    for k in ("uname_change_mode", "uname_otp_sent", "uname_pending"):
                        st.session_state.pop(k, None)
                    st.rerun()
                else:
                    st.error("Invalid or expired code.")
            if col_cancel2.button("Cancel", key="uname_cancel2"):
                for k in ("uname_change_mode", "uname_otp_sent", "uname_pending"):
                    st.session_state.pop(k, None)
                st.rerun()
        else:
            # Step 1 — enter new username
            st.warning("You can only change your username once. This cannot be undone.")
            new_uname_input = st.text_input("New username", value=user.get("username", ""), key="uname_input")
            col_send, col_cancel3, _ = st.columns([1, 1, 4])
            if col_send.button("Send Verification Code", key="uname_send"):
                if not new_uname_input:
                    st.error("Username cannot be empty.")
                elif new_uname_input == user.get("username"):
                    st.error("New username must be different from your current username.")
                elif get_user_by_username(new_uname_input) is not None:
                    st.error("That username is already taken.")
                else:
                    code = generate_otp(user_id)
                    send_otp_email(email_addr, user.get("display_name"), code)
                    st.session_state["uname_otp_sent"] = True
                    st.session_state["uname_pending"] = new_uname_input
                    st.rerun()
            if col_cancel3.button("Cancel", key="uname_cancel3"):
                for k in ("uname_change_mode", "uname_otp_sent", "uname_pending"):
                    st.session_state.pop(k, None)
                st.rerun()

    st.caption(f"Your User ID (for `AI_DASH_USER_ID` env var): `{user_id}`")

    email = user.get("email", "")
    if st.button(f"Send password reset link to {email}"):
        try:
            base_url = st.secrets.get("BASE_URL", "http://localhost:8503")
            token = generate_reset_token(user_id)
            reset_url = f"{base_url}/?reset_token={token}"
            send_reset_email(email, user.get("display_name"), reset_url)
            st.success(f"Reset link sent to {email}. Check your inbox.")
        except Exception as exc:
            st.error(f"Failed to send reset email: {exc}")

    st.divider()

    # ── Tool Configuration ────────────────────────────────────────────────────
    st.subheader("Tool Configuration")
    tools_cfg = config.get("tools", {})
    if tools_cfg:
        rows = []
        for tool_id, tcfg in tools_cfg.items():
            color = tcfg.get("color", "#888888")
            rows.append({
                "Tool ID": tool_id,
                "Display Name": tcfg.get("name", tool_id),
                "Color": color,
                "Monthly Cost": f"${tcfg.get('monthly_cost', 0):.2f}",
            })
        df = pd.DataFrame(rows).set_index("Tool ID")
        # Show color swatches via HTML
        html_rows = ""
        for _, r in df.iterrows():
            swatch = f"<span style='display:inline-block;width:14px;height:14px;background:{r['Color']};border-radius:3px;vertical-align:middle;margin-right:6px'></span>"
            html_rows += f"<tr><td>{r.name}</td><td>{r['Display Name']}</td><td>{swatch}{r['Color']}</td><td>{r['Monthly Cost']}</td></tr>"
        st.markdown(
            f"<table><thead><tr><th>Tool ID</th><th>Display Name</th><th>Color</th><th>Monthly Cost</th></tr></thead>"
            f"<tbody>{html_rows}</tbody></table>",
            unsafe_allow_html=True,
        )
    else:
        st.info("No tool configuration found.")

    st.divider()

    # ── Data Export ───────────────────────────────────────────────────────────
    st.subheader("Data Export")

    sessions = load_sessions(90, user_id)
    raw      = load_raw_events(30, user_id)

    col1, col2 = st.columns(2)
    with col1:
        if not sessions.empty:
            csv_sess = sessions.drop(columns=["date", "hour", "weekday", "active_minutes", "is_deep_work"],
                                     errors="ignore").to_csv(index=False)
            st.download_button(
                "Download Sessions CSV (90 days)",
                data=csv_sess,
                file_name="sessions.csv",
                mime="text/csv",
            )
        else:
            st.button("Download Sessions CSV", disabled=True)

    with col2:
        if not raw.empty:
            csv_raw = raw.to_csv(index=False)
            st.download_button(
                "Download Raw Events CSV (30 days)",
                data=csv_raw,
                file_name="raw_events.csv",
                mime="text/csv",
            )
        else:
            st.button("Download Raw Events CSV", disabled=True)

    st.divider()

    # ── Dashboard Info ────────────────────────────────────────────────────────
    st.subheader("Dashboard Info")

    db_path = BASE_DIR / "database" / "usage.db"
    st.markdown(f"**Local DB path:** `{db_path}`")
    st.caption("Production data is stored in Turso (cloud). Local SQLite is a fallback.")

    stats = load_db_stats()
    counts = stats.get("counts", {})
    last_events = stats.get("last_events", pd.DataFrame())

    info_col1, info_col2 = st.columns(2)
    with info_col1:
        st.markdown("**Record Counts**")
        for table, cnt in counts.items():
            st.markdown(f"- `{table}`: {cnt:,} rows")

    with info_col2:
        st.markdown("**Last Event per Tool**")
        if not last_events.empty:
            for _, row in last_events.iterrows():
                st.markdown(f"- `{row['tool']}`: {row['last_event']}")
        else:
            st.info("No event data.")

    st.divider()
    st.caption("Copyright 2026 Rohan Pal. All Rights Reserved.")
