from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from jira_stackrank.config import Settings


class RankingError(Exception):
    """Raised when issues cannot be deterministically ranked from the PRD rules."""


class RankBucket(str, Enum):
    RANK_1 = "Rank 1"
    RANK_2 = "Rank 2"
    RANK_3 = "Rank 3"


@dataclass(frozen=True)
class IssueRecord:
    key: str
    issue_type: str
    summary: str
    original_index: int
    priority_name: str | None
    priority_rank: int
    current_rank_value: str | None
    is_done: bool
    labels: tuple[str, ...]
    epic_key: str | None
    epic_summary: str | None
    is_client_bug: bool
    pod: str | None
    found_in_environment: str | None
    client: str | None


@dataclass(frozen=True)
class RankedIssue:
    key: str
    issue_type: str
    summary: str
    current_position: int
    new_position: int
    priority_name: str | None
    current_rank_value: str | None
    kind: str | None
    rank_bucket: RankBucket


def compute_ranked_order(issues: list[IssueRecord], settings: Settings) -> list[RankedIssue]:
    annotated = [(issue, _bucket_for(issue)) for issue in issues]

    # Each band is sorted independently, then concatenated to match the PRD's
    # fixed Rank 1 -> Rank 2 -> Rank 3 precedence.
    rank_groups = _partition_by_bucket(annotated)
    final = (
        _sort_by_priority_then_stable(rank_groups[RankBucket.RANK_1])
        + _sort_rank_2(rank_groups[RankBucket.RANK_2])
        + _sort_by_priority_then_stable(rank_groups[RankBucket.RANK_3])
    )
    positions = {issue.key: index + 1 for index, issue in enumerate(final)}
    buckets = {issue.key: bucket for issue, bucket in annotated}

    return [
        RankedIssue(
            key=issue.key,
            issue_type=issue.issue_type,
            summary=issue.summary,
            current_position=issue.original_index + 1,
            new_position=positions[issue.key],
            priority_name=issue.priority_name,
            current_rank_value=issue.current_rank_value,
            kind=_kind_label(issue, buckets[issue.key], settings),
            rank_bucket=buckets[issue.key],
        )
        for issue in issues
    ]


def _bucket_for(issue: IssueRecord) -> RankBucket:
    raw_issue_type = _normalize(issue.issue_type)
    issue_type = _canonical_issue_type(issue.issue_type)

    if issue_type not in {"bug", "task", "enhancement"}:
        raise RankingError(
            f"Issue {issue.key} has unsupported type '{issue.issue_type}'. "
            "The PRD only defines ranking for Bug, Enhancement, and Task."
        )

    if issue_type == "bug":
        if raw_issue_type == "vulnerability" or issue.is_client_bug:
            return RankBucket.RANK_1
        return RankBucket.RANK_3

    return RankBucket.RANK_2


def _partition_by_bucket(
    annotated: list[tuple[IssueRecord, RankBucket]]
) -> dict[RankBucket, list[IssueRecord]]:
    grouped: dict[RankBucket, list[IssueRecord]] = {
        RankBucket.RANK_1: [],
        RankBucket.RANK_2: [],
        RankBucket.RANK_3: [],
    }
    for issue, bucket in annotated:
        grouped[bucket].append(issue)
    return grouped


def _sort_rank_2(issues: list[IssueRecord]) -> list[IssueRecord]:
    epic_issues: list[IssueRecord] = []
    enhancement_without_epic: list[IssueRecord] = []
    task_without_epic: list[IssueRecord] = []

    for issue in issues:
        issue_type = _canonical_issue_type(issue.issue_type)
        if issue.epic_key:
            epic_issues.append(issue)
        elif issue_type == "enhancement":
            enhancement_without_epic.append(issue)
        else:
            task_without_epic.append(issue)

    # Rank 2 keeps epic-linked work and standalone enhancements in the primary
    # band, with non-epic tasks intentionally trailing that band.
    return (
        _sort_rank_2_primary(epic_issues, enhancement_without_epic)
        + _sort_by_priority_then_stable(task_without_epic)
    )


def _sort_rank_2_primary(epic_issues: list[IssueRecord], enhancement_without_epic: list[IssueRecord]) -> list[IssueRecord]:
    units: list[tuple[int, list[IssueRecord]]] = []
    seen_epics: set[str] = set()

    # Walk the original board order so epic groups keep their first-seen position
    # relative to standalone enhancements.
    combined = sorted(
        epic_issues + enhancement_without_epic,
        key=lambda issue: issue.original_index,
    )

    epic_groups = _group_epic_members(epic_issues)
    for issue in combined:
        if issue.epic_key is None:
            units.append((issue.original_index, [issue]))
            continue

        if issue.epic_key in seen_epics:
            continue

        seen_epics.add(issue.epic_key)
        members = epic_groups[issue.epic_key]
        units.append((min(member.original_index for member in members), _sort_by_priority_then_stable(members)))

    return [member for _, unit in sorted(units, key=lambda item: item[0]) for member in unit]


def _group_epic_members(issues: list[IssueRecord]) -> dict[str, list[IssueRecord]]:
    groups: dict[str, list[IssueRecord]] = defaultdict(list)
    for issue in issues:
        if issue.epic_key is None:
            continue
        groups[issue.epic_key].append(issue)
    return groups


def _sort_by_priority_then_stable(issues: list[IssueRecord]) -> list[IssueRecord]:
    return sorted(issues, key=lambda issue: (issue.priority_rank, issue.original_index))


def _normalize(value: str | None) -> str:
    return (value or "").strip().casefold()


def _canonical_issue_type(issue_type: str | None) -> str:
    normalized = _normalize(issue_type)
    aliases = {
        "vulnerability": "bug",
        "enhancements": "enhancement",
    }
    return aliases.get(normalized, normalized)


def _kind_label(issue: IssueRecord, bucket: RankBucket, settings: Settings) -> str | None:
    issue_type = _canonical_issue_type(issue.issue_type)
    if issue_type in {"task", "enhancement"}:
        return _epic_title_prefix(issue.epic_summary, settings.epic_title_prefix_length)
    if issue_type != "bug":
        return None
    if bucket == RankBucket.RANK_1:
        return "Client Bug"
    return "Internal Bug"


def _epic_title_prefix(epic_summary: str | None, limit: int) -> str | None:
    if not epic_summary:
        return None
    return epic_summary.strip()[:limit] or None
