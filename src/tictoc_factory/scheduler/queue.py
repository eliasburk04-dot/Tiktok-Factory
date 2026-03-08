from __future__ import annotations

from pathlib import Path

from ..models import QueueJob
from ..utils.files import atomic_write_json, load_json


class QueueStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def upsert(self, job: QueueJob) -> None:
        atomic_write_json(self.root / f"{job.job_id}.json", job.model_dump(mode="json"))

    def list_jobs(self) -> list[QueueJob]:
        jobs = []
        for path in sorted(self.root.glob("*.json")):
            jobs.append(QueueJob.model_validate(load_json(path, {})))
        return jobs

    def find_by_state(self, *states: str) -> list[QueueJob]:
        state_set = set(states)
        return [job for job in self.list_jobs() if job.state in state_set]
