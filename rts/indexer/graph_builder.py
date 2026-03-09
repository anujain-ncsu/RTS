"""Builds a dependency graph from parsed source files across multiple languages.

The graph captures which files import which other files, enabling
both forward (what does this file depend on?) and reverse
(what depends on this file?) traversal.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import rts.analyzers  # Ensures analyzers are registered
from rts.analyzers.registry import get_registry
from rts.analyzers.base import ParseResult
from rts.models import FileInfo, FileType, IndexData, Relationship, TestMapping

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Builds the complete dependency graph and test mappings for a repository."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.registry = get_registry()

    def build_index(self, old_index: IndexData | None = None) -> IndexData:
        """Build the complete index for the repository.

        Args:
            old_index: Optional existing index to use for incremental updates.

        Returns:
            IndexData containing file information, dependency graph,
            and source-to-test mappings.
        """
        # Step 1: Discover files
        all_files = self._discover_files()
        logger.info("Discovered %d source files", len(all_files))

        # Check existing files to bypass parsing
        file_set = set(all_files)
        reused_files: dict[str, FileInfo] = {}
        files_to_parse: list[str] = []
        file_stats: dict[str, tuple[float, int]] = {}

        for rel_path in all_files:
            full_path = self.repo_root / rel_path
            try:
                stat = full_path.stat()
                mtime = stat.st_mtime
                size = stat.st_size
                file_stats[rel_path] = (mtime, size)
            except OSError:
                mtime = 0.0
                size = 0
                file_stats[rel_path] = (mtime, size)

            if old_index and rel_path in old_index.files:
                old_info = old_index.files[rel_path]
                if old_info.mtime == mtime and old_info.size == size:
                    reused_files[rel_path] = old_info
                    continue

            files_to_parse.append(rel_path)

        logger.info(
            "Incremental: %d files unchanged, %d files to parse",
            len(reused_files),
            len(files_to_parse),
        )

        # Step 2 & 3: Parse modified/added files (delegated to analyzers)
        parse_results = self._parse_all_files(files_to_parse)
        logger.info("Parsed %d files successfully", len(parse_results))

        # Group all files by language for context in resolutions
        files_by_lang: dict[str, list[str]] = defaultdict(list)
        for rel_path in all_files:
            analyzer = self.registry.get_analyzer_for_file(Path(rel_path))
            if analyzer:
                files_by_lang[analyzer.language_name].append(rel_path)

        # Step 4, 5: Resolve imports and build file info & dependency graph
        files, forward_graph = self._build_file_graph(
            all_files, file_set, parse_results, files_by_lang, reused_files, file_stats
        )

        # Step 6: Build reverse graph (imported_by)
        reverse_graph = self._build_reverse_graph(forward_graph)

        # Update imported_by in file info
        for file_path, importers in reverse_graph.items():
            if file_path in files:
                files[file_path].imported_by = sorted(importers)

        # Step 7: Classify files
        for fp, info in files.items():
            if fp in reused_files:
                continue # Classification doesn't change if file didn't change (assuming isolated tests)
            
            analyzer = self.registry.get_analyzer_for_file(Path(fp))
            if analyzer:
                test_funcs = parse_results[fp].test_functions if fp in parse_results else info.test_functions
                is_test = analyzer.is_test_file(fp, test_funcs)
                info.file_type = FileType.TEST if is_test else FileType.SOURCE

        # Step 8: Build source-to-test and test-to-source mappings
        source_to_tests, test_to_sources = self._build_test_mappings(
            files, forward_graph, reverse_graph
        )

        # Step 9: Add naming convention heuristic mappings
        self._enrich_with_naming_heuristics(files, source_to_tests, test_to_sources)

        languages = sorted({analyzer.language_name for analyzer in self.registry.get_all_analyzers()})

        index = IndexData(
            version="1.1",
            repository=str(self.repo_root),
            created_at=datetime.now(timezone.utc).isoformat(),
            languages=languages,
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
        """Find all relevant files in the repository based on registered extensions."""
        all_files: list[str] = []
        extensions = self.registry.get_all_extensions()

        for file_path in self.repo_root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in extensions:
                continue

            # Skip hidden directories and common non-source dirs
            parts = file_path.relative_to(self.repo_root).parts
            if any(
                part.startswith(".") or part in {"__pycache__", "node_modules", ".git", "venv", ".venv", "env", ".env", ".tox", ".nox", "build", "dist", ".eggs", "target"}
                for part in parts
            ):
                continue
            
            rel_path = str(file_path.relative_to(self.repo_root))
            all_files.append(rel_path)

        return sorted(all_files)

    def _parse_all_files(self, files_to_parse: list[str]) -> dict[str, ParseResult]:
        """Parse all files by delegating to their respective analyzers."""
        results: dict[str, ParseResult] = {}

        for rel_path in files_to_parse:
            full_path = self.repo_root / rel_path
            analyzer = self.registry.get_analyzer_for_file(full_path)
            if not analyzer:
                continue

            try:
                result = analyzer.parse_file(full_path, rel_path)
                results[rel_path] = result
            except Exception as e:
                logger.error("Analyzer error parsing %s: %s", rel_path, e, exc_info=True)
                continue

        return results

    def _build_file_graph(
        self,
        all_files: list[str],
        file_set: set[str],
        parse_results: dict[str, ParseResult],
        files_by_lang: dict[str, list[str]],
        reused_files: dict[str, FileInfo],
        file_stats: dict[str, tuple[float, int]],
    ) -> tuple[dict[str, FileInfo], dict[str, set[str]]]:
        """Build FileInfo entries and forward dependency graph."""
        files: dict[str, FileInfo] = {}
        forward_graph: dict[str, set[str]] = defaultdict(set)

        for rel_path in all_files:
            mtime, size = file_stats.get(rel_path, (0.0, 0))
            analyzer = self.registry.get_analyzer_for_file(Path(rel_path))
            if not analyzer:
                continue

            language = analyzer.language_name

            if rel_path in reused_files:
                info = reused_files[rel_path]
                # Filter imports to exclude deleted files
                valid_imports = [imp for imp in info.imports if imp in file_set]

                files[rel_path] = FileInfo(
                    path=info.path,
                    file_type=info.file_type,
                    language=info.language,
                    imports=valid_imports,
                    symbols=info.symbols,
                    test_functions=info.test_functions,
                    mtime=info.mtime,
                    size=info.size,
                )
                for imp in valid_imports:
                    forward_graph[rel_path].add(imp)
            else:
                result = parse_results.get(rel_path)
                if not result:
                    continue

                # Resolve imports (delegated to analyzer)
                lang_files = files_by_lang.get(language, [])
                resolved_imports = analyzer.resolve_imports(result, self.repo_root, lang_files)

                # Filter self-imports and non-existent files
                unique_imports: list[str] = []
                for imp_path in resolved_imports:
                    if imp_path != rel_path and imp_path in file_set:
                        unique_imports.append(imp_path)
                        forward_graph[rel_path].add(imp_path)

                files[rel_path] = FileInfo(
                    path=rel_path,
                    file_type=FileType.SOURCE,  # Adjusted after reverse graph built
                    language=language,
                    imports=unique_imports,
                    symbols=result.symbols,
                    test_functions=result.test_functions,
                    mtime=mtime,
                    size=size,
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
                    
                    # Prevent cross-language boundary resolution to avoid unexpected cross-lang test connections unless intended
                    # Currently we trust the graph
                    if importer in test_files:
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
        """Add test mappings based on language-specific naming conventions."""
        tests_by_lang: dict[str, set[str]] = defaultdict(set)
        for fp, info in files.items():
            if info.file_type == FileType.TEST:
                tests_by_lang[info.language].add(fp)

        source_files = {
            fp for fp, info in files.items() if info.file_type == FileType.SOURCE
        }

        for source_file in source_files:
            info = files[source_file]
            analyzer = self.registry.get_analyzer_for_file(Path(source_file))
            if not analyzer:
                continue

            lang_tests = tests_by_lang.get(info.language, set())
            heuristic_matches = analyzer.get_heuristic_matches(source_file, lang_tests)

            for test_file, reasons in heuristic_matches.items():
                if "naming_convention" in reasons:
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
