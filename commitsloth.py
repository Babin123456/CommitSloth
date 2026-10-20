#!/usr/bin/env python3
"""
CommitSloth - Local, offline-first developer productivity tool.
Entrypoint script for running CommitSloth from the repository root.
"""

import sys

# Ensure UTF-8 console output on Windows to handle emojis cleanly
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from commitsloth.cli import main

if __name__ == "__main__":
    sys.exit(main())
