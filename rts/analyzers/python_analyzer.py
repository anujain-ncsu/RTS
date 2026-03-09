"""Python language analyzer plugin."""

from __future__ import annotations
from pathlib import Path

from rts.analyzers.base import LanguageAnalyzer, ParseResult
from rts.indexer.ast_parser import ASTParser, ImportInfo
from rts.indexer.regex_parser import RegexParser
from rts.indexer.import_resolver import ImportResolver
from rts.indexer.test_classifier import TestClassifier


class PythonAnalyzer(LanguageAnalyzer):
    """Analyzer for Python files using AST and regex fallback."""

    def __init__(self) -> None:
        self.ast_parser = ASTParser()
        self.regex_parser = RegexParser()
        self.test_classifier = TestClassifier()

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> set[str]:
        return {".py"}

    def parse_file(self, filepath: Path, rel_path: str) -> ParseResult:
        ast_result = self.ast_parser.parse_file(filepath)

        if ast_result.parse_error:
            # Fallback to regex parser
            regex_result = self.regex_parser.parse_file(filepath)

            imports = [
                ImportInfo(
                    module=ri.module,
                    names=ri.names,
                    is_relative=ri.is_relative,
                    level=ri.level,
                )
                for ri in regex_result.imports
            ]

            return ParseResult(
                file_path=rel_path,
                imports=imports,
                symbols=[],
                test_functions=regex_result.test_functions,
                parse_error=True,
            )

        return ParseResult(
            file_path=rel_path,
            imports=ast_result.imports,
            symbols=ast_result.symbols,
            test_functions=ast_result.test_functions,
            parse_error=False,
        )

    def resolve_imports(
        self, parse_result: ParseResult, repo_root: Path, all_files_in_lang: list[str]
    ) -> list[str]:
        resolver = ImportResolver(repo_root, all_files_in_lang)
        resolved = []
        for imp in parse_result.imports:
            targets = resolver.resolve(imp, parse_result.file_path)
            for target in targets:
                if target != parse_result.file_path:
                    resolved.append(target)

        # deduplicate primitive preserving order
        return list(dict.fromkeys(resolved))

    def is_test_file(
        self, rel_path: str, test_functions: list[str] | None = None
    ) -> bool:
        classifications = self.test_classifier.classify_files(
            [rel_path], {rel_path: test_functions or []}
        )
        return classifications.get(rel_path, False)

    def get_heuristic_matches(
        self, source_file: str, test_files: set[str]
    ) -> dict[str, list[str]]:
        matches = {}
        source_stem = Path(source_file).stem
        clean_stem = source_stem.lstrip("_")
        test_name = f"test_{clean_stem}"

        test_basename_map: dict[str, list[str]] = {}
        for tf in test_files:
            basename = Path(tf).stem
            if basename not in test_basename_map:
                test_basename_map[basename] = []
            test_basename_map[basename].append(tf)

        test_names = [f"test_{clean_stem}", f"{clean_stem}_test"]
        for test_name in test_names:
            if test_name in test_basename_map:
                for tf in test_basename_map[test_name]:
                    matches.setdefault(tf, []).append("naming_convention")

        return matches
