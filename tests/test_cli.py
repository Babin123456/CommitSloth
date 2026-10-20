"""
Unit tests for CommitSloth CLI.
"""

from pathlib import Path
import pytest

from commitsloth.cli import create_parser, main


def test_cli_parser_defaults():
    parser = create_parser()
    args = parser.parse_args([])

    assert args.repo == "."
    assert args.staged is False
    assert args.branch is None
    assert args.commit is None
    assert args.model == "gemma:2b"
    assert args.host == "http://localhost:11434"
    assert args.mock is False
    assert args.diff_only is False


def test_cli_parser_custom_args():
    parser = create_parser()
    args = parser.parse_args([
        "--repo", "/custom/path",
        "--staged",
        "--model", "gemma:7b",
        "--output", "PR_NOTE.md",
        "--mock",
    ])

    assert args.repo == "/custom/path"
    assert args.staged is True
    assert args.model == "gemma:7b"
    assert args.output == "PR_NOTE.md"
    assert args.mock is True


def test_cli_non_git_repo(tmp_path):
    # Non-git directory should return exit code 1
    exit_code = main(["--repo", str(tmp_path)])
    assert exit_code == 1
