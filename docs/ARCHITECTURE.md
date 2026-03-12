# Architecture

## Overview

The tool follows a simple linear flow:

1. Load runtime settings from `.env`
2. Connect to Jira and discover board/sprint context
3. Fetch sprint issues and enrich them with Jira metadata
4. Compute the deterministic target order
5. Build the minimal move plan needed to reach that order
6. Show a dry-run preview, or apply the moves to Jira

## Module Responsibilities

### `jira_stackrank/config.py`

- parses `.env`
- applies defaults
- validates required configuration

### `jira_stackrank/jira_client.py`

- talks to Jira REST APIs
- discovers custom field IDs
- fetches active sprint issues
- enriches issues with client-bug and epic-summary data
- applies rank changes

### `jira_stackrank/ranking_engine.py`

- classifies issues into rank buckets
- sorts issues inside each bucket
- produces the final ranked order

### `jira_stackrank/main.py`

- owns the CLI flow
- orchestrates config loading, Jira fetches, ranking, preview, and apply
- computes the move plan that minimizes unnecessary Jira rank updates

### `jira_stackrank/cli_output.py`

- centralizes Rich terminal output
- configures logging
- renders execution status, rank preview tables, move progress, and summary panels

## Data Flow

### 1. Settings

`load_settings()` reads `.env` and returns a `Settings` object used everywhere else.

### 2. Jira Fetch

`JiraClient`:

- resolves the active sprint
- fetches board-scoped sprint issues with pagination
- maps Jira payloads into `IssueRecord`

### 3. Ranking

`compute_ranked_order()` transforms `IssueRecord` values into `RankedIssue` values.

This is the core ranking step:

- Rank 1: client bugs and vulnerabilities
- Rank 2: enhancements and tasks, with epic-linked grouping
- Rank 3: internal bugs

### 4. Move Planning

`build_move_plan()` compares current order vs target order and keeps the longest already-correct subsequence fixed. That reduces unnecessary Jira rank operations.

### 5. Apply

When `--apply` is passed, the CLI iterates over the computed `MovePlan` values and sends Jira rank update requests.

## Important Design Choices

- The CLI defaults to dry run.
- Multiple active sprints are resolved deterministically by choosing the highest sprint id.
- Duplicate Jira custom field names are treated as an error.
- Rich output is centralized in one module instead of being spread across business logic.
