"""Application configuration constants."""

APP_VERSION = "0.3.0"

# Seven-dimension fusion weights (Phase 1, AHP prior).
DEFAULT_WEIGHTS: dict[str, float] = {
    "reputation": 0.32,
    "skill": 0.20,
    "expertise": 0.15,
    "collaborative": 0.13,
    "preference": 0.10,
    "load": 0.06,
    "customer_preference": 0.04,
}

# Phase 1 data defaults.
DEFAULT_SEED = 42
DEFAULT_N_WORKERS = 100
DEFAULT_N_TASKS = 500
DEFAULT_N_ASSIGNMENTS = 3000

# Breach policy (Phase 1).
BREACH_WINDOW_DAYS = 180
BREACH_EXCLUDE_THRESHOLD = 2
