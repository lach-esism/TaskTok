"""JSON-backed weight versioning, diff, and rollback."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.learning.weights import validate_weights


@dataclass
class WeightVersion:
    version: str
    weights: dict[str, float]
    prior: dict[str, float]
    sample_count: int
    source: str
    metrics: dict
    updated_at: str


class WeightStore:
    def __init__(self, directory: Path, prior: dict[str, float]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.prior = dict(prior)
        if not (self.directory / "active.json").exists():
            self.create(self.prior, 0, "prior")

    def _version_path(self, version: str) -> Path:
        return self.directory / f"weights_{version}.json"

    def _next_version(self) -> str:
        indices = []
        for path in self.directory.glob("weights_v*.json"):
            match = re.fullmatch(r"weights_v(\d+)\.json", path.name)
            if match:
                indices.append(int(match.group(1)))
        index = max(indices) + 1 if indices else 0
        return f"v{index:04d}"

    def _read_version(self, version: str) -> WeightVersion:
        path = self._version_path(version)
        if not path.exists():
            raise KeyError(version)
        data = json.loads(path.read_text(encoding="utf-8"))
        return WeightVersion(
            version=data["version"],
            weights={key: float(value) for key, value in data["weights"].items()},
            prior={key: float(value) for key, value in data["prior"].items()},
            sample_count=int(data["sample_count"]),
            source=str(data["source"]),
            metrics=dict(data.get("metrics", {})),
            updated_at=str(data["updated_at"]),
        )

    def _atomic_write(self, path: Path, text: str) -> None:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=self.directory,
        )
        try:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, path)

    def _append_changelog(self, event: dict) -> None:
        path = self.directory / "changelog.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")

    def create(
        self,
        weights: dict[str, float],
        sample_count: int,
        source: str,
        metrics: dict | None = None,
    ) -> WeightVersion:
        validate_weights(weights)
        version = self._next_version()
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "version": version,
            "weights": dict(weights),
            "prior": dict(self.prior),
            "sample_count": sample_count,
            "source": source,
            "metrics": metrics or {},
            "updated_at": updated_at,
        }
        self._atomic_write(
            self._version_path(version),
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        self._atomic_write(
            self.directory / "active.json",
            json.dumps({"active_version": version}),
        )
        self._append_changelog(
            {
                "event_type": "create",
                "version": version,
                "source": source,
                "sample_count": sample_count,
                "updated_at": updated_at,
            }
        )
        return self._read_version(version)

    def get(self, version: str) -> WeightVersion:
        return self._read_version(version)

    def active(self) -> WeightVersion:
        active_path = self.directory / "active.json"
        if not active_path.exists():
            return self.create(self.prior, 0, "prior")
        data = json.loads(active_path.read_text(encoding="utf-8"))
        return self._read_version(data["active_version"])

    def rollback(self, to_version: str, reason: str = "") -> WeightVersion:
        target = self._read_version(to_version)
        self._atomic_write(
            self.directory / "active.json",
            json.dumps({"active_version": target.version}),
        )
        self._append_changelog(
            {
                "event_type": "rollback",
                "version": target.version,
                "reason": reason,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return target

    def diff(
        self, from_version: str, to_version: str
    ) -> dict[str, dict[str, float]]:
        before = self._read_version(from_version)
        after = self._read_version(to_version)
        keys = sorted(set(before.weights) | set(after.weights))
        return {
            key: {
                "from": before.weights.get(key, 0.0),
                "to": after.weights.get(key, 0.0),
                "delta": after.weights.get(key, 0.0)
                - before.weights.get(key, 0.0),
            }
            for key in keys
        }

    def changelog(self) -> list[dict]:
        path = self.directory / "changelog.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
