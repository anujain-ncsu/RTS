"""Graph traversal for selecting tests based on dependency relationships.

Uses BFS to traverse the dependency graph at configurable depths,
controlled by the thoroughness level.
"""

from __future__ import annotations

import logging
from collections import deque

from rts.models import IndexData, FileType, Thoroughness

logger = logging.getLogger(__name__)

# Maximum BFS depth per thoroughness level
_DEPTH_LIMITS: dict[Thoroughness, int | None] = {
    Thoroughness.QUICK: 0,        # Direct imports only (depth=0 in reverse graph)
    Thoroughness.STANDARD: 3,     # Up to 3 levels of transitive deps
    Thoroughness.THOROUGH: None,  # Unlimited depth
}


class GraphTraversal:
    """Traverses the dependency graph to find affected tests."""

    def __init__(self, index: IndexData) -> None:
        self.index = index
        # Pre-compute reverse graph for faster lookups
        self._reverse_graph: dict[str, set[str]] = {}
        self._build_reverse_graph()

    def _build_reverse_graph(self) -> None:
        """Build reverse graph from index data (who imports this file?)."""
        for path, file_info in self.index.files.items():
            for imported_file in file_info.imports:
                if imported_file not in self._reverse_graph:
                    self._reverse_graph[imported_file] = set()
                self._reverse_graph[imported_file].add(path)

    def find_affected_tests(
        self,
        changed_files: list[str],
        thoroughness: Thoroughness,
    ) -> dict[str, int]:
        """Find test files affected by the changed files.

        Uses BFS through the reverse dependency graph to find all test files
        that transitively depend on any changed file.

        Args:
            changed_files: List of changed file paths (relative to repo root).
            thoroughness: Controls the depth of traversal.

        Returns:
            Dict mapping test file path -> minimum depth at which it was reached.
            Depth 0 means the test directly imports the changed file.
        """
        max_depth = _DEPTH_LIMITS[thoroughness]
        affected_tests: dict[str, int] = {}

        test_files = {
            fp
            for fp, info in self.index.files.items()
            if info.file_type == FileType.TEST
        }

        for changed_file in changed_files:
            # Normalize the changed file path
            normalized = self._normalize_path(changed_file)
            if not normalized:
                logger.warning(
                    "Changed file not found in index: %s", changed_file
                )
                continue

            # BFS from the changed file through the reverse graph
            visited: set[str] = {normalized}
            queue: deque[tuple[str, int]] = deque([(normalized, 0)])

            while queue:
                current, depth = queue.popleft()

                # Check depth limit
                if max_depth is not None and depth > max_depth:
                    continue

                for importer in self._reverse_graph.get(current, set()):
                    if importer in visited:
                        continue
                    visited.add(importer)

                    if importer in test_files:
                        # Record the minimum depth at which we reached this test
                        if importer not in affected_tests or depth < affected_tests[importer]:
                            affected_tests[importer] = depth

                    # Continue BFS even through test files (they might import other test utils)
                    if max_depth is None or depth + 1 <= max_depth:
                        queue.append((importer, depth + 1))

        return affected_tests

    def _normalize_path(self, file_path: str) -> str | None:
        """Try to find the file in the index, handling minor path variations."""
        # Direct match
        if file_path in self.index.files:
            return file_path

        # Try without leading ./
        if file_path.startswith("./"):
            stripped = file_path[2:]
            if stripped in self.index.files:
                return stripped

        # Try with forward slashes normalized
        normalized = file_path.replace("\\", "/")
        if normalized in self.index.files:
            return normalized

        return None
