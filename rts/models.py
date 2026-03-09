"""Shared data models for RTS."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class FileType(str, Enum):
    """Classification of a Python file."""

    SOURCE = "source"
    TEST = "test"


class Relationship(str, Enum):
    """How a test relates to a source file."""

    DIRECT_IMPORT = "direct_import"
    TRANSITIVE = "transitive"
    NAMING_CONVENTION = "naming_convention"
    SAME_PACKAGE = "same_package"


class Thoroughness(str, Enum):
    """Thoroughness level for test selection."""

    QUICK = "quick"
    STANDARD = "standard"
    THOROUGH = "thorough"


@dataclasses.dataclass
class FileInfo:
    """Information about a single Python file in the repository."""

    path: str
    file_type: FileType
    imports: list[str] = dataclasses.field(default_factory=list)
    imported_by: list[str] = dataclasses.field(default_factory=list)
    symbols: list[str] = dataclasses.field(default_factory=list)
    test_functions: list[str] = dataclasses.field(default_factory=list)
    mtime: float = 0.0
    size: int = 0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.file_type.value,
            "imports": self.imports,
            "symbols": self.symbols,
            "mtime": self.mtime,
            "size": self.size,
        }
        if self.imported_by:
            d["imported_by"] = self.imported_by
        if self.test_functions:
            d["test_functions"] = self.test_functions
        return d

    @classmethod
    def from_dict(cls, path: str, data: dict[str, Any]) -> FileInfo:
        return cls(
            path=path,
            file_type=FileType(data["type"]),
            imports=data.get("imports", []),
            imported_by=data.get("imported_by", []),
            symbols=data.get("symbols", []),
            test_functions=data.get("test_functions", []),
            mtime=data.get("mtime", 0.0),
            size=data.get("size", 0),
        )


@dataclasses.dataclass
class TestMapping:
    """A mapping from a source file to a test that covers it."""

    test_file: str
    relationship: Relationship
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_file": self.test_file,
            "relationship": self.relationship.value,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestMapping:
        return cls(
            test_file=data["test_file"],
            relationship=Relationship(data["relationship"]),
            confidence=data["confidence"],
        )


@dataclasses.dataclass
class IndexData:
    """The complete index for a repository."""

    version: str = "1.0"
    repository: str = ""
    created_at: str = ""
    files: dict[str, FileInfo] = dataclasses.field(default_factory=dict)
    source_to_tests: dict[str, list[TestMapping]] = dataclasses.field(
        default_factory=dict
    )
    test_to_sources: dict[str, list[str]] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "repository": self.repository,
            "created_at": self.created_at,
            "files": {
                path: info.to_dict() for path, info in self.files.items()
            },
            "source_to_tests": {
                path: [m.to_dict() for m in mappings]
                for path, mappings in self.source_to_tests.items()
            },
            "test_to_sources": self.test_to_sources,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexData:
        files = {
            path: FileInfo.from_dict(path, info)
            for path, info in data.get("files", {}).items()
        }
        source_to_tests = {
            path: [TestMapping.from_dict(m) for m in mappings]
            for path, mappings in data.get("source_to_tests", {}).items()
        }
        return cls(
            version=data.get("version", "1.0"),
            repository=data.get("repository", ""),
            created_at=data.get("created_at", ""),
            files=files,
            source_to_tests=source_to_tests,
            test_to_sources=data.get("test_to_sources", {}),
        )


@dataclasses.dataclass
class SelectedTest:
    """A test selected by the selector with confidence and reasoning."""

    test_file: str
    test_functions: list[str] = dataclasses.field(default_factory=list)
    confidence: float = 0.0
    reasons: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_file": self.test_file,
            "test_functions": self.test_functions,
            "confidence": round(self.confidence, 4),
            "reasons": self.reasons,
        }


@dataclasses.dataclass
class SelectionResult:
    """The complete output of the selector."""

    changed_files: list[str]
    thoroughness: Thoroughness
    selected_tests: list[SelectedTest]
    total_tests_in_suite: int
    selection_time_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_files": self.changed_files,
            "thoroughness": self.thoroughness.value,
            "selected_tests": [t.to_dict() for t in self.selected_tests],
            "total_tests_selected": len(self.selected_tests),
            "total_tests_in_suite": self.total_tests_in_suite,
            "selection_time_ms": round(self.selection_time_ms, 2),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
