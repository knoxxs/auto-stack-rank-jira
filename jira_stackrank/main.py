from __future__ import annotations

import argparse
from bisect import bisect_left
import logging
from pathlib import Path
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime

from jira_stackrank.config import ConfigError, Settings, load_settings
from jira_stackrank.jira_client import JiraClient, JiraClientError
from jira_stackrank.ranking_engine import RankedIssue, RankingError, compute_ranked_order
from jira_stackrank.ranking_engine import _canonical_issue_type


LOGGER = logging.getLogger("jira_stackrank")


@dataclass(frozen=True)
class MovePlan:
    issue_key: str
    anchor_issue_key: str
    position: str


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Deterministically reorder Jira sprint issues.")
    parser.add_argument("--apply", action="store_true", help="Apply Jira rank changes.")
    parser.add_argument(
        "--confirm-each",
        action="store_true",
        help="Prompt before each rank change while applying updates.",
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
        client = JiraClient(settings)
        LOGGER.info("Using Jira base URL: %s", settings.jira_base_url)
        board = client.get_board_info()
        LOGGER.info(
            "Using board: %s (%s, type=%s)",
            board.board_name or "<unnamed>",
            board.board_id,
            board.board_type or "<unknown>",
        )
        field_map = client.discover_fields()
        priority_order = client.get_priority_order()
        sprint = client.get_active_sprint()
        if sprint is None:
            LOGGER.info("No active sprint found.")
            return 0
        LOGGER.info("Selected active sprint: %s (%s)", sprint.sprint_name or "<unnamed>", sprint.sprint_id)

        issues = client.get_active_sprint_issues(
            sprint_id=sprint.sprint_id,
            field_map=field_map,
            priority_order=priority_order,
        )
        LOGGER.info("Fetched %s issues from board %s sprint %s.", len(issues), settings.board_id, sprint.sprint_id)
        LOGGER.info("Fetched issue type counts: %s", format_issue_type_counts(issues))
        skipped_subtasks = [issue for issue in issues if is_subtask(issue.issue_type, issue.labels, settings)]
        if skipped_subtasks:
            LOGGER.info("Ignoring %s sub-task issues.", len(skipped_subtasks))
        issues = [issue for issue in issues if not is_subtask(issue.issue_type, issue.labels, settings)]
        issues = [replace(issue, original_index=index) for index, issue in enumerate(issues)]
        LOGGER.info("Ranking %s non-sub-task issues.", len(issues))
        unsupported = [
            f"{issue.key} ({issue.issue_type})"
            for issue in issues
            if _canonical_issue_type(issue.issue_type) not in {"bug", "task", "enhancement"}
        ]
        if unsupported:
            LOGGER.warning("Unsupported issue types returned by Jira: %s", ", ".join(unsupported))
        ranked = compute_ranked_order(issues, settings)
        moves = build_move_plan(ranked)

        log_dry_run_table(ranked, settings)
        LOGGER.info("Total issues: %s", len(ranked))
        LOGGER.info("Moves required: %s", len(moves))

        if not moves:
            LOGGER.info("No reordering required.")
            return 0

        if not args.apply:
            return 0

        for move in moves:
            if args.confirm_each and not confirm_move(move):
                LOGGER.info("Stopped before applying remaining rank updates.")
                return 0
            LOGGER.info("Moving %s %s %s", move.issue_key, move.position, move.anchor_issue_key)
            if move.position == "after":
                client.move_issue_after(issue_key=move.issue_key, after_issue_key=move.anchor_issue_key)
            else:
                client.move_issue_before(issue_key=move.issue_key, before_issue_key=move.anchor_issue_key)
        LOGGER.info("Applied %s rank updates.", len(moves))
        return 0
    except (ConfigError, JiraClientError, RankingError) as exc:
        LOGGER.error(str(exc))
        return 1


def configure_logging() -> Path:
    log_directory = repo_root() / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"{datetime.now().strftime('%Y-%m-%d %H-%M-%S')}.log"

    formatter = logging.Formatter("%(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    LOGGER.info("Writing run log to %s", log_path)
    return log_path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def build_move_plan(ranked: list[RankedIssue]) -> list[MovePlan]:
    current_order = [issue.key for issue in sorted(ranked, key=lambda item: item.current_position)]
    target_order = [issue.key for issue in sorted(ranked, key=lambda item: item.new_position)]

    if current_order == target_order:
        return []

    # Keep the longest already-correct subsequence fixed so Jira rank updates only
    # move the minimum set of issues needed to reach the target order.
    keep_in_place = _longest_increasing_target_subsequence(current_order, target_order)
    working_order = current_order[:]
    moves: list[MovePlan] = []

    for index, issue_key in enumerate(target_order):
        if issue_key in keep_in_place:
            continue

        current_index = working_order.index(issue_key)

        if index == 0:
            # Jira supports placing an issue before a known anchor, so handle the
            # head-of-list case explicitly instead of trying to invent a predecessor.
            before_issue_key = target_order[1]
            if current_index + 1 < len(working_order) and working_order[current_index + 1] == before_issue_key:
                continue
            working_order.pop(current_index)
            before_index = working_order.index(before_issue_key)
            working_order.insert(before_index, issue_key)
            moves.append(MovePlan(issue_key=issue_key, anchor_issue_key=before_issue_key, position="before"))
            continue

        issue_key = target_order[index]
        after_issue_key = target_order[index - 1]
        current_index = working_order.index(issue_key)
        predecessor_index = working_order.index(after_issue_key)

        if current_index == predecessor_index + 1:
            continue

        working_order.pop(current_index)
        predecessor_index = working_order.index(after_issue_key)
        working_order.insert(predecessor_index + 1, issue_key)
        moves.append(MovePlan(issue_key=issue_key, anchor_issue_key=after_issue_key, position="after"))

    return moves


def _longest_increasing_target_subsequence(current_order: list[str], target_order: list[str]) -> set[str]:
    current_positions = {issue_key: index for index, issue_key in enumerate(current_order)}
    sequence = [current_positions[issue_key] for issue_key in target_order]
    if not sequence:
        return set()

    # Standard patience-sorting LIS bookkeeping: tails stores the smallest ending
    # value for each subsequence length, and previous lets us reconstruct the path.
    tails: list[int] = []
    tails_indices: list[int] = []
    previous: list[int] = [-1] * len(sequence)

    for index, value in enumerate(sequence):
        insertion_point = bisect_left(tails, value)
        if insertion_point > 0:
            previous[index] = tails_indices[insertion_point - 1]

        if insertion_point == len(tails):
            tails.append(value)
            tails_indices.append(index)
        else:
            tails[insertion_point] = value
            tails_indices[insertion_point] = index

    lis_indices: list[int] = []
    trace_index = tails_indices[-1]
    while trace_index != -1:
        lis_indices.append(trace_index)
        trace_index = previous[trace_index]

    return {target_order[index] for index in reversed(lis_indices)}


def log_dry_run_table(ranked: list[RankedIssue], settings: Settings) -> None:
    rows = sorted(ranked, key=lambda item: item.new_position)
    headers = (
        "Issue Key",
        "Type",
        "Kind",
        "Title",
        "Priority",
        "Current Position",
        "New Position",
        "Current Rank Value",
        "Rank Bucket",
    )
    data = [
        (
            row.key,
            row.issue_type,
            row.kind or "",
            truncate_title(row.summary, settings),
            row.priority_name or "",
            str(row.current_position),
            str(row.new_position),
            row.current_rank_value or "",
            row.rank_bucket.value,
        )
        for row in rows
    ]
    widths = [
        max(len(header), *(len(record[column]) for record in data)) if data else len(header)
        for column, header in enumerate(headers)
    ]

    def render(values: tuple[str, str, str, str, str, str, str, str, str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(values))

    LOGGER.info(render(headers))
    LOGGER.info("-+-".join("-" * width for width in widths))
    for record in data:
        LOGGER.info(render(record))


def format_issue_type_counts(issues: list[object]) -> str:
    counts = Counter(getattr(issue, "issue_type", "<unknown>") for issue in issues)
    if not counts:
        return "<none>"
    return ", ".join(f"{issue_type}={count}" for issue_type, count in sorted(counts.items()))


def confirm_move(move: MovePlan) -> bool:
    while True:
        response = input(
            f"Apply rank move for {move.issue_key} {move.position} {move.anchor_issue_key}? [y/N/q]: "
        ).strip().casefold()
        if response in {"y", "yes"}:
            return True
        if response in {"", "n", "no", "q", "quit"}:
            return False
        print("Please respond with 'y' to apply or 'n'/'q' to stop.")


def is_subtask(issue_type: str, labels: tuple[str, ...], settings: Settings) -> bool:
    configured_issue_types = {value.casefold() for value in settings.subtask_issue_types}
    return issue_type.strip().casefold() in configured_issue_types


def truncate_title(summary: str, settings: Settings) -> str:
    limit = settings.title_truncation_limit
    if len(summary) <= limit:
        return summary
    return f"{summary[: limit - 3]}..."


if __name__ == "__main__":
    sys.exit(main())
