from pathlib import Path
import unittest
from unittest.mock import patch

from jira_stackrank.config import Settings
from jira_stackrank.jira_client import BoardInfo, FieldMap, SprintInfo
from jira_stackrank.main import main
from jira_stackrank.ranking_engine import IssueRecord


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


def issue(key: str, original_index: int, priority_rank: int) -> IssueRecord:
    return IssueRecord(
        key=key,
        issue_type="Task",
        summary=key,
        original_index=original_index,
        priority_name=f"P{priority_rank}",
        priority_rank=priority_rank,
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


class FakeJiraClient:
    def __init__(self, issues: list[IssueRecord], sprint: SprintInfo | None) -> None:
        self._issues = issues
        self._sprint = sprint
        self.after_moves: list[tuple[str, str]] = []
        self.before_moves: list[tuple[str, str]] = []

    def get_board_info(self) -> BoardInfo:
        return BoardInfo(board_id=1124, board_name="Board", board_type="scrum")

    def discover_fields(self) -> FieldMap:
        return FieldMap(
            rank_field_id="customfield_rank",
            epic_link_field_id="customfield_epic",
            pod_field_id="customfield_pod",
            found_in_environment_field_id="customfield_env",
            client_field_id="customfield_client",
        )

    def get_priority_order(self) -> dict[str, int]:
        return {"p1": 0, "p2": 1}

    def get_active_sprint(self) -> SprintInfo | None:
        return self._sprint

    def get_active_sprint_issues(
        self, sprint_id: int, field_map: FieldMap, priority_order: dict[str, int]
    ) -> list[IssueRecord]:
        return self._issues

    def move_issue_after(self, issue_key: str, after_issue_key: str) -> None:
        self.after_moves.append((issue_key, after_issue_key))

    def move_issue_before(self, issue_key: str, before_issue_key: str) -> None:
        self.before_moves.append((issue_key, before_issue_key))


class MainIntegrationTests(unittest.TestCase):
    def test_main_returns_zero_when_no_active_sprint_exists(self) -> None:
        client = FakeJiraClient(issues=[], sprint=None)

        with patch("jira_stackrank.main.configure_logging", return_value=Path("logs/test.log")):
            with patch("jira_stackrank.main.load_settings", return_value=settings()):
                with patch("jira_stackrank.main.JiraClient", return_value=client):
                    with patch("sys.argv", ["jira-stackrank"]):
                        exit_code = main()

        self.assertEqual(0, exit_code)
        self.assertEqual([], client.before_moves)
        self.assertEqual([], client.after_moves)

    def test_main_applies_rank_moves_when_apply_flag_is_present(self) -> None:
        client = FakeJiraClient(
            issues=[
                issue("TASK-1", original_index=0, priority_rank=2),
                issue("TASK-2", original_index=1, priority_rank=1),
            ],
            sprint=SprintInfo(sprint_id=55, sprint_name="Sprint 55"),
        )

        with patch("jira_stackrank.main.configure_logging", return_value=Path("logs/test.log")):
            with patch("jira_stackrank.main.load_settings", return_value=settings()):
                with patch("jira_stackrank.main.JiraClient", return_value=client):
                    with patch("sys.argv", ["jira-stackrank", "--apply"]):
                        exit_code = main()

        self.assertEqual(0, exit_code)
        self.assertEqual([("TASK-2", "TASK-1")], client.before_moves)
        self.assertEqual([], client.after_moves)


if __name__ == "__main__":
    unittest.main()
