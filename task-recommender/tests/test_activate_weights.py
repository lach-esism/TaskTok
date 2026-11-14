"""Tests for the explicit tuned-weight activation command."""

import json

from app.config import DEFAULT_WEIGHTS
from app.versioning import WeightStore
from scripts import activate_weights as aw


def test_activate_creates_version_and_points_active_at_it(tmp_path):
    source = tmp_path / "weights_choice.json"
    weights = {
        "reputation": 0.367546550922,
        "skill": 0.124367748878,
        "expertise": 0.27845724286,
        "collaborative": 0.034863927247,
        "preference": 0.078898218881,
        "load": 0.068106525956,
        "customer_preference": 0.047759785256,
    }
    source.write_text(json.dumps(weights), encoding="utf-8")
    weights_dir = tmp_path / "weights"

    assert (
        aw.main(
            [
                "--input",
                str(source),
                "--weights-dir",
                str(weights_dir),
                "--source",
                "choice-tuned",
            ]
        )
        == 0
    )

    store = WeightStore(weights_dir, prior=DEFAULT_WEIGHTS)
    active = store.active()
    assert active.source == "choice-tuned"
    assert active.weights == weights
    assert (weights_dir / f"weights_{active.version}.json").exists()
    assert json.loads(
        (weights_dir / "active.json").read_text(encoding="utf-8")
    ) == {"active_version": active.version}


def test_activate_rejects_invalid_simplex(tmp_path):
    source = tmp_path / "bad.json"
    bad = dict(DEFAULT_WEIGHTS)
    bad["reputation"] = 0.99  # violates the 0.40 upper bound
    source.write_text(json.dumps(bad), encoding="utf-8")

    assert (
        aw.main(
            [
                "--input",
                str(source),
                "--weights-dir",
                str(tmp_path / "weights"),
            ]
        )
        == 2
    )
