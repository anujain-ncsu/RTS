"""Tests for heuristic matching."""

import pytest

from rts.models import FileInfo, FileType, IndexData
from rts.selector.heuristics import Heuristics


def _make_index() -> IndexData:
    """Create a test index for heuristic testing."""
    files = {
        "httpx/_models.py": FileInfo(
            path="httpx/_models.py", file_type=FileType.SOURCE,
            imports=[], symbols=["Request", "Response"],
        ),
        "httpx/_client.py": FileInfo(
            path="httpx/_client.py", file_type=FileType.SOURCE,
            imports=["httpx/_models.py"], symbols=["Client"],
        ),
        "httpx/_auth.py": FileInfo(
            path="httpx/_auth.py", file_type=FileType.SOURCE,
            imports=[], symbols=["Auth"],
        ),
        "tests/test_models.py": FileInfo(
            path="tests/test_models.py", file_type=FileType.TEST,
            imports=["httpx/_models.py"], test_functions=["test_request"],
        ),
        "tests/test_client.py": FileInfo(
            path="tests/test_client.py", file_type=FileType.TEST,
            imports=["httpx/_client.py"], test_functions=["test_client"],
        ),
        "tests/test_auth.py": FileInfo(
            path="tests/test_auth.py", file_type=FileType.TEST,
            imports=[], test_functions=["test_auth_flow"],
        ),
    }
    return IndexData(files=files)


class TestHeuristics:
    """Tests for naming convention and path heuristics."""

    def test_naming_convention_match(self):
        """_models.py should match test_models.py via naming convention."""
        index = _make_index()
        heuristics = Heuristics(index)

        # test_models.py is already selected, so it should not appear again
        matches = heuristics.find_related_tests(
            ["httpx/_models.py"],
            already_selected={"tests/test_models.py"},
        )
        assert "tests/test_models.py" not in matches

    def test_naming_convention_new_match(self):
        """When test_auth.py is NOT already selected, naming should find it."""
        index = _make_index()
        heuristics = Heuristics(index)

        matches = heuristics.find_related_tests(
            ["httpx/_auth.py"],
            already_selected=set(),
        )
        assert "tests/test_auth.py" in matches
        reasons = matches["tests/test_auth.py"]
        assert any("naming_convention" in r for r in reasons)

    def test_no_match_for_unknown_source(self):
        """A source file with no naming match should return empty."""
        index = _make_index()
        heuristics = Heuristics(index)

        matches = heuristics.find_related_tests(
            ["httpx/_unknown.py"],
            already_selected=set(),
        )
        assert len(matches) == 0

    def test_underscore_stripped_for_matching(self):
        """Leading underscores in source filenames should be stripped for matching."""
        index = _make_index()
        heuristics = Heuristics(index)

        # _client.py -> test_client.py (strips leading underscore)
        matches = heuristics.find_related_tests(
            ["httpx/_client.py"],
            already_selected=set(),
        )
        assert "tests/test_client.py" in matches
