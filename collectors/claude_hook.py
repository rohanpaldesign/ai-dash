"""
claude_hook.py — Claude Code hook logger.

Called by Claude Code on every hook event. Reads JSON from stdin,
writes a raw_event to the SQLite database.

Configure in ~/.claude/settings.json:
  "hooks": {
    "UserPromptSubmit":  [{"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}],
    "PreToolUse":        [{"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}],
    "PostToolUse":       [{"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}],
    "PostToolUseFailure":[{"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}],
    "Stop":              [{"type": "command", "command": "python D:/ai-dash-source/collectors/claude_hook.py"}]
  }
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import get_connection


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_repo(cwd: str | None) -> str | None:
    """Walk up from cwd to find a .git directory and return repo name."""
    if not cwd:
        return None
    p = Path(cwd)
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent.name
    return None


def handle_event(data: dict) -> None:
    hook_event = data.get("hook_event_name", "")
    session_id = data.get("session_id")
    cwd = data.get("cwd") or os.getcwd()
    repo = extract_repo(cwd)

    # Map hook event → event_type + field extraction
    event_type = "unknown"
    prompt_chars = None
    estimated_tokens = None
    tool_name = None
    success = None
    metadata = {}

    if hook_event == "UserPromptSubmit":
        event_type = "prompt"
        prompt = data.get("prompt", "")
        prompt_chars = len(prompt)
        estimated_tokens = prompt_chars // 4
        metadata = {"model": data.get("model")}

    elif hook_event == "PreToolUse":
        event_type = "tool_call"
        tool_name = data.get("tool_name")
        metadata = {"tool_input": data.get("tool_input")}

    elif hook_event == "PostToolUse":
        event_type = "tool_call"
        tool_name = data.get("tool_name")
        success = 1
        metadata = {"tool_response": str(data.get("tool_response", ""))[:200]}

    elif hook_event == "PostToolUseFailure":
        event_type = "tool_failure"
        tool_name = data.get("tool_name")
        success = 0
        metadata = {"error": str(data.get("error", ""))[:500]}

    elif hook_event == "Stop":
        event_type = "stop"
        metadata = {"stop_reason": data.get("stop_reason")}

    else:
        event_type = hook_event.lower() if hook_event else "unknown"

    with get_connection() as db:
        db.execute(
            """
            INSERT INTO raw_events
              (timestamp, tool, event_type, session_id, repo, cwd,
               prompt_chars, estimated_tokens, tool_name, success, metadata_json)
            VALUES (?, 'claude_code', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                event_type,
                session_id,
                repo,
                cwd,
                prompt_chars,
                estimated_tokens,
                tool_name,
                success,
                json.dumps(metadata) if metadata else None,
            ),
        )


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        handle_event(data)
    except Exception as exc:
        # Never crash Claude Code — log to stderr silently
        print(f"claude_hook error: {exc}", file=sys.stderr)
        sys.exit(0)  # exit 0 so Claude Code isn't disrupted


if __name__ == "__main__":
    main()
