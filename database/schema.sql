-- AI Usage Dashboard Database Schema

CREATE TABLE IF NOT EXISTS raw_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL,          -- ISO 8601
    tool             TEXT NOT NULL,          -- claude_code / cursor / chatgpt / gemini
    event_type       TEXT NOT NULL,          -- window_active / prompt / tool_call / tool_failure / commit
    session_id       TEXT,
    repo             TEXT,
    cwd              TEXT,
    window_title     TEXT,
    prompt_chars     INTEGER,
    estimated_tokens INTEGER,
    tool_name        TEXT,                   -- bash / edit / search / etc.
    success          INTEGER,                -- 1/0 for tool calls
    duration_seconds REAL,                  -- window active duration
    metadata_json    TEXT                   -- extra hook data
);

CREATE INDEX IF NOT EXISTS idx_raw_events_timestamp ON raw_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_raw_events_tool      ON raw_events(tool);
CREATE INDEX IF NOT EXISTS idx_raw_events_session   ON raw_events(session_id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    tool            TEXT NOT NULL,
    start_time      TEXT NOT NULL,
    end_time        TEXT,
    active_seconds  REAL DEFAULT 0,
    repo            TEXT,
    prompt_count    INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    failure_count   INTEGER DEFAULT 0,
    subagent_count  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_tool       ON sessions(tool);
CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON sessions(start_time);

CREATE TABLE IF NOT EXISTS daily_metrics (
    date             TEXT NOT NULL,          -- YYYY-MM-DD
    tool             TEXT NOT NULL,
    active_minutes   REAL DEFAULT 0,
    session_count    INTEGER DEFAULT 0,
    prompt_count     INTEGER DEFAULT 0,
    estimated_tokens INTEGER DEFAULT 0,
    commits_after_ai INTEGER DEFAULT 0,
    PRIMARY KEY (date, tool)
);
