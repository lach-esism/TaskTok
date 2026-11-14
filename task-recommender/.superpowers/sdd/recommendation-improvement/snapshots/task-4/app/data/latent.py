"""Latent true-weight generation shared by the DGP and evaluation."""

from __future__ import annotations

import random

from app.config import DEFAULT_WEIGHTS


def true_weight_simplex(rng: random.Random) -> dict[str, float]:
    keys = list(DEFAULT_WEIGHTS)
    values = {key: rng.random() for key in keys}
    total = sum(values.values())
    return {key: value / total for key, value in values.items()}
