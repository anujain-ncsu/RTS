"""AST-based parser for extracting imports and symbols from Python files.

This is the primary parser. For files that fail AST parsing, see regex_parser.py.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Result of parsing a single Python file."""

    file_path: str
    imports: list[ImportInfo] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    test_functions: list[str] = field(default_factory=list)
    parse_error: str | None = None


@dataclass
class ImportInfo:
    """Information about a single import statement."""

    module: str  # The module being imported (e.g., "os.path" or "httpx._models")
    names: list[str] = field(default_factory=list)  # Specific names imported via `from X import a, b`
    is_relative: bool = False
    level: int = 0  # Number of dots in relative import (e.g., 1 for `.foo`, 2 for `..foo`)


class ASTParser:
    """Parses Python files using the ast module to extract imports and symbols."""

    def parse_file(self, file_path: Path) -> ParseResult:
        """Parse a Python file and extract imports, symbols, and test functions.

        Args:
            file_path: Path to the Python file.

        Returns:
            ParseResult with extracted information, or with parse_error set on failure.
        """
        result = ParseResult(file_path=str(file_path))

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError) as e:
            result.parse_error = f"Could not read file: {e}"
            logger.warning("Failed to read %s: %s", file_path, e)
            return result

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            result.parse_error = f"Syntax error: {e}"
            logger.debug("AST parse failed for %s: %s", file_path, e)
            return result

        result.imports = self._extract_imports(tree)
        result.symbols = self._extract_symbols(tree)
        result.test_functions = self._extract_test_functions(tree)

        return result

    def _extract_imports(self, tree: ast.Module) -> list[ImportInfo]:
        """Extract all import statements from an AST."""
        imports: list[ImportInfo] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ImportInfo(
                            module=alias.name,
                            names=[],
                            is_relative=False,
                            level=0,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.name for alias in node.names]
                level = node.level or 0
                imports.append(
                    ImportInfo(
                        module=module,
                        names=names,
                        is_relative=level > 0,
                        level=level,
                    )
                )

        return imports

    def _extract_symbols(self, tree: ast.Module) -> list[str]:
        """Extract top-level class and function definitions."""
        symbols: list[str] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(node.name)
            elif isinstance(node, ast.ClassDef):
                symbols.append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        symbols.append(target.id)

        return symbols

    def _extract_test_functions(self, tree: ast.Module) -> list[str]:
        """Extract test function names (functions/methods starting with 'test_')."""
        test_funcs: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    test_funcs.append(node.name)

        return test_funcs
