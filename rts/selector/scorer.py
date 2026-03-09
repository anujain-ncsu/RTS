"""Confidence scoring for selected tests.

Combines signals from graph traversal depth, naming conventions,
and path proximity to produce a final confidence score per test.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Score weights for different signals
SCORE_DIRECT_IMPORT = 0.95
SCORE_TRANSITIVE_DEPTH_1 = 0.75
SCORE_TRANSITIVE_DEPTH_2 = 0.55
SCORE_TRANSITIVE_DEPTH_3_PLUS = 0.35
SCORE_NAMING_CONVENTION = 0.60
SCORE_SAME_PACKAGE = 0.40


class Scorer:
    """Calculates confidence scores for selected tests."""

    def score_from_depth(self, depth: int) -> float:
        """Calculate confidence score based on graph traversal depth.

        Args:
            depth: BFS depth at which the test was reached.
                   0 = direct import, 1 = one hop, etc.

        Returns:
            Confidence score between 0.0 and 1.0.
        """
        if depth == 0:
            return SCORE_DIRECT_IMPORT
        elif depth == 1:
            return SCORE_TRANSITIVE_DEPTH_1
        elif depth == 2:
            return SCORE_TRANSITIVE_DEPTH_2
        else:
            return SCORE_TRANSITIVE_DEPTH_3_PLUS

    def score_from_reasons(self, reasons: list[str]) -> float:
        """Calculate confidence score based on heuristic match reasons.

        Args:
            reasons: List of reason strings (e.g., "naming_convention(...)",
                     "same_package(...)").

        Returns:
            Confidence score between 0.0 and 1.0.
        """
        score = 0.0
        for reason in reasons:
            if reason.startswith("naming_convention"):
                score = max(score, SCORE_NAMING_CONVENTION)
            elif reason.startswith("same_package"):
                score = max(score, SCORE_SAME_PACKAGE)
            elif reason.startswith("parallel_directory"):
                score = max(score, SCORE_SAME_PACKAGE)

        return score

    def combine_scores(self, *scores: float) -> float:
        """Combine multiple confidence scores additively, capped at 1.0.

        Args:
            *scores: Individual confidence scores to combine.

        Returns:
            Combined score, capped at 1.0.
        """
        return min(1.0, sum(scores))

    def depth_to_reason(self, depth: int) -> str:
        """Convert a graph depth to a human-readable reason string.

        Args:
            depth: BFS depth.

        Returns:
            Reason string.
        """
        if depth == 0:
            return "direct_import"
        else:
            return f"transitive_import(depth={depth})"
