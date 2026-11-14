## Task 9: SemanticMatcher

**Files:**
- Create: `app/semantic.py`
- Test: `tests/test_semantic.py` (create)

**Interfaces:**
- Consumes: scikit-learn `TfidfVectorizer`, `TruncatedSVD`.
- Produces:
  - `SemanticMatcher(provider: str = "tfidf_svd", model: str | None = None, cache_dir: Path | None = None, random_state: int = 42)`.
  - `SemanticMatcher.fit(worker_texts: list[str], task_texts: list[str]) -> "SemanticMatcher"`.
  - `SemanticMatcher.similarity(task_text: str, worker_text: str) -> float`.
  - `SemanticMatcher.similarity_batch(task_text: str, worker_texts: list[str]) -> list[float]`.
  - `SemanticMatcher.provider -> str`; `SemanticMatcher.fit_count -> int`.
  - `build_matcher(provider: str | None = None) -> SemanticMatcher`.
  - `build_worker_text(worker: Worker) -> str` — concatenate resume-surface fields (headline, skills, projects, certifications); never internal scores. Cache by `worker_id` so repeated candidate scoring does not rebuild the resume.
  - `build_task_text(task: Task) -> str` — `title + description + requirements + category`, joined with `"。"`. Cache by `task_id`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_semantic.py`:

```python
import pytest
from app.semantic import SemanticMatcher, build_matcher


def test_tfidf_svd_similarity_is_bounded_and_deterministic():
    matcher = SemanticMatcher(provider="tfidf_svd").fit(
        ["Python 后端开发，支付系统", "品牌 VI 与包装设计", "数据分析与报表"],
        ["需要 Python 后端工程师开发支付接口", "需要品牌设计师做 VI 包装", "需要数据分析师"],
    )
    sim = matcher.similarity(
        "需要 Python 后端工程师开发支付接口", "Python 后端开发，支付系统",
    )
    assert 0.0 <= sim <= 1.0
    assert sim == pytest.approx(
        matcher.similarity("需要 Python 后端工程师开发支付接口", "Python 后端开发，支付系统")
    )
    assert matcher.fit_count == 1


def test_disabled_provider_returns_half():
    matcher = SemanticMatcher(provider="disabled")
    assert matcher.similarity("a", "b") == 0.5


def test_sentence_transformer_falls_back_when_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    matcher = build_matcher("sentence_transformer")
    assert matcher.provider == "tfidf_svd"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_semantic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.semantic'`.

- [ ] **Step 3: Implement the matcher**

- `tfidf_svd`: fit `TfidfVectorizer(analyzer="char", ngram_range=(2,4), min_df=2, sublinear_tf=True)` on the union of worker/task texts, then `TruncatedSVD(n_components=min(128, max(2, n_docs - 1)), random_state=random_state)`. Transform texts, L2-normalize, cosine = dot product; clamp to `[0,1]`.
- `disabled`: `similarity` returns 0.5.
- `sentence_transformer`: lazy `from sentence_transformers import SentenceTransformer`; on ImportError, fall back to `tfidf_svd` and set `provider = "tfidf_svd"`. Encode with `normalize_embeddings=True`; cosine mapped to `[0,1]`.
- Cache: `_cache: dict[tuple[str,str], float]`; keyed by text pair; `fit_count` increments only in `fit`.
- `build_matcher(provider)`: read config defaults if `None`; return `SemanticMatcher(provider=provider or "tfidf_svd")`.
- `build_worker_text`: call `app.resume.build_resume(worker)` and concatenate the visible surface fields (`headline`, `skills`, `projects`, `certifications`, `city`); do not include `platform_data`. Cache by `worker_id`.
- `build_task_text`: join `title`, `description`, `requirements`, and `category` with `"。".join(...)`; cache by `task_id`.
- Persistent sha256 disk embedding cache (design §9.3) is deferred; the in-memory pair cache is sufficient for the 100-worker/1,000-task scale. Record this as a performance follow-up.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_semantic.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

