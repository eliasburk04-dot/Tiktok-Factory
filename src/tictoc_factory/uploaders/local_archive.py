from __future__ import annotations

import shutil
from pathlib import Path

from ..models import QueueJob
from ..utils.files import atomic_write_json


class LocalArchiveUploader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def publish(self, job: QueueJob, video_path: Path) -> dict[str, str]:
        destination_dir = self.root / (job.account_name or "default")
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / f"{job.job_id}.mp4"
        shutil.copy2(video_path, destination_path)
        receipt = {
            "provider": "local_archive",
            "destination": str(destination_path),
            "status": "archived",
        }
        atomic_write_json(destination_path.with_suffix(".json"), receipt)
        return receipt
