"""Tests for the AST parser module."""

import textwrap
from pathlib import Path

import pytest

from rts.indexer.ast_parser import ASTParser, ImportInfo, ParseResult


@pytest.fixture
def parser():
    return ASTParser()


@pytest.fixture
def tmp_py_file(tmp_path):
    """Helper to write a Python file and return its path."""
    def _write(content: str, name: str = "test_module.py") -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(content))
        return p
    return _write


class TestASTParser:
    """Tests for ASTParser.parse_file()."""

    def test_parse_absolute_import(self, parser, tmp_py_file):
        path = tmp_py_file("import os\nimport sys\n")
        result = parser.parse_file(path)

        assert result.parse_error is None
        assert len(result.imports) == 2
        assert result.imports[0].module == "os"
        assert result.imports[1].module == "sys"
        assert not result.imports[0].is_relative

    def test_parse_from_import(self, parser, tmp_py_file):
        path = tmp_py_file("from os.path import join, exists\n")
        result = parser.parse_file(path)

        assert result.parse_error is None
        assert len(result.imports) == 1
        assert result.imports[0].module == "os.path"
        assert result.imports[0].names == ["join", "exists"]
        assert not result.imports[0].is_relative

    def test_parse_relative_import(self, parser, tmp_py_file):
        path = tmp_py_file("from . import sibling\nfrom ..parent import thing\n")
        result = parser.parse_file(path)

        assert len(result.imports) == 2
        assert result.imports[0].is_relative
        assert result.imports[0].level == 1
        assert result.imports[0].names == ["sibling"]
        assert result.imports[1].is_relative
        assert result.imports[1].level == 2
        assert result.imports[1].module == "parent"

    def test_parse_star_import(self, parser, tmp_py_file):
        path = tmp_py_file("from os import *\n")
        result = parser.parse_file(path)

        assert len(result.imports) == 1
        assert result.imports[0].names == ["*"]

    def test_extract_symbols(self, parser, tmp_py_file):
        path = tmp_py_file("""
            class MyClass:
                pass

            def my_function():
                pass

            MY_CONSTANT = 42
        """)
        result = parser.parse_file(path)

        assert "MyClass" in result.symbols
        assert "my_function" in result.symbols
        assert "MY_CONSTANT" in result.symbols

    def test_extract_test_functions(self, parser, tmp_py_file):
        path = tmp_py_file("""
            def test_something():
                assert True

            def test_another_thing():
                assert True

            def helper_function():
                pass

            class TestMyClass:
                def test_method(self):
                    pass

                def setup_method(self):
                    pass
        """)
        result = parser.parse_file(path)

        assert "test_something" in result.test_functions
        assert "test_another_thing" in result.test_functions
        assert "test_method" in result.test_functions
        assert "helper_function" not in result.test_functions
        assert "setup_method" not in result.test_functions

    def test_parse_syntax_error(self, parser, tmp_py_file):
        path = tmp_py_file("def broken(\n")
        result = parser.parse_file(path)

        assert result.parse_error is not None
        assert "Syntax error" in result.parse_error

    def test_parse_nonexistent_file(self, parser, tmp_path):
        path = tmp_path / "nonexistent.py"
        result = parser.parse_file(path)

        assert result.parse_error is not None

    def test_parse_conditional_import(self, parser, tmp_py_file):
        path = tmp_py_file("""
            import os

            if True:
                import sys

            try:
                import optional
            except ImportError:
                pass
        """)
        result = parser.parse_file(path)

        modules = [imp.module for imp in result.imports]
        assert "os" in modules
        assert "sys" in modules
        assert "optional" in modules

    def test_parse_async_function(self, parser, tmp_py_file):
        path = tmp_py_file("""
            async def test_async_thing():
                pass

            async def async_helper():
                pass
        """)
        result = parser.parse_file(path)

        assert "test_async_thing" in result.test_functions
        assert "async_helper" not in result.test_functions
        assert "test_async_thing" in result.symbols
        assert "async_helper" in result.symbols
