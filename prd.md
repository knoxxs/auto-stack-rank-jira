# Jira Sprint Auto Stack Rank Utility

## MVP Product Requirements Document

Version: v1
Owner: Director of Engineering
Type: Solo CLI Automation Utility

---

# 1. Purpose

Automate deterministic stack ranking of issues in the active sprint of Jira Board `1124` according to predefined business rules.

This is:

* A local CLI utility
* Single user
* Single board
* No UI
* No scheduling
* No multi-user support

---

# 2. Objective

When executed, the utility:

1. Fetches all issues visible on Board `1124` that belong to the active sprint
2. Computes the correct deterministic stack rank order
3. Reorders issues in Jira only if required
4. Defaults to dry run unless `--apply` is specified

**Success Criteria**

* Active sprint order exactly matches ranking rules
* Zero unnecessary rank API calls
* Idempotent behavior

---

# 3. Scope

## In Scope

* Jira Cloud
* Board ID: `1124`
* Active sprint only
* All issues in sprint including Done
* Ignore issue types: `BE Sub-task`, `Bug Sub-task`, `FE Sub-task`, `QA Sub-task`
* Treat `Vulnerability` as `Client Bug`
* Deterministic full ordering logic
* CLI execution
* Poetry-based project
* Project-local virtual environment
* Console dry-run output
* Skip rank API call if order already correct

## Out of Scope

* Multiple boards
* Multiple users
* UI
* Slack integration
* Scheduling
* Undo feature
* Configurable rules
* Analytics
* AI logic

---

# 4. Development & Environment Requirements

## Dependency Management

* Use **Poetry**
* Project must be initialized with:

```bash
poetry init
```

## Virtual Environment

* Use project-scoped virtual environment:

```bash
poetry config virtualenvs.in-project true
```

This creates:

```
.venv/
```

inside project root.

No global Python usage allowed.

---

## Project Structure

```
jira-stackrank/
│
├── pyproject.toml
├── poetry.lock
├── .env
├── .gitignore
├── jira_stackrank/
│   ├── __init__.py
│   ├── main.py
│   ├── jira_client.py
│   ├── ranking_engine.py
│   ├── config.py
```

---

# 5. Authentication

Jira Cloud Basic Auth using:

* `JIRA_EMAIL`
* `JIRA_API_TOKEN`
* `JIRA_BASE_URL`

Stored in `.env` file.

`.env` must be in `.gitignore`.

No hardcoded secrets.

---

# 6. Data Fetch Strategy

## Step 1 – Get Active Sprint

```
GET /rest/agile/1.0/board/1124/sprint?state=active
```

Extract `sprintId`.

---

## Step 2 – Fetch Issues Scoped to Board + Sprint

```
GET /rest/agile/1.0/board/1124/sprint/{sprintId}/issue?startAt=0&maxResults=100
```

Pagination required until all issues are fetched.

This guarantees:

* Board filter applied
* Only visible board issues
* Only active sprint issues
* Includes Done
* Matches UI ordering

Note:

* Jira may return sub-task issue types in sprint results
* The utility must fetch all returned sprint issues, then exclude only:
  * `BE Sub-task`
  * `Bug Sub-task`
  * `FE Sub-task`
  * `QA Sub-task`
* After excluding ignored issue types, the utility must reassign current positions based on the remaining board order
* No other issue types may be ignored unless explicitly defined here

---

# 7. Ranking Rules

Final global order:

```
Rank 1
→ Rank 2
→ Rank 3
```

All issues must appear exactly once.

Stable ordering preserved for ties.

---

## Rank 1 – Client Production Bugs

Criteria:

* `type = Bug` or `type = Vulnerability`
* `Pod = pod-iicm`
* `Found in Environment = Production`
* `Client != Ontic Technologies`

Sorting:

1. Priority (highest first)
2. Stable original order

---

## Rank 2 – Enhancements & Tasks

Sequence:

1. Enhancements without epic or Enhancements/Tasks with epic (with all Enhancements/Tasks of same epic grouped together)
2. Tasks without epic

---

### Epic Group Ordering

Epic groups ordered by:

1. Existing order

---

### Within Each Epic Group

Sort by:

1. Priority
2. Stable order

---

### Non-Epic Issues

Sort by:

1. Priority
2. Stable order

---

## Rank 3 – Internal Bugs

Definition:

All remaining `type = Bug` not in Rank 1.

Sort by:

1. Priority
2. Stable order

---

# 8. Global Algorithm

1. Fetch issues in current board order
2. Assign original index
3. Determine rank bucket
4. Partition into Rank 1, Rank 2, Rank 3
5. Apply sorting rules
6. Concatenate buckets
7. Produce final ordered list

Deterministic full rebuild every run.

---

# 9. Reordering Strategy

Use:

```
POST /rest/agile/1.0/issue/rank
```

Execution logic:

1. Compare current order with computed final order
2. If identical → exit without any rank API calls
3. If different:

    * Iterate through final order top to bottom
    * Move issue only if its position differs
    * Skip move if already correctly positioned

This ensures:

* No unnecessary rerank calls
* Minimal API usage
* Idempotent execution
* Safe repeated runs

---

# 10. CLI Interface

## Dry Run (default)

```bash
poetry run jira-stackrank
```

## Apply Changes

```bash
poetry run jira-stackrank --apply
```

---

# 11. Dry Run Output

Console table:

| Key | Type | Bug Kind | Title | Priority | Current Position | New Position | Current Rank Value | Rank Bucket |

Column definitions:

* `Bug Kind` is populated only for `Bug` and `Vulnerability`
* `Bug Kind = Client Bug` for Rank 1 bug-like issues
* `Bug Kind = Internal Bug` for Rank 3 bug-like issues
* `Title` should show the issue summary in truncated form for console readability
* `Current Rank Value` is the current Jira rank field value from the fetched issue data

Summary:

```
Total issues: X
Moves required: Y
```

If `Moves required = 0`:

```
No reordering required.
```

---

# 12. Error Handling

* No active sprint → graceful exit
* API failure → abort execution
* Missing priority → treated as lowest
* Unknown fields → handled safely
* Any unsupported non-ignored issue type → abort execution with clear error

Dry run must never mutate state.

---

# 13. Operational Logging

Runtime logs must include:

* Jira base URL
* Board ID, board name, and board type
* Selected active sprint ID and sprint name
* Total fetched issue count
* Fetched issue type counts
* Count of ignored sub-task issues
* Count of issues remaining for ranking

These logs are for console visibility only. No file output.

---

# 14. Non-Functional Requirements

* Handles up to 200 sprint issues
* Pagination safe
* No hardcoded custom field IDs
* Stable sorting
* Deterministic
* Idempotent
* Minimal dependencies

---

# 15. Definition of Done

MVP is complete when:

* Running dry run produces correct proposed ordering
* Running with `--apply` results in exact board reordering
* Re-running after apply results in zero moves
* No unnecessary rank API calls are made
