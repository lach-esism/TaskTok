"""Feature builder for the natural-language round benchmark."""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer

from app.learning.weights import KEYS
from app.models.itemcf import ItemCF
from app.nlp.classifier import extract_fields, rule_scores

FEATURE_KEYS = list(KEYS)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class BenchmarkFeatureBuilder:
    """Text similarity plus observable platform signals.

    The builder never receives gold labels. Task category is inferred from
    the task text with the lexicon classifier, not read from a label.
    """

    def __init__(
        self,
        workers: list[dict],
        tasks: list[dict],
        customers: list[dict],
        itemcf: ItemCF | None = None,
    ):
        self.workers = workers
        self.tasks = tasks
        self.itemcf = itemcf
        self.worker_index = {
            worker["worker_id"]: index
            for index, worker in enumerate(workers)
        }
        self.task_index = {
            task["task_id"]: index for index, task in enumerate(tasks)
        }
        self.customer_by_id = {
            customer["customer_id"]: customer for customer in customers
        }

        corpus = [worker["resume_text"] for worker in workers] + [
            task["task_text"] for task in tasks
        ]
        self.vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 4),
            min_df=1,
            sublinear_tf=True,
        )
        matrix = self.vectorizer.fit_transform(corpus)
        self.worker_matrix = matrix[: len(workers)]
        self.task_matrix = matrix[len(workers):]
        self.similarity = (
            self.task_matrix @ self.worker_matrix.T
        ).toarray()

        self._cache: dict[tuple[str, str], dict[str, float]] = {}
        self.task_categories: dict[str, str] = {}
        self.task_skills: dict[str, set[str]] = {}
        for task in tasks:
            scores = rule_scores(task["task_text"])
            self.task_categories[task["task_id"]] = max(
                scores, key=scores.get
            )
            self.task_skills[task["task_id"]] = set(
                extract_fields(task["task_text"])["skills"]
            )

    def features(self, task_id: str, worker_id: str) -> dict[str, float]:
        key = (task_id, worker_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        task = self.tasks[self.task_index[task_id]]
        worker = self.workers[self.worker_index[worker_id]]
        category = self.task_categories[task_id]

        task_skills = self.task_skills[task_id]
        worker_skills = worker["skills"]
        if task_skills:
            skill = sum(
                min(worker_skills.get(skill, 0), 4) / 4.0
                for skill in task_skills
            ) / len(task_skills)
        else:
            skill = 0.4

        capacity = max(float(worker["capacity_hours"]), 1.0)
        load = 1.0 - float(worker["current_load_hours"]) / capacity

        collaborative = 0.0
        if self.itemcf is not None:
            pair = (worker_id, task_id)
            collaborative = self.itemcf.normalize(
                {pair: self.itemcf.score(worker_id, task_id)}
            )[pair]

        preference = float(
            worker.get("preferred_categories", {}).get(category, 0.2)
        )
        customer = self.customer_by_id.get(task["customer_id"], {})
        customer_preference = float(
            customer.get("preferred_categories", {}).get(category, 0.2)
        )

        result = {
            "reputation": _clamp(
                0.7 * float(worker["rating"]) / 5.0
                + 0.3 * float(worker["on_time_rate"])
            ),
            "skill": _clamp(skill),
            "expertise": _clamp(
                float(
                    self.similarity[
                        self.task_index[task_id],
                        self.worker_index[worker_id],
                    ]
                )
            ),
            "collaborative": _clamp(collaborative),
            "preference": _clamp(preference),
            "load": _clamp(load),
            "customer_preference": _clamp(customer_preference),
        }
        self._cache[key] = result
        return result
