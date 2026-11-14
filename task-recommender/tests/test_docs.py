import re
from pathlib import Path


def _readme() -> str:
    return Path("README.md").read_text(encoding="utf-8")


def _flow() -> str:
    return Path("docs/recommendation-flow.md").read_text(encoding="utf-8")


def test_readme_documents_events_and_strict_eval():
    text = _readme()
    assert "/events" in text
    assert "evaluate_strict.py" in text
    assert "strict_eval" in text


def test_flow_doc_documents_events_and_propensity():
    text = _flow()
    assert "RecommendationEvent" in text
    assert "propensity" in text
    assert "strict" in text.lower()


def test_docs_state_exact_propensity_command_and_cold_fields():
    readme = _readme()
    flow = _flow()
    for text in (readme, flow):
        assert "N-K+1" in text or "N - K + 1" in text
        assert "cold_start.queries" in text
        assert "cold_start.measured" in text
    for text in (readme, flow):
        assert "scripts/tune_weights.py" in text
        assert "scripts/activate_weights.py" in text
        assert "weights_choice.json" in text
        assert "strict_eval_tuned" in text
        assert "active.json" in text


def test_docs_describe_serving_parity_and_endpoint_latency_boundary():
    for text in (_readme(), _flow()):
        assert "serving" in text.lower()
        assert "endpoint_latency" in text or "端点" in text
        assert "N/A" in text
        assert "scoring_latency" in text or "进程内打分" in text


def test_docs_distinguish_benchmarks_and_train_only_collaborative():
    readme = _readme()
    flow = _flow()
    for text in (readme, flow):
        assert "collaborative" in text
        assert "1,000" in text or "1000" in text
        assert "10,000" in text or "10000" in text
        assert "train-only" in text or "训练期" in text
    assert "large_benchmark_eval.md" in readme


def test_readme_documents_upload_and_nlp_final_work():
    text = _readme()
    for token in (
        "/upload/task",
        "/upload/resume",
        "/resume/analyze",
        "build_large_benchmark.py",
        "scripts/tune_weights.py",
        "reports/strict_eval_tuned.md",
        "Flate",
    ):
        assert token in text


def test_readme_test_count_is_current():
    match = re.search(r"当前 (\d+) 个测试", _readme())
    assert match is not None
    # Exact, not a lower bound: adding tests must update README or this fails.
    assert int(match.group(1)) == 392
