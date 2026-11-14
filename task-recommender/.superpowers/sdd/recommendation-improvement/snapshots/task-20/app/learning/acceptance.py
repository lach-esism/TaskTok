"""Acceptance-probability model learned from accept/reject events."""

from __future__ import annotations

from sklearn.linear_model import LogisticRegression

from app.domain import Task, Worker

#: Fixed feature order shared by fitting, prediction, and ``accept_features``.
FEATURE_KEYS: tuple[str, ...] = (
    "category_match",
    "skill_match",
    "pay_fit",
    "load_ratio",
    "region_match",
    "historical_accept_rate",
)

#: Below this many events the model stays unfitted and returns its prior.
MIN_SAMPLES = 20


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def accept_features(
    worker: Worker,
    task: Task,
    skill: float,
    pay_fit: float,
    region_match: float,
    historical_accept_rate: float,
) -> dict[str, float]:
    """Build the ordered feature vector fed to :class:`AcceptanceModel`.

    ``region_match`` and ``historical_accept_rate`` are supplied by the
    caller because they depend on assignment/event context the worker and
    task objects do not carry.
    """
    load_ratio = _clamp(
        (worker.current_load_hours + task.estimated_hours)
        / max(worker.capacity_hours, 1.0)
    )
    return {
        "category_match": float(
            worker.preferred_categories.get(task.category, 0.0)
        ),
        "skill_match": float(skill),
        "pay_fit": float(pay_fit),
        "load_ratio": load_ratio,
        "region_match": float(region_match),
        "historical_accept_rate": float(historical_accept_rate),
    }


class AcceptanceModel:
    """Logistic ``P(accept)`` model over accept/reject events.

    The model is trained only on observed acceptance events, never on
    ground-truth labels. Until it has seen at least :data:`MIN_SAMPLES`
    samples it stays unfitted and :meth:`predict` returns ``prior``.
    """

    def __init__(self, prior: float = 0.5, l2: float = 0.1) -> None:
        if l2 <= 0:
            raise ValueError("l2 must be positive")
        self.prior = _clamp(prior)
        self.l2 = float(l2)
        self._model: LogisticRegression | None = None

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    @staticmethod
    def _vector(features: dict[str, float]) -> list[float]:
        return [float(features.get(key, 0.0)) for key in FEATURE_KEYS]

    def fit(
        self,
        samples: list[tuple[dict[str, float], int]],
        sample_weight: list[float] | None = None,
    ) -> "AcceptanceModel":
        """(Re)fit on ``(features, accepted)`` samples and return ``self``.

        Fit is all-or-nothing: too few samples, or samples containing a
        single class (which logistic regression cannot separate), leave the
        model unfitted rather than raising or keeping a stale fit.
        """
        if len(samples) < MIN_SAMPLES:
            self._model = None
            return self
        rows = [self._vector(features) for features, _ in samples]
        labels = [int(label) for _, label in samples]
        if len(set(labels)) < 2:
            self._model = None
            return self
        model = LogisticRegression(
            fit_intercept=True,
            C=1.0 / self.l2,
            max_iter=1000,
        )
        model.fit(rows, labels, sample_weight=sample_weight)
        self._model = model
        return self

    def predict(self, features: dict[str, float]) -> float:
        if self._model is None:
            return float(self.prior)
        probabilities = self._model.predict_proba([self._vector(features)])[0]
        classes = list(self._model.classes_)
        index = classes.index(1) if 1 in classes else len(classes) - 1
        return _clamp(probabilities[index])
