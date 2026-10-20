"""
Unit tests for CommitSloth Agent Core.
"""

import pytest

from commitsloth.agent_core import (
    AgentCore,
    CommitSlothResult,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    SecurityViolationError,
)
from commitsloth.git_parser import DiffFile, GitDiffPayload


def test_zero_cloud_leakage_guardrail():
    # Localhost and loopback IPs should be accepted
    AgentCore.verify_zero_cloud_leakage("http://localhost:11434")
    AgentCore.verify_zero_cloud_leakage("http://127.0.0.1:11434")
    AgentCore.verify_zero_cloud_leakage("http://0.0.0.0:11434")
    AgentCore.verify_zero_cloud_leakage("http://[::1]:11434")

    # Any remote cloud host MUST be blocked immediately with SecurityViolationError
    with pytest.raises(SecurityViolationError) as exc_info:
        AgentCore.verify_zero_cloud_leakage("https://api.openai.com/v1")
    assert "strictly offline-first" in str(exc_info.value)

    with pytest.raises(SecurityViolationError):
        AgentCore.verify_zero_cloud_leakage("https://remote-llm.mycloud.com:11434")

    with pytest.raises(SecurityViolationError):
        AgentCore.verify_zero_cloud_leakage("http://192.168.1.50:11434")


def test_construct_gemma_prompt():
    agent = AgentCore(host="http://localhost:11434", model_name="gemma:2b")
    file1 = DiffFile(
        file_path="src/auth.py",
        change_type="modified",
        insertions=12,
        deletions=3,
        diff_content="+ def verify_token(): return True",
    )
    payload = GitDiffPayload(
        repo_name="demo-app",
        repo_path="/demo",
        current_branch="auth-feature",
        diff_scope="staged",
        files=[file1],
        total_insertions=12,
        total_deletions=3,
    )

    prompt = agent.construct_gemma_prompt(payload)
    assert "You are CommitSloth" in prompt
    assert "Conventional Commit" in prompt
    assert "## PR Title: " in prompt
    assert "## Changelog" in prompt
    assert "## Testing Instructions" in prompt
    assert "src/auth.py" in prompt
    assert "verify_token" in prompt


def test_parse_gemma_response():
    agent = AgentCore()
    sample_gemma_output = """## PR Title: feat(auth): add local token validation and offline session caching

## Changelog
- **`src/auth.py`**: Added `verify_token` implementation to check local cryptographic signatures.
- **`src/config.py`**: Added configuration for offline cache expiration.

## Testing Instructions
1. Run pytest auth suite: `pytest tests/test_auth.py`
2. Test token with valid signature: `python -m src.auth verify`
3. Verify rejection of expired credentials.

## Release Summary
CommitSloth added offline token verification without contacting remote authorization endpoints."""

    result = agent.parse_gemma_response(sample_gemma_output, model_name="gemma:2b", duration_sec=1.42)

    assert result.pr_title == "feat(auth): add local token validation and offline session caching"
    assert "verify_token" in result.changelog
    assert "pytest tests/test_auth.py" in result.testing_instructions
    assert "offline token verification" in result.release_notes
    assert result.model_name == "gemma:2b"
    assert result.total_duration_sec == 1.42

    # Check to_markdown output
    md = result.to_markdown()
    assert "# feat(auth): add local token validation" in md
    assert "## 📋 Changelog & Key Changes" in md
    assert "## 🧪 Testing Instructions" in md
    assert "CommitSloth 🦥" in md


def test_generate_mock():
    agent = AgentCore(model_name="gemma:2b")
    file1 = DiffFile(
        file_path="commitsloth/git_parser.py",
        change_type="added",
        insertions=150,
        deletions=0,
        diff_content="+ class GitParser:",
    )
    payload = GitDiffPayload(
        repo_name="CommitSloth",
        repo_path="/code",
        current_branch="main",
        diff_scope="uncommitted",
        files=[file1],
        total_insertions=150,
        total_deletions=0,
    )

    result = agent.generate(payload, mock=True)
    assert isinstance(result, CommitSlothResult)
    assert "feat" in result.pr_title
    assert "commitsloth/git_parser.py" in result.changelog
    assert "pytest" in result.testing_instructions
    assert "mock" in result.model_name
