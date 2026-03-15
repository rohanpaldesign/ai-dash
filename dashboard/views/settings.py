"""dashboard/views/settings.py — Config display and data export."""

import pandas as pd
import streamlit as st

from data import (
    BASE_DIR,
    load_db_stats,
    load_sessions,
    load_raw_events,
)


def page_settings(config: dict) -> None:
    st.title("Settings")

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

    sessions = load_sessions(90)
    raw      = load_raw_events(30)

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
