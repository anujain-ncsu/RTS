"""Go language analyzer plugin."""

from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from rts.analyzers.base import LanguageAnalyzer, ParseResult


class GoAnalyzer(LanguageAnalyzer):
    """Analyzer for Go files using regex mapping."""

    def __init__(self) -> None:
        self.import_re = re.compile(r'^import\s+(?:[\w.]+\s+)?"([^"]+)"', re.MULTILINE)
        self.import_block_re = re.compile(r'import\s+\((.*?)\)', re.DOTALL)
        self.import_line_re = re.compile(r'"([^"]+)"')
        self.test_func_re = re.compile(r'^func\s+(Test\w+|Benchmark\w+)\s*\(', re.MULTILINE)

    @property
    def language_name(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> set[str]:
        return {".go"}

    def parse_file(self, filepath: Path, rel_path: str) -> ParseResult:
        try:
            content = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ParseResult(rel_path, [], [], [], parse_error=True)

        imports: list[str] = []
        
        # Single line imports
        for match in self.import_re.finditer(content):
            imports.append(match.group(1))
            
        # Block imports
        for block_match in self.import_block_re.finditer(content):
            block_content = block_match.group(1)
            for line_match in self.import_line_re.finditer(block_content):
                imports.append(line_match.group(1))

        # Deduplicate
        imports = list(dict.fromkeys(imports))

        test_funcs = [m.group(1) for m in self.test_func_re.finditer(content)]

        return ParseResult(
            file_path=rel_path,
            imports=imports,
            symbols=[],
            test_functions=test_funcs,
            parse_error=False,
        )

    def resolve_imports(
        self, parse_result: ParseResult, repo_root: Path, all_files_in_lang: list[str]
    ) -> list[str]:
        # For Go, "imports" are directory-based packages
        # We need to map 'package/path' to the files in that directory within the repo
        # To keep things simple and avoid parsing go.mod, we will match against `all_files_in_lang`
        
        resolved_files = set()
        
        # Go implicit same-package dependency: all .go files in the same directory
        # are part of the same package and implicitly depend on each other.
        current_dir = str(Path(parse_result.file_path).parent)
        for f in all_files_in_lang:
            if f != parse_result.file_path and str(Path(f).parent) == current_dir:
                resolved_files.add(f)
        
        for imp in parse_result.imports:
            # Only intra-repo packages matter. We'll simply check if the import path matches any suffix
            # of the directories in all_files_in_lang.
            # e.g. imp = 'github.com/my/repo/internal/handler' => `internal/handler/handler.go`
            # For simplicity, if the directory `internal/handler` exists in our repo, it's a match.
            
            imp_parts = imp.split('/')
            
            # Try matching suffixes
            for f in all_files_in_lang:
                f_path = Path(f)
                f_dir_parts = f_path.parent.parts
                
                # If f_dir_parts ends with some subset of imp_parts
                match = False
                for i in range(1, len(imp_parts) + 1):
                    suffix = tuple(imp_parts[-i:])
                    if len(f_dir_parts) >= i and f_dir_parts[-i:] == suffix:
                        match = True
                        break
                        
                if match and f != parse_result.file_path:
                    resolved_files.add(f)

        return list(resolved_files)

    def is_test_file(
        self, rel_path: str, test_functions: list[str] | None = None
    ) -> bool:
        return rel_path.endswith("_test.go")

    def get_heuristic_matches(
        self, source_file: str, test_files: set[str]
    ) -> dict[str, list[str]]:
        matches = {}
        # Go colocation convention: `foo.go` -> `foo_test.go`
        if not source_file.endswith(".go") or source_file.endswith("_test.go"):
            return matches
            
        expected_test = source_file[:-3] + "_test.go"
        if expected_test in test_files:
            matches[expected_test] = ["naming_convention"]

        return matches
