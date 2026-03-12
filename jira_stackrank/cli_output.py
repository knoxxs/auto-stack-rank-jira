from __future__ import annotations

import logging
from pathlib import Path

from rich.box import ROUNDED
from rich.console import Console
from rich.logging import RichHandler
from rich.align import Align
from rich.panel import Panel
from rich.styled import Styled
from rich.text import Text
from rich.table import Table

from jira_stackrank.config import Settings
from jira_stackrank.ranking_engine import RankedIssue


CONSOLE = Console()
PRIORITY_COLUMN_WIDTH = 9
POSITION_COLUMN_WIDTH = 5


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


def print_section_title(title: str, subtitle: str | None = None) -> None:
    heading = Text(title, style="bold cyan")
    if subtitle:
        heading.append(f"\n{subtitle}", style="dim")
    CONSOLE.print(Panel(heading, border_style="cyan", padding=(0, 1)))


def print_step(message: str) -> None:
    CONSOLE.print(f"[dim]{message}...[/dim]")


def print_rank_preview(
    ranked: list[RankedIssue],
    settings: Settings,
) -> None:
    table = Table(
        title="Sprint Rank Preview",
        box=ROUNDED,
        header_style="bold cyan",
        row_styles=["white", "bright_black"],
        expand=True,
        padding=(0, 0),
    )
    table.add_column("Issue Key", style="bold white", no_wrap=True, justify="center")
    table.add_column("Type", style="cyan", justify="center")
    table.add_column("Kind", style="magenta", justify="center")
    table.add_column("Title", overflow="ellipsis", max_width=34)
    table.add_column("Priority", justify="center", width=PRIORITY_COLUMN_WIDTH, no_wrap=True)
    table.add_column("Current", justify="center", width=POSITION_COLUMN_WIDTH, no_wrap=True)
    table.add_column("New", justify="center", width=POSITION_COLUMN_WIDTH, no_wrap=True)
    table.add_column("Move", justify="center", style="green")
    table.add_column("Bucket", style="bold blue", justify="center")

    for row in sorted(ranked, key=lambda item: item.new_position):
        movement = _movement_label(row.current_position, row.new_position)
        table.add_row(
            row.key,
            row.issue_type,
            row.kind or "",
            truncate_title(row.summary, settings),
            _priority_label(row.priority_name),
            _position_label(row.current_position, changed=row.current_position != row.new_position),
            _position_label(row.new_position, changed=row.current_position != row.new_position),
            movement,
            row.rank_bucket.value,
        )

    CONSOLE.print(table)


def print_execution_summary(
    issue_count: int,
    moves_required: int,
    apply_mode: bool,
    duration_seconds: float,
) -> None:
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Mode", "Apply changes" if apply_mode else "Dry run")
    summary.add_row("Ranked issues", str(issue_count))
    summary.add_row("Moves required", str(moves_required))
    summary.add_row("Duration", _format_duration(duration_seconds))
    CONSOLE.print(
        Align.left(
            Panel(
                summary,
                title="Execution Summary",
                border_style="blue",
                padding=(0, 1),
                expand=False,
            )
        )
    )


def print_move_step(issue_key: str, position: str, anchor_issue_key: str, current: int, total: int) -> None:
    CONSOLE.print(
        f"[cyan]→[/cyan] [dim][{current}/{total}] moving[/dim] [bold]{issue_key}[/bold] "
        f"[dim]{position}[/dim] [bold]{anchor_issue_key}[/bold]"
    )


def print_no_changes() -> None:
    CONSOLE.print("[green]No reordering required.[/green]")


def print_apply_section(total_moves: int) -> None:
    CONSOLE.print(
        Panel(
            f"[bold]Applying {total_moves} rank update{'s' if total_moves != 1 else ''}[/bold]",
            border_style="green",
            padding=(0, 1),
            expand=False,
        )
    )


def print_apply_complete(total_moves: int) -> None:
    CONSOLE.print(
        Panel(
            f"[bold green]Applied {total_moves} rank update{'s' if total_moves != 1 else ''}[/bold green]",
            border_style="green",
            padding=(0, 1),
            expand=False,
        )
    )


def print_invalid_confirmation_response() -> None:
    CONSOLE.print("[yellow]Please respond with 'y' to apply or 'n'/'q' to stop.[/yellow]")


def truncate_title(summary: str, settings: Settings) -> str:
    limit = settings.title_truncation_limit
    if len(summary) <= limit:
        return summary
    return f"{summary[: limit - 3]}..."


def _movement_label(current_position: int, new_position: int) -> str:
    delta = current_position - new_position
    if delta > 0:
        return f"[green]↑ {delta}[/green]"
    if delta < 0:
        return f"[yellow]↓ {abs(delta)}[/yellow]"
    return "[dim]·[/dim]"


def _priority_label(priority_name: str | None) -> str:
    if not priority_name:
        return _cell_text("-", PRIORITY_COLUMN_WIDTH, "dim")
    style = _priority_style(priority_name)
    return _cell_text(priority_name.strip()[:PRIORITY_COLUMN_WIDTH], PRIORITY_COLUMN_WIDTH, style)


def _position_label(position: int, changed: bool) -> str:
    if changed:
        return _cell_text(str(position), POSITION_COLUMN_WIDTH, "bold black on #b8ccd8")
    return _cell_text(str(position), POSITION_COLUMN_WIDTH, "white")


def _priority_style(priority_name: str) -> str:
    normalized = priority_name.strip().casefold()
    styles = {
        "critical": "bold white on #a65d5d",
        "highest": "bold white on #b86a6a",
        "high": "bold black on #d9a07f",
        "medium": "bold black on #c6b07a",
        "low": "bold black on #97bda7",
        "lowest": "bold black on #9ab4c7",
    }
    return styles.get(normalized, "bold black on #c6ccd2")


def _format_duration(duration_seconds: float) -> str:
    if duration_seconds < 1:
        return f"{duration_seconds * 1000:.0f} ms"
    return f"{duration_seconds:.2f} s"


def _cell_text(value: str, width: int, style: str):
    text = Text(value, no_wrap=True)
    aligned = Align.center(text, vertical="middle", width=width)
    return Styled(aligned, style)
