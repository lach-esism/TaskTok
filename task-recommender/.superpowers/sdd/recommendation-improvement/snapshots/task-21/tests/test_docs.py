from pathlib import Path


def test_readme_documents_events_and_strict_eval():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "/events" in text
    assert "evaluate_strict.py" in text
    assert "strict_eval" in text


def test_flow_doc_documents_events_and_propensity():
    text = Path("docs/recommendation-flow.md").read_text(encoding="utf-8")
    assert "RecommendationEvent" in text
    assert "propensity" in text
    assert "strict" in text.lower()


def test_docs_state_exact_propensity_command_and_cold_fields():
    readme = Path("README.md").read_text(encoding="utf-8")
    flow = Path("docs/recommendation-flow.md").read_text(encoding="utf-8")
    for text in (readme, flow):
        assert "N-K+1" in text or "N - K + 1" in text
        assert "cold_start.queries" in text
        assert "cold_start.measured" in text
    assert (
        "--candidate-weights data/weights/weights_v0007.json" in readme
    )
    assert (
        "--candidate-weights data/weights/weights_v0007.json" in flow
    )
