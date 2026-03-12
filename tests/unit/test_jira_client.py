import json
import unittest
from unittest.mock import MagicMock, patch

from jira_stackrank.config import Settings
from jira_stackrank.jira_client import JiraClient, JiraClientError, LOGGER


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


if __name__ == "__main__":
    unittest.main()
