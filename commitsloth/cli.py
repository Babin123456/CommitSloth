"""
CommitSloth CLI Interface.

Command-line entry point for CommitSloth. Provides developer options for diff extraction,
Ollama communication, local model selection, and PR/release notes generation.
"""

import argparse
from pathlib import Path
import sys
from typing import Optional

# Ensure UTF-8 console output on Windows to handle emojis cleanly
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel

from . import __version__
from .agent_core import (
    AgentCore,
    OllamaConnectionError,
    OllamaError,
    OllamaModelNotFoundError,
    SecurityViolationError,
)
from .config import DEFAULT_MODEL, DEFAULT_OLLAMA_HOST
from .formatter import (
    console,
    export_markdown_to_file,
    render_banner,
    render_diff_summary,
    render_result,
)
from .git_parser import (
    EmptyDiffError,
    GitError,
    GitParser,
    NotAGitRepositoryError,
)


def create_parser() -> argparse.ArgumentParser:
    """Creates the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="commitsloth",
        description="🦥 CommitSloth: Local, offline-first developer productivity tool powered by Google Gemma.",
        epilog="Hacktoberfest 2026 Open-Source AI Challenge - Slow and Steady Week.",
    )

    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"CommitSloth v{__version__}",
    )

    parser.add_argument(
        "-r", "--repo",
        type=str,
        default=".",
        help="Path to git repository (default: current directory).",
    )

    # Diff Selection Options
    diff_group = parser.add_argument_group("Diff Selection Options")
    diff_group.add_argument(
        "-s", "--staged",
        action="store_true",
        help="Analyze only staged git changes (git diff --cached).",
    )
    diff_group.add_argument(
        "-b", "--branch",
        type=str,
        metavar="BASE_BRANCH",
        help="Compare current branch against base branch (e.g. main or master).",
    )
    diff_group.add_argument(
        "-c", "--commit",
        type=str,
        metavar="COMMIT_HASH",
        help="Analyze a specific commit hash or ref (e.g. HEAD~1).",
    )

    # Local AI & Ollama Options
    ai_group = parser.add_argument_group("Local AI & Ollama Options")
    ai_group.add_argument(
        "-m", "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL}).",
    )
    ai_group.add_argument(
        "--host",
        type=str,
        default=DEFAULT_OLLAMA_HOST,
        help=f"Local Ollama endpoint URL (default: {DEFAULT_OLLAMA_HOST}).",
    )
    ai_group.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds for local model inference (default: 120s).",
    )
    ai_group.add_argument(
        "--stream",
        action="store_true",
        help="Stream response tokens in real-time as the model generates them.",
    )
    ai_group.add_argument(
        "--mock",
        action="store_true",
        help="Run with synthetic AI response without querying Ollama (useful for CI/testing).",
    )

    # Output Options
    out_group = parser.add_argument_group("Output Options")
    out_group.add_argument(
        "-o", "--output",
        type=str,
        metavar="FILEPATH",
        help="Save generated Markdown output to specified file (e.g. PR.md).",
    )
    out_group.add_argument(
        "--diff-only",
        action="store_true",
        help="Extract and inspect git diff and statistics without querying the AI model.",
    )

    return parser


def main(args: Optional[list] = None) -> int:
    """Main CLI execution flow."""
    parser = create_parser()
    cli_args = parser.parse_args(args)

    render_banner()

    repo_path = Path(cli_args.repo).resolve()

    # Step 1: Initialize Git Parser and Validate Repository
    try:
        git_parser = GitParser(repo_path=repo_path)
    except NotAGitRepositoryError as e:
        console.print(f"[bold red]❌ Repository Error:[/bold red] {e}")
        return 1
    except GitError as e:
        console.print(f"[bold red]❌ Git Error:[/bold red] {e}")
        return 1

    # Step 2: Fetch and Parse Code Diff
    console.print(f"[dim]🔍 Inspecting git status at: {repo_path}...[/dim]")
    try:
        diff_payload = git_parser.fetch_diff(
            staged_only=cli_args.staged,
            base_branch=cli_args.branch,
            commit_hash=cli_args.commit,
        )
    except EmptyDiffError as e:
        console.print(Panel(
            f"[bold yellow]⚠️ No Changes Detected[/bold yellow]\n\n{e}",
            border_style="yellow",
        ))
        return 0
    except GitError as e:
        console.print(f"[bold red]❌ Git Diff Error:[/bold red] {e}")
        return 1

    # Step 3: Render Diff Summary Table
    render_diff_summary(diff_payload)

    # If --diff-only flag passed, exit early
    if cli_args.diff_only:
        console.print("\n[bold green]✅ Diff analysis complete (--diff-only mode).[/bold green]")
        return 0

    # Step 4: Initialize Agent Core
    try:
        agent = AgentCore(
            host=cli_args.host,
            model_name=cli_args.model,
            timeout=cli_args.timeout,
        )
    except SecurityViolationError as e:
        console.print(f"[bold red]🛡️ Security Alert:[/bold red] {e}")
        return 1

    # Step 5: Check Ollama Connection and Model Availability unless --mock
    if not cli_args.mock:
        with console.status("[bold cyan]Connecting to local Ollama daemon...[/bold cyan]"):
            is_healthy, health_msg = agent.check_health()
            if not is_healthy:
                console.print(Panel(
                    f"[bold red]❌ Ollama Offline[/bold red]\n\n{health_msg}",
                    border_style="red",
                ))
                return 1

            try:
                active_model = agent.verify_model_available(auto_fallback=True)
                console.print(f"[dim]🧠 Using local model: [bold cyan]{active_model}[/bold cyan][/dim]")
            except OllamaModelNotFoundError as e:
                console.print(Panel(
                    f"[bold yellow]⚠️ Model Not Found[/bold yellow]\n\n{e}",
                    border_style="yellow",
                ))
                return 1

    # Step 6: Generate PR Paperwork
    console.print(f"\n[bold green]🦥 CommitSloth is generating documentation... (Slow and Steady!)[/bold green]")

    def streaming_callback(token: str) -> None:
        sys.stdout.write(token)
        sys.stdout.flush()

    try:
        if cli_args.stream and not cli_args.mock:
            console.print("[dim]Streaming output from Gemma:[/dim]\n")
            result = agent.generate(
                diff_payload=diff_payload,
                stream_callback=streaming_callback,
                mock=cli_args.mock,
            )
            console.print("\n")
        else:
            with console.status("[bold green]Analyzing diff with Gemma...[/bold green]"):
                result = agent.generate(
                    diff_payload=diff_payload,
                    stream_callback=None,
                    mock=cli_args.mock,
                )

        # Render Rich UI of Result
        render_result(result)

        # Step 7: Export to File if Requested
        if cli_args.output:
            out_file = Path(cli_args.output)
            saved_path = export_markdown_to_file(result.to_markdown(), out_file)
            console.print(f"\n[bold green]💾 Saved PR documentation to:[/bold green] [cyan]{saved_path}[/cyan]")

        return 0

    except OllamaConnectionError as e:
        console.print(f"[bold red]❌ Ollama Connection Failed:[/bold red] {e}")
        return 1
    except OllamaError as e:
        console.print(f"[bold red]❌ AI Generation Error:[/bold red] {e}")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user. Exiting CommitSloth.[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
