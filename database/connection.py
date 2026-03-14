"""
database/connection.py — Single DB abstraction layer.

Returns a libsql (Turso cloud) connection when TURSO_URL + TURSO_TOKEN are set,
otherwise falls back to local SQLite.
"""

import os
import sqlite3
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
_LOCAL_DB = BASE_DIR / "database" / "usage.db"


def _get_turso_creds():
    url = os.environ.get("TURSO_URL")
    token = os.environ.get("TURSO_TOKEN")
    if url and token:
        return url, token
    try:
        import streamlit as st
        url = st.secrets.get("TURSO_URL")
        token = st.secrets.get("TURSO_TOKEN")
        if url and token:
            return url, token
    except Exception:
        pass
    return None, None


def get_connection():
    """Returns a DB connection. libsql (cloud) if TURSO_* env vars set, else local sqlite3."""
    url, token = _get_turso_creds()
    if url and token:
        import libsql
        return libsql.connect(url, auth_token=token)
    conn = sqlite3.connect(_LOCAL_DB)
    conn.row_factory = sqlite3.Row
    return conn


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Execute SELECT and return DataFrame. Works for both sqlite3 and libsql.
    (pandas.read_sql_query is NOT used — it fails with libsql connections.)"""
    with get_connection() as db:
        cur = db.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)
