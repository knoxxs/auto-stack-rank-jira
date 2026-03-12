import unittest

from jira_stackrank.config import Settings
from jira_stackrank.ranking_engine import IssueRecord, compute_ranked_order


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
    )


def issue(
    key: str,
    issue_type: str,
    original_index: int,
    priority_rank: int,
    epic_key: str | None,
    epic_summary: str | None = None,
) -> IssueRecord:
    return IssueRecord(
        key=key,
        issue_type=issue_type,
        summary=key,
        original_index=original_index,
        priority_name=f"P{priority_rank}",
        priority_rank=priority_rank,
        current_rank_value=None,
        is_done=False,
        labels=(),
        epic_key=epic_key,
        epic_summary=epic_summary,
        is_client_bug=False,
        pod=None,
        found_in_environment=None,
        client=None,
    )


class ComputeRankedOrderTests(unittest.TestCase):
    def test_kind_marks_epic_items_for_tasks_and_enhancements(self) -> None:
        issues = [
            issue("ENH-1", "Enhancement", 0, 2, "EPIC-A", "Customer onboarding"),
            issue("TASK-1", "Task", 1, 1, "EPIC-A", "Customer onboarding"),
            issue("TASK-2", "Task", 2, 1, None),
        ]

        ranked = {item.key: item for item in compute_ranked_order(issues, settings())}

        self.assertEqual("Customer onboard", ranked["ENH-1"].kind)
        self.assertEqual("Customer onboard", ranked["TASK-1"].kind)
        self.assertIsNone(ranked["TASK-2"].kind)

    def test_rank_2_epic_groups_keep_existing_order(self) -> None:
        issues = [
            issue("ENH-1", "Enhancement", 0, 3, "EPIC-A"),
            issue("ENH-2", "Enhancement", 1, 1, "EPIC-B"),
            issue("ENH-3", "Enhancement", 2, 1, "EPIC-A"),
            issue("ENH-4", "Enhancement", 3, 2, "EPIC-B"),
        ]

        ranked = compute_ranked_order(issues, settings())
        target_order = [item.key for item in sorted(ranked, key=lambda item: item.new_position)]

        self.assertEqual(["ENH-3", "ENH-1", "ENH-2", "ENH-4"], target_order)

    def test_rank_2_groups_tasks_with_their_epic(self) -> None:
        issues = [
            issue("ENH-1", "Enhancement", 0, 2, "EPIC-A"),
            issue("TASK-1", "Task", 1, 1, "EPIC-A"),
            issue("ENH-2", "Enhancement", 2, 1, None),
            issue("TASK-2", "Task", 3, 1, None),
        ]

        ranked = compute_ranked_order(issues, settings())
        target_order = [item.key for item in sorted(ranked, key=lambda item: item.new_position)]

        self.assertEqual(["TASK-1", "ENH-1", "ENH-2", "TASK-2"], target_order)

    def test_rank_2_non_epic_tasks_stay_after_primary_band(self) -> None:
        issues = [
            issue("TASK-1", "Task", 0, 1, None),
            issue("ENH-1", "Enhancement", 1, 3, None),
            issue("TASK-2", "Task", 2, 2, "EPIC-A"),
            issue("ENH-2", "Enhancement", 3, 1, "EPIC-A"),
        ]

        ranked = compute_ranked_order(issues, settings())
        target_order = [item.key for item in sorted(ranked, key=lambda item: item.new_position)]

        self.assertEqual(["ENH-1", "ENH-2", "TASK-2", "TASK-1"], target_order)


if __name__ == "__main__":
    unittest.main()
