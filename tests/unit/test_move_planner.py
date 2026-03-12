import unittest
from unittest.mock import patch

from jira_stackrank.main import MovePlan, build_move_plan, confirm_move
from jira_stackrank.ranking_engine import RankBucket, RankedIssue


def ranked_issues(current_order: list[str], target_order: list[str]) -> list[RankedIssue]:
    current_positions = {issue_key: index + 1 for index, issue_key in enumerate(current_order)}
    target_positions = {issue_key: index + 1 for index, issue_key in enumerate(target_order)}
    issues = sorted(current_order, key=lambda issue_key: current_positions[issue_key])
    return [
        RankedIssue(
            key=issue_key,
            issue_type="Task",
            summary=issue_key,
            current_position=current_positions[issue_key],
            new_position=target_positions[issue_key],
            priority_name=None,
            current_rank_value=None,
            kind=None,
            rank_bucket=RankBucket.RANK_2,
        )
        for issue_key in issues
    ]


def apply_moves(current_order: list[str], moves: list[MovePlan]) -> list[str]:
    working = current_order[:]
    for move in moves:
        working.remove(move.issue_key)
        anchor_index = working.index(move.anchor_issue_key)
        insert_at = anchor_index if move.position == "before" else anchor_index + 1
        working.insert(insert_at, move.issue_key)
    return working


class BuildMovePlanTests(unittest.TestCase):
    def test_no_moves_when_already_sorted(self) -> None:
        current_order = ["A", "B", "C"]
        moves = build_move_plan(ranked_issues(current_order, current_order))
        self.assertEqual([], moves)

    def test_moves_first_issue_before_anchor_when_that_is_optimal(self) -> None:
        current_order = ["B", "C", "A", "D"]
        target_order = ["A", "B", "C", "D"]

        moves = build_move_plan(ranked_issues(current_order, target_order))

        self.assertEqual(
            [MovePlan(issue_key="A", anchor_issue_key="B", position="before")],
            moves,
        )
        self.assertEqual(target_order, apply_moves(current_order, moves))

    def test_keeps_longest_subsequence_and_moves_each_other_issue_once(self) -> None:
        current_order = ["D", "A", "B", "C"]
        target_order = ["A", "B", "C", "D"]

        moves = build_move_plan(ranked_issues(current_order, target_order))

        self.assertEqual(
            [MovePlan(issue_key="D", anchor_issue_key="C", position="after")],
            moves,
        )
        self.assertEqual(target_order, apply_moves(current_order, moves))

    def test_reorders_complex_permutation(self) -> None:
        current_order = ["H", "A", "B", "E", "C", "D", "F", "G"]
        target_order = ["A", "B", "C", "D", "E", "F", "G", "H"]

        moves = build_move_plan(ranked_issues(current_order, target_order))

        self.assertEqual(target_order, apply_moves(current_order, moves))
        self.assertEqual(2, len(moves))


class ConfirmMoveTests(unittest.TestCase):
    def test_accepts_yes_response(self) -> None:
        move = MovePlan(issue_key="A", anchor_issue_key="B", position="before")

        with patch("builtins.input", return_value="y"):
            self.assertTrue(confirm_move(move))

    def test_rejects_default_response(self) -> None:
        move = MovePlan(issue_key="A", anchor_issue_key="B", position="before")

        with patch("builtins.input", return_value=""):
            self.assertFalse(confirm_move(move))

    def test_reprompts_on_invalid_response(self) -> None:
        move = MovePlan(issue_key="A", anchor_issue_key="B", position="before")

        with patch("builtins.input", side_effect=["maybe", "yes"]):
            self.assertTrue(confirm_move(move))


if __name__ == "__main__":
    unittest.main()
