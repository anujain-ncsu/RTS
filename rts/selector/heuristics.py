"""Naming convention and path-based heuristics for test selection.

Used at the 'thorough' thoroughness level to catch tests that may not be
connected via the import graph but are related by naming conventions.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rts.models import FileType, IndexData

logger = logging.getLogger(__name__)


class Heuristics:
    """Applies naming and path-based heuristics to find related tests."""

    def __init__(self, index: IndexData) -> None:
        self.index = index
        self._test_files: set[str] = {
            fp
            for fp, info in self.index.files.items()
            if info.file_type == FileType.TEST
        }
        # Pre-build lookup maps
        self._test_by_stem: dict[str, list[str]] = {}
        self._test_by_dir: dict[str, list[str]] = {}
        self._build_lookups()

    def _build_lookups(self) -> None:
        """Build lookup maps for fast heuristic matching."""
        for tf in self._test_files:
            p = Path(tf)
            stem = p.stem  # e.g., "test_models"
            self._test_by_stem.setdefault(stem, []).append(tf)

            # Group test files by directory
            dir_path = str(p.parent)
            self._test_by_dir.setdefault(dir_path, []).append(tf)

    def find_related_tests(
        self,
        changed_files: list[str],
        already_selected: set[str] | None = None,
    ) -> dict[str, list[str]]:
        """Find tests related to changed files via heuristics.

        Args:
            changed_files: List of changed file paths.
            already_selected: Set of test files already selected by graph traversal.

        Returns:
            Dict mapping test file -> list of reasons why it was matched.
        """
        already = already_selected or set()
        matches: dict[str, list[str]] = {}

        for changed_file in changed_files:
            p = Path(changed_file)
            source_stem = p.stem.lstrip("_")  # "_models" -> "models"

            # 1. Naming convention: source.py -> test_source.py
            test_stem = f"test_{source_stem}"
            for candidate in self._test_by_stem.get(test_stem, []):
                if candidate not in already:
                    matches.setdefault(candidate, []).append(
                        f"naming_convention({p.name})"
                    )

            # 2. Same package: tests in the same directory as the changed file
            source_dir = str(p.parent)
            for candidate in self._test_by_dir.get(source_dir, []):
                if candidate not in already and candidate not in matches:
                    matches.setdefault(candidate, []).append(
                        f"same_package({source_dir})"
                    )

            # 3. Parallel test directory: src/foo/bar.py -> tests/foo/test_bar.py
            # Try to find a tests/ directory that mirrors the source structure
            parts = list(p.parts)
            for i, part in enumerate(parts):
                if part in ("src", "lib", "pkg"):
                    # Replace with "tests" and look for test files
                    test_parts = list(parts)
                    test_parts[i] = "tests"
                    test_dir = str(Path(*test_parts[: -1]))
                    for candidate in self._test_by_dir.get(test_dir, []):
                        if candidate not in already and candidate not in matches:
                            matches.setdefault(candidate, []).append(
                                f"parallel_directory({test_dir})"
                            )
                    break

        return matches
