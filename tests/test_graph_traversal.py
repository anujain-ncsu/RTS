"""Tests for the graph traversal module."""

import pytest

from rts.models import FileInfo, FileType, IndexData, Thoroughness
from rts.selector.graph_traversal import GraphTraversal


def _make_index() -> IndexData:
    """Create a test index with known dependency structure.

    Structure:
        src/core.py      <-- src/utils.py imports core
        src/utils.py     <-- src/api.py imports utils
        src/api.py       <-- tests/test_api.py imports api
        src/standalone.py
        tests/test_api.py       (direct import of api)
        tests/test_core.py      (direct import of core)
        tests/test_utils.py     (direct import of utils)
    """
    files = {
        "src/core.py": FileInfo(
            path="src/core.py", file_type=FileType.SOURCE,
            imports=[], symbols=["Core"],
        ),
        "src/utils.py": FileInfo(
            path="src/utils.py", file_type=FileType.SOURCE,
            imports=["src/core.py"], symbols=["helper"],
        ),
        "src/api.py": FileInfo(
            path="src/api.py", file_type=FileType.SOURCE,
            imports=["src/utils.py"], symbols=["API"],
        ),
        "src/standalone.py": FileInfo(
            path="src/standalone.py", file_type=FileType.SOURCE,
            imports=[], symbols=["Standalone"],
        ),
        "tests/test_api.py": FileInfo(
            path="tests/test_api.py", file_type=FileType.TEST,
            imports=["src/api.py"], test_functions=["test_api_works"],
        ),
        "tests/test_core.py": FileInfo(
            path="tests/test_core.py", file_type=FileType.TEST,
            imports=["src/core.py"], test_functions=["test_core_works"],
        ),
        "tests/test_utils.py": FileInfo(
            path="tests/test_utils.py", file_type=FileType.TEST,
            imports=["src/utils.py"], test_functions=["test_utils_work"],
        ),
    }

    return IndexData(
        version="1.0",
        repository="/fake/repo",
        created_at="2026-01-01T00:00:00Z",
        files=files,
    )


class TestGraphTraversal:
    """Tests for BFS graph traversal at different depths."""

    def test_quick_direct_import(self):
        """Quick mode should find tests that directly import the changed file."""
        index = _make_index()
        traversal = GraphTraversal(index)

        affected = traversal.find_affected_tests(["src/api.py"], Thoroughness.QUICK)
        assert "tests/test_api.py" in affected
        assert affected["tests/test_api.py"] == 0  # Direct import

    def test_quick_no_transitive(self):
        """Quick mode should NOT find transitively affected tests."""
        index = _make_index()
        traversal = GraphTraversal(index)

        affected = traversal.find_affected_tests(["src/core.py"], Thoroughness.QUICK)
        # test_core.py directly imports core, so it's found
        assert "tests/test_core.py" in affected
        # test_utils.py imports utils which imports core, but that's transitive
        assert "tests/test_utils.py" not in affected

    def test_standard_transitive(self):
        """Standard mode should find transitively affected tests."""
        index = _make_index()
        traversal = GraphTraversal(index)

        affected = traversal.find_affected_tests(["src/core.py"], Thoroughness.STANDARD)
        assert "tests/test_core.py" in affected      # direct
        assert "tests/test_utils.py" in affected      # transitive depth 1
        assert "tests/test_api.py" in affected         # transitive depth 2

    def test_standard_depth_tracking(self):
        """Standard mode should track correct depths."""
        index = _make_index()
        traversal = GraphTraversal(index)

        affected = traversal.find_affected_tests(["src/core.py"], Thoroughness.STANDARD)
        assert affected["tests/test_core.py"] == 0     # direct
        assert affected["tests/test_utils.py"] == 1    # 1 hop
        assert affected["tests/test_api.py"] == 2      # 2 hops

    def test_thorough_unlimited_depth(self):
        """Thorough mode should traverse to unlimited depth."""
        index = _make_index()
        traversal = GraphTraversal(index)

        affected = traversal.find_affected_tests(["src/core.py"], Thoroughness.THOROUGH)
        assert "tests/test_core.py" in affected
        assert "tests/test_utils.py" in affected
        assert "tests/test_api.py" in affected

    def test_no_affected_tests(self):
        """Standalone file with no importers should return nothing."""
        index = _make_index()
        traversal = GraphTraversal(index)

        affected = traversal.find_affected_tests(["src/standalone.py"], Thoroughness.THOROUGH)
        assert len(affected) == 0

    def test_unknown_file(self):
        """Unknown changed file should be silently skipped."""
        index = _make_index()
        traversal = GraphTraversal(index)

        affected = traversal.find_affected_tests(["nonexistent.py"], Thoroughness.STANDARD)
        assert len(affected) == 0

    def test_multiple_changed_files(self):
        """Multiple changed files should union their affected tests."""
        index = _make_index()
        traversal = GraphTraversal(index)

        affected = traversal.find_affected_tests(
            ["src/core.py", "src/standalone.py"],
            Thoroughness.QUICK,
        )
        assert "tests/test_core.py" in affected
        # standalone has no tests
        assert len(affected) == 1
