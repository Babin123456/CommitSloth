"""
CommitSloth Configuration & Constants.
"""

from dataclasses import dataclass, field
from typing import List, Set

# Default Ollama Connection Settings
DEFAULT_OLLAMA_HOST: str = "http://localhost:11434"
DEFAULT_MODEL: str = "gemma:2b"
SUPPORTED_GEMMA_PREFIXES: List[str] = ["gemma", "gemma2", "gemma:2b", "gemma:7b", "gemma2:2b", "gemma2:9b", "gemma2:27b"]

# Maximum characters allowed for diff payload before smart truncation (approx 3,000-4,000 tokens)
DEFAULT_MAX_DIFF_CHARS: int = 14000
DEFAULT_MAX_FILE_DIFF_LINES: int = 350

# Irrelevant assets, lockfiles, and generated files to ignore during diff analysis
DEFAULT_IGNORED_PATTERNS: Set[str] = {
    # Lockfiles
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "mix.lock",
    "go.sum",
    "flake.lock",
    # Minified & bundle files
    "*.min.js",
    "*.min.css",
    "*.bundle.js",
    "*.bundle.css",
    "*.map",
    # Binary assets & images
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.ico",
    "*.svg",
    "*.webp",
    "*.bmp",
    "*.tiff",
    "*.pdf",
    "*.mp4",
    "*.mov",
    "*.webm",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.bin",
    "*.exe",
    "*.dll",
    "*.so",
    "*.dylib",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.eot",
    # Python & runtime caches
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "__pycache__/*",
    ".pytest_cache/*",
    ".mypy_cache/*",
    ".ruff_cache/*",
    ".tox/*",
    # Build & distribution directories
    "dist/*",
    "build/*",
    "target/*",
    "node_modules/*",
    ".venv/*",
    "venv/*",
    "env/*",
    ".next/*",
    ".nuxt/*",
    ".output/*",
}


@dataclass
class CommitSlothConfig:
    """Runtime configuration for CommitSloth."""
    ollama_host: str = DEFAULT_OLLAMA_HOST
    model_name: str = DEFAULT_MODEL
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS
    max_file_diff_lines: int = DEFAULT_MAX_FILE_DIFF_LINES
    temperature: float = 0.2
    top_p: float = 0.9
    timeout: int = 120
    ignored_patterns: Set[str] = field(default_factory=lambda: set(DEFAULT_IGNORED_PATTERNS))
