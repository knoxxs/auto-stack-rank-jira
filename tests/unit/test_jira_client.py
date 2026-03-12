import json
import unittest
from unittest.mock import MagicMock, patch

from jira_stackrank.config import Settings
from jira_stackrank.jira_client import (
    FieldMap,
    JiraClient,
    JiraClientError,
    LOGGER,
    _priority_rank,
    _string_list,
    _string_value,
)
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
        request_timeout_seconds=45,
    )


class JiraClientTests(unittest.TestCase):
    def test_requested_issue_fields_skips_missing_optionals(self) -> None:
        client = JiraClient(settings())

        fields = client._requested_issue_fields(
            FieldMap(
                rank_field_id="customfield_rank",
                epic_link_field_id=None,
                pod_field_id="customfield_pod",
                found_in_environment_field_id=None,
                client_field_id="customfield_client",
            )
        )

        self.assertEqual(
            [
                "issuetype",
                "priority",
                "status",
                "summary",
                "labels",
                "customfield_rank",
                "customfield_pod",
                "customfield_client",
            ],
            fields,
        )

    def test_discover_fields_returns_expected_ids_when_unique(self) -> None:
        client = JiraClient(settings())

        with patch.object(
            client,
            "_request_json",
            return_value=[
                {"id": "customfield_rank", "name": "Rank"},
                {"id": "customfield_epic", "name": "Epic Link"},
                {"id": "customfield_pod", "name": "Pod"},
                {"id": "customfield_env", "name": "Found in Environment"},
                {"id": "customfield_client", "name": "Client"},
            ],
        ):
            field_map = client.discover_fields()

        self.assertEqual("customfield_rank", field_map.rank_field_id)
        self.assertEqual("customfield_epic", field_map.epic_link_field_id)
        self.assertEqual("customfield_pod", field_map.pod_field_id)
        self.assertEqual("customfield_env", field_map.found_in_environment_field_id)
        self.assertEqual("customfield_client", field_map.client_field_id)

    def test_discover_fields_rejects_duplicate_custom_field_names(self) -> None:
        client = JiraClient(settings())

        with patch.object(
            client,
            "_request_json",
            return_value=[
                {"id": "customfield_1", "name": "Pod"},
                {"id": "customfield_2", "name": "Pod"},
            ],
        ):
            with self.assertRaises(JiraClientError) as exc_info:
                client.discover_fields()

        self.assertIn("Multiple Jira fields matched Pod", str(exc_info.exception))

    def test_get_active_sprint_chooses_highest_id_when_multiple_are_active(self) -> None:
        client = JiraClient(settings())

        with patch.object(
            client,
            "_request_json",
            return_value={
                "values": [
                    {"id": 12, "name": "Sprint 12"},
                    {"id": 27, "name": "Sprint 27"},
                    {"id": 20, "name": "Sprint 20"},
                ]
            },
        ):
            with self.assertLogs(LOGGER.name, level="WARNING") as captured:
                sprint = client.get_active_sprint()

        self.assertIsNotNone(sprint)
        assert sprint is not None
        self.assertEqual(27, sprint.sprint_id)
        self.assertEqual("Sprint 27", sprint.sprint_name)
        self.assertIn("Multiple active sprints found", captured.output[0])
        self.assertIn("(27)", captured.output[0])

    def test_get_active_sprint_without_parallel_sprints_emits_no_warning(self) -> None:
        client = JiraClient(settings())

        with patch.object(
            client,
            "_request_json",
            return_value={"values": [{"id": 12, "name": "Sprint 12"}]},
        ):
            with patch.object(LOGGER, "warning") as warning_mock:
                sprint = client.get_active_sprint()

        self.assertIsNotNone(sprint)
        assert sprint is not None
        self.assertEqual(12, sprint.sprint_id)
        warning_mock.assert_not_called()

    def test_search_issues_follows_next_page_tokens(self) -> None:
        client = JiraClient(settings())

        with patch.object(
            client,
            "_request_json",
            side_effect=[
                {"issues": [{"key": "A"}], "nextPageToken": "token-1"},
                {"issues": [{"key": "B"}], "nextPageToken": None},
            ],
        ) as request_mock:
            issues = client._search_issues("project = TEST", ["summary"], 50)

        self.assertEqual([{"key": "A"}, {"key": "B"}], issues)
        self.assertEqual("token-1", request_mock.call_args_list[1].kwargs["body"]["nextPageToken"])

    def test_fetch_sprint_issues_paginates_and_preserves_original_indexes(self) -> None:
        client = JiraClient(settings())
        field_map = FieldMap("rank", "epic", "pod", "env", "client")
        priority_order = {"high": 0}

        def make_record(issue: dict[str, str], original_index: int, **_: object) -> IssueRecord:
            return IssueRecord(
                key=issue["key"],
                issue_type="Task",
                summary=issue["key"],
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

        with patch.object(
            client,
            "_request_json",
            side_effect=[
                {"issues": [{"key": "A"}, {"key": "B"}], "total": 3},
                {"issues": [{"key": "C"}], "total": 3},
            ],
        ) as request_mock:
            with patch.object(client, "_to_issue_record", side_effect=make_record):
                records = client._fetch_sprint_issues(77, field_map, priority_order)

        self.assertEqual(["A", "B", "C"], [record.key for record in records])
        self.assertEqual([0, 1, 2], [record.original_index for record in records])
        self.assertEqual(
            "issuetype,priority,status,summary,labels,rank,epic,pod,env,client",
            request_mock.call_args_list[0].args[2]["fields"],
        )
        self.assertEqual(2, request_mock.call_count)

    def test_get_active_sprint_issues_enriches_bugs_and_epic_summaries(self) -> None:
        client = JiraClient(settings())
        base_issues = [
            IssueRecord(
                key="BUG-1",
                issue_type="Bug",
                summary="Client bug",
                original_index=0,
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
            ),
            IssueRecord(
                key="TASK-1",
                issue_type="Task",
                summary="Task in epic",
                original_index=1,
                priority_name="Medium",
                priority_rank=1,
                current_rank_value=None,
                is_done=False,
                labels=(),
                epic_key="EPIC-1",
                epic_summary=None,
                is_client_bug=False,
                pod=None,
                found_in_environment=None,
                client=None,
            ),
        ]

        with patch.object(client, "_fetch_sprint_issues", return_value=base_issues):
            with patch.object(client, "_search_issue_keys", return_value={"BUG-1"}):
                with patch.object(client, "_get_issue_summaries", return_value={"EPIC-1": "Epic summary"}):
                    issues = client.get_active_sprint_issues(1, FieldMap(None, None, None, None, None), {})

        self.assertTrue(issues[0].is_client_bug)
        self.assertEqual("Epic summary", issues[1].epic_summary)

    def test_to_issue_record_maps_known_fields(self) -> None:
        client = JiraClient(settings())
        field_map = FieldMap("rank", "epic", "pod", "env", "client")
        issue = {
            "key": "TASK-1",
            "fields": {
                "issuetype": {"name": "Task"},
                "summary": "Do the thing",
                "priority": {"id": "1", "name": "High"},
                "status": {"statusCategory": {"name": "Done"}},
                "labels": ["a", "b"],
                "rank": "123|abc:",
                "epic": "EPIC-1",
                "pod": {"value": "pod-iicm"},
                "env": {"value": "Production"},
                "client": {"value": "Contoso"},
            },
        }

        record = client._to_issue_record(issue, 7, field_map, {"1": 0})

        self.assertEqual("TASK-1", record.key)
        self.assertEqual("Task", record.issue_type)
        self.assertEqual(7, record.original_index)
        self.assertEqual("High", record.priority_name)
        self.assertEqual(0, record.priority_rank)
        self.assertTrue(record.is_done)
        self.assertEqual(("a", "b"), record.labels)
        self.assertEqual("123|abc:", record.current_rank_value)
        self.assertEqual("EPIC-1", record.epic_key)
        self.assertEqual("pod-iicm", record.pod)
        self.assertEqual("Production", record.found_in_environment)
        self.assertEqual("Contoso", record.client)

    def test_request_json_uses_configured_timeout(self) -> None:
        client = JiraClient(settings())
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        response.headers.get_content_charset.return_value = "utf-8"

        with patch("jira_stackrank.jira_client.urlopen", return_value=response) as urlopen_mock:
            payload = client._request_json("GET", "/rest/api/3/myself")

        self.assertEqual({"ok": True}, payload)
        self.assertEqual(45, urlopen_mock.call_args.kwargs["timeout"])

    def test_priority_rank_falls_back_to_name_and_default_bucket(self) -> None:
        self.assertEqual(1, _priority_rank({"name": "Medium"}, {"medium": 1}))
        self.assertEqual(3, _priority_rank({}, {"high": 0, "medium": 1}))

    def test_string_value_and_string_list_cover_dict_and_list_inputs(self) -> None:
        self.assertEqual("Alpha", _string_value({"displayName": "Alpha"}))
        self.assertEqual("one, two", _string_value([{"name": "one"}, "two"]))
        self.assertEqual(["x", "y"], _string_list(["x", "y"]))
        self.assertEqual(["pod-iicm"], _string_list({"value": "pod-iicm"}))


if __name__ == "__main__":
    unittest.main()
