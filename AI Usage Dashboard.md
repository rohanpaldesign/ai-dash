# Personal AI Usage Dashboard

## Goal

Build a **local dashboard** that tracks personal usage across AI tools:

- Claude Code
- Cursor
- ChatGPT
- Gemini

The dashboard will measure:

- sessions
- prompts
- tool usage
- coding edits accepted
- repo/project context
- productivity metrics
- estimated token usage
- estimated cost

The system runs **entirely locally** and costs **$0 to operate**.

---

# System Architecture

```
AI Tools
│
├ Claude Code
├ Cursor
├ ChatGPT
└ Gemini
     │
     ▼
Collectors
│
├ ActivityWatch ingestion
├ Claude Code hook logger
├ Repo/git analyzer
└ Browser activity collector
     │
     ▼
SQLite Database
     │
     ▼
Metrics Processor
     │
     ▼
Streamlit Dashboard
```

---

# Technology Stack

| Component | Technology |
|-----------|------------|
Collectors | Python |
Database | SQLite |
Activity tracking | ActivityWatch |
Dashboard | Streamlit |
Scheduling | Windows Task Scheduler / cron |
Charts | Streamlit charts |

All tools are **free and open source**.

---

# Folder Structure

```
ai-dashboard/
│
├ collectors/
│   ├ activitywatch_collector.py
│   ├ claude_hook.py
│   ├ browser_collector.py
│   └ repo_analyzer.py
│
├ processors/
│   ├ sessionizer.py
│   └ metrics_calculator.py
│
├ database/
│   ├ schema.sql
│   └ usage.db
│
├ dashboard/
│   └ app.py
│
├ config/
│   └ subscriptions.yaml
│
└ docs/
    └ ai-usage-dashboard-plan.md
```

---

# Database Schema

## raw_events

Stores all raw telemetry events.

| column | description |
|------|-------------|
timestamp | event timestamp |
tool | claude_code / cursor / chatgpt / gemini |
event_type | prompt / tool_call / window_active |
session_id | session identifier |
repo | repository name |
cwd | working directory |
prompt_chars | prompt size |
estimated_tokens | estimated tokens |
tool_name | tool invoked |
success | tool success |
duration_seconds | duration |
metadata_json | extra data |

---

## sessions

Aggregated session data.

| column | description |
|------|-------------|
session_id | session identifier |
tool | AI tool |
start_time | start time |
end_time | end time |
active_seconds | duration |
repo | repository |
prompt_count | prompts |
tool_call_count | tool calls |
failure_count | failures |
files_touched | files edited |
subagent_count | subagent usage |

---

## daily_metrics

Daily aggregated metrics.

| column | description |
|------|-------------|
date | day |
tool | AI tool |
active_minutes | time spent |
session_count | sessions |
prompt_count | prompts |
accepted_edits | accepted edits |
estimated_tokens | tokens |
estimated_cost | estimated API cost |

---

# Metrics

## Time Metrics

### Active Time

Time when the tool window is active and the user is not AFK.

Source: ActivityWatch

```
active_minutes = sum(non_afk_seconds) / 60
```

---

### Session Count

A session begins when:

- tool becomes active
- previous inactivity >5 minutes
- tool switches

A session ends when:

- user goes AFK
- tool switches
- inactivity >5 minutes

---

### Average Session Duration

```
average_session = active_time / session_count
```

---

# Interaction Metrics

## Prompt Count

Number of prompts sent to the AI.

Instrumentation:

Claude Code  
- hook event `UserPromptSubmit`

Cursor  
- estimated via editor interaction

ChatGPT / Gemini  
- browser activity detection

---

## Prompt Length

Token estimate:

```
tokens ≈ characters / 4
```

---

## Response Count

Number of AI responses returned.

---

# Coding Metrics

## Tool Calls

Number of AI tool executions.

Examples:

- bash
- file edit
- search
- test

Claude Code events:

```
PreToolUse
PostToolUse
PostToolUseFailure
```

---

## Tool Failure Rate

```
failure_rate = failures / tool_calls
```

---

## Files Edited

Number of unique files modified during a session.

Sources:

- tool events
- git diff

---

## Accepted Edits

Definition:

AI-generated code edits accepted into the project.

Measurement methods:

### Direct acceptance

If the tool exposes acceptance events.

### Diff survival method

1. detect AI edit event  
2. snapshot file  
3. check file after delay  
4. if change persists → accepted  

---

# Repo Metrics

## Repo Usage

Tracks which repository AI was used in.

Sources:

- Claude Code hook `cwd`
- Cursor workspace
- window title

---

## Repo Time

Total AI usage time per repository.

---

# Productivity Metrics

## Commit After AI

```
commit_after_ai_rate =
commits_within_30_minutes_of_ai_session
/
ai_sessions
```

---

## Files Changed

Files modified during AI sessions.

---

## Deep Work Sessions

Defined as:

```
duration >= 25 minutes
AND
tool_switches <= 1
```

---

# Cost Metrics

Since subscriptions hide exact usage costs, estimate them.

---

## Subscription Cost

Defined in:

```
config/subscriptions.yaml
```

Example:

```
claude: 20
cursor: 20
chatgpt: 20
gemini: 20
```

Daily allocation:

```
daily_cost = monthly_cost / 30
```

---

## Estimated API Cost

```
estimated_cost =
estimated_tokens * model_price
```

Used for comparison only.

---

# Collectors

## ActivityWatch Collector

Poll ActivityWatch API every 5 minutes.

Collect:

- active window
- AFK state
- browser URL

Insert events into `raw_events`.

---

## Claude Code Hook Logger

Configure Claude Code hooks to emit events.

Example event:

```
{
 "event":"user_prompt_submit",
 "session_id":"abc123",
 "repo":"poptasks",
 "prompt_chars":420
}
```

Store event in database.

---

## Repo Analyzer

Runs periodically.

Collects:

- git diff
- commits
- changed files

Maps results to sessions.

---

## Browser Collector

Detects browser activity.

Tracks usage of:

- ChatGPT
- Gemini

Based on URL detection.

---

# Session Processing

Script: `sessionizer.py`

Steps:

1. read raw events  
2. group events by tool  
3. detect inactivity gaps  
4. generate sessions  
5. compute session metrics  

---

# Metrics Processing

Script: `metrics_calculator.py`

Aggregates:

- daily metrics
- repo metrics
- productivity metrics

---

# Dashboard

Framework: **Streamlit**

Run the dashboard:

```
streamlit run dashboard/app.py
```

Open:

```
http://localhost:8501
```

---

# Dashboard Pages

## Overview

Shows:

- total AI time today
- sessions
- prompts
- tokens
- estimated cost

Charts:

- usage by tool
- daily trend

---

## Tool Breakdown

Displays per tool:

- sessions
- prompts
- active time
- tool calls
- failures

---

## Coding Productivity

Shows:

- accepted edits
- files changed
- commits after AI
- repo usage

---

## Session Analytics

Charts:

- session duration distribution
- session counts
- deep work sessions

---

## Time Heatmap

Hourly AI usage heatmap.

---

# Scheduling

Collectors run periodically.

Example schedule:

Every 5 minutes:

```
collect activitywatch events
```

Every 10 minutes:

```
run repo analyzer
```

---

# MVP Build Order

Step 1

Install dependencies.

```
pip install streamlit sqlite-utils
```

Install ActivityWatch.

---

Step 2

Create database schema.

---

Step 3

Implement ActivityWatch collector.

Track:

- active window
- AFK state

---

Step 4

Add Claude Code hooks.

Capture:

- prompts
- tool calls
- failures

---

Step 5

Implement sessionizer.

---

Step 6

Build Streamlit dashboard.

---

# Future Improvements

Cursor extension:

- detect prompt events
- detect accepted edits

Browser extension:

- track prompts in ChatGPT
- track prompts in Gemini

AI workflow analytics:

- prompt → edit → commit chains
- productivity insights

---

# Example Dashboard Output

```
AI Usage Today

Total AI Time: 4h 12m

Claude Code
  sessions: 7
  prompts: 42
  tool calls: 85

Cursor
  sessions: 3
  prompts: 18

ChatGPT
  sessions: 2
  prompts: 10

Gemini
  sessions: 1
  prompts: 3
```

All data remains **local and private**.