"""Parses diffs and extracts changed file paths.

Supports three input formats:
1. Unified diff (text) — from `git diff` output
2. Commit range — runs `git diff` internally
3. File list — comma-separated or newline-separated file paths
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Matches the --- a/path and +++ b/path lines in unified diffs
_DIFF_FILE_PATTERN = re.compile(r"^(?:---|\+\+\+) [ab]/(.+)$", re.MULTILINE)

# Matches the diff --git a/path b/path header
_DIFF_HEADER_PATTERN = re.compile(
    r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE
)


class DiffParser:
    """Parses various diff formats to extract changed file paths."""

    def parse_unified_diff(self, diff_text: str) -> list[str]:
        """Extract changed file paths from a unified diff.

        Args:
            diff_text: The unified diff text (e.g., from `git diff`).

        Returns:
            Sorted list of unique changed file paths.
        """
        changed_files: set[str] = set()

        # Try the --git header format first (most common)
        for match in _DIFF_HEADER_PATTERN.finditer(diff_text):
            # Use the 'b' path (new path) as it handles renames
            changed_files.add(match.group(2))

        # If no --git headers found, try --- / +++ lines
        if not changed_files:
            for match in _DIFF_FILE_PATTERN.finditer(diff_text):
                path = match.group(1)
                if path != "/dev/null":
                    changed_files.add(path)

        return sorted(changed_files)

    def parse_commit_range(
        self, repo_path: Path, commit_range: str
    ) -> list[str]:
        """Extract changed files from a git commit range.

        Runs `git diff --name-only` for the given range.

        Args:
            repo_path: Path to the git repository.
            commit_range: Git commit range (e.g., "HEAD~3..HEAD", or a single commit hash).

        Returns:
            Sorted list of changed file paths.

        Raises:
            subprocess.CalledProcessError: If git command fails.
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", commit_range],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            files = [
                f.strip()
                for f in result.stdout.strip().split("\n")
                if f.strip()
            ]
            return sorted(set(files))
        except subprocess.CalledProcessError as e:
            logger.error("git diff failed: %s", e.stderr)
            raise
        except subprocess.TimeoutExpired:
            logger.error("git diff timed out after 30s")
            raise

    def parse_file_list(self, file_list: str) -> list[str]:
        """Parse a comma-separated or newline-separated list of file paths.

        Args:
            file_list: Comma or newline-separated file paths.

        Returns:
            Sorted list of file paths.
        """
        # Split on commas and newlines
        files: set[str] = set()
        for line in file_list.replace(",", "\n").split("\n"):
            stripped = line.strip()
            if stripped:
                files.add(stripped)

        return sorted(files)

    def parse_diff_file(self, diff_path: Path) -> list[str]:
        """Read and parse a diff from a file.

        Args:
            diff_path: Path to the diff file.

        Returns:
            Sorted list of changed file paths.
        """
        diff_text = diff_path.read_text(encoding="utf-8")
        return self.parse_unified_diff(diff_text)
