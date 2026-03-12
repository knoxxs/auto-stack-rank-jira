from __future__ import annotations

import argparse
from bisect import bisect_left
import logging
from pathlib import Path
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime

from jira_stackrank.cli_output import configure_logging as configure_rich_logging
from jira_stackrank.cli_output import print_invalid_confirmation_response, print_rank_preview
from jira_stackrank.cli_output import truncate_title
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
    args = parse_args()

    try:
        settings = load_settings()
        client = JiraClient(settings)
        sprint = log_runtime_context(client, settings)
        if sprint is None:
            LOGGER.info("No active sprint found.")
            return 0

        issues = fetch_rankable_issues(client, settings, sprint.sprint_id)
        ranked = compute_ranked_order(issues, settings)
        moves = build_move_plan(ranked)
        log_rank_preview(ranked, moves, settings)

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministically reorder Jira sprint issues.")
    parser.add_argument("--apply", action="store_true", help="Apply Jira rank changes.")
    parser.add_argument(
        "--confirm-each",
        action="store_true",
        help="Prompt before each rank change while applying updates.",
    )
    return parser.parse_args()


def log_runtime_context(client: JiraClient, settings: Settings):
    LOGGER.info("Using Jira base URL: %s", settings.jira_base_url)
    board = client.get_board_info()
    LOGGER.info(
        "Using board: %s (%s, type=%s)",
        board.board_name or "<unnamed>",
        board.board_id,
        board.board_type or "<unknown>",
    )
    sprint = client.get_active_sprint()
    if sprint is not None:
        LOGGER.info("Selected active sprint: %s (%s)", sprint.sprint_name or "<unnamed>", sprint.sprint_id)
    return sprint


def fetch_rankable_issues(client: JiraClient, settings: Settings, sprint_id: int):
    field_map = client.discover_fields()
    priority_order = client.get_priority_order()
    fetched_issues = client.get_active_sprint_issues(
        sprint_id=sprint_id,
        field_map=field_map,
        priority_order=priority_order,
    )
    LOGGER.info("Fetched %s issues from board %s sprint %s.", len(fetched_issues), settings.board_id, sprint_id)
    LOGGER.info("Fetched issue type counts: %s", format_issue_type_counts(fetched_issues))

    rankable_issues = [issue for issue in fetched_issues if not is_subtask(issue.issue_type, issue.labels, settings)]
    skipped_count = len(fetched_issues) - len(rankable_issues)
    if skipped_count:
        LOGGER.info("Ignoring %s sub-task issues.", skipped_count)

    rankable_issues = [replace(issue, original_index=index) for index, issue in enumerate(rankable_issues)]
    LOGGER.info("Ranking %s non-sub-task issues.", len(rankable_issues))
    log_unsupported_issue_types(rankable_issues)
    return rankable_issues


def log_unsupported_issue_types(issues: list[object]) -> None:
    unsupported = [
        f"{getattr(issue, 'key', '<unknown>')} ({getattr(issue, 'issue_type', '<unknown>')})"
        for issue in issues
        if _canonical_issue_type(getattr(issue, "issue_type", None)) not in {"bug", "task", "enhancement"}
    ]
    if unsupported:
        LOGGER.warning("Unsupported issue types returned by Jira: %s", ", ".join(unsupported))


def log_rank_preview(ranked: list[RankedIssue], moves: list[MovePlan], settings: Settings) -> None:
    print_rank_preview(ranked, settings)
    LOGGER.info("Total issues: %s", len(ranked))
    LOGGER.info("Moves required: %s", len(moves))


def configure_logging() -> Path:
    log_directory = repo_root() / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"{datetime.now().strftime('%Y-%m-%d %H-%M-%S')}.log"

    configure_rich_logging(log_path)
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
        print_invalid_confirmation_response()


def is_subtask(issue_type: str, labels: tuple[str, ...], settings: Settings) -> bool:
    configured_issue_types = {value.casefold() for value in settings.subtask_issue_types}
    return issue_type.strip().casefold() in configured_issue_types

if __name__ == "__main__":
    sys.exit(main())
