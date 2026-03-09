"""Regex-based fallback parser for extracting imports from Python files.

Used when AST parsing fails (syntax errors, encoding issues, partial files).
Less accurate than AST but works on broken/partial Python files.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns for import statements
# Matches: import foo, import foo.bar, import foo as bar
_IMPORT_PATTERN = re.compile(
    r"^\s*import\s+([\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)",
    re.MULTILINE,
)

# Matches: from foo import bar, from foo.bar import baz, from . import foo
_FROM_IMPORT_PATTERN = re.compile(
    r"^\s*from\s+(\.{0,3}[\w.]*)\s+import\s+(.+?)(?:\s*#.*)?$",
    re.MULTILINE,
)

# Matches: def test_something or async def test_something
_TEST_FUNC_PATTERN = re.compile(
    r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(",
    re.MULTILINE,
)


@dataclass
class RegexImportInfo:
    """Import information extracted via regex."""

    module: str
    names: list[str] = field(default_factory=list)
    is_relative: bool = False
    level: int = 0


@dataclass
class RegexParseResult:
    """Result of regex-based parsing."""

    file_path: str
    imports: list[RegexImportInfo] = field(default_factory=list)
    test_functions: list[str] = field(default_factory=list)


class RegexParser:
    """Fallback parser using regex patterns for import extraction."""

    def parse_file(self, file_path: Path) -> RegexParseResult:
        """Parse a Python file using regex to extract imports.

        Args:
            file_path: Path to the Python file.

        Returns:
            RegexParseResult with extracted imports.
        """
        result = RegexParseResult(file_path=str(file_path))

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("Failed to read %s: %s", file_path, e)
            return result

        result.imports = self._extract_imports(source)
        result.test_functions = self._extract_test_functions(source)

        return result

    def _extract_imports(self, source: str) -> list[RegexImportInfo]:
        """Extract imports using regex patterns."""
        imports: list[RegexImportInfo] = []

        # Handle `import X` statements
        for match in _IMPORT_PATTERN.finditer(source):
            modules_str = match.group(1)
            for part in modules_str.split(","):
                part = part.strip()
                # Remove `as alias` suffix
                module = part.split(" as ")[0].strip() if " as " in part else part
                if module:
                    imports.append(RegexImportInfo(module=module))

        # Handle `from X import Y` statements
        for match in _FROM_IMPORT_PATTERN.finditer(source):
            module_str = match.group(1)
            names_str = match.group(2)

            # Count leading dots for relative imports
            level = 0
            for ch in module_str:
                if ch == ".":
                    level += 1
                else:
                    break

            module = module_str[level:]  # Strip leading dots
            is_relative = level > 0

            # Parse imported names
            names: list[str] = []
            if names_str.strip() != "*":
                # Handle parenthesized imports roughly (won't catch multi-line perfectly)
                cleaned = names_str.strip().strip("()")
                for name_part in cleaned.split(","):
                    name = name_part.strip().split(" as ")[0].strip()
                    if name and name != "\\":
                        names.append(name)

            imports.append(
                RegexImportInfo(
                    module=module,
                    names=names,
                    is_relative=is_relative,
                    level=level,
                )
            )

        return imports

    def _extract_test_functions(self, source: str) -> list[str]:
        """Extract test function names using regex."""
        return [match.group(1) for match in _TEST_FUNC_PATTERN.finditer(source)]
