"""Builds a dependency graph from parsed Python files.

The graph captures which files import which other files, enabling
both forward (what does this file depend on?) and reverse
(what depends on this file?) traversal.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from pathlib import Path

from rts.indexer.ast_parser import ASTParser, ImportInfo, ParseResult
from rts.indexer.import_resolver import ImportResolver
from rts.indexer.regex_parser import RegexParser
from rts.indexer.test_classifier import TestClassifier
from rts.models import FileInfo, FileType, IndexData, Relationship, TestMapping

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Builds the complete dependency graph and test mappings for a repository."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.ast_parser = ASTParser()
        self.regex_parser = RegexParser()
        self.test_classifier = TestClassifier()

    def build_index(self) -> IndexData:
        """Build the complete index for the repository.

        Returns:
            IndexData containing file information, dependency graph,
            and source-to-test mappings.
        """
        # Step 1: Discover Python files
        python_files = self._discover_files()
        logger.info("Discovered %d Python files", len(python_files))

        # Step 2 & 3: Parse all files (AST primary, regex fallback)
        parse_results = self._parse_all_files(python_files)
        logger.info("Parsed %d files successfully", len(parse_results))

        # Step 4: Set up import resolver
        resolver = ImportResolver(self.repo_root, python_files)

        # Step 5: Build file info and dependency graph
        files, forward_graph = self._build_file_graph(
            python_files, parse_results, resolver
        )

        # Step 6: Build reverse graph (imported_by)
        reverse_graph = self._build_reverse_graph(forward_graph)

        # Update imported_by in file info
        for file_path, importers in reverse_graph.items():
            if file_path in files:
                files[file_path].imported_by = sorted(importers)

        # Step 7: Classify files and build test mappings
        test_funcs = {
            fp: pr.test_functions
            for fp, pr in parse_results.items()
            if pr.test_functions
        }
        classifications = self.test_classifier.classify_files(python_files, test_funcs)

        # Update file types
        for fp, is_test in classifications.items():
            if fp in files:
                files[fp].file_type = FileType.TEST if is_test else FileType.SOURCE

        # Step 8: Build source-to-test and test-to-source mappings
        source_to_tests, test_to_sources = self._build_test_mappings(
            files, forward_graph, reverse_graph
        )

        # Step 9: Add naming convention heuristic mappings
        self._enrich_with_naming_heuristics(
            files, source_to_tests, test_to_sources
        )

        from datetime import datetime, timezone

        index = IndexData(
            version="1.0",
            repository=str(self.repo_root),
            created_at=datetime.now(timezone.utc).isoformat(),
            files=files,
            source_to_tests=source_to_tests,
            test_to_sources=test_to_sources,
        )

        logger.info(
            "Index built: %d files, %d source-to-test mappings",
            len(files),
            sum(len(v) for v in source_to_tests.values()),
        )

        return index

    def _discover_files(self) -> list[str]:
        """Find all Python files in the repository."""
        python_files: list[str] = []

        for py_file in self.repo_root.rglob("*.py"):
            # Skip hidden directories and common non-source dirs
            parts = py_file.relative_to(self.repo_root).parts
            if any(
                part.startswith(".") or part in {"__pycache__", "node_modules", ".git", "venv", ".venv", "env", ".env", ".tox", ".nox", "build", "dist", ".eggs"}
                for part in parts
            ):
                continue
            rel_path = str(py_file.relative_to(self.repo_root))
            python_files.append(rel_path)

        return sorted(python_files)

    def _parse_all_files(
        self, python_files: list[str]
    ) -> dict[str, ParseResult]:
        """Parse all Python files, using AST first and regex as fallback."""
        results: dict[str, ParseResult] = {}

        for rel_path in python_files:
            full_path = self.repo_root / rel_path
            result = self.ast_parser.parse_file(full_path)

            if result.parse_error:
                # Fallback to regex parser
                logger.debug("Falling back to regex parser for %s", rel_path)
                regex_result = self.regex_parser.parse_file(full_path)

                # Convert regex result back into a ParseResult
                from rts.indexer.ast_parser import ImportInfo as ASTImportInfo

                result = ParseResult(file_path=rel_path)
                result.imports = [
                    ASTImportInfo(
                        module=ri.module,
                        names=ri.names,
                        is_relative=ri.is_relative,
                        level=ri.level,
                    )
                    for ri in regex_result.imports
                ]
                result.test_functions = regex_result.test_functions

            results[rel_path] = result

        return results

    def _build_file_graph(
        self,
        python_files: list[str],
        parse_results: dict[str, ParseResult],
        resolver: ImportResolver,
    ) -> tuple[dict[str, FileInfo], dict[str, set[str]]]:
        """Build FileInfo entries and forward dependency graph."""
        files: dict[str, FileInfo] = {}
        forward_graph: dict[str, set[str]] = defaultdict(set)

        for rel_path in python_files:
            result = parse_results.get(rel_path)
            if not result:
                continue

            # Resolve imports to file paths
            resolved_imports: list[str] = []
            for imp in result.imports:
                targets = resolver.resolve(imp, rel_path)
                for target in targets:
                    if target != rel_path:  # Skip self-imports
                        resolved_imports.append(target)
                        forward_graph[rel_path].add(target)

            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_imports: list[str] = []
            for imp_path in resolved_imports:
                if imp_path not in seen:
                    seen.add(imp_path)
                    unique_imports.append(imp_path)

            files[rel_path] = FileInfo(
                path=rel_path,
                file_type=FileType.SOURCE,  # Will be updated later
                imports=unique_imports,
                symbols=result.symbols,
                test_functions=result.test_functions,
            )

        return files, forward_graph

    def _build_reverse_graph(
        self, forward_graph: dict[str, set[str]]
    ) -> dict[str, set[str]]:
        """Build the reverse dependency graph (imported_by)."""
        reverse: dict[str, set[str]] = defaultdict(set)
        for source, targets in forward_graph.items():
            for target in targets:
                reverse[target].add(source)
        return reverse

    def _build_test_mappings(
        self,
        files: dict[str, FileInfo],
        forward_graph: dict[str, set[str]],
        reverse_graph: dict[str, set[str]],
    ) -> tuple[dict[str, list[TestMapping]], dict[str, list[str]]]:
        """Build source-to-test and test-to-source mappings using BFS."""
        source_to_tests: dict[str, list[TestMapping]] = defaultdict(list)
        test_to_sources: dict[str, list[str]] = defaultdict(list)

        test_files = {
            fp for fp, info in files.items() if info.file_type == FileType.TEST
        }
        source_files = {
            fp for fp, info in files.items() if info.file_type == FileType.SOURCE
        }

        for source_file in source_files:
            # BFS from source file through the reverse graph to find test files
            visited: set[str] = set()
            queue: deque[tuple[str, int]] = deque([(source_file, 0)])
            visited.add(source_file)

            while queue:
                current, depth = queue.popleft()

                # Check if any file that imports `current` is a test file
                for importer in reverse_graph.get(current, set()):
                    if importer in visited:
                        continue
                    visited.add(importer)

                    if importer in test_files:
                        # Determine relationship and confidence
                        if depth == 0:
                            relationship = Relationship.DIRECT_IMPORT
                            confidence = 0.95
                        else:
                            relationship = Relationship.TRANSITIVE
                            if depth == 1:
                                confidence = 0.75
                            elif depth == 2:
                                confidence = 0.55
                            else:
                                confidence = 0.35

                        source_to_tests[source_file].append(
                            TestMapping(
                                test_file=importer,
                                relationship=relationship,
                                confidence=confidence,
                            )
                        )
                        test_to_sources[importer].append(source_file)

                    # Continue BFS to find transitive test deps
                    queue.append((importer, depth + 1))

        # Sort mappings by confidence (highest first)
        for mappings in source_to_tests.values():
            mappings.sort(key=lambda m: m.confidence, reverse=True)

        # Deduplicate test_to_sources
        for test_file in test_to_sources:
            test_to_sources[test_file] = sorted(set(test_to_sources[test_file]))

        return dict(source_to_tests), dict(test_to_sources)

    def _enrich_with_naming_heuristics(
        self,
        files: dict[str, FileInfo],
        source_to_tests: dict[str, list[TestMapping]],
        test_to_sources: dict[str, list[str]],
    ) -> None:
        """Add test mappings based on naming conventions.

        For example, `httpx/_models.py` should map to `tests/test_models.py`
        if such a file exists but wasn't connected via imports.
        """
        test_files = {
            fp for fp, info in files.items() if info.file_type == FileType.TEST
        }
        source_files = {
            fp for fp, info in files.items() if info.file_type == FileType.SOURCE
        }

        # Build a lookup of test file basenames
        test_basename_map: dict[str, str] = {}
        for tf in test_files:
            basename = Path(tf).stem  # e.g., "test_models"
            test_basename_map[basename] = tf

        for source_file in source_files:
            source_stem = Path(source_file).stem  # e.g., "_models" or "models"
            # Strip leading underscore for matching
            clean_stem = source_stem.lstrip("_")

            # Look for test_<name>.py
            test_name = f"test_{clean_stem}"
            if test_name in test_basename_map:
                test_file = test_basename_map[test_name]

                # Check if this mapping already exists
                existing = source_to_tests.get(source_file, [])
                if not any(m.test_file == test_file for m in existing):
                    if source_file not in source_to_tests:
                        source_to_tests[source_file] = []
                    source_to_tests[source_file].append(
                        TestMapping(
                            test_file=test_file,
                            relationship=Relationship.NAMING_CONVENTION,
                            confidence=0.60,
                        )
                    )
                    if test_file not in test_to_sources:
                        test_to_sources[test_file] = []
                    if source_file not in test_to_sources[test_file]:
                        test_to_sources[test_file].append(source_file)
