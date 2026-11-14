"""In-memory chain-plan versions and active pointers."""

from __future__ import annotations

from app.domain import ChainPlan


class ChainPlanStore:
    def __init__(self) -> None:
        self._versions: dict[str, list[ChainPlan]] = {}
        self._active: dict[str, int] = {}

    def save(self, plan: ChainPlan) -> int:
        versions = self._versions.setdefault(plan.chain_id, [])
        versions.append(plan)
        version = len(versions)
        self._active[plan.chain_id] = version
        return version

    def active(self, chain_id: str) -> ChainPlan:
        versions = self._versions.get(chain_id, [])
        if not versions:
            raise KeyError(chain_id)
        return versions[self._active[chain_id] - 1]

    def rollback(self, chain_id: str, version: int) -> ChainPlan:
        versions = self._versions.get(chain_id, [])
        if version < 1 or version > len(versions):
            raise KeyError(version)
        self._active[chain_id] = version
        return versions[version - 1]

    def versions(self, chain_id: str) -> list[ChainPlan]:
        return list(self._versions.get(chain_id, []))
