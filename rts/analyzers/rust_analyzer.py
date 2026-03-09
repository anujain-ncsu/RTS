"""Rust language analyzer plugin."""

from __future__ import annotations
import re
from pathlib import Path

from rts.analyzers.base import LanguageAnalyzer, ParseResult


class RustAnalyzer(LanguageAnalyzer):
    """Analyzer for Rust files using regex mapping."""

    def __init__(self) -> None:
        self.use_re = re.compile(r'use\s+([a-zA-Z0-9_:{},\s]+)')
        self.mod_re = re.compile(r'mod\s+([a-zA-Z0-9_]+)\s*;')
        self.inline_test_re = re.compile(r'#\[cfg\(test\)\]\s*mod\s+tests')
        self.test_func_re = re.compile(r'#\[(?:tokio|actix_rt|async_std|[\w_]+)::test\]|#\[test\]')

    @property
    def language_name(self) -> str:
        return "rust"

    @property
    def file_extensions(self) -> set[str]:
        return {".rs"}

    def parse_file(self, filepath: Path, rel_path: str) -> ParseResult:
        try:
            content = filepath.read_text(encoding="utf-8")
        except OSError:
            return ParseResult(rel_path, [], [], [], parse_error=True)

        imports: list[str] = []
        
        for match in self.use_re.finditer(content):
            imports.append(match.group(1))
            
        for match in self.mod_re.finditer(content):
            imports.append(f"mod::{match.group(1)}")

        # Special marker for inline tests:
        # We don't extract the actual function names for rust inline tests yet
        test_funcs = []
        if self.inline_test_re.search(content):
            test_funcs.append("__inline_tests__")
            
        if self.test_func_re.search(content):
            test_funcs.append("__external_tests__")

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
        resolved_files = set()
        
        for imp in parse_result.imports:
            # Look for mod declarations first
            if imp.startswith("mod::"):
                mod_name = imp[5:]
                # Can map to mod_name.rs or mod_name/mod.rs in the same directory
                curr_dir = Path(parse_result.file_path).parent
                opt1 = str(curr_dir / f"{mod_name}.rs")
                opt2 = str(curr_dir / mod_name / "mod.rs")
                
                if opt1 in all_files_in_lang:
                    resolved_files.add(opt1)
                elif opt2 in all_files_in_lang:
                    resolved_files.add(opt2)
            else:
                # `use crate::foo::bar`
                if imp.startswith("crate::"):
                    parts = imp.split("::")
                    parts = [p for p in parts if p != "crate"]
                    if not parts:
                        continue
                        
                    target_stem = parts[-1]
                    preceding_segments = parts[:-1]
                    
                    for f in all_files_in_lang:
                        if not f.endswith(".rs"):
                            continue
                        f_path = Path(f)
                        f_stem = f_path.stem
                        f_parts = f_path.with_suffix("").parts
                        
                        if f_stem == target_stem:
                            parent_parts = list(f_parts[:-1])
                            if not preceding_segments or (
                                len(parent_parts) >= len(preceding_segments) and
                                parent_parts[-len(preceding_segments):] == preceding_segments
                            ):
                                resolved_files.add(f)
                        elif f_stem == "mod" and f_path.parent.name == target_stem:
                            parent_parts = list(f_parts[:-2])
                            if not preceding_segments or (
                                len(parent_parts) >= len(preceding_segments) and
                                parent_parts[-len(preceding_segments):] == preceding_segments
                            ):
                                resolved_files.add(f)

        return list(resolved_files)

    def is_test_file(
        self, rel_path: str, test_functions: list[str] | None = None
    ) -> bool:
        # In rust, files in tests/ are integration tests
        normalized_parts = Path(rel_path).parts
        if "tests" in normalized_parts:
            return True
        # If it contains an inline test module or #[test] functions, treat it as a source file that *has* tests
        # We model this by saying the file tests itself in `get_heuristic_matches`.
        # However, it is primarily a SOURCE file, so we return False here, unless it's ONLY tests.
        return False

    def get_heuristic_matches(
        self, source_file: str, test_files: set[str]
    ) -> dict[str, list[str]]:
        matches = {}
        # Inline tests (if we parse it again, though we really just track it)
        # We mapped inline test existence to `__inline_tests__`.
        # Actually a better design is to inject a self-edge.
        # But this method gets called for test_files (which are solely tests).
        # We rely on integration tests inside `tests/` which `use crate::foo`.
        # So heuristic matches here are minimal, except maybe `foo.rs` -> `tests/foo.rs` or `tests/foo_test.rs`.
        source_stem = Path(source_file).stem
        
        for tf in test_files:
            tf_stem = Path(tf).stem
            # e.g. tests/integration_foo.rs -> matches foo.rs
            if source_stem in tf_stem:
                matches[tf] = ["naming_convention"]

        return matches
