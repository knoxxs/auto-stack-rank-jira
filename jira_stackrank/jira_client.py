from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, replace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from jira_stackrank.config import Settings
from jira_stackrank.ranking_engine import IssueRecord


LOGGER = logging.getLogger("jira_stackrank")


class JiraClientError(Exception):
    """Raised when Jira API access fails."""


@dataclass(frozen=True)
class FieldMap:
    rank_field_id: str | None
    epic_link_field_id: str | None
    pod_field_id: str | None
    found_in_environment_field_id: str | None
    client_field_id: str | None


@dataclass(frozen=True)
class SprintInfo:
    sprint_id: int
    sprint_name: str


@dataclass(frozen=True)
class BoardInfo:
    board_id: int
    board_name: str
    board_type: str


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        token = f"{settings.jira_email}:{settings.jira_api_token}".encode("utf-8")
        self._auth_header = base64.b64encode(token).decode("ascii")

    def discover_fields(self) -> FieldMap:
        fields = self._request_json("GET", "/rest/api/3/field")
        if not isinstance(fields, list):
            raise JiraClientError("Unexpected Jira field discovery response.")

        rank_field_id = None
        for field in fields:
            if str(field.get("name", "")).casefold() == "rank":
                rank_field_id = str(field.get("id"))
                break

        return FieldMap(
            rank_field_id=rank_field_id,
            epic_link_field_id=self._find_field_id(fields, "Epic Link"),
            pod_field_id=self._find_field_id(fields, "Pod"),
            found_in_environment_field_id=self._find_field_id(fields, "Found in Environment"),
            client_field_id=self._find_field_id(fields, "Client"),
        )

    def get_board_info(self) -> BoardInfo:
        payload = self._request_json("GET", f"/rest/agile/1.0/board/{self._settings.board_id}")
        return BoardInfo(
            board_id=int(payload.get("id", self._settings.board_id)),
            board_name=str(payload.get("name", "")),
            board_type=str(payload.get("type", "")),
        )

    def get_priority_order(self) -> dict[str, int]:
        priorities = self._request_json("GET", "/rest/api/3/priority")
        if not isinstance(priorities, list):
            raise JiraClientError("Unexpected Jira priority response.")

        order: dict[str, int] = {}
        for index, priority in enumerate(priorities):
            priority_id = priority.get("id")
            priority_name = priority.get("name")
            if priority_id is not None:
                order[str(priority_id)] = index
            if priority_name:
                order[str(priority_name).casefold()] = index
        return order

    def get_active_sprint(self) -> SprintInfo | None:
        payload = self._request_json("GET", f"/rest/agile/1.0/board/{self._settings.board_id}/sprint", {"state": "active"})
        active_sprints = [sprint for sprint in payload.get("values", []) if sprint.get("id") is not None]
        if not active_sprints:
            return None
        sprint = max(active_sprints, key=lambda sprint: int(sprint["id"]))
        self._log_parallel_sprint_choice(active_sprints, sprint)
        return SprintInfo(
            sprint_id=int(sprint["id"]),
            sprint_name=str(sprint.get("name", "")),
        )

    def get_sprint(self, sprint_selector: str) -> SprintInfo | None:
        normalized_selector = sprint_selector.strip()
        if not normalized_selector:
            raise JiraClientError("Sprint selector cannot be empty.")

        matched_sprints: list[dict[str, Any]] = []
        start_at = 0

        while True:
            payload = self._request_json(
                "GET",
                f"/rest/agile/1.0/board/{self._settings.board_id}/sprint",
                {
                    "startAt": start_at,
                    "maxResults": 50,
                    "state": "active,closed,future",
                },
            )
            page_sprints = [sprint for sprint in payload.get("values", []) if sprint.get("id") is not None]
            matched_sprints.extend(
                sprint for sprint in page_sprints if self._sprint_matches_selector(sprint, normalized_selector)
            )

            is_last = bool(payload.get("isLast", False))
            start_at += len(page_sprints)
            if is_last or not page_sprints:
                break

        if not matched_sprints:
            return None

        sprint = self._choose_matching_sprint(matched_sprints, normalized_selector)

        return SprintInfo(
            sprint_id=int(sprint["id"]),
            sprint_name=str(sprint.get("name", "")),
        )

    def get_active_sprint_issues(
        self, sprint_id: int, field_map: FieldMap, priority_order: dict[str, int]
    ) -> list[IssueRecord]:
        issues = self._fetch_sprint_issues(sprint_id, field_map, priority_order)
        issues = self._annotate_client_bugs(issues)
        return self._annotate_epic_summaries(issues)

    def move_issue_after(self, issue_key: str, after_issue_key: str) -> None:
        self._request_json(
            "PUT",
            "/rest/agile/1.0/issue/rank",
            body={"issues": [issue_key], "rankAfterIssue": after_issue_key},
        )

    def move_issue_before(self, issue_key: str, before_issue_key: str) -> None:
        self._request_json(
            "PUT",
            "/rest/agile/1.0/issue/rank",
            body={"issues": [issue_key], "rankBeforeIssue": before_issue_key},
        )

    def _to_issue_record(
        self,
        issue: dict[str, Any],
        original_index: int,
        field_map: FieldMap,
        priority_order: dict[str, int],
    ) -> IssueRecord:
        fields = issue.get("fields", {})
        priority = fields.get("priority") or {}
        priority_rank = _priority_rank(priority, priority_order)
        status = fields.get("status") or {}
        status_category = status.get("statusCategory") or {}

        return IssueRecord(
            key=str(issue["key"]),
            issue_type=str((fields.get("issuetype") or {}).get("name", "")),
            summary=str(fields.get("summary", "")),
            original_index=original_index,
            priority_name=_string_value(priority),
            priority_rank=priority_rank,
            current_rank_value=_string_value(fields.get(field_map.rank_field_id)) if field_map.rank_field_id else None,
            is_done=str(status_category.get("name", "")).casefold() == "done",
            labels=tuple(_string_list(fields.get("labels"))),
            epic_key=_string_value(fields.get(field_map.epic_link_field_id)) if field_map.epic_link_field_id else None,
            epic_summary=None,
            is_client_bug=False,
            pod=_string_value(fields.get(field_map.pod_field_id)) if field_map.pod_field_id else None,
            found_in_environment=(
                _string_value(fields.get(field_map.found_in_environment_field_id))
                if field_map.found_in_environment_field_id
                else None
            ),
            client=_string_value(fields.get(field_map.client_field_id)) if field_map.client_field_id else None,
        )

    def _get_issue_summaries(self, issue_keys: set[str]) -> dict[str, str]:
        summaries: dict[str, str] = {}
        for issue in self._search_issues(f"key in ({', '.join(sorted(issue_keys))})", ["summary"], 50):
            key = issue.get("key")
            if key is None:
                continue
            summary = _string_value((issue.get("fields") or {}).get("summary"))
            if summary:
                summaries[str(key)] = summary

        return summaries

    def _search_issue_keys(self, jql: str) -> set[str]:
        return {
            str(issue["key"])
            for issue in self._search_issues(jql, ["key"], 100)
            if issue.get("key") is not None
        }

    def _search_issues(self, jql: str, fields: list[str], max_results: int) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None

        while True:
            # Jira's newer search endpoint uses an opaque nextPageToken rather than
            # numeric offsets, so loop until the server stops returning a token.
            body: dict[str, Any] = {
                "jql": jql,
                "fields": fields,
                "maxResults": max_results,
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token

            payload = self._request_json(
                "POST",
                "/rest/api/3/search/jql",
                body=body,
            )
            issues.extend(payload.get("issues", []))
            next_page_token = _string_value(payload.get("nextPageToken"))
            if not next_page_token:
                break

        return issues

    def _request_json(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._settings.jira_base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            url=url,
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self._auth_header}",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )

        try:
            with urlopen(request, timeout=self._settings.request_timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                content = response.read().decode(charset)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise JiraClientError(f"Jira API request failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise JiraClientError(f"Failed to reach Jira API: {exc.reason}") from exc

        if not content:
            return {}
        return json.loads(content)

    def _find_field_id(self, fields: list[dict[str, Any]], *names: str) -> str | None:
        lookup = {name.casefold() for name in names}
        matches = [
            str(field.get("id"))
            for field in fields
            if str(field.get("name", "")).casefold() in lookup
        ]
        if len(matches) > 1:
            raise JiraClientError(
                f"Multiple Jira fields matched {', '.join(names)}. "
                "Please make the field names unique in Jira before running this tool."
            )
        return matches[0] if matches else None

    def _sprint_matches_selector(self, sprint: dict[str, Any], selector: str) -> bool:
        sprint_id = sprint.get("id")
        sprint_name = str(sprint.get("name", ""))
        return str(sprint_id) == selector or self._normalized_sprint_name(sprint_name) == self._normalized_sprint_name(
            selector
        )

    def _choose_matching_sprint(self, matched_sprints: list[dict[str, Any]], selector: str) -> dict[str, Any]:
        exact_id_matches = [sprint for sprint in matched_sprints if str(sprint.get("id")) == selector]
        if len(exact_id_matches) == 1:
            return exact_id_matches[0]

        if len(matched_sprints) == 1:
            return matched_sprints[0]

        sprint_names = ", ".join(
            f"{str(item.get('name', '')) or '<unnamed>'} ({int(item['id'])})" for item in matched_sprints
        )
        raise JiraClientError(
            f"Multiple sprints matched {selector!r} on board {self._settings.board_id}: {sprint_names}."
        )

    def _normalized_sprint_name(self, sprint_name: str) -> str:
        normalized_name = sprint_name.strip().casefold()
        if normalized_name.startswith("sprint "):
            return normalized_name.removeprefix("sprint ").strip()
        return normalized_name

    def _log_parallel_sprint_choice(
        self,
        active_sprints: list[dict[str, Any]],
        chosen_sprint: dict[str, Any],
    ) -> None:
        if len(active_sprints) <= 1:
            return
        chosen_name = str(chosen_sprint.get("name", ""))
        chosen_id = int(chosen_sprint["id"])
        LOGGER.warning(
            f"Multiple active sprints found on board {self._settings.board_id}; "
            f"using latest sprint {chosen_name or '<unnamed>'} ({chosen_id})."
        )

    def _fetch_sprint_issues(
        self,
        sprint_id: int,
        field_map: FieldMap,
        priority_order: dict[str, int],
    ) -> list[IssueRecord]:
        requested_fields = self._requested_issue_fields(field_map)
        issues: list[IssueRecord] = []
        start_at = 0

        while True:
            payload = self._request_json(
                "GET",
                f"/rest/agile/1.0/board/{self._settings.board_id}/sprint/{sprint_id}/issue",
                {
                    "startAt": start_at,
                    "maxResults": 100,
                    "fields": ",".join(requested_fields),
                },
            )
            page_issues = payload.get("issues", [])
            issues.extend(
                self._to_issue_record(
                    issue=issue,
                    original_index=start_at + offset,
                    field_map=field_map,
                    priority_order=priority_order,
                )
                for offset, issue in enumerate(page_issues)
            )

            total = int(payload.get("total", len(issues)))
            start_at += len(page_issues)
            if start_at >= total or not page_issues:
                return issues

    def _requested_issue_fields(self, field_map: FieldMap) -> list[str]:
        requested_fields = ["issuetype", "priority", "status", "summary", "labels"]
        requested_fields.extend((
            field_map.rank_field_id,
            field_map.epic_link_field_id,
            field_map.pod_field_id,
            field_map.found_in_environment_field_id,
            field_map.client_field_id,
        ))
        return [field_id for field_id in requested_fields if field_id]

    def _annotate_client_bugs(self, issues: list[IssueRecord]) -> list[IssueRecord]:
        client_bug_keys = self._search_issue_keys(self._settings.client_bug_jql)
        return [replace(issue, is_client_bug=issue.key in client_bug_keys) for issue in issues]

    def _annotate_epic_summaries(self, issues: list[IssueRecord]) -> list[IssueRecord]:
        epic_keys = {issue.epic_key for issue in issues if issue.epic_key}
        if not epic_keys:
            return issues

        epic_summaries = self._get_issue_summaries(epic_keys)
        return [replace(issue, epic_summary=epic_summaries.get(issue.epic_key)) for issue in issues]


def _priority_rank(priority: dict[str, Any], priority_order: dict[str, int]) -> int:
    if not priority:
        return len(priority_order) + 1

    priority_id = priority.get("id")
    if priority_id is not None and str(priority_id) in priority_order:
        return priority_order[str(priority_id)]

    priority_name = priority.get("name")
    if priority_name is not None and str(priority_name).casefold() in priority_order:
        return priority_order[str(priority_name).casefold()]

    return len(priority_order) + 1


def _string_value(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in ("value", "name", "displayName", "key"):
            if raw.get(key):
                return str(raw[key])
        return None
    if isinstance(raw, list):
        values = [_string_value(item) for item in raw]
        joined = ", ".join(value for value in values if value)
        return joined or None
    return str(raw)


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item is not None]
    value = _string_value(raw)
    return [value] if value else []
