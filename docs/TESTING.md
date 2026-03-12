# Testing

## Test Layout

The suite is split into two groups.

### `tests/unit`

Focused tests for:

- config parsing
- Jira client helpers
- ranking logic
- move planning
- extracted CLI helper functions

These should stay fast and isolate a specific behavior.

### `tests/integration`

Higher-level tests for:

- CLI orchestration
- end-to-end flow through `main()`
- collaboration between modules using mocked Jira client behavior

## Running Tests

Run everything:

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

## Testing Guidance

- Prefer unit tests for ranking and move-planning rules.
- Add regression tests whenever a production bug is found.
- If a helper can fail due to data-shaping or pagination, test that helper directly.
- Keep integration tests focused on orchestration, not on live Jira access.

## Current Coverage Focus

The suite currently emphasizes:

- ranking correctness
- move plan correctness
- Jira field discovery and pagination behavior
- CLI dry run vs apply flow

There is no live Jira integration test suite. All integration tests are mocked.
