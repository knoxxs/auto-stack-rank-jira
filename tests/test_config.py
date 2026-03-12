import tempfile
import unittest
from pathlib import Path

from jira_stackrank.config import ConfigError, load_settings


class LoadSettingsTests(unittest.TestCase):
    def test_load_settings_uses_defaults_and_strips_quotes(self) -> None:
        env_body = """
        JIRA_EMAIL="user@example.com"
        JIRA_API_TOKEN='secret'
        JIRA_BASE_URL=https://example.atlassian.net/
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(env_body, encoding="utf-8")

            loaded = load_settings(env_path)

        self.assertEqual("user@example.com", loaded.jira_email)
        self.assertEqual("secret", loaded.jira_api_token)
        self.assertEqual("https://example.atlassian.net", loaded.jira_base_url)
        self.assertEqual(1124, loaded.board_id)
        self.assertEqual(30, loaded.request_timeout_seconds)

    def test_load_settings_parses_optional_overrides(self) -> None:
        env_body = """
        JIRA_EMAIL=user@example.com
        JIRA_API_TOKEN=secret
        JIRA_BASE_URL=https://example.atlassian.net
        BOARD_ID=4321
        EPIC_TITLE_PREFIX_LENGTH=20
        SUBTASK_ISSUE_TYPES=one,two
        TITLE_TRUNCATION_LIMIT=50
        REQUEST_TIMEOUT_SECONDS=12
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(env_body, encoding="utf-8")

            loaded = load_settings(env_path)

        self.assertEqual(4321, loaded.board_id)
        self.assertEqual(20, loaded.epic_title_prefix_length)
        self.assertEqual(("one", "two"), loaded.subtask_issue_types)
        self.assertEqual(50, loaded.title_truncation_limit)
        self.assertEqual(12, loaded.request_timeout_seconds)

    def test_load_settings_requires_core_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("JIRA_EMAIL=user@example.com\n", encoding="utf-8")

            with self.assertRaises(ConfigError) as exc_info:
                load_settings(env_path)

        self.assertIn("Missing required environment variables", str(exc_info.exception))


if __name__ == "__main__":
    unittest.main()
