# jira-stackrank

Deterministic Jira sprint stack-ranking CLI for a single board.

The tool:
- finds the active sprint on the configured Jira board
- fetches all board-visible sprint issues
- removes configured sub-task issue types
- computes the target order from the ranking rules
- shows a Rich dry-run preview by default
- applies Jira rank changes only when `--apply` is provided

## How It Works

The final order is:

1. Rank 1: client production bugs and vulnerabilities
2. Rank 2: enhancements and tasks, with epic-linked work grouped together
3. Rank 3: internal bugs

Within each bucket, ordering is deterministic. The tool also minimizes Jira move operations by keeping the longest already-correct subsequence in place.

## Project Layout

```text
jira_stackrank/
  cli_output.py      Rich terminal output and logging helpers
  config.py          .env parsing and runtime settings
  jira_client.py     Jira API access and response mapping
  main.py            CLI flow and move planning
  ranking_engine.py  Ranking rules and ordering logic

tests/
  unit/              Focused unit tests
  integration/       End-to-end CLI flow tests with mocked Jira client

docs/
  prd.md             Original product requirements
  ARCHITECTURE.md    Codebase walkthrough and data flow
  OPERATIONS.md      Runbook for dry runs and apply mode
  TESTING.md         Test strategy and conventions
  CHANGELOG.md       Human-readable project history
```

## Setup

```bash
./scripts/bootstrap-asdf.sh
poetry config virtualenvs.in-project true
poetry install
cp .env.example .env
```

This repo pins tool versions in `.tool-versions` and plugin sources in `.tool-plugins`.

Fill in `.env` with Jira credentials and board-specific values.

## Configuration

Environment variables:

- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_BASE_URL`
- `BOARD_ID`
- `CLIENT_BUG_JQL`
- `EPIC_TITLE_PREFIX_LENGTH`
- `SUBTASK_ISSUE_TYPES`
- `TITLE_TRUNCATION_LIMIT`
- `REQUEST_TIMEOUT_SECONDS`

See [.env.example](/Users/aapa/workspace/projects/personal/auto-stack-rank-ontic-jira/.env.example) for the current template.

## Usage

Dry run:

```bash
poetry run jira-stackrank
```

Apply rank changes:

```bash
poetry run jira-stackrank --apply
```

Apply rank changes with per-move confirmation:

```bash
poetry run jira-stackrank --apply --confirm-each
```

## Output

The CLI uses Rich output for:

- step-by-step execution status
- a ranked preview table
- move progress during apply
- an execution summary with duration

Run logs are also written to the local `logs/` directory.

## Testing

Run the full suite:

```bash
poetry run pytest -q
```

Run only unit tests:

```bash
poetry run pytest -q tests/unit
```

Run only integration tests:

```bash
poetry run pytest -q tests/integration
```
