"""dashboard/views/reset_password.py — Dedicated password-reset page (email-link flow)."""

import streamlit as st

from auth import (
    generate_otp,
    get_user_by_id,
    invalidate_reset_token,
    send_otp_email,
    update_password,
    verify_otp,
    verify_reset_token,
)


def _mask_email(email: str) -> str:
    """Return r***@gmail.com style masked email."""
    try:
        local, domain = email.split("@", 1)
        return f"{local[0]}***@{domain}"
    except Exception:
        return "***"


def page_reset_password() -> None:
    token = st.query_params.get("reset_token", "")

    # ── Validate token ────────────────────────────────────────────────────────
    user_id = verify_reset_token(token) if token else None
    if not user_id:
        st.error("This password reset link is invalid or has already been used.")
        if st.button("Back to sign in"):
            st.query_params.clear()
            st.rerun()
        return

    user = get_user_by_id(user_id)
    if not user:
        st.error("User not found. Please request a new reset link.")
        return

    email = user.get("email", "")
    display_name = user.get("display_name") or user.get("username", "")
    masked = _mask_email(email)

    st.title("Reset Password")
    st.caption(f"Resetting password for **{masked}**")

    # ── Step 1: enter new password ────────────────────────────────────────────
    if not st.session_state.get("pw_reset_otp_sent"):
        new_pw = st.text_input("New password", type="password", key="rp_new_pw")
        confirm_pw = st.text_input("Confirm new password", type="password", key="rp_confirm_pw")

        if st.button("Send verification code"):
            if not new_pw:
                st.error("Please enter a new password.")
            elif new_pw != confirm_pw:
                st.error("Passwords do not match.")
            else:
                try:
                    code = generate_otp(user_id)
                    send_otp_email(email, display_name, code)
                    st.session_state["pw_reset_otp_sent"] = True
                    st.session_state["pw_reset_pending"] = {
                        "token": token,
                        "user_id": user_id,
                        "new_password": new_pw,
                    }
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to send verification code: {exc}")
        return

    # ── Step 2: enter OTP ─────────────────────────────────────────────────────
    st.info(f"A verification code was sent to {masked}. Enter it below.")
    otp_code = st.text_input("Verification code", key="rp_otp_code")

    if st.button("Reset Password"):
        pending = st.session_state.get("pw_reset_pending", {})
        if not otp_code:
            st.error("Please enter the verification code.")
        elif not verify_otp(pending["user_id"], otp_code):
            st.error("Invalid or expired code.")
        else:
            update_password(pending["user_id"], pending["new_password"])
            invalidate_reset_token(pending["token"])
            # Clean up session state
            st.session_state.pop("pw_reset_otp_sent", None)
            st.session_state.pop("pw_reset_pending", None)
            st.query_params.clear()
            st.session_state["auth_view"] = "login"
            st.success("Password updated! Redirecting to sign in...")
            st.rerun()
