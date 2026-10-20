"""
CommitSloth Agent Core.

Communicates with local Ollama running Google's Gemma model at http://localhost:11434/api/generate,
enforces zero-cloud-leakage guardrails, constructs structured prompts, and parses generated PR documentation.
"""

from dataclasses import dataclass, field
import json
import re
from typing import Callable, Dict, Generator, List, Optional, Tuple
import urllib.parse
import urllib.request
import urllib.error

import requests

from .config import DEFAULT_OLLAMA_HOST, DEFAULT_MODEL
from .git_parser import GitDiffPayload


class OllamaError(Exception):
    """Base exception for Ollama interactions."""
    pass


class OllamaConnectionError(OllamaError):
    """Raised when Ollama daemon is unreachable on localhost."""
    pass


class OllamaModelNotFoundError(OllamaError):
    """Raised when requested Gemma model is not installed locally."""
    pass


class SecurityViolationError(Exception):
    """Raised if an attempt is made to send code diffs to non-localhost destinations."""
    pass


@dataclass
class CommitSlothResult:
    """Structured output parsed from Gemma's response."""
    raw_response: str
    pr_title: str
    changelog: str
    testing_instructions: str
    release_notes: str = ""
    model_name: str = ""
    total_duration_sec: float = 0.0

    def to_markdown(self) -> str:
        """Renders complete, polished GitHub PR description markdown."""
        parts = [
            f"# {self.pr_title}\n",
            "## 📋 Changelog & Key Changes",
            self.changelog.strip() + "\n",
            "## 🧪 Testing Instructions",
            self.testing_instructions.strip() + "\n",
        ]
        if self.release_notes.strip():
            parts.extend([
                "## 🚀 Release Summary",
                self.release_notes.strip() + "\n",
            ])
        parts.append(
            "\n---\n*Generated locally & privately by [CommitSloth 🦥](https://github.com/CommitSloth/CommitSloth) "
            f"using `{self.model_name}` via Ollama.*"
        )
        return "\n".join(parts)


class AgentCore:
    """Manages prompt engineering, local Ollama communication, and response extraction."""

    def __init__(
        self,
        host: str = DEFAULT_OLLAMA_HOST,
        model_name: str = DEFAULT_MODEL,
        timeout: int = 120,
    ):
        self.host = host.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self.verify_zero_cloud_leakage(self.host)

    @staticmethod
    def verify_zero_cloud_leakage(host_url: str) -> None:
        """
        Guardrail: Strictly verifies that all AI requests remain locked to localhost.
        Prevents accidental leakage of proprietary source code to external servers.
        """
        parsed = urllib.parse.urlparse(host_url)
        hostname = (parsed.hostname or "").lower()
        allowed_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

        if hostname not in allowed_hosts:
            raise SecurityViolationError(
                f"[SECURITY ALERT] CommitSloth is strictly offline-first. "
                f"Target host '{host_url}' is not a local loopback address ({allowed_hosts}). "
                "Transmission of source code diffs to remote hosts is blocked to prevent data leakage."
            )

    def check_health(self) -> Tuple[bool, str]:
        """
        Checks if Ollama service is reachable on localhost.
        Returns (is_reachable, message).
        """
        try:
            resp = requests.get(f"{self.host}/", timeout=3)
            if resp.status_code == 200:
                return True, "Ollama is running."
            return False, f"Ollama returned HTTP status {resp.status_code}."
        except requests.exceptions.ConnectionError:
            return False, (
                f"Could not connect to Ollama at {self.host}.\n"
                "Please make sure Ollama is installed and running:\n"
                "  1. Start the service: run 'ollama serve' in a terminal\n"
                "  2. Verify it at: http://localhost:11434"
            )
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    def get_installed_models(self) -> List[str]:
        """Queries Ollama /api/tags for installed local models."""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return [m.get("name", "") for m in data.get("models", [])]
            return []
        except Exception:
            return []

    def verify_model_available(self, auto_fallback: bool = True) -> str:
        """
        Verifies that the requested model or an available Gemma variant is installed.
        Returns the confirmed model tag to use.
        """
        is_up, msg = self.check_health()
        if not is_up:
            raise OllamaConnectionError(msg)

        models = self.get_installed_models()

        # Check exact match
        if self.model_name in models:
            return self.model_name

        # Check with :latest or prefix match
        for m in models:
            if m.startswith(self.model_name + ":") or m == f"{self.model_name}:latest":
                self.model_name = m
                return m

        # Check if another gemma model is installed
        if auto_fallback:
            gemma_candidates = [m for m in models if "gemma" in m.lower()]
            if gemma_candidates:
                chosen = gemma_candidates[0]
                self.model_name = chosen
                return chosen

        # Neither model nor fallback found
        installed_list = ", ".join(models) if models else "None"
        raise OllamaModelNotFoundError(
            f"Model '{self.model_name}' was not found in local Ollama repository.\n"
            f"Currently installed models: [{installed_list}]\n\n"
            f"To pull Google's Gemma model, run:\n"
            f"  ollama pull {self.model_name}\n"
            f"or for the ultra-fast 2B parameter version:\n"
            f"  ollama pull gemma:2b"
        )

    def construct_gemma_prompt(self, diff_payload: GitDiffPayload, prompt_style: str = "all") -> str:
        """
        Constructs a structured instruction prompt tailored for Google's Gemma model.
        Leverages Gemma's instruction-following capabilities to ensure strict markdown output.
        """
        rendered_diff = diff_payload.render_diff_for_prompt()

        prompt = f"""You are CommitSloth, a high-caliber code reviewer, principal software engineer, and release documentation assistant.
Your job is to analyze the following Git diff from repository '{diff_payload.repo_name}' and produce clean, developer-focused paperwork.

Follow these strict output guidelines:
1. PR Title:
   - Write ONE line starting with "## PR Title: " followed by a Conventional Commit format message.
   - Format: `<type>(<scope>): <concise description>`
   - Allowed types: feat, fix, refactor, docs, chore, test, perf, style.
   - Example: `feat(git): add offline diff parser and gemma integration`

2. Key Changes & Changelog:
   - Provide a section starting with "## Changelog"
   - Use clear bullet points explaining WHAT changed and WHY from a technical standpoint.
   - Group related file changes logically.
   - Be concise, precise, and avoid filler words.

3. Testing Instructions:
   - Provide a section starting with "## Testing Instructions"
   - Detail step-by-step actions a code reviewer must take locally to verify these changes.
   - Include specific CLI commands, unit tests, or edge-case test vectors where applicable.

4. Release Summary (Brief):
   - Provide a section starting with "## Release Summary"
   - 1-2 sentence high-level overview suitable for release notes or git tag descriptions.

=== GIT DIFF DATA ===
{rendered_diff}
=== END GIT DIFF DATA ===

Now, produce the structured Markdown documentation:"""

        return prompt

    def generate(
        self,
        diff_payload: GitDiffPayload,
        stream_callback: Optional[Callable[[str], None]] = None,
        mock: bool = False,
    ) -> CommitSlothResult:
        """
        Sends the payload to Ollama /api/generate and returns parsed CommitSlothResult.
        """
        if mock:
            return self._generate_mock(diff_payload)

        # Ensure model is ready
        active_model = self.verify_model_available(auto_fallback=True)
        prompt = self.construct_gemma_prompt(diff_payload)

        url = f"{self.host}/api/generate"
        payload = {
            "model": active_model,
            "prompt": prompt,
            "stream": stream_callback is not None,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_predict": 1200,
            },
        }

        try:
            if stream_callback:
                return self._generate_streaming(url, payload, stream_callback, active_model)
            else:
                return self._generate_non_streaming(url, payload, active_model)
        except requests.exceptions.ConnectionError:
            raise OllamaConnectionError(
                f"Failed to communicate with Ollama at {self.host}.\n"
                "Please ensure 'ollama serve' is active."
            )
        except requests.exceptions.Timeout:
            raise OllamaError(
                f"Ollama request timed out after {self.timeout}s.\n"
                "Tip: Local models may require more time on first load. Consider using a smaller model like 'gemma:2b'."
            )

    def _generate_non_streaming(self, url: str, payload: dict, model_name: str) -> CommitSlothResult:
        """Handles non-streaming Ollama response."""
        resp = requests.post(url, json=payload, timeout=self.timeout)
        if resp.status_code != 200:
            raise OllamaError(f"Ollama error (HTTP {resp.status_code}): {resp.text}")

        data = resp.json()
        raw_text = data.get("response", "").strip()
        total_duration = data.get("total_duration", 0) / 1e9  # nanoseconds to seconds

        return self.parse_gemma_response(raw_text, model_name=model_name, duration_sec=total_duration)

    def _generate_streaming(
        self,
        url: str,
        payload: dict,
        stream_callback: Callable[[str], None],
        model_name: str,
    ) -> CommitSlothResult:
        """Handles streaming Ollama response line-by-line."""
        accumulated_text = []
        total_duration = 0.0

        with requests.post(url, json=payload, stream=True, timeout=self.timeout) as resp:
            if resp.status_code != 200:
                raise OllamaError(f"Ollama error (HTTP {resp.status_code}): {resp.text}")

            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode("utf-8"))
                    text_piece = chunk.get("response", "")
                    if text_piece:
                        accumulated_text.append(text_piece)
                        stream_callback(text_piece)
                    if chunk.get("done", False):
                        total_duration = chunk.get("total_duration", 0) / 1e9
                except Exception:
                    continue

        full_raw_text = "".join(accumulated_text).strip()
        return self.parse_gemma_response(full_raw_text, model_name=model_name, duration_sec=total_duration)

    def parse_gemma_response(
        self,
        raw_text: str,
        model_name: str = "",
        duration_sec: float = 0.0,
    ) -> CommitSlothResult:
        """
        Parses the Markdown response into discrete sections (PR Title, Changelog, Testing, Release).
        """
        pr_title = "feat: update project codebase and documentation"
        changelog = ""
        testing_instructions = ""
        release_notes = ""

        # Extract PR Title
        title_match = re.search(r"##\s*PR Title:\s*(.*)", raw_text, re.IGNORECASE)
        if not title_match:
            title_match = re.search(r"PR Title:\s*`?(feat|fix|refactor|docs|chore|test|perf|style)[^`\n]+`?", raw_text, re.IGNORECASE)
        if not title_match:
            # Fallback to first line if formatted as conventional commit
            first_line = raw_text.splitlines()[0].strip().lstrip("#").strip()
            if any(first_line.startswith(t) for t in ["feat", "fix", "refactor", "docs", "chore", "test"]):
                pr_title = first_line
        else:
            pr_title = title_match.group(1).strip().strip("`*")

        # Split into sections using Markdown headers
        sections = re.split(r"\n(?=##\s+)", raw_text)

        for sec in sections:
            sec_clean = sec.strip()
            if re.match(r"^##\s*Changelog", sec_clean, re.IGNORECASE):
                # Strip header
                changelog = re.sub(r"^##\s*Changelog[^\n]*\n", "", sec_clean, flags=re.IGNORECASE).strip()
            elif re.match(r"^##\s*Testing Instructions", sec_clean, re.IGNORECASE):
                testing_instructions = re.sub(r"^##\s*Testing Instructions[^\n]*\n", "", sec_clean, flags=re.IGNORECASE).strip()
            elif re.match(r"^##\s*Release Summary", sec_clean, re.IGNORECASE):
                release_notes = re.sub(r"^##\s*Release Summary[^\n]*\n", "", sec_clean, flags=re.IGNORECASE).strip()

        # Fallback if section splitting didn't catch sections
        if not changelog:
            changelog = raw_text
        if not testing_instructions:
            testing_instructions = "- Execute automated test suite: `pytest`\n- Verify repository working status with: `git status`"

        return CommitSlothResult(
            raw_response=raw_text,
            pr_title=pr_title,
            changelog=changelog,
            testing_instructions=testing_instructions,
            release_notes=release_notes,
            model_name=model_name or self.model_name,
            total_duration_sec=duration_sec,
        )

    def _generate_mock(self, diff_payload: GitDiffPayload) -> CommitSlothResult:
        """
        Generates a synthetic mock response for testing and offline environments
        without requiring active Ollama or downloaded weights.
        """
        files_list = [f.file_path for f in diff_payload.files]
        primary_file = files_list[0] if files_list else "core"
        scope = primary_file.split("/")[0].replace(".py", "").replace(".", "")

        pr_title = f"feat({scope}): implement offline git diff analysis and documentation generation"

        changelog_bullets = []
        for f in diff_payload.files[:8]:
            changelog_bullets.append(f"- **`{f.file_path}`**: Updated logic ({f.change_type}, +{f.insertions}/-{f.deletions} lines).")

        if diff_payload.filtered_files:
            changelog_bullets.append(f"- *(Filtered {len(diff_payload.filtered_files)} noise and lockfile assets from diff payload)*")

        changelog = "\n".join(changelog_bullets)

        testing = (
            "1. Run test suite to verify code diff extraction and parsing:\n"
            "   ```bash\n"
            "   pytest tests/ -v\n"
            "   ```\n"
            "2. Validate offline guardrail integrity:\n"
            "   ```bash\n"
            "   python commitsloth.py --diff-only\n"
            "   ```\n"
            "3. Test local Ollama endpoint connection:\n"
            "   ```bash\n"
            "   python commitsloth.py --mock\n"
            "   ```"
        )

        release = (
            f"CommitSloth processed {diff_payload.total_files_changed} files "
            f"(+{diff_payload.total_insertions}/-{diff_payload.total_deletions} lines) "
            "with zero cloud leakage, generating Conventional Commits PR documentation locally."
        )

        raw = (
            f"## PR Title: {pr_title}\n\n"
            f"## Changelog\n{changelog}\n\n"
            f"## Testing Instructions\n{testing}\n\n"
            f"## Release Summary\n{release}"
        )

        return CommitSlothResult(
            raw_response=raw,
            pr_title=pr_title,
            changelog=changelog,
            testing_instructions=testing,
            release_notes=release,
            model_name=f"{self.model_name} (mock)",
            total_duration_sec=0.15,
        )
