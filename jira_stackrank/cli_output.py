from __future__ import annotations

import logging
from pathlib import Path

from rich.box import SIMPLE_HEAVY
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from jira_stackrank.config import Settings
from jira_stackrank.ranking_engine import RankedIssue


CONSOLE = Console()


def configure_logging(log_path: Path) -> None:
    formatter = logging.Formatter("%(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = RichHandler(
        console=CONSOLE,
        show_time=False,
        show_level=False,
        show_path=False,
        markup=False,
        rich_tracebacks=True,
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def print_rank_preview(ranked: list[RankedIssue], settings: Settings) -> None:
    table = Table(title="Sprint Rank Preview", box=SIMPLE_HEAVY, header_style="bold cyan")
    table.add_column("Issue Key", style="bold")
    table.add_column("Type")
    table.add_column("Kind")
    table.add_column("Title", overflow="fold")
    table.add_column("Priority")
    table.add_column("Current", justify="right")
    table.add_column("New", justify="right")
    table.add_column("Rank Value")
    table.add_column("Bucket", style="magenta")

    for row in sorted(ranked, key=lambda item: item.new_position):
        table.add_row(
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

    CONSOLE.print(table)


def print_invalid_confirmation_response() -> None:
    CONSOLE.print("[yellow]Please respond with 'y' to apply or 'n'/'q' to stop.[/yellow]")


def truncate_title(summary: str, settings: Settings) -> str:
    limit = settings.title_truncation_limit
    if len(summary) <= limit:
        return summary
    return f"{summary[: limit - 3]}..."
