# Operations

## Normal Workflow

### Dry run

Use dry run first to inspect the computed order without changing Jira:

```bash
poetry run jira-stackrank
```

### Apply changes

Apply the planned Jira rank updates:

```bash
poetry run jira-stackrank --apply
```

### Apply with confirmation

Prompt before each move:

```bash
poetry run jira-stackrank --apply --confirm-each
```

## What To Check Before Apply

- `.env` points to the correct Jira site and board
- the active sprint shown in the output is the expected sprint
- the preview table looks reasonable
- the move count is plausible

## Logs

Each run writes a log file into `logs/`.

Use logs to inspect:

- board and sprint selection
- issue counts
- skipped sub-task counts
- move operations applied
- Jira API errors

## Common Failure Modes

### Multiple active sprints

The tool logs a warning and selects the sprint with the highest id.

### Duplicate custom field names

The tool fails fast. Resolve the duplicate field names in Jira before running again.

### Timeout or connectivity issues

Check:

- `JIRA_BASE_URL`
- credentials
- network access
- `REQUEST_TIMEOUT_SECONDS`

### Unsupported issue types

The CLI logs a warning when Jira returns issue types outside the supported ranking rules.

## Safe Recovery

If a dry run looks wrong:

1. Do not run with `--apply`
2. inspect `.env`
3. inspect the log file
4. verify the current active sprint and board in Jira
5. re-run after correcting configuration or rules
