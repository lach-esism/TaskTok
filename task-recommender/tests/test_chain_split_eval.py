def test_split_eval_script_outputs_metrics(tmp_path):
    import json
    import subprocess
    import sys

    output = tmp_path / "chain_split_eval.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_chain_split.py",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["cases"] >= 10
    assert 0.0 <= data["dispatchable_rate"] <= 1.0
    assert data["duplicate_dispatch"] == 0
