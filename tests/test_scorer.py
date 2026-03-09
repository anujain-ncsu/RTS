"""Tests for the confidence scorer."""

import pytest

from rts.selector.scorer import (
    SCORE_DIRECT_IMPORT,
    SCORE_NAMING_CONVENTION,
    SCORE_SAME_PACKAGE,
    SCORE_TRANSITIVE_DEPTH_1,
    SCORE_TRANSITIVE_DEPTH_2,
    SCORE_TRANSITIVE_DEPTH_3_PLUS,
    Scorer,
)


@pytest.fixture
def scorer():
    return Scorer()


class TestScorer:
    """Tests for confidence scoring logic."""

    def test_score_direct_import(self, scorer):
        assert scorer.score_from_depth(0) == SCORE_DIRECT_IMPORT

    def test_score_transitive_depth_1(self, scorer):
        assert scorer.score_from_depth(1) == SCORE_TRANSITIVE_DEPTH_1

    def test_score_transitive_depth_2(self, scorer):
        assert scorer.score_from_depth(2) == SCORE_TRANSITIVE_DEPTH_2

    def test_score_transitive_depth_3_plus(self, scorer):
        assert scorer.score_from_depth(3) == SCORE_TRANSITIVE_DEPTH_3_PLUS
        assert scorer.score_from_depth(5) == SCORE_TRANSITIVE_DEPTH_3_PLUS
        assert scorer.score_from_depth(100) == SCORE_TRANSITIVE_DEPTH_3_PLUS

    def test_scores_decrease_with_depth(self, scorer):
        """Scores should decrease as depth increases."""
        scores = [scorer.score_from_depth(d) for d in range(4)]
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1]

    def test_score_naming_convention(self, scorer):
        score = scorer.score_from_reasons(["naming_convention(models.py)"])
        assert score == SCORE_NAMING_CONVENTION

    def test_score_same_package(self, scorer):
        score = scorer.score_from_reasons(["same_package(httpx)"])
        assert score == SCORE_SAME_PACKAGE

    def test_score_multiple_reasons_takes_max(self, scorer):
        """Multiple reasons should take the max score, not add."""
        score = scorer.score_from_reasons([
            "naming_convention(models.py)",
            "same_package(httpx)",
        ])
        # Should be the max: naming_convention (0.60) > same_package (0.40)
        assert score == SCORE_NAMING_CONVENTION

    def test_combine_scores_additive(self, scorer):
        combined = scorer.combine_scores(0.95, 0.60)
        assert combined == 1.0  # Capped at 1.0

    def test_combine_scores_capped(self, scorer):
        combined = scorer.combine_scores(0.5, 0.3, 0.4)
        assert combined == 1.0  # 0.5 + 0.3 + 0.4 = 1.2 -> capped at 1.0

    def test_combine_scores_below_cap(self, scorer):
        combined = scorer.combine_scores(0.3, 0.2)
        assert abs(combined - 0.5) < 0.001

    def test_depth_to_reason_direct(self, scorer):
        assert scorer.depth_to_reason(0) == "direct_import"

    def test_depth_to_reason_transitive(self, scorer):
        assert scorer.depth_to_reason(1) == "transitive_import(depth=1)"
        assert scorer.depth_to_reason(3) == "transitive_import(depth=3)"
