import pytest

from app.evaluation_phase2 import learning_curve, weight_recovery
from app.learning.weights import AHP_PRIOR
from app.personalization.segments import Segmenter
from app.personalization.user_weights import PersonalizationService


def test_weight_recovery_perfect_and_orthogonal():
    weights = dict(AHP_PRIOR)
    assert weight_recovery(weights, weights) == pytest.approx(1.0)
    orthogonal = {key: 0.0 for key in weights}
    orthogonal["reputation"] = 1.0
    assert weight_recovery(weights, orthogonal) < 0.9


def test_learning_curve_returns_expected_keys(small_store):
    personalizer = PersonalizationService(
        small_store, Segmenter(), AHP_PRIOR
    )
    curve = learning_curve(
        small_store, personalizer, ["w_new"], steps=(0, 1)
    )
    assert set(curve) == {"n", "ndcg", "hr", "regret", "weight_cosine"}
    assert len(curve["n"]) == 2
    assert len(curve["ndcg"]) == 2


def test_two_run_metrics_do_not_fabricate_rmse_or_gini(small_store):
    from app.evaluation_phase2 import evaluate_two_runs
    from app.service import RecommendationService

    metrics = evaluate_two_runs(
        small_store,
        RecommendationService(small_store),
        AHP_PRIOR,
        AHP_PRIOR,
    )
    assert metrics["baseline_rmse"] is None
    assert metrics["learned_rmse"] is None
    assert metrics["gini"] is None
