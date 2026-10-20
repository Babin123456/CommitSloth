"""
CommitSloth Git Parser & Diff Analyzer.

Handles safe execution of local git commands via subprocess, parses unified diffs,
filters noise and build artifacts, and constructs structured payloads for local LLM consumption.
"""

from dataclasses import dataclass, field
import fnmatch
from pathlib import Path
import re
import subprocess
from typing import Dict, List, Optional, Set, Tuple

from .config import DEFAULT_IGNORED_PATTERNS, DEFAULT_MAX_DIFF_CHARS, DEFAULT_MAX_FILE_DIFF_LINES


class GitError(Exception):
    """Base exception for Git operations."""
    pass


class NotAGitRepositoryError(GitError):
    """Raised when target directory is not an active git repository."""
    pass


class EmptyDiffError(GitError):
    """Raised when no code diff was detected to analyze."""
    pass


@dataclass
class DiffFile:
    """Represents a single file within a git diff."""
    file_path: str
    old_path: Optional[str] = None
    change_type: str = "modified"  # modified, added, deleted, renamed, binary
    insertions: int = 0
    deletions: int = 0
    diff_content: str = ""
    is_binary: bool = False
    is_ignored: bool = False
    ignore_reason: Optional[str] = None


@dataclass
class GitDiffPayload:
    """Structured collection of diff files, stats, and context for AI prompts."""
    repo_name: str
    repo_path: str
    current_branch: str
    diff_scope: str  # e.g., 'uncommitted', 'staged', 'branch:main', 'commit:abc123'
    files: List[DiffFile] = field(default_factory=list)
    filtered_files: List[DiffFile] = field(default_factory=list)
    recent_commits: List[str] = field(default_factory=list)
    total_insertions: int = 0
    total_deletions: int = 0
    is_truncated: bool = False
    truncation_note: Optional[str] = None

    @property
    def total_files_changed(self) -> int:
        return len(self.files)

    @property
    def total_filtered_count(self) -> int:
        return len(self.filtered_files)

    def get_summary_stats(self) -> Dict[str, int]:
        return {
            "files_changed": self.total_files_changed,
            "filtered_files": self.total_filtered_count,
            "insertions": self.total_insertions,
            "deletions": self.total_deletions,
        }

    def render_diff_for_prompt(self, max_chars: int = DEFAULT_MAX_DIFF_CHARS) -> str:
        """
        Renders a clean, structured text representation of the diff payload for Gemma.
        Guarantees that token limits are respected while preserving structural context.
        """
        parts: List[str] = []

        # Repository and change overview header
        parts.append(f"Repository: {self.repo_name}")
        parts.append(f"Branch: {self.current_branch}")
        parts.append(f"Diff Scope: {self.diff_scope}")
        parts.append(f"Summary: {self.total_files_changed} files changed, +{self.total_insertions} -{self.total_deletions} lines.")

        if self.recent_commits:
            parts.append("\nRecent Commits on Branch:")
            for c in self.recent_commits[:5]:
                parts.append(f"- {c}")

        if self.filtered_files:
            parts.append("\nExcluded Noise/Lockfiles (Omitted from diff payload):")
            for ff in self.filtered_files:
                reason = f" ({ff.ignore_reason})" if ff.ignore_reason else ""
                parts.append(f"- {ff.file_path}{reason}")

        parts.append("\n--- File Diffs ---")

        current_char_count = sum(len(p) for p in parts)
        truncated = False

        for file_obj in self.files:
            file_header = f"\n### File: {file_obj.file_path} [{file_obj.change_type.upper()}] (+{file_obj.insertions}/-{file_obj.deletions})\n"
            content = file_obj.diff_content.strip()

            if file_obj.is_binary:
                entry = f"{file_header}[Binary file content omitted]\n"
            elif not content:
                entry = f"{file_header}[Empty or metadata-only change]\n"
            else:
                entry = f"{file_header}```diff\n{content}\n```\n"

            if current_char_count + len(entry) > max_chars:
                # Need to truncate remaining files
                remaining_files = [f.file_path for f in self.files[self.files.index(file_obj):]]
                parts.append(
                    f"\n[... Diff truncated: {len(remaining_files)} remaining files not shown: "
                    f"{', '.join(remaining_files[:6])} ...]"
                )
                truncated = True
                break

            parts.append(entry)
            current_char_count += len(entry)

        if truncated:
            self.is_truncated = True
            self.truncation_note = f"Diff truncated to stay within local model context budget (~{max_chars} chars)."

        return "\n".join(parts)


class GitParser:
    """Executes safe git commands and structures diff output."""

    def __init__(self, repo_path: Optional[Path] = None, ignored_patterns: Optional[Set[str]] = None):
        self.repo_path = Path(repo_path or Path.cwd()).resolve()
        self.ignored_patterns = ignored_patterns or set(DEFAULT_IGNORED_PATTERNS)
        self.validate_repository()

    def run_git(self, args: List[str], check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
        """
        Safely executes a git command via subprocess with argument list (no shell=True).
        """
        cmd = ["git"] + args
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            if check and result.returncode != 0:
                raise GitError(f"Git command failed: {' '.join(cmd)}\nStderr: {result.stderr.strip()}")
            return result
        except FileNotFoundError:
            raise GitError("Git executable not found in system PATH. Please ensure git is installed.")
        except subprocess.TimeoutExpired:
            raise GitError(f"Git command timed out after {timeout} seconds: {' '.join(cmd)}")

    def validate_repository(self) -> None:
        """Ensures target path is an active git repository."""
        proc = self.run_git(["rev-parse", "--is-inside-work-tree"], check=False)
        if proc.returncode != 0 or proc.stdout.strip() != "true":
            raise NotAGitRepositoryError(
                f"Directory '{self.repo_path}' is not a valid git repository.\n"
                "Please run CommitSloth inside a git repository or specify --repo <path>."
            )

    def get_repo_name(self) -> str:
        """Retrieves root directory name of repository."""
        proc = self.run_git(["rev-parse", "--show-toplevel"], check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).name
        return self.repo_path.name

    def get_current_branch(self) -> str:
        """Retrieves the active branch name or HEAD commit hash if detached."""
        proc = self.run_git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
        branch = proc.stdout.strip()
        if branch and branch != "HEAD":
            return branch
        # Fallback to short hash if detached HEAD
        hash_proc = self.run_git(["rev-parse", "--short", "HEAD"], check=False)
        if hash_proc.returncode == 0 and hash_proc.stdout.strip():
            return f"detached-at-{hash_proc.stdout.strip()}"
        return "initial-commit"

    def get_recent_commits(self, count: int = 5) -> List[str]:
        """Fetches up to `count` recent commits on the current branch."""
        proc = self.run_git(
            ["log", f"-n{count}", "--pretty=format:%h - %s (%an, %cr)"],
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return [line.strip() for line in proc.stdout.strip().splitlines() if line.strip()]
        return []

    def has_commits(self) -> bool:
        """Checks if the repository has at least one commit."""
        proc = self.run_git(["rev-parse", "--verify", "HEAD"], check=False)
        return proc.returncode == 0

    def is_file_ignored(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Determines whether a file matches any of the ignored noise patterns.
        """
        normalized_path = file_path.replace("\\", "/")
        filename = Path(normalized_path).name

        for pattern in self.ignored_patterns:
            # Match against filename (e.g., package-lock.json or *.png)
            if fnmatch.fnmatch(filename, pattern):
                return True, f"matches pattern '{pattern}'"
            # Match against full relative path (e.g., dist/* or .venv/*)
            if fnmatch.fnmatch(normalized_path, pattern):
                return True, f"matches path pattern '{pattern}'"

        return False, None

    def fetch_diff(
        self,
        staged_only: bool = False,
        base_branch: Optional[str] = None,
        commit_hash: Optional[str] = None,
    ) -> GitDiffPayload:
        """
        Retrieves raw git diff based on provided parameters, parses file chunks,
        filters noise assets, and packages into a structured GitDiffPayload.
        """
        diff_output = ""
        diff_scope = "uncommitted"

        if commit_hash:
            # Commit diff
            diff_scope = f"commit:{commit_hash}"
            proc = self.run_git(["show", "--binary", commit_hash])
            diff_output = proc.stdout
        elif base_branch:
            # Branch comparison: base_branch...HEAD or base_branch
            diff_scope = f"branch-compare:{base_branch}...HEAD"
            proc = self.run_git(["diff", "--binary", f"{base_branch}...HEAD"], check=False)
            if proc.returncode != 0:
                # Fallback to direct two-dot diff
                proc = self.run_git(["diff", "--binary", f"{base_branch}"], check=True)
            diff_output = proc.stdout
        elif staged_only:
            diff_scope = "staged"
            proc = self.run_git(["diff", "--binary", "--cached"])
            diff_output = proc.stdout
        else:
            # Working tree: check if HEAD exists
            if self.has_commits():
                diff_scope = "uncommitted (staged & unstaged)"
                proc = self.run_git(["diff", "--binary", "HEAD"])
                diff_output = proc.stdout
            else:
                # New repository with no commits yet; check cached/staged
                diff_scope = "staged (initial repository commit)"
                proc = self.run_git(["diff", "--binary", "--cached"])
                diff_output = proc.stdout
                if not diff_output.strip():
                    # Check untracked files if unstaged
                    diff_output = ""

        # Check for untracked files if diff is empty and no commits exist yet
        if not diff_output.strip() and not staged_only and not base_branch and not commit_hash:
            # Check if there are unstaged changes in working tree
            unstaged_proc = self.run_git(["diff", "--binary"])
            if unstaged_proc.stdout.strip():
                diff_output = unstaged_proc.stdout
                diff_scope = "unstaged working changes"

        if not diff_output.strip():
            raise EmptyDiffError(
                f"No git diff changes found for scope: {diff_scope}.\n"
                "Tip: Stage files with 'git add .' or specify a branch with '--branch <name>'."
            )

        return self.parse_diff_output(diff_output, diff_scope)

    def parse_diff_output(self, raw_diff: str, diff_scope: str) -> GitDiffPayload:
        """
        Parses raw unified diff into individual DiffFile objects and computes stats.
        """
        # Split diff by file header: 'diff --git a/... b/...'
        raw_chunks = re.split(r"(?=^diff --git )", raw_diff, flags=re.MULTILINE)

        files: List[DiffFile] = []
        filtered_files: List[DiffFile] = []
        total_insertions = 0
        total_deletions = 0

        for chunk in raw_chunks:
            chunk = chunk.strip()
            if not chunk or not chunk.startswith("diff --git"):
                continue

            lines = chunk.splitlines()
            header_line = lines[0]
            # e.g., 'diff --git a/src/index.ts b/src/index.ts'
            match = re.match(r"^diff --git a/(.*?) b/(.*?)$", header_line)
            if not match:
                continue

            old_file_path = match.group(1)
            new_file_path = match.group(2)
            display_path = new_file_path if new_file_path != "/dev/null" else old_file_path

            # Detect change type
            change_type = "modified"
            is_binary = False
            for line in lines[1:8]:
                if line.startswith("new file mode"):
                    change_type = "added"
                elif line.startswith("deleted file mode"):
                    change_type = "deleted"
                elif line.startswith("similarity index"):
                    change_type = "renamed"
                elif "Binary files" in line or "GIT binary patch" in line:
                    is_binary = True

            # Check if file should be ignored/filtered
            is_ignored, ignore_reason = self.is_file_ignored(display_path)

            # Count insertions and deletions
            insertions = 0
            deletions = 0
            diff_lines: List[str] = []

            for line in lines:
                if line.startswith("+") and not line.startswith("+++"):
                    insertions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1

                # Clean up chunk line for display
                if not line.startswith("index ") and not line.startswith("diff --git"):
                    diff_lines.append(line)

            # Cap individual file diff lines to prevent runaway lockfiles or minified code
            if len(diff_lines) > DEFAULT_MAX_FILE_DIFF_LINES:
                truncated_count = len(diff_lines) - DEFAULT_MAX_FILE_DIFF_LINES
                diff_lines = diff_lines[:DEFAULT_MAX_FILE_DIFF_LINES]
                diff_lines.append(f"\n[... {truncated_count} lines truncated for this file ...]")

            clean_diff_content = "\n".join(diff_lines)

            diff_file = DiffFile(
                file_path=display_path,
                old_path=old_file_path if old_file_path != new_file_path else None,
                change_type=change_type,
                insertions=insertions,
                deletions=deletions,
                diff_content=clean_diff_content,
                is_binary=is_binary,
                is_ignored=is_ignored,
                ignore_reason=ignore_reason,
            )

            if is_ignored:
                filtered_files.append(diff_file)
            else:
                files.append(diff_file)
                total_insertions += insertions
                total_deletions += deletions

        # If all files were ignored (e.g. only package-lock.json changed), keep them with a notice
        if not files and filtered_files:
            files = filtered_files
            filtered_files = []
            for f in files:
                f.is_ignored = False

        repo_name = self.get_repo_name()
        current_branch = self.get_current_branch()
        recent_commits = self.get_recent_commits(count=5)

        return GitDiffPayload(
            repo_name=repo_name,
            repo_path=str(self.repo_path),
            current_branch=current_branch,
            diff_scope=diff_scope,
            files=files,
            filtered_files=filtered_files,
            recent_commits=recent_commits,
            total_insertions=total_insertions,
            total_deletions=total_deletions,
        )
