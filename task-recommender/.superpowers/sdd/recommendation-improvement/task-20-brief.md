## Task 20: End-to-End Strict Evaluation, Benchmark Re-Baseline, and Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/recommendation-flow.md`
- Test: `tests/test_docs.py` (create)
- Reports: `reports/strict_eval.json`, `reports/strict_eval.md`, `reports/benchmark_rounds.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a final strict-eval report, a benchmark re-baseline, and updated docs.

- [ ] **Step 1: Write the failing docs test**

Create `tests/test_docs.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_docs.py -v`
Expected: FAIL because the docs do not mention the new flow.

- [ ] **Step 3: Update the docs**

Add to `README.md`:
- A short “推荐机制改进” section listing `/events`, `/events/metrics`, `scripts/evaluate_strict.py`, and the strict metrics.
- A note that the ranker remains seven-dimension linear and that choice learning only estimates weights.
- The exact command `python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10`.

Update `docs/recommendation-flow.md` with the new flow:
```text
请求 → 硬约束 → 候选 + ItemCF → 语义/七维特征 → 权重 → 精确 ε-greedy
→ Top-N + request_id → impression → click/apply/accept/reject/ignore
→ pairwise/listwise 选择学习 → 权重版本 / 校准 / 回滚
```
Mention `RecommendationEvent`, exact propensity, and the strict evaluator.

- [ ] **Step 4: Run the tests and the end-to-end evaluation**

```bash
python -m pytest tests/ -q
python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10 --candidate-weights data/weights/weights_v0007.json
python scripts/run_benchmark_rounds.py --rounds 10
```

Expected: all tests pass; the strict report and benchmark report are written. Check the strict report against the targets:
- `NDCG@10` relative improvement ≥10% or `HR@10` ≥5pp in at least one direction, and the other direction does not deteriorate.
- 95% CI does not cross 0.
- Constraint violations = 0.
- Cold-start counts as measured only when `cold_start.available` is true **and** `cold_start.queries > 0`; otherwise report N/A, never "passed".
- Benchmark Top-1 not worse than the fresh baseline you recorded in Task 0 (re-run after the `benchmark/features.py` change; do not compare to the historical 0.731 without re-running).
- `reports/strict_eval.md` includes Brier score and reliability bins for the calibrated `P(rating>=4)`; calibration is reported even though it does not affect ranking.
- Use `--candidate-weights` with a real learned weights JSON. Do not pass an empty/zero-key dict; `baseline_equals_candidate` must reflect the effective weights. If candidate == baseline, the report must say identity and no improvement claim is allowed.
- **Document the exact propensity formula, not `0.9` / `1/候选数`.** README and `docs/recommendation-flow.md` must state: top-(K-1)=1.0, rank K=`(1-ε)+ε/(N-K+1)`, tail=`ε/(N-K+1)`.
- **Correct the leakage sentence.** Test data is used for scoring and calibration labels, not for feature construction. State that boundary.
- **Add `cold_start.queries` and `cold_start.measured` to the JSON** so machine consumers do not have to parse Markdown; docs must match.
- **Benchmark narrative:** report the absolute R10 vs prior historical R10 (e.g., 0.568 vs 0.731) explicitly, in addition to the fresh-baseline comparison; regenerate `reports/benchmark_visual.md` or label it historical.
- **Tests:** cover target `MET`/`NOT MET`/`n/a`, cold-start `n/a`, seven-key candidate validation, and effective-weight identity. Do not only test substrings in docs.

If a target is not met, do not claim success. Record the gap in `reports/strict_eval.md` and create a follow-up task; the implementation is still complete, but the accuracy goal is not. Do not present a zero-query cold-start subset or an identity candidate as a passed guardrail.

- [ ] **Step 5: Final full-suite run**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint and report**

No git commit. Update `reports/strict_eval.md` and `reports/benchmark_rounds.md`; summarize the measured deltas, confidence intervals, and any unmet target in the final handoff.

---

