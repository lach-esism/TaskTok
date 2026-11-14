from app.config import DEFAULT_WEIGHTS
from app.learning.weights import project_weights_with_report


def test_projection_reports_reputation_high_bound():
    weights = dict(DEFAULT_WEIGHTS)
    weights["reputation"] = 0.9
    projected, report = project_weights_with_report(weights)
    assert projected["reputation"] <= 0.40 + 1e-9
    assert report.reputation_hit_high == 1
    assert abs(sum(projected.values()) - 1.0) < 1e-9


def test_projection_reports_min_weight_hits():
    weights = dict(DEFAULT_WEIGHTS)
    weights["customer_preference"] = 0.0
    projected, report = project_weights_with_report(weights)
    assert projected["customer_preference"] >= 0.02 - 1e-9
    assert report.min_hits.get("customer_preference", 0) >= 1
