"""dashboard/views/users.py — User management page (admin/owner only)."""

import streamlit as st


def page_users(config: dict) -> None:
    from auth import get_all_users, update_user_role, delete_user
    st.title("Users")

    viewer = st.session_state["user"]
    viewer_role = viewer.get("role", "basic")

    if viewer_role not in ("admin", "owner"):
        st.error("Access denied.")
        return

    all_users = get_all_users()
    current_uid = viewer["user_id"]
    me = [u for u in all_users if u["user_id"] == current_uid]
    others = [u for u in all_users if u["user_id"] != current_uid]
    ordered = me + others

    # Header row
    h1, h2, h3, h4 = st.columns([2, 2, 1.5, 3])
    h1.markdown("**Username**")
    h2.markdown("**Display Name**")
    h3.markdown("**Role**")
    h4.markdown("**Actions**")
    st.divider()

    for u in ordered:
        is_me = u["user_id"] == current_uid
        is_owner_account = u.get("role") == "owner"

        c1, c2, c3, c4 = st.columns([2, 2, 1.5, 3])
        c1.markdown(f"**{u['username']}**" + (" *(you)*" if is_me else ""))
        c2.write(u.get("display_name") or "—")
        c3.write(u.get("role", "basic"))

        with c4:
            if is_owner_account:
                st.caption("Protected")
            else:
                # Role options
                role_opts = ["basic", "admin", "owner"] if viewer_role == "owner" else ["basic", "admin"]
                cur_role = u.get("role", "basic")
                cur_idx = role_opts.index(cur_role) if cur_role in role_opts else 0

                a1, a2 = st.columns(2)
                new_role = a1.selectbox(
                    "Role", role_opts, index=cur_idx,
                    key=f"role_{u['user_id']}", label_visibility="collapsed",
                )
                if a1.button("Save", key=f"save_{u['user_id']}"):
                    update_user_role(u["user_id"], new_role)
                    if is_me:
                        st.session_state["user"]["role"] = new_role
                    st.rerun()

                # Delete: owner can delete anyone; admin can only delete basic users
                can_delete = (
                    not is_me and (
                        viewer_role == "owner" or
                        (viewer_role == "admin" and cur_role == "basic")
                    )
                )
                if can_delete:
                    if a2.button("Delete", key=f"del_{u['user_id']}"):
                        st.session_state[f"confirm_del_{u['user_id']}"] = True
                        st.rerun()

                    if st.session_state.get(f"confirm_del_{u['user_id']}"):
                        st.warning(f"Delete **{u['username']}**? This removes all their data and cannot be undone.")
                        d1, d2, _ = st.columns([1, 1, 4])
                        if d1.button("Confirm", key=f"confirm_{u['user_id']}", type="primary"):
                            delete_user(u["user_id"])
                            st.session_state.pop(f"confirm_del_{u['user_id']}", None)
                            st.rerun()
                        if d2.button("Cancel", key=f"cancel_{u['user_id']}"):
                            st.session_state.pop(f"confirm_del_{u['user_id']}", None)
                            st.rerun()

        st.divider()
