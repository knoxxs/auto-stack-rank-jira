from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ENV_FILE = ".env"
DEFAULT_BOARD_ID = 1124
DEFAULT_CLIENT_BUG_JQL = (
    '(type = "Bug" AND Pod = "pod-iicm" AND "Found in Environment" = Production '
    'AND Client != "Ontic Technologies") or type = "Vulnerability"'
)
DEFAULT_EPIC_TITLE_PREFIX_LENGTH = 16
DEFAULT_SUBTASK_ISSUE_TYPES = (
    "be sub-task",
    "bug sub-task",
    "design sub-task",
    "fe sub-task",
    "qa sub-task",
)
DEFAULT_TITLE_TRUNCATION_LIMIT = 36
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30


class ConfigError(Exception):
    """Raised when configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    jira_email: str
    jira_api_token: str
    jira_base_url: str
    board_id: int
    client_bug_jql: str
    epic_title_prefix_length: int
    subtask_issue_types: tuple[str, ...]
    title_truncation_limit: int
    request_timeout_seconds: int


def load_settings(env_path: str | Path = ENV_FILE) -> Settings:
    values = _parse_env_file(Path(env_path))
    required = ("JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_BASE_URL")
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    return Settings(
        jira_email=values["JIRA_EMAIL"],
        jira_api_token=values["JIRA_API_TOKEN"],
        jira_base_url=values["JIRA_BASE_URL"].rstrip("/"),
        board_id=_int_value(values.get("BOARD_ID"), DEFAULT_BOARD_ID),
        client_bug_jql=(values.get("CLIENT_BUG_JQL") or DEFAULT_CLIENT_BUG_JQL).strip(),
        epic_title_prefix_length=_int_value(
            values.get("EPIC_TITLE_PREFIX_LENGTH"), DEFAULT_EPIC_TITLE_PREFIX_LENGTH
        ),
        subtask_issue_types=_csv_tuple(values.get("SUBTASK_ISSUE_TYPES"), DEFAULT_SUBTASK_ISSUE_TYPES),
        title_truncation_limit=_int_value(
            values.get("TITLE_TRUNCATION_LIMIT"), DEFAULT_TITLE_TRUNCATION_LIMIT
        ),
        request_timeout_seconds=_int_value(
            values.get("REQUEST_TIMEOUT_SECONDS"), DEFAULT_REQUEST_TIMEOUT_SECONDS
        ),
    )


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise ConfigError(f"Missing environment file: {path}")

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _strip_quotes(value.strip())
    return values


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _int_value(raw: str | None, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def _csv_tuple(raw: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())
