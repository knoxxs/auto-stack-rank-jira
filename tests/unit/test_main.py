import unittest
from unittest.mock import patch

from jira_stackrank.config import Settings
from jira_stackrank.main import MovePlan, apply_moves, fetch_rankable_issues, handle_noop_run
from jira_stackrank.ranking_engine import IssueRecord, RankBucket, RankedIssue


def settings() -> Settings:
    return Settings(
        jira_email="test@example.com",
        jira_api_token="token",
        jira_base_url="https://example.atlassian.net",
        board_id=1124,
        client_bug_jql='type in ("Bug", "Vulnerability")',
        epic_title_prefix_length=16,
        subtask_issue_types=("be sub-task", "bug sub-task", "fe sub-task", "qa sub-task"),
        title_truncation_limit=36,
        request_timeout_seconds=30,
    )


def issue(key: str, issue_type: str, original_index: int) -> IssueRecord:
    return IssueRecord(
        key=key,
        issue_type=issue_type,
        summary=key,
        original_index=original_index,
        priority_name="High",
        priority_rank=0,
        current_rank_value=None,
        is_done=False,
        labels=(),
        epic_key=None,
        epic_summary=None,
        is_client_bug=False,
        pod=None,
        found_in_environment=None,
        client=None,
    )


class FakeRankMover:
    def __init__(self) -> None:
        self.after_moves: list[tuple[str, str]] = []
        self.before_moves: list[tuple[str, str]] = []

    def move_issue_after(self, issue_key: str, after_issue_key: str) -> None:
        self.after_moves.append((issue_key, after_issue_key))

    def move_issue_before(self, issue_key: str, before_issue_key: str) -> None:
        self.before_moves.append((issue_key, before_issue_key))


class MainHelperTests(unittest.TestCase):
    def test_handle_noop_run_emits_summary_when_there_are_no_moves(self) -> None:
        ranked = [
            RankedIssue(
                key="TASK-1",
                issue_type="Task",
                summary="TASK-1",
                current_position=1,
                new_position=1,
                priority_name="High",
                current_rank_value=None,
                kind=None,
                rank_bucket=RankBucket.RANK_2,
            )
        ]

        with patch("jira_stackrank.main.print_no_changes") as no_changes_mock:
            with patch("jira_stackrank.main.print_execution_summary") as summary_mock:
                result = handle_noop_run(ranked, [], apply_mode=False, started_at=0.0)

        self.assertTrue(result)
        no_changes_mock.assert_called_once()
        summary_mock.assert_called_once()

    def test_handle_noop_run_returns_false_when_moves_exist(self) -> None:
        result = handle_noop_run([], [MovePlan("A", "B", "after")], apply_mode=False, started_at=0.0)
        self.assertFalse(result)

    def test_apply_moves_executes_before_and_after_moves(self) -> None:
        mover = FakeRankMover()
        moves = [
            MovePlan("A", "B", "before"),
            MovePlan("C", "D", "after"),
        ]

        with patch("jira_stackrank.main.print_apply_section"):
            with patch("jira_stackrank.main.print_apply_complete"):
                with patch("jira_stackrank.main.print_move_step"):
                    applied = apply_moves(mover, moves, confirm_each=False)

        self.assertTrue(applied)
        self.assertEqual([("A", "B")], mover.before_moves)
        self.assertEqual([("C", "D")], mover.after_moves)

    def test_apply_moves_stops_when_confirmation_is_rejected(self) -> None:
        mover = FakeRankMover()
        moves = [MovePlan("A", "B", "before")]

        with patch("jira_stackrank.main.confirm_move", return_value=False):
            with patch("jira_stackrank.main.print_apply_section"):
                applied = apply_moves(mover, moves, confirm_each=True)

        self.assertFalse(applied)
        self.assertEqual([], mover.before_moves)
        self.assertEqual([], mover.after_moves)

    def test_fetch_rankable_issues_filters_subtasks_and_reindexes(self) -> None:
        client = unittest.mock.Mock()
        client.discover_fields.return_value = "fields"
        client.get_priority_order.return_value = {"high": 0}
        client.get_active_sprint_issues.return_value = [
            issue("SUB-1", "BE Sub-task", 0),
            issue("TASK-1", "Task", 1),
            issue("TASK-2", "Task", 2),
        ]

        issues = fetch_rankable_issues(client, settings(), sprint_id=10)

        self.assertEqual(["TASK-1", "TASK-2"], [item.key for item in issues])
        self.assertEqual([0, 1], [item.original_index for item in issues])


if __name__ == "__main__":
    unittest.main()
