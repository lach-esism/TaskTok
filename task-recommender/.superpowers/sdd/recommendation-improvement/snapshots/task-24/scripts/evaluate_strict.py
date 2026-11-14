"""Run the strict task<->worker evaluation and write JSON/Markdown reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DEFAULT_WEIGHTS  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402
from app.evaluation_strict import evaluate_strict  # noqa: E402
from app.learning.weights import KEYS as WEIGHT_KEYS  # noqa: E402

_DIRECTIONS = (
    "task_to_workers",
    "task_to_workers_exposed",
    "worker_to_tasks",
    "worker_to_tasks_exposed",
)
_METRICS = ("hr", "ndcg", "mrr")


def _parse_seeds(raw: str) -> tuple[int, ...]:
    seeds: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            seeds.append(int(part))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid seed: {part!r}"
            ) from exc
    if not seeds:
        raise argparse.ArgumentTypeError("at least one seed is required")
    return tuple(seeds)


def _read_weight_payload(path: Path) -> dict[str, float]:
    """Read a raw weight dict or a WeightStore version file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(
        payload.get("weights"), dict
    ):
        payload = payload["weights"]
    if not isinstance(payload, dict):
        raise ValueError("candidate weights must be a JSON object")
    weights: dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(
            value, (int, float)
        ):
            raise ValueError(
                f"candidate weight {key!r} is not numeric"
            )
        weights[str(key)] = float(value)
    if not weights:
        raise ValueError("candidate weights JSON object is empty")
    expected = set(WEIGHT_KEYS)
    missing = sorted(expected - set(weights))
    extra = sorted(set(weights) - expected)
    if missing or extra:
        raise ValueError(
            "candidate weights must contain exactly the seven canonical "
            f"keys; missing={missing}, extra={extra}"
        )
    negative = sorted(key for key, value in weights.items() if value < 0)
    if negative:
        raise ValueError(
            f"candidate weights must be non-negative; got {negative}"
        )
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(
            f"candidate weights must sum to 1.0, got {total}"
        )
    return weights


def _load_candidate_weights(
    root: Path, override_path: str | None = None
) -> tuple[dict[str, float], str]:
    """Resolve the candidate weights and their source label.

    Precedence: explicit ``--candidate-weights`` file, then the active weight
    version, then the AHP prior / ``DEFAULT_WEIGHTS``.
    """
    if override_path is not None:
        return _read_weight_payload(Path(override_path)), "override"

    weights_dir = root / "data" / "weights"
    active_path = weights_dir / "active.json"
    if not active_path.exists():
        return dict(DEFAULT_WEIGHTS), "default"
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        version = str(active["active_version"])
        weights = _read_weight_payload(
            weights_dir / f"weights_{version}.json"
        )
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return dict(DEFAULT_WEIGHTS), "default"
    return weights, "active"


def _format_delta(result: dict) -> str:
    return (
        f"{result['mean']:+.4f} "
        f"[{result['low']:+.4f}, {result['high']:+.4f}] "
        f"p={result['p_value']:.4f}"
    )


def _format_rate(value) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _relative_delta(baseline: float, candidate: float) -> float:
    if baseline > 0.0:
        return (candidate - baseline) / baseline
    return 0.0 if candidate == baseline else float("inf")


def _target_lines(result: dict) -> list[str]:
    """Describe the plan's accuracy/guardrail targets without overclaiming."""
    equal = bool(result["baseline_equals_candidate"])
    if equal:
        return [
            "## Target check (strict metrics)",
            "",
            "- Accuracy target: n/a (candidate weights are identical to "
            "the baseline)",
            "- Guardrails: see constraint violations and cold-start status "
            "above",
        ]

    primary = ("task_to_workers", "worker_to_tasks")
    stats: dict[str, dict] = {}
    for name in primary:
        baseline = result["baselines"][name]
        candidate = result["candidate"][name]
        stats[name] = {
            "ndcg_rel": _relative_delta(baseline["ndcg"], candidate["ndcg"]),
            "hr_pp": (candidate["hr"] - baseline["hr"]) * 100.0,
            "ndcg_ci": result["deltas"][name]["ndcg"],
            "hr_ci": result["deltas"][name]["hr"],
        }

    lines = [
        "## Target check (strict metrics)",
        "",
        (
            "Accuracy target: NDCG@10 relative improvement ≥10% or "
            "HR@10 ≥5pp in at least one primary direction, and the other "
            "primary direction does not deteriorate."
        ),
        "",
        "| Direction | NDCG@10 rel | HR@10 pp | NDCG CI | HR CI |",
        "|---|---|---|---|---|",
    ]
    for name in primary:
        item = stats[name]
        lines.append(
            f"| {name} | {item['ndcg_rel'] * 100:+.2f}% | "
            f"{item['hr_pp']:+.2f} | "
            f"[{item['ndcg_ci']['low']:+.4f}, "
            f"{item['ndcg_ci']['high']:+.4f}] | "
            f"[{item['hr_ci']['low']:+.4f}, "
            f"{item['hr_ci']['high']:+.4f}] |"
        )

    qualifying = [
        name
        for name in primary
        if (
            stats[name]["ndcg_rel"] >= 0.10
            and stats[name]["ndcg_ci"]["low"] > 0.0
        )
        or (
            stats[name]["hr_pp"] >= 5.0
            and stats[name]["hr_ci"]["low"] > 0.0
        )
    ]
    met = False
    if qualifying:
        others = [name for name in primary if name not in qualifying]
        if not others:
            met = True
        else:
            other = others[0]
            met = (
                result["deltas"][other]["ndcg"]["mean"] >= 0.0
                and result["deltas"][other]["hr"]["mean"] >= 0.0
            )
    lines.extend(
        [
            "",
            f"- status: {'MET' if met else 'NOT MET'}",
        ]
    )
    if not met:
        lines.append(
            "- gap: the conjunctive accuracy target is not met; inspect the "
            "per-direction NDCG relative delta, HR delta, and 95% CIs above. "
            "A relative NDCG gain on a very low absolute baseline is called "
            "out separately and is not treated as success by itself."
        )
    for name in qualifying:
        if (
            stats[name]["ndcg_rel"] >= 0.10
            and result["candidate"][name]["ndcg"] < 0.05
        ):
            lines.append(
                f"- caveat: {name} NDCG@10 relative gain rests on a very "
                f"low absolute baseline ({result['baselines'][name]['ndcg']:.4f})"
            )
    lines.extend(
        [
            (
                "- Constraint violations: "
                f"{result['constraint_violations']} "
                f"({'PASS' if result['constraint_violations'] == 0 else 'FAIL'})"
            ),
        ]
    )
    cold = result["cold_start"]
    cold_queries = cold.get("queries")
    if cold_queries is None:
        cold_queries = sum(
            cold["baseline"][name]["queries"] for name in _DIRECTIONS
        )
    cold_measured = cold.get("measured")
    if cold_measured is None:
        cold_measured = bool(cold["available"]) and cold_queries > 0
    lines.append(
        "- Cold start: "
        + ("MEASURED" if cold_measured else "N/A (not measured)")
        + f" (queries={cold_queries})"
    )
    calibration = result.get("calibration", {})
    lines.append(
        "- Calibration: "
        + ("reported above (ranking unaffected)"
           if calibration.get("available")
           else "N/A (see calibration section)")
    )
    lines.append(
        "- Benchmark re-baseline: see reports/benchmark_rounds.md"
    )
    return lines


def _render_markdown(
    result: dict, weights: dict[str, float], source: str
) -> str:
    seeds = (
        ", ".join(str(seed) for seed in result["seeds"])
        if result["seeds"]
        else "(provided dataset)"
    )
    k = result["k"]
    equal = bool(result["baseline_equals_candidate"])
    cold = result["cold_start"]
    cold_reason = cold["reason"] or "n/a"
    lines = [
        "# Strict Evaluation",
        "",
        f"- Seeds: {seeds}",
        f"- k: {k}",
        f"- Candidate source: {source}",
        (
            "- Candidate weights: "
            f"{json.dumps(weights, ensure_ascii=False, sort_keys=True)}"
        ),
        f"- baseline_equals_candidate: {str(equal).lower()}",
        f"- Constraint violations: {result['constraint_violations']}",
        (
            "- Latency p50/p95: "
            f"{result['latency_p50_ms']:.4f} / "
            f"{result['latency_p95_ms']:.4f} ms"
        ),
    ]
    if equal:
        lines.extend(
            [
                "",
                (
                    "> **baseline_equals_candidate: true** — candidate "
                    "weights are identical to the baseline; the deltas "
                    "below are shown as n/a because they are zero by "
                    "construction and are not evidence of improvement."
                ),
            ]
        )
    lines.extend(
        [
            "",
            f"## Baseline vs candidate (HR@{k}, NDCG@{k}, MRR@{k})",
            "",
            "| Direction | Metric | Baseline | Candidate | Delta mean [95% CI] p |",
            "|---|---|---|---|---|",
        ]
    )
    for name in _DIRECTIONS:
        baseline = result["baselines"][name]
        candidate = result["candidate"][name]
        for metric in _METRICS:
            delta = (
                "n/a (identical weights)"
                if equal
                else _format_delta(result["deltas"][name][metric])
            )
            lines.append(
                f"| {name} | {metric} | "
                f"{baseline[metric]:.4f} | {candidate[metric]:.4f} | "
                f"{delta} |"
            )

    cold_queries = cold.get("queries")
    if cold_queries is None:
        cold_queries = sum(
            cold["baseline"][name]["queries"] for name in _DIRECTIONS
        )
    cold_measured = cold.get("measured")
    if cold_measured is None:
        cold_measured = bool(cold["available"]) and cold_queries > 0
    lines.extend(
        [
            "",
            "## Cold start (workers with no train assignments)",
            "",
            f"- available: {str(bool(cold['available'])).lower()}",
            f"- reason: {cold_reason}",
            f"- queries: {cold_queries}",
            f"- measured: {str(cold_measured).lower()}",
            "",
            "| Direction | Metric | Baseline | Candidate | Delta mean [95% CI] p |",
            "|---|---|---|---|---|",
        ]
    )
    for name in _DIRECTIONS:
        baseline = cold["baseline"][name]
        candidate = cold["candidate"][name]
        for metric in _METRICS:
            if equal:
                delta = "n/a (identical weights)"
            elif not cold_measured:
                delta = "n/a (cold-start subset not measured)"
            else:
                delta = _format_delta(cold["deltas"][name][metric])
            lines.append(
                f"| {name} | {metric} | "
                f"{baseline[metric]:.4f} | {candidate[metric]:.4f} | "
                f"{delta} |"
            )

    calibration = result.get("calibration", {})
    calibration_available = bool(calibration.get("available"))
    calibration_reason = calibration.get("reason") or "n/a"
    lines.extend(
        [
            "",
            "## Calibration: P(rating>=4)",
            "",
            "> Calibration is reported for interpretability only. It does "
            "not affect ranking.",
            "",
            f"- available: {str(calibration_available).lower()}",
            f"- reason: {calibration_reason}",
            f"- label: {calibration.get('label', 'rating>=4')}",
            (
                f"- train samples: {calibration.get('train_samples', 0)} "
                f"(positive rate "
                f"{_format_rate(calibration.get('train_positive_rate'))})"
            ),
            (
                f"- test samples: {calibration.get('test_samples', 0)} "
                f"(positive rate "
                f"{_format_rate(calibration.get('test_positive_rate'))})"
            ),
        ]
    )
    if calibration_available:
        lines.extend(
            [
                f"- Brier (calibrated): {calibration['brier']:.4f}",
                f"- Brier (raw score): {calibration['raw_brier']:.4f}",
                (
                    "- Platt a/b: "
                    f"{calibration['a']:.4f} / {calibration['b']:.4f}"
                ),
                "",
                "Reliability bins (test):",
                "",
                "| Bin | Count | Mean predicted | Observed rate |",
                "|---|---|---|---|",
            ]
        )
        for item in calibration["reliability_bins"]:
            predicted = _format_rate(item["mean_predicted"])
            observed = _format_rate(item["observed_rate"])
            lines.append(
                f"| [{item['bin_low']:.2f}, {item['bin_high']:.2f}) | "
                f"{item['count']} | {predicted} | {observed} |"
            )
    else:
        lines.extend(
            [
                "",
                (
                    "Calibration unavailable: no Brier score or reliability "
                    "bins are reported."
                ),
            ]
        )

    lines.extend(["", *_target_lines(result)])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Strict leakage-free evaluation of task<->worker ranking."
        )
    )
    parser.add_argument(
        "--seeds",
        type=_parse_seeds,
        default=(42,),
        help="comma-separated data seeds, e.g. 42,43,44",
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "reports"),
        help="directory for strict_eval.json and strict_eval.md",
    )
    parser.add_argument(
        "--candidate-weights",
        default=None,
        metavar="PATH",
        help=(
            "optional JSON object of candidate weights; defaults to the "
            "active weight version, then DEFAULT_WEIGHTS"
        ),
    )
    args = parser.parse_args(argv)

    try:
        weights, source = _load_candidate_weights(
            ROOT, args.candidate_weights
        )
    except (OSError, ValueError) as exc:
        print(
            f"error: cannot load candidate weights: {exc}",
            file=sys.stderr,
        )
        return 2

    dataset = generate_dataset(seed=args.seeds[0])
    result = evaluate_strict(
        dataset, weights, k=args.k, seeds=args.seeds
    )
    result["candidate_source"] = source

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "strict_eval.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "strict_eval.md").write_text(
        _render_markdown(result, weights, source),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "seeds": result["seeds"],
                "k": result["k"],
                "candidate_source": source,
                "baseline_equals_candidate": result[
                    "baseline_equals_candidate"
                ],
                "baselines": result["baselines"],
                "candidate": result["candidate"],
                "deltas": result["deltas"],
                "cold_start": {
                    "available": result["cold_start"]["available"],
                    "reason": result["cold_start"]["reason"],
                    "queries": result["cold_start"]["queries"],
                    "measured": result["cold_start"]["measured"],
                },
                "calibration": {
                    "available": result["calibration"]["available"],
                    "reason": result["calibration"]["reason"],
                    "brier": result["calibration"]["brier"],
                    "raw_brier": result["calibration"]["raw_brier"],
                },
                "constraint_violations": result[
                    "constraint_violations"
                ],
                "latency_p50_ms": result["latency_p50_ms"],
                "latency_p95_ms": result["latency_p95_ms"],
                "reports": [
                    str(out_dir / "strict_eval.json"),
                    str(out_dir / "strict_eval.md"),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
