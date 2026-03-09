"""Tests for the regex fallback parser."""

import textwrap
from pathlib import Path

import pytest

from rts.indexer.regex_parser import RegexParser


@pytest.fixture
def parser():
    return RegexParser()


@pytest.fixture
def tmp_py_file(tmp_path):
    def _write(content: str, name: str = "test_module.py") -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(content))
        return p
    return _write


class TestRegexParser:
    """Tests for RegexParser.parse_file()."""

    def test_parse_import(self, parser, tmp_py_file):
        path = tmp_py_file("import os\nimport sys\n")
        result = parser.parse_file(path)

        modules = [imp.module for imp in result.imports]
        assert "os" in modules
        assert "sys" in modules

    def test_parse_from_import(self, parser, tmp_py_file):
        path = tmp_py_file("from os.path import join, exists\n")
        result = parser.parse_file(path)

        assert len(result.imports) == 1
        assert result.imports[0].module == "os.path"
        assert "join" in result.imports[0].names
        assert "exists" in result.imports[0].names

    def test_parse_relative_import(self, parser, tmp_py_file):
        path = tmp_py_file("from . import foo\nfrom ..bar import baz\n")
        result = parser.parse_file(path)

        assert any(imp.is_relative and imp.level == 1 for imp in result.imports)
        assert any(imp.is_relative and imp.level == 2 for imp in result.imports)

    def test_parse_test_functions(self, parser, tmp_py_file):
        path = tmp_py_file("""
            def test_something():
                pass

            async def test_async():
                pass

            def helper():
                pass
        """)
        result = parser.parse_file(path)

        assert "test_something" in result.test_functions
        assert "test_async" in result.test_functions
        assert "helper" not in result.test_functions

    def test_parse_broken_syntax(self, parser, tmp_py_file):
        """Regex parser should still extract imports from syntactically broken files."""
        path = tmp_py_file("""
            import os
            from sys import path

            def broken(
                # missing closing paren
        """)
        result = parser.parse_file(path)

        modules = [imp.module for imp in result.imports]
        assert "os" in modules
        assert "sys" in modules

    def test_parse_multiline_import_as(self, parser, tmp_py_file):
        """Test import with 'as' alias."""
        path = tmp_py_file("import numpy as np\nimport pandas as pd\n")
        result = parser.parse_file(path)

        modules = [imp.module for imp in result.imports]
        assert "numpy" in modules
        assert "pandas" in modules

    def test_nonexistent_file(self, parser, tmp_path):
        path = tmp_path / "nonexistent.py"
        result = parser.parse_file(path)

        assert result.imports == []
        assert result.test_functions == []
