"""Tests for the graph builder module."""

from pathlib import Path

import pytest

from rts.indexer.graph_builder import GraphBuilder
from rts.models import FileType


@pytest.fixture
def sample_repo(tmp_path):
    """Create a minimal Python repo for graph builder testing."""
    # Source package
    pkg = tmp_path / "mylib"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from mylib.core import MyClass\n")
    (pkg / "core.py").write_text(
        "class MyClass:\n    pass\n"
    )
    (pkg / "utils.py").write_text(
        "from mylib.core import MyClass\n\ndef helper():\n    pass\n"
    )

    # Tests
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_core.py").write_text(
        "from mylib.core import MyClass\n\ndef test_myclass():\n    assert True\n"
    )
    (tests / "test_utils.py").write_text(
        "from mylib.utils import helper\n\ndef test_helper():\n    assert True\n"
    )

    return tmp_path


class TestGraphBuilder:
    """Tests for the full indexing pipeline."""

    def test_discovers_python_files(self, sample_repo):
        builder = GraphBuilder(sample_repo)
        files = builder._discover_files()

        # Should find all .py files
        assert "mylib/__init__.py" in files
        assert "mylib/core.py" in files
        assert "mylib/utils.py" in files
        assert "tests/__init__.py" in files
        assert "tests/test_core.py" in files
        assert "tests/test_utils.py" in files

    def test_skips_hidden_directories(self, sample_repo):
        # Create a hidden directory with Python files
        hidden = sample_repo / ".hidden"
        hidden.mkdir()
        (hidden / "secret.py").write_text("x = 1\n")

        builder = GraphBuilder(sample_repo)
        files = builder._discover_files()

        assert not any(".hidden" in f for f in files)

    def test_skips_pycache(self, sample_repo):
        cache = sample_repo / "mylib" / "__pycache__"
        cache.mkdir()
        (cache / "core.cpython-39.pyc").write_text("")

        builder = GraphBuilder(sample_repo)
        files = builder._discover_files()

        assert not any("__pycache__" in f for f in files)

    def test_build_index_classifies_files(self, sample_repo):
        builder = GraphBuilder(sample_repo)
        index = builder.build_index()

        assert index.files["tests/test_core.py"].file_type == FileType.TEST
        assert index.files["tests/test_utils.py"].file_type == FileType.TEST
        assert index.files["mylib/core.py"].file_type == FileType.SOURCE

    def test_build_index_resolves_imports(self, sample_repo):
        builder = GraphBuilder(sample_repo)
        index = builder.build_index()

        # test_core.py imports mylib.core
        test_core_imports = index.files["tests/test_core.py"].imports
        assert "mylib/core.py" in test_core_imports

    def test_build_index_creates_source_to_test_mappings(self, sample_repo):
        builder = GraphBuilder(sample_repo)
        index = builder.build_index()

        # core.py should be mapped to test_core.py
        assert "mylib/core.py" in index.source_to_tests
        test_files = [m.test_file for m in index.source_to_tests["mylib/core.py"]]
        assert "tests/test_core.py" in test_files

    def test_build_index_metadata(self, sample_repo):
        builder = GraphBuilder(sample_repo)
        index = builder.build_index()

        assert index.version == "1.1"
        assert str(sample_repo) in index.repository
        assert index.created_at  # Should be non-empty

    def test_build_index_extracts_test_functions(self, sample_repo):
        builder = GraphBuilder(sample_repo)
        index = builder.build_index()

        assert "test_myclass" in index.files["tests/test_core.py"].test_functions
        assert "test_helper" in index.files["tests/test_utils.py"].test_functions
