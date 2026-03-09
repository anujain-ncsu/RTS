"""Tests for the import resolver module."""

from pathlib import Path

import pytest

from rts.indexer.ast_parser import ImportInfo
from rts.indexer.import_resolver import ImportResolver


@pytest.fixture
def sample_files():
    """Simulate a repo with these file paths."""
    return [
        "httpx/__init__.py",
        "httpx/_models.py",
        "httpx/_client.py",
        "httpx/_urls.py",
        "httpx/_content.py",
        "httpx/_transports/__init__.py",
        "httpx/_transports/default.py",
        "tests/__init__.py",
        "tests/test_models.py",
        "tests/test_client.py",
        "tests/conftest.py",
    ]


@pytest.fixture
def resolver(tmp_path, sample_files):
    return ImportResolver(tmp_path, sample_files)


class TestImportResolver:
    """Tests for import resolution logic."""

    def test_resolve_absolute_module(self, resolver):
        imp = ImportInfo(module="httpx._models", names=[], is_relative=False, level=0)
        result = resolver.resolve(imp, "tests/test_client.py")
        assert "httpx/_models.py" in result

    def test_resolve_absolute_package(self, resolver):
        imp = ImportInfo(module="httpx", names=[], is_relative=False, level=0)
        result = resolver.resolve(imp, "tests/test_client.py")
        assert "httpx/__init__.py" in result

    def test_resolve_from_import_submodule(self, resolver):
        imp = ImportInfo(module="httpx", names=["_models", "_client"], is_relative=False, level=0)
        result = resolver.resolve(imp, "tests/test_client.py")
        assert "httpx/_models.py" in result
        assert "httpx/_client.py" in result

    def test_resolve_relative_import_same_package(self, resolver):
        imp = ImportInfo(module="_models", names=[], is_relative=True, level=1)
        result = resolver.resolve(imp, "httpx/_client.py")
        assert "httpx/_models.py" in result

    def test_resolve_relative_import_from_dot(self, resolver):
        imp = ImportInfo(module="", names=["_models"], is_relative=True, level=1)
        result = resolver.resolve(imp, "httpx/_client.py")
        assert "httpx/_models.py" in result

    def test_resolve_external_import_returns_empty(self, resolver):
        imp = ImportInfo(module="requests", names=[], is_relative=False, level=0)
        result = resolver.resolve(imp, "httpx/_client.py")
        assert result == []

    def test_resolve_nested_package(self, resolver):
        imp = ImportInfo(module="httpx._transports.default", names=[], is_relative=False, level=0)
        result = resolver.resolve(imp, "tests/test_client.py")
        assert "httpx/_transports/default.py" in result

    def test_resolve_relative_parent_package(self, resolver):
        imp = ImportInfo(module="_models", names=[], is_relative=True, level=2)
        result = resolver.resolve(imp, "httpx/_transports/default.py")
        assert "httpx/_models.py" in result
