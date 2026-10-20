"""
CommitSloth Formatter & Visual UI Module.

Provides colorful terminal rendering via Rich, displays sloth mascots and diff metrics,
and handles export to Markdown files or clipboard.
"""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agent_core import CommitSlothResult
from .git_parser import GitDiffPayload

console = Console()

SLOTH_BANNER = r"""
 [bold green]   ___                      _ _   ____  _       _   _     [/bold green]
 [bold green]  / __\___  _ __ ___  _ __ (_) |_/ ___|| | ___ | |_| |__  [/bold green]
 [bold green] / /  / _ \| '_ ` _ \| '_ \| | __\___ \| |/ _ \| __| '_ \ [/bold green]
 [bold green]/ /__| (_) | | | | | | |_) | | |_ ___) | | (_) | |_| | | |[/bold green]
 [bold green]\____/\___/|_| |_| |_| .__/|_|\__|____/|_|\___/ \__|_| |_|[/bold green]
 [bold green]                     |_|                                   [/bold green]
 [bold yellow]   🦥  "Slow and Steady" Offline AI Developer Paperwork  🦥 [/bold yellow]
"""

SLOTH_MASCOT = r"""
    .-""-.
   / .--. \
  / /    \ \
  | |    | |       🦥 CommitSloth is reading your diff...
  \ \.__./ /       Local Gemma is analyzing every change.
   '-.__.-'        Zero cloud leakage. 100% offline.
   /|_||_|\
  (_)(__)(_)
"""


def render_banner() -> None:
    """Prints the rich CommitSloth terminal banner."""
    console.print(SLOTH_BANNER)


def render_diff_summary(payload: GitDiffPayload) -> None:
    """Renders a colorful summary table of the git diff."""
    table = Table(
        title=f"📁 Git Diff Overview: {payload.repo_name} ({payload.diff_scope})",
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
    )
    table.add_column("File Path", style="cyan", no_wrap=False)
    table.add_column("Change", justify="center")
    table.add_column("Insertions", justify="right", style="green")
    table.add_column("Deletions", justify="right", style="red")

    change_colors = {
        "added": "[bold green]ADDED[/bold green]",
        "modified": "[yellow]MODIFIED[/yellow]",
        "deleted": "[bold red]DELETED[/bold red]",
        "renamed": "[blue]RENAMED[/blue]",
    }

    for f in payload.files:
        status_label = change_colors.get(f.change_type, f.change_type.upper())
        table.add_row(
            f.file_path,
            status_label,
            f"+{f.insertions}",
            f"-{f.deletions}",
        )

    console.print(table)

    # Display overall metrics
    stat_text = (
        f"[bold]Total Files Changed:[/bold] {payload.total_files_changed} | "
        f"[bold green]+{payload.total_insertions}[/bold green] lines | "
        f"[bold red]-{payload.total_deletions}[/bold red] lines"
    )
    if payload.filtered_files:
        stat_text += f" | [dim italic]({len(payload.filtered_files)} noise files omitted)[/dim italic]"

    console.print(Panel(stat_text, border_style="cyan", padding=(0, 1)))

    if payload.filtered_files:
        filter_names = [f.file_path for f in payload.filtered_files]
        preview = ", ".join(filter_names[:5])
        if len(filter_names) > 5:
            preview += f" ... (+{len(filter_names) - 5} more)"
        console.print(f"[dim]🛡️ Filtered lockfiles/assets: {preview}[/dim]")


def render_result(result: CommitSlothResult) -> None:
    """Renders the AI generated PR description and changelog in rich format."""
    # PR Title Panel
    title_panel = Panel(
        Text(result.pr_title, style="bold cyan"),
        title="[bold green]🦥 Generated Conventional Commit PR Title[/bold green]",
        subtitle=f"Model: {result.model_name} | Generated in {result.total_duration_sec:.2f}s",
        border_style="green",
    )
    console.print(title_panel)

    # Changelog
    console.print("\n[bold magenta]📋 Key Changes & Technical Breakdown[/bold magenta]")
    console.print(Markdown(result.changelog))

    # Testing Instructions
    console.print("\n[bold yellow]🧪 Testing Instructions for Reviewers[/bold yellow]")
    console.print(Markdown(result.testing_instructions))

    # Release Summary if available
    if result.release_notes.strip():
        console.print("\n[bold blue]🚀 Release Notes Summary[/bold blue]")
        console.print(Markdown(result.release_notes))


def export_markdown_to_file(content: str, output_path: Path) -> Path:
    """Exports generated documentation to a file."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path
