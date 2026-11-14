import math
from pathlib import Path

from app.data.ground_truth import build_ground_truth
from app.data.synthetic import generate_dataset


def _correlation(xs, ys):
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    covariance = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)
    )
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    if variance_x <= 0 or variance_y <= 0:
        return 0.0
    return covariance / math.sqrt(variance_x * variance_y)


def test_generate_dataset_includes_new_users_and_ground_truth(tmp_path):
    dataset = generate_dataset(
        n_workers=20,
        n_tasks=30,
        n_assignments=100,
        n_new_users=5,
    )
    assert len(dataset.new_users) == 5
    assert all(not worker.ratings for worker in dataset.new_users)
    path = build_ground_truth(
        dataset, tmp_path / "ground_truth.csv"
    )
    assert path.exists()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 20 * 30 + 1


def test_new_user_profiles_correlate_with_latent_weights():
    dataset = generate_dataset(
        n_workers=20,
        n_tasks=30,
        n_assignments=100,
        n_new_users=40,
        seed=7,
    )
    skill_weights = [
        dataset.true_weights[worker.worker_id]["skill"]
        for worker in dataset.new_users
    ]
    skill_counts = [len(worker.skills) for worker in dataset.new_users]
    assert _correlation(skill_weights, skill_counts) > 0.2


def test_ground_truth_isolation_from_recommendation_paths():
    root = Path(__file__).resolve().parent.parent / "app"
    for relative in (
        "features.py",
        "service.py",
        "main.py",
        "learning/online.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "ground_truth" not in text
