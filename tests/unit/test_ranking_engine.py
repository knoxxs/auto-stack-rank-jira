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
        request_timeout_seconds=30,
    )


def issue(
    key: str,
    issue_type: str,
    original_index: int,
    priority_rank: int,
    epic_key: str | None,
    epic_summary: str | None = None,
    priority_name: str | None = None,
    is_client_bug: bool = False,
) -> IssueRecord:
    """
    Create an IssueRecord test fixture with the specified ranking and epic metadata.
    
    Parameters:
        key (str): Issue identifier and summary.
        issue_type (str): Issue type.
        original_index (int): Original position before ranking.
        priority_rank (int): Numeric priority rank.
        epic_key (str | None): Associated epic identifier, if any.
        epic_summary (str | None): Associated epic summary, if any.
        priority_name (str | None): Priority name; defaults to a name derived from priority_rank.
        is_client_bug (bool): Whether the issue is classified as a client bug.
    
    Returns:
        IssueRecord: An initialized issue record with default test state.
    """
    return IssueRecord(
        key=key,
        issue_type=issue_type,
        summary=key,
        original_index=original_index,
        priority_name=priority_name or f"P{priority_rank}",
        priority_rank=priority_rank,
        current_rank_value=None,
        is_done=False,
        labels=(),
        epic_key=epic_key,
        epic_summary=epic_summary,
        is_client_bug=is_client_bug,
        pod=None,
        found_in_environment=None,
        client=None,
    )


class ComputeRankedOrderTests(unittest.TestCase):
    def test_custom_request_is_treated_as_task_in_rank_2(self) -> None:
        issues = [
            issue("CCR-1", "Custom Request", 0, 1, None),
            issue("ENH-1", "Enhancement", 1, 2, None),
        ]

        ranked = {item.key: item for item in compute_ranked_order(issues, settings())}

        self.assertIsNone(ranked["CCR-1"].kind)
        self.assertEqual("Rank 2", ranked["CCR-1"].rank_bucket.value)

    def test_property_is_treated_as_task_in_rank_2(self) -> None:
        issues = [
            issue("CCR-799", "Property", 0, 1, None),
            issue("ENH-1", "Enhancement", 1, 2, None),
        ]

        ranked = {item.key: item for item in compute_ranked_order(issues, settings())}

        self.assertIsNone(ranked["CCR-799"].kind)
        self.assertEqual("Rank 2", ranked["CCR-799"].rank_bucket.value)

    def test_vulnerability_is_treated_as_rank_1_client_bug(self) -> None:
        issues = [issue("BUG-1", "Vulnerability", 0, 2, None)]

        ranked = compute_ranked_order(issues, settings())

        self.assertEqual("Client Bug", ranked[0].kind)
        self.assertEqual("Rank 1", ranked[0].rank_bucket.value)

    def test_regular_bug_stays_in_rank_3(self) -> None:
        issues = [issue("BUG-1", "Bug", 0, 2, None)]

        ranked = compute_ranked_order(issues, settings())

        self.assertEqual("Internal Bug", ranked[0].kind)
        self.assertEqual("Rank 3", ranked[0].rank_bucket.value)

    def test_medium_and_low_client_bugs_rank_after_tasks_and_before_internal_bugs(self) -> None:
        issues = [
            issue("CLIENT-LOW", "Bug", 0, 3, None, priority_name="Low", is_client_bug=True),
            issue("INTERNAL-CRITICAL", "Bug", 1, 0, None, priority_name="Critical"),
            issue("ENH-1", "Enhancement", 2, 1, None, priority_name="High"),
            issue("CLIENT-MEDIUM", "Bug", 3, 2, None, priority_name="Medium", is_client_bug=True),
            issue("CLIENT-HIGH", "Bug", 4, 1, None, priority_name="High", is_client_bug=True),
        ]

        ranked = compute_ranked_order(issues, settings())
        by_key = {item.key: item for item in ranked}
        target_order = [item.key for item in sorted(ranked, key=lambda item: item.new_position)]

        self.assertEqual(
            ["CLIENT-HIGH", "ENH-1", "CLIENT-MEDIUM", "CLIENT-LOW", "INTERNAL-CRITICAL"],
            target_order,
        )
        self.assertEqual("Rank 1", by_key["CLIENT-HIGH"].rank_bucket.value)
        self.assertEqual("Rank 2.5", by_key["CLIENT-MEDIUM"].rank_bucket.value)
        self.assertEqual("Rank 2.5", by_key["CLIENT-LOW"].rank_bucket.value)
        self.assertEqual("Client Bug", by_key["CLIENT-MEDIUM"].kind)
        self.assertEqual("Client Bug", by_key["CLIENT-LOW"].kind)
        self.assertEqual("Internal Bug", by_key["INTERNAL-CRITICAL"].kind)

    def test_medium_vulnerability_ranks_after_tasks_as_deferred_client_bug(self) -> None:
        issues = [
            issue("VULN-1", "Vulnerability", 0, 2, None, priority_name="Medium"),
            issue("TASK-1", "Task", 1, 1, None, priority_name="High"),
        ]

        ranked = compute_ranked_order(issues, settings())
        by_key = {item.key: item for item in ranked}
        target_order = [item.key for item in sorted(ranked, key=lambda item: item.new_position)]

        self.assertEqual(["TASK-1", "VULN-1"], target_order)
        self.assertEqual("Client Bug", by_key["VULN-1"].kind)
        self.assertEqual("Rank 2.5", by_key["VULN-1"].rank_bucket.value)

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
