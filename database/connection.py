"""
database/connection.py — Single DB abstraction layer.

Returns a libsql (Turso cloud) connection when TURSO_URL + TURSO_TOKEN are set,
otherwise falls back to local SQLite.
"""

import json
import numbers
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
_LOCAL_DB = BASE_DIR / "database" / "usage.db"


def _get_turso_creds():
    url = os.environ.get("TURSO_URL")
    token = os.environ.get("TURSO_TOKEN")
    if url and token:
        return url, token

    # Fallback: read directly from Windows user env registry.
    # Handles subprocesses (e.g. Claude Code hooks) that don't inherit
    # env vars set via setx after the parent process was launched.
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            if not url:
                url, _ = winreg.QueryValueEx(key, "TURSO_URL")
            if not token:
                token, _ = winreg.QueryValueEx(key, "TURSO_TOKEN")
    except Exception:
        pass
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


def _turso_cell(cell):
    """Convert a Turso HTTP API cell to a Python value."""
    t = cell["type"]
    if t == "null":
        return None
    v = cell["value"]
    if t == "integer":
        return int(v)
    if t in ("float", "real"):
        return float(v)
    return v  # text / blob


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Execute SELECT and return DataFrame.

    Uses Turso HTTP API when credentials are available (always fresh, no
    embedded-replica staleness). Falls back to local sqlite3 otherwise.
    """
    url, token = _get_turso_creds()
    if url and token:
        http_url = url.replace("libsql://", "https://") + "/v2/pipeline"
        args = []
        for p in params:
            if p is None:
                args.append({"type": "null"})
            elif isinstance(p, int):
                args.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                args.append({"type": "float", "value": float(p)})
            else:
                args.append({"type": "text", "value": str(p)})
        body = json.dumps({
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "args": args}},
                {"type": "close"},
            ]
        }).encode()
        req = urllib.request.Request(
            http_url,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        result = data["results"][0]["response"]["result"]
        cols = [c["name"] for c in result["cols"]]
        rows = [[_turso_cell(cell) for cell in row] for row in result["rows"]]
        return pd.DataFrame(rows, columns=cols)

    # SQLite fallback
    conn = sqlite3.connect(_LOCAL_DB)
    conn.row_factory = sqlite3.Row
    with conn:
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def execute_many(sql: str, params_list: list) -> None:
    """Execute the same SQL with multiple parameter sets in a single batch request."""
    if not params_list:
        return

    def _enc(p):
        if p is None:
            return {"type": "null"}
        if isinstance(p, bool):
            return {"type": "integer", "value": "1" if p else "0"}
        try:
            f = float(p)
            i = int(f)
            if f == i and abs(f) < 2**53:
                return {"type": "integer", "value": str(i)}
            return {"type": "float", "value": f}  # native Python float → JSON number
        except (TypeError, ValueError):
            pass
        return {"type": "text", "value": str(p)}

    url, token = _get_turso_creds()
    if url and token:
        http_url = url.replace("libsql://", "https://") + "/v2/pipeline"
        requests = [
            {"type": "execute", "stmt": {"sql": sql, "args": [_enc(p) for p in params]}}
            for params in params_list
        ]
        requests.append({"type": "close"})
        body = json.dumps({"requests": requests}).encode()
        import sys as _sys
        _sys.stderr.write(f"[execute_many] first_args={json.dumps([_enc(p) for p in params_list[0]])[:200]}\n")
        req = urllib.request.Request(
            http_url,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                resp.read()
        except urllib.error.HTTPError as _e:
            try:
                _body = _e.read().decode(errors="replace")
            except Exception:
                _body = "(unreadable)"
            raise RuntimeError(f"Turso execute_many HTTP {_e.code}: {_body}") from None
        return

    conn = sqlite3.connect(_LOCAL_DB)
    with conn:
        conn.executemany(sql, params_list)
        conn.commit()


def execute_write(sql: str, params: tuple = ()) -> None:
    """Execute INSERT/UPDATE/DELETE.

    Uses Turso HTTP API when credentials are available.
    Falls back to local sqlite3 otherwise.
    """
    url, token = _get_turso_creds()
    if url and token:
        http_url = url.replace("libsql://", "https://") + "/v2/pipeline"
        args = []
        for p in params:
            if p is None:
                args.append({"type": "null"})
            elif isinstance(p, int):
                args.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                args.append({"type": "float", "value": float(p)})
            else:
                args.append({"type": "text", "value": str(p)})
        body = json.dumps({
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "args": args}},
                {"type": "close"},
            ]
        }).encode()
        req = urllib.request.Request(
            http_url,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            resp.read()  # consume response; raise on HTTP error
        return

    # SQLite fallback
    conn = sqlite3.connect(_LOCAL_DB)
    with conn:
        conn.execute(sql, params)
        conn.commit()
