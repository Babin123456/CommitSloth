"""
Unit tests for CommitSloth Git Parser.
"""

from pathlib import Path
import pytest

from commitsloth.git_parser import (
    DiffFile,
    EmptyDiffError,
    GitDiffPayload,
    GitParser,
    NotAGitRepositoryError,
)

SAMPLE_RAW_DIFF = """diff --git a/commitsloth/agent_core.py b/commitsloth/agent_core.py
index e69de29..4b825dc 100644
--- a/commitsloth/agent_core.py
+++ b/commitsloth/agent_core.py
@@ -1,5 +1,10 @@
+import requests
+
 def analyze():
-    pass
+    print("Analyzing code diff locally with Gemma")
+    return True
diff --git a/package-lock.json b/package-lock.json
index 1111111..2222222 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,3 +1,6 @@
+{
+  "lockfileVersion": 3
+}
diff --git a/docs/logo.png b/docs/logo.png
new file mode 100644
index 0000000..3333333
Binary files /dev/null and b/docs/logo.png differ
"""


class DummyGitParser(GitParser):
    """Subclass of GitParser bypassing actual repo check for unit testing."""
    def __init__(self):
        self.repo_path = Path("/mock/repo")
        self.ignored_patterns = {
            "package-lock.json",
            "*.png",
            "*.min.js",
            "node_modules/*",
        }

    def validate_repository(self) -> None:
        pass

    def get_repo_name(self) -> str:
        return "mock-repo"

    def get_current_branch(self) -> str:
        return "feature/offline-ai"

    def get_recent_commits(self, count: int = 5):
        return ["a1b2c3d - Initial commit (author, 1 day ago)"]


def test_is_file_ignored():
    parser = DummyGitParser()

    # Lockfiles & assets should be ignored
    ignored, reason = parser.is_file_ignored("package-lock.json")
    assert ignored is True
    assert "package-lock.json" in reason

    ignored, reason = parser.is_file_ignored("assets/banner.png")
    assert ignored is True

    ignored, reason = parser.is_file_ignored("dist/bundle.min.js")
    assert ignored is True

    # Real source files should NOT be ignored
    ignored, reason = parser.is_file_ignored("commitsloth/agent_core.py")
    assert ignored is False
    assert reason is None

    ignored, reason = parser.is_file_ignored("src/components/App.tsx")
    assert ignored is False


def test_parse_diff_output():
    parser = DummyGitParser()
    payload = parser.parse_diff_output(SAMPLE_RAW_DIFF, diff_scope="uncommitted")

    assert payload.repo_name == "mock-repo"
    assert payload.current_branch == "feature/offline-ai"
    assert payload.diff_scope == "uncommitted"

    # We expect 1 active file (agent_core.py) and 2 filtered files (package-lock.json, logo.png)
    assert len(payload.files) == 1
    assert payload.files[0].file_path == "commitsloth/agent_core.py"
    assert payload.files[0].change_type == "modified"
    assert payload.files[0].insertions > 0

    assert len(payload.filtered_files) == 2
    filtered_paths = [f.file_path for f in payload.filtered_files]
    assert "package-lock.json" in filtered_paths
    assert "docs/logo.png" in filtered_paths


def test_render_diff_for_prompt():
    parser = DummyGitParser()
    payload = parser.parse_diff_output(SAMPLE_RAW_DIFF, diff_scope="uncommitted")

    rendered = payload.render_diff_for_prompt(max_chars=2000)
    assert "Repository: mock-repo" in rendered
    assert "Branch: feature/offline-ai" in rendered
    assert "Excluded Noise/Lockfiles" in rendered
    assert "package-lock.json" in rendered
    assert "commitsloth/agent_core.py" in rendered
    assert "print(\"Analyzing code diff locally with Gemma\")" in rendered


def test_render_diff_truncation():
    file1 = DiffFile(
        file_path="huge_file.py",
        change_type="modified",
        insertions=500,
        deletions=100,
        diff_content="+" + "x" * 2000,
    )
    file2 = DiffFile(
        file_path="another_file.py",
        change_type="added",
        insertions=100,
        deletions=0,
        diff_content="+" + "y" * 2000,
    )

    payload = GitDiffPayload(
        repo_name="huge-repo",
        repo_path="/path",
        current_branch="main",
        diff_scope="test",
        files=[file1, file2],
        total_insertions=600,
        total_deletions=100,
    )

    rendered = payload.render_diff_for_prompt(max_chars=1000)
    assert payload.is_truncated is True
    assert "Diff truncated" in rendered
