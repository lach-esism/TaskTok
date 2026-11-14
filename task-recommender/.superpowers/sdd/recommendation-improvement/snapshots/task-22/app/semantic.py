"""Semantic matching between task descriptions and worker resumes.

The ranker consumes one scalar per candidate, so this module exposes a small
``similarity(task_text, worker_text) -> float`` surface rather than vectors.
Three providers are supported:

``tfidf_svd`` (default)
    Character n-gram TF-IDF reduced with TruncatedSVD. Deterministic and
    dependency-free beyond scikit-learn.
``sentence_transformer`` (optional)
    Uses ``sentence-transformers`` with normalized embeddings. The package is
    imported lazily; when it is missing the matcher falls back to
    ``tfidf_svd``.
``disabled``
    Always returns the neutral prior ``0.5``.

Pair scores are cached per ``(task_text, worker_text)``. ``fit`` only stores
the corpus statistics; previously unseen texts are transformed on demand.
Built worker/task texts are memoized by ID on the assumption that entities do
not change during a run; call :func:`clear_text_caches` after a data refresh.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from app import config as app_config
from app.domain import Task, Worker
from app.resume import build_resume

__all__ = [
    "DEFAULT_PROVIDER",
    "NEUTRAL_SIMILARITY",
    "SemanticMatcher",
    "build_matcher",
    "build_task_text",
    "build_worker_text",
    "clear_text_caches",
]

DEFAULT_PROVIDER = "tfidf_svd"
DISABLED_PROVIDER = "disabled"
SENTENCE_TRANSFORMER_PROVIDER = "sentence_transformer"
PROVIDERS = frozenset(
    {DEFAULT_PROVIDER, DISABLED_PROVIDER, SENTENCE_TRANSFORMER_PROVIDER}
)

#: Neutral value used when semantic matching is unavailable. It matches the
#: ``semantic_similarity`` prior expected by the seven-dimension features.
NEUTRAL_SIMILARITY = 0.5

DEFAULT_SENTENCE_MODEL = "BAAI/bge-small-zh-v1.5"

_TFIDF_ANALYZER = "char"
_TFIDF_NGRAM_RANGE = (2, 4)
_TFIDF_MIN_DF = 2
_MAX_SVD_COMPONENTS = 128

#: Memoized resume-surface text, keyed by ``worker_id``. Inputs are assumed
#: static for the duration of a run (100 workers / 1,000 tasks scale).
_WORKER_TEXT_CACHE: dict[str, str] = {}
#: Memoized task text, keyed by ``task_id``.
_TASK_TEXT_CACHE: dict[str, str] = {}


def _clamp01(value: float) -> float:
    """Clamp a cosine score to the ``[0, 1]`` range, mapping NaN to neutral."""
    value = float(value)
    if value != value:  # NaN
        return NEUTRAL_SIMILARITY
    return max(0.0, min(1.0, value))


def _clean(text: str | None) -> str:
    return "" if text is None else str(text)


class SemanticMatcher:
    """Compute a bounded semantic similarity between task and worker texts."""

    #: Upload drafts introduce unseen text pairs on every request, so the pair
    #: cache must be bounded rather than growing for the process lifetime.
    MAX_CACHE_ENTRIES = 2_048
    #: The text→vector cache has the same problem: on-demand transforms for
    #: unseen upload texts would otherwise accumulate for the process lifetime.
    MAX_VECTOR_ENTRIES = 4_096

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        model: str | None = None,
        cache_dir: Path | None = None,
        random_state: int = 42,
    ) -> None:
        provider = (provider or DEFAULT_PROVIDER).strip().lower()
        if provider not in PROVIDERS:
            provider = DEFAULT_PROVIDER
        self._provider = provider
        self.model = model
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.random_state = int(random_state)

        self._vectorizer: TfidfVectorizer | None = None
        self._svd: TruncatedSVD | None = None
        self._encoder = None
        self._encoder_class = None
        self._vectors: dict[str, np.ndarray] = {}
        self._cache: dict[tuple[str, str], float] = {}
        self._fit_count = 0
        self._fitted = False

        if self._provider == SENTENCE_TRANSFORMER_PROVIDER:
            self._import_sentence_transformer()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------
    @property
    def provider(self) -> str:
        """The provider actually in use (may be the TF-IDF fallback)."""
        return self._provider

    @property
    def fit_count(self) -> int:
        """Number of ``fit`` calls; ``similarity`` never changes this."""
        return self._fit_count

    @property
    def is_fitted(self) -> bool:
        """Whether the current provider has usable corpus state."""
        if self._provider == DISABLED_PROVIDER:
            return True
        return self._fitted

    def fit(
        self, worker_texts: list[str], task_texts: list[str]
    ) -> "SemanticMatcher":
        """Fit the corpus statistics used by later ``similarity`` calls."""
        worker_texts = [_clean(text) for text in worker_texts]
        task_texts = [_clean(text) for text in task_texts]

        self._fit_count += 1
        self._fitted = False
        self._cache.clear()
        self._vectors.clear()
        self._vectorizer = None
        self._svd = None

        if self._provider == DISABLED_PROVIDER:
            return self

        if self._provider == SENTENCE_TRANSFORMER_PROVIDER:
            try:
                self._vectors = self._encode_texts(
                    worker_texts + task_texts
                )
            except (ImportError, OSError):
                # The optional package/model disappeared since construction.
                self._provider = DEFAULT_PROVIDER
                self._encoder = None
                self._encoder_class = None
            else:
                self._fitted = True
                return self

        self._fit_tfidf(worker_texts, task_texts)
        return self

    def similarity(self, task_text: str, worker_text: str) -> float:
        """Cosine similarity in ``[0, 1]`` for one task/worker text pair."""
        task_text = _clean(task_text)
        worker_text = _clean(worker_text)
        if self._provider == DISABLED_PROVIDER:
            return NEUTRAL_SIMILARITY
        if not task_text.strip() or not worker_text.strip():
            return NEUTRAL_SIMILARITY

        key = (task_text, worker_text)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        value = self._compute_similarity(task_text, worker_text)
        if len(self._cache) >= self.MAX_CACHE_ENTRIES:
            # dict preserves insertion order; evict the oldest entry.
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = value
        return value

    def similarity_batch(
        self, task_text: str, worker_texts: list[str]
    ) -> list[float]:
        """Score one task text against several worker texts."""
        return [
            self.similarity(task_text, worker_text)
            for worker_text in worker_texts
        ]

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------
    def _import_sentence_transformer(self) -> None:
        """Import the optional package without loading a model yet."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            self._provider = DEFAULT_PROVIDER
            return
        self._encoder_class = SentenceTransformer

    def _get_encoder(self):
        if self._encoder is None:
            if self._encoder_class is None:
                raise ImportError("sentence_transformers is not available")
            kwargs = {}
            if self.cache_dir is not None:
                kwargs["cache_folder"] = str(self.cache_dir)
            self._encoder = self._encoder_class(
                self.model or DEFAULT_SENTENCE_MODEL, **kwargs
            )
        return self._encoder

    def _compute_similarity(
        self, task_text: str, worker_text: str
    ) -> float:
        if self._provider == SENTENCE_TRANSFORMER_PROVIDER:
            try:
                task_vector = self._embedding_for(task_text)
                worker_vector = self._embedding_for(worker_text)
            except (ImportError, OSError):
                self._provider = DEFAULT_PROVIDER
                self._encoder = None
                self._encoder_class = None
                self._fitted = False
                return NEUTRAL_SIMILARITY
            if task_vector is None or worker_vector is None:
                return NEUTRAL_SIMILARITY
            return _clamp01(np.dot(task_vector, worker_vector))

        if not self._fitted or self._vectorizer is None or self._svd is None:
            return NEUTRAL_SIMILARITY
        task_vector = self._vector_for(task_text)
        worker_vector = self._vector_for(worker_text)
        if task_vector is None or worker_vector is None:
            return NEUTRAL_SIMILARITY
        return _clamp01(float(np.dot(task_vector, worker_vector)))

    def _fit_tfidf(
        self, worker_texts: list[str], task_texts: list[str]
    ) -> None:
        corpus = [
            text for text in worker_texts + task_texts if text.strip()
        ]
        if not corpus:
            return

        vectorizer = None
        matrix = None
        # ``min_df=2`` is the brief's default; the retry keeps very small
        # corpora (one or two documents) usable instead of raising.
        for min_df in (_TFIDF_MIN_DF, 1):
            candidate = TfidfVectorizer(
                analyzer=_TFIDF_ANALYZER,
                ngram_range=_TFIDF_NGRAM_RANGE,
                min_df=min_df,
                sublinear_tf=True,
            )
            try:
                candidate_matrix = candidate.fit_transform(corpus)
            except ValueError:
                continue
            # TruncatedSVD requires at least two input features, and a
            # one-column vocabulary carries no useful semantic signal.
            if candidate_matrix.shape[1] < 2:
                continue
            vectorizer = candidate
            matrix = candidate_matrix
            break
        if vectorizer is None or matrix is None:
            return

        n_docs, n_features = matrix.shape
        if n_docs < 2:
            # A single document cannot yield a meaningful relative embedding;
            # callers treat an unfitted matcher as the neutral prior.
            return
        n_components = min(
            _MAX_SVD_COMPONENTS,
            max(2, n_docs - 1),
            n_features,
        )
        n_components = max(1, n_components)
        svd = TruncatedSVD(
            n_components=n_components, random_state=self.random_state
        )
        # Degenerate corpora (identical or very small document sets) can make
        # sklearn's explained-variance ratio divide by zero. The components
        # themselves stay finite, so the warning is cosmetic.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            svd.fit(matrix)

        self._vectorizer = vectorizer
        self._svd = svd
        self._vectors = self._transform_texts(corpus)
        self._fitted = True

    def _transform_texts(self, texts: list[str]) -> dict[str, np.ndarray]:
        unique = list(dict.fromkeys(text for text in texts if text.strip()))
        if not unique or self._vectorizer is None or self._svd is None:
            return {}
        matrix = self._vectorizer.transform(unique)
        reduced = normalize(self._svd.transform(matrix))
        return {
            text: reduced[index] for index, text in enumerate(unique)
        }

    def _encode_texts(self, texts: list[str]) -> dict[str, np.ndarray]:
        unique = list(dict.fromkeys(text for text in texts if text.strip()))
        if not unique:
            return {}
        encoder = self._get_encoder()
        vectors = encoder.encode(
            unique,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        vectors = np.asarray(vectors, dtype=float)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        vectors = normalize(vectors)
        return {
            text: vectors[index] for index, text in enumerate(unique)
        }

    def _remember_vectors(self, vectors: dict[str, np.ndarray]) -> None:
        """Insert vectors with an oldest-entry eviction bound."""
        for text, vector in vectors.items():
            if len(self._vectors) >= self.MAX_VECTOR_ENTRIES:
                self._vectors.pop(next(iter(self._vectors)))
            self._vectors[text] = vector

    def _embedding_for(self, text: str) -> np.ndarray | None:
        vector = self._vectors.get(text)
        if vector is not None:
            return vector
        self._remember_vectors(self._encode_texts([text]))
        return self._vectors.get(text)

    def _vector_for(self, text: str) -> np.ndarray | None:
        vector = self._vectors.get(text)
        if vector is not None:
            return vector
        if self._vectorizer is None or self._svd is None:
            return None
        transformed = self._transform_texts([text])
        vector = transformed.get(text)
        if vector is not None:
            self._remember_vectors({text: vector})
        return vector


def build_matcher(provider: str | None = None) -> SemanticMatcher:
    """Build a matcher, using ``app.config`` defaults when not overridden."""
    configured_provider = getattr(app_config, "SEMANTIC_PROVIDER", None)
    configured_model = getattr(app_config, "SEMANTIC_MODEL", None)
    configured_cache_dir = getattr(
        app_config, "SEMANTIC_CACHE_DIR", None
    )
    return SemanticMatcher(
        provider=provider or configured_provider or DEFAULT_PROVIDER,
        model=configured_model,
        cache_dir=configured_cache_dir,
    )


def clear_text_caches() -> None:
    """Drop memoized worker/task texts after the backing data changes."""
    _WORKER_TEXT_CACHE.clear()
    _TASK_TEXT_CACHE.clear()


def build_worker_text(worker: Worker) -> str:
    """Concatenate the resume surface fields visible to a customer.

    Internal scores, load, and ``platform_data`` are deliberately excluded:
    the semantic signal must only see what the resume actually shows. The
    result is memoized by ``worker_id``; workers are assumed static during a
    run, so call :func:`clear_text_caches` after a data refresh.
    """
    cached = _WORKER_TEXT_CACHE.get(worker.worker_id)
    if cached is not None:
        return cached

    resume = build_resume(worker).get("resume", {})
    parts: list[str] = [
        _clean(resume.get("headline")),
        _clean(resume.get("city")),
    ]
    parts.extend(_clean(skill) for skill in resume.get("skills", []) or [])
    for project in resume.get("projects", []) or []:
        parts.append(_clean(project.get("name")))
        parts.append(_clean(project.get("role")))
        parts.extend(
            _clean(bullet) for bullet in project.get("bullets", []) or []
        )
    parts.extend(
        _clean(certification)
        for certification in resume.get("certifications", []) or []
    )
    text = "。".join(part.strip() for part in parts if part.strip())
    _WORKER_TEXT_CACHE[worker.worker_id] = text
    return text


def build_task_text(task: Task) -> str:
    """Join the task title, description, requirements, and category.

    The result is memoized by ``task_id``; tasks are assumed static during a
    run, so call :func:`clear_text_caches` after a data refresh.
    """
    cached = _TASK_TEXT_CACHE.get(task.task_id)
    if cached is not None:
        return cached

    requirements = "。".join(
        cleaned
        for requirement in task.requirements or []
        if (cleaned := _clean(requirement).strip())
    )
    parts = [
        _clean(task.title),
        _clean(task.description),
        requirements,
        _clean(task.category),
    ]
    text = "。".join(part.strip() for part in parts if part.strip())
    _TASK_TEXT_CACHE[task.task_id] = text
    return text
