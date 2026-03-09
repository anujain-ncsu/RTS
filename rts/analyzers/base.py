"""Base protocol and registry for language analyzers."""

from __future__ import annotations
from typing import Protocol, Any
from pathlib import Path
from dataclasses import dataclass

@dataclass
class ParseResult:
    """Standardized parse result from an analyzer."""
    file_path: str
    imports: list[Any]
    symbols: list[str]
    test_functions: list[str]
    parse_error: bool = False

class LanguageAnalyzer(Protocol):
    @property
    def language_name(self) -> str:
        """e.g., 'python', 'go', 'rust'"""
        ...

    @property
    def file_extensions(self) -> set[str]:
        """e.g., {'.py'}, {'.go'}, {'.rs'}"""
        ...

    def parse_file(self, filepath: Path, rel_path: str) -> ParseResult:
        """Extract raw import/dependency strings, symbols, and test function names."""
        ...

    def resolve_imports(self, parse_result: ParseResult, repo_root: Path, all_files_in_lang: list[str]) -> list[str]:
        """Resolve parsed imports to absolute or repo-relative file paths string."""
        ...

    def is_test_file(self, rel_path: str, test_functions: list[str] | None = None) -> bool:
        """Language-specific test file detection."""
        ...

    def get_heuristic_matches(self, source_file: str, test_files: set[str]) -> dict[str, list[str]]:
        """Return naming/path convention matches mapping from test file to reasons."""
        ...
