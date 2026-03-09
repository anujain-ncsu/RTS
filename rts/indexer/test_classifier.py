"""Classifies Python files as test files or source files."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directory names that typically contain tests
_TEST_DIR_NAMES = {"tests", "test", "testing", "test_suite"}

# File name patterns that indicate test files
_TEST_FILE_PREFIXES = ("test_",)
_TEST_FILE_SUFFIXES = ("_test.py",)


class TestClassifier:
    """Classifies Python files as test or source based on path and naming heuristics."""

    def is_test_file(self, file_path: str, test_functions: list[str] | None = None) -> bool:
        """Determine if a file is a test file.

        Uses a combination of:
        1. Path-based heuristics (file is under a test directory)
        2. Filename conventions (starts with test_ or ends with _test.py)
        3. Content-based signals (contains test functions)

        Args:
            file_path: Relative path to the file.
            test_functions: List of test function names found in the file, if available.

        Returns:
            True if the file is classified as a test file.
        """
        p = Path(file_path)

        # Check filename conventions
        if p.name.startswith("test_"):
            return True
        if p.name.endswith("_test.py"):
            return True

        # conftest.py is test infrastructure
        if p.name == "conftest.py":
            return True

        # Check if any parent directory is a test directory
        for parent in p.parents:
            if parent.name.lower() in _TEST_DIR_NAMES:
                return True

        # Check if the file contains test functions
        if test_functions and len(test_functions) > 0:
            return True

        return False

    def classify_files(
        self,
        file_paths: list[str],
        file_test_functions: dict[str, list[str]] | None = None,
    ) -> dict[str, bool]:
        """Classify a batch of files as test or source.

        Args:
            file_paths: List of relative file paths.
            file_test_functions: Optional mapping of file path -> test functions found.

        Returns:
            Dict mapping file path -> True if test, False if source.
        """
        result: dict[str, bool] = {}
        test_funcs = file_test_functions or {}

        for fp in file_paths:
            result[fp] = self.is_test_file(fp, test_funcs.get(fp))

        return result
